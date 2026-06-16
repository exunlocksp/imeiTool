"""Chạy tự động các dịch vụ đã tick — gửi server, poll kết quả, ghi vào note."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from typing import Callable

from src.api_client import (
    ImeiOrderResult,
    SickwOrderPollResult,
    fetch_orders_status,
    list_imei_orders,
    submit_imei_order,
    submit_imei_orders_bulk,
)
from src.api_config import load_api_config
from src.database import DeviceDatabase, PendingOrderRow
from src.models import DeviceRecord
from src.services_store import ServiceItem, find_service_by_id
from src.simlock_sync import fetch_simlock

logger = logging.getLogger(__name__)

ORDER_STATUS_DENIED = 3
ORDER_STATUS_DONE = 4
ORDER_STATUS_PROCESSING = 2
ORDER_STATUS_PENDING = 1

_PENDING_DB: DeviceDatabase | None = None


def _pending_db() -> DeviceDatabase:
    global _PENDING_DB
    if _PENDING_DB is None:
        _PENDING_DB = DeviceDatabase()
    return _PENDING_DB


def _order_needs_polling(status: int) -> bool:
    return status in (ORDER_STATUS_PENDING, ORDER_STATUS_PROCESSING)


def _resume_waiting_note(service: ServiceItem, order: dict[str, Any]) -> str:
    oid = int(order.get("id") or 0)
    label = str(order.get("status_label") or "").strip()
    provider = service.provider_label()
    if label:
        return f"{label} ({provider}) — đơn #{oid}"
    return f"Đang chờ {provider}… — đơn #{oid}"


def _apply_resume_waiting_note(
    record: DeviceRecord,
    service: ServiceItem,
    order: dict[str, Any],
    *,
    on_record_result: Optional[OnRecordResult] = None,
) -> None:
    append_service_note(record, service.name, _resume_waiting_note(service, order))
    if on_record_result is not None:
        on_record_result(record)


def _extend_resume_deadline(
    pending: dict[int, tuple[DeviceRecord, ServiceItem, float]],
    oid: int,
    service: ServiceItem,
) -> None:
    record, _, _ = pending[oid]
    pending[oid] = (record, service, _resume_timeout_deadline(service))


def _track_pending_order(
    record: DeviceRecord,
    service: ServiceItem,
    order_id: int,
    *,
    poll_timeout: float,
) -> None:
    if order_id <= 0 or record.id is None:
        return
    _pending_db().save_pending_order(
        order_id=order_id,
        device_record_id=record.id,
        service_id=service.server_id,
        service_name=service.name,
        imei1=record.imei1,
        imei2=record.imei2,
        serial=record.serial,
        poll_timeout_sec=poll_timeout,
    )


def _untrack_pending_order(order_id: int) -> None:
    _pending_db().delete_pending_order(order_id)


@dataclass
class AutoServiceLine:
    service_id: int
    service_name: str
    ok: bool
    text: str
    record_updated: bool = False


@dataclass
class AutoServicesResult:
    lines: list[AutoServiceLine] = field(default_factory=list)
    simlock: str = ""
    credits: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.lines) and all(line.ok for line in self.lines)


_SERVICE_NOTE_HEAD_RE = re.compile(r"^\[([^\]]+)\]\s*", re.DOTALL)


def merge_notes(existing: str, incoming: str) -> str:
    """Gộp hai đoạn ghi chú — không bỏ nội dung cũ khi cắm USB lại."""
    left = (existing or "").strip()
    right = (incoming or "").strip()
    if not left:
        return right
    if not right:
        return left
    if right in left:
        return left
    if left in right:
        return right
    return f"{left}; {right}"


def _parse_note_segments(note: str) -> tuple[list[str], dict[str, str], list[str]]:
    """Tách ghi chú: phần thường + map/block theo tên dịch vụ [Tên]."""
    base_parts: list[str] = []
    service_blocks: dict[str, str] = {}
    service_order: list[str] = []
    for segment in (s.strip() for s in (note or "").split("; ") if s.strip()):
        match = _SERVICE_NOTE_HEAD_RE.match(segment)
        if match:
            name = match.group(1).strip()
            if name not in service_blocks:
                service_order.append(name)
            service_blocks[name] = segment
        else:
            base_parts.append(segment)
    return base_parts, service_blocks, service_order


def append_service_note(record: DeviceRecord, service_name: str, text: str) -> None:
    body = (text or "").strip()
    if not body:
        return
    name = (service_name or "").strip() or "Dịch vụ"
    line = f"[{name}] {body}"
    base_parts, service_blocks, service_order = _parse_note_segments(record.note or "")
    if name not in service_blocks:
        service_order.append(name)
    service_blocks[name] = line
    segments = [*base_parts, *[service_blocks[n] for n in service_order]]
    record.note = "; ".join(segments)


def run_auto_services(
    record: DeviceRecord,
    service_ids: list[int],
    *,
    poll_interval: float = 1.5,
    poll_timeout: float = 90.0,
) -> AutoServicesResult:
    """Chạy lần lượt các dịch vụ đã chọn. Gọi từ background thread."""
    result = AutoServicesResult()
    cfg = load_api_config()
    if not cfg.enabled:
        logger.warning("Auto services: API chưa cấu hình")
        return result

    for service_id in service_ids:
        service = find_service_by_id(service_id)
        if service is None:
            logger.warning("Auto services: không tìm thấy dịch vụ server_id=%s", service_id)
            line = AutoServiceLine(
                service_id=service_id,
                service_name=f"ID {service_id}",
                ok=False,
                text="Dịch vụ không có trong cache — bấm Làm mới trong menu Dịch vụ.",
            )
            result.lines.append(line)
            append_service_note(record, line.service_name, line.text)
            continue

        timeout = (
            service.provider_poll_timeout()
            if service.uses_external_provider
            else poll_timeout
        )
        line = _run_one_service(
            record,
            service,
            poll_interval=poll_interval,
            poll_timeout=timeout,
        )
        if line is None:
            continue

        result.lines.append(line)
        if not line.record_updated:
            append_service_note(record, line.service_name, line.text)

        if service.is_simlock and line.ok and not record.simlock:
            simlock_val = _simlock_from_note_line(line.text)
            if simlock_val:
                result.simlock = simlock_val

    return result


def analyze_active(text: str) -> str:
    """'Yes'/'No'/'replaced' từ kết quả dịch vụ; ngược lại trả '' (để trống)."""
    replaced = _parse_replaced_notice(text)
    if replaced:
        return replaced
    return _parse_activation_status(text) or ""


def analyze_fmi(text: str) -> str:
    """'On'/'Off' nếu kết quả có Find My iPhone / iCloud Lock; ngược lại trả ''."""
    status = _parse_fmi_status(text)
    return status or ""


def analyze_carrier(text: str) -> str:
    """Nhà mạng từ Locked Carrier; nếu Sim-Lock Unlocked thì trả 'Unlocked'."""
    if _parse_simlock_status(text) == "Unlocked":
        return "Unlocked"
    return _parse_carrier(text) or ""


def analyze_simlock(text: str) -> str:
    """'Locked'/'Unlocked' từ dòng Sim-Lock Status; ngược lại trả ''."""
    return _parse_simlock_status(text) or ""


def analyze_model(text: str) -> str:
    """Tên model gọn (vd. 'iPhone 16 Pro Max') từ Model Description hoặc Device:."""
    desc = _extract_model_description_fragment(text)
    if desc:
        return _finalize_model_name(desc)
    return ""


def analyze_color(text: str) -> str:
    """Màu từ Model Description (vd. 'Desert', 'Deep Blue'); '' nếu không có."""
    desc = _extract_model_description_fragment(text)
    if not desc:
        return ""
    _model, color, _capacity = _split_model_description(desc)
    return color


def analyze_storage(text: str) -> str:
    """Dung lượng từ Model Description (vd. '256 GB', '1 TB'); '' nếu không có."""
    desc = _extract_model_description_fragment(text)
    if not desc:
        return ""
    _model, _color, capacity = _split_model_description(desc)
    return capacity


def _extract_model_description_fragment(text: str) -> str:
    desc = _parse_model_description(text)
    if desc:
        return desc
    plain = _strip_html_text(text).strip()
    if not plain:
        return ""
    for pattern in (
        r"Device\s*:\s*(.+?)(?:\n|<br|;|$)",
        r"Model\s*:\s*(.+?)(?:\n|<br|;|$)",
    ):
        m = re.search(pattern, plain, re.IGNORECASE)
        if m:
            fragment = _trim_model_description(m.group(1))
            if fragment:
                return fragment
    if re.search(r"\b(?:IPHONE|IPAD)\b", plain, re.IGNORECASE):
        return _trim_model_description(plain)
    return ""


def _finalize_model_name(fragment: str) -> str:
    fragment = re.sub(r"\s+", " ", (fragment or "").strip())
    if not fragment:
        return ""
    model, _, _ = _split_model_description(fragment)
    if not model:
        model = _clean_model_suffixes(_format_model_tokens(fragment.split()))
    else:
        model = _clean_model_suffixes(model)
    return model if _is_plausible_model(model) else ""


def _clean_model_suffixes(model: str) -> str:
    """Bỏ mã màu / vùng / model number (A3106-VIE…) dính cuối tên model."""
    cleaned = (model or "").strip()
    if not cleaned:
        return ""
    color_names = sorted(
        {name for name in _COLOR_CODES.values()} | {w.capitalize() for w in _COLOR_WORDS},
        key=len,
        reverse=True,
    )
    for _ in range(5):
        trimmed = cleaned
        for code in sorted(_COLOR_CODES, key=len, reverse=True):
            trimmed = re.sub(
                rf"\s+\b{re.escape(code)}\b\s*$",
                "",
                trimmed,
                flags=re.IGNORECASE,
            )
        for name in color_names:
            trimmed = re.sub(
                rf"\s+{re.escape(name)}\s*$",
                "",
                trimmed,
                flags=re.IGNORECASE,
            )
        trimmed = re.sub(
            r"\s+\bA\d{4}(?:-[A-Z]{2,5})?\b\s*$",
            "",
            trimmed,
            flags=re.IGNORECASE,
        )
        trimmed = re.sub(
            r"\s+\b[A-Z]{2,5}-(?:USA|US|A|LL|ZP|ZA|CH|VN|TH|KH|JP|VIE)\b\s*$",
            "",
            trimmed,
            flags=re.IGNORECASE,
        )
        trimmed = re.sub(
            r"\s+\b(?:SPR|VZW|TMO|ATT|NAUS|CHNA)\b\s*$",
            "",
            trimmed,
            flags=re.IGNORECASE,
        )
        trimmed = trimmed.strip()
        if trimmed == cleaned:
            break
        cleaned = trimmed
    return cleaned


def _clean_serial(raw: str) -> str:
    serial = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    if len(serial) < 8 or len(serial) > 14:
        return ""
    if serial.isdigit():
        return ""
    return serial


def _clean_imei(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) < 14 or len(digits) > 16:
        return ""
    return digits


def analyze_imei2(text: str) -> str:
    """IMEI2 từ JSON/HTML GSX — không nhầm với IMEI/IMEI Number."""
    blob = _extract_result_json(text)
    if blob:
        val = _clean_imei(_json_field_value(blob, "IMEI2", "imei2"))
        if val:
            return val
    plain = _strip_html_text(text)
    found = ""
    for m in re.finditer(r"\bIMEI2\s*(?:Number)?\s*:\s*([0-9]+)", plain, re.IGNORECASE):
        val = _clean_imei(m.group(1))
        if val:
            found = val
    if found:
        return found
    # Dual-SIM: một số provider ghi hai dòng "IMEI Number:" (không ghi IMEI2).
    imeis: list[str] = []
    for m in re.finditer(r"\bIMEI\s*(?:Number)?\s*:\s*([0-9]+)", plain, re.IGNORECASE):
        val = _clean_imei(m.group(1))
        if val and val not in imeis:
            imeis.append(val)
    if len(imeis) >= 2:
        return imeis[1]
    return ""


def analyze_serial(text: str) -> str:
    """Serial Number từ JSON/HTML GSX."""
    blob = _extract_result_json(text)
    if blob:
        val = _clean_serial(_json_field_value(blob, "Serial Number", "Serial", "serial"))
        if val:
            return val
    plain = _strip_html_text(text)
    found = ""
    for m in re.finditer(
        r"\bSerial\s*(?:Number)?\s*:\s*([A-Za-z0-9]+)",
        plain,
        re.IGNORECASE,
    ):
        val = _clean_serial(m.group(1))
        if val:
            found = val
    return found


_MODEL_DESC_PATTERNS = (
    r'"Model\s*Description"\s*:\s*"([^"]+)"',
    r"Model\s*Description\s*:\s*(.+?)(?:\n|<br|\bModel\s*:|;|\bIMEI\s*(?:Number)?\s*:|\bIMEI2\b|\bMEID\b|\bSerial\b|$)",
)

_COLOR_CODES = {
    "BLU": "Blue",
    "DBLUE": "Deep Blue",
    "BLK": "Black",
    "WHT": "White",
    "GRN": "Green",
    "RED": "Red",
    "PRP": "Purple",
    "PNK": "Pink",
    "GLD": "Gold",
    "SLV": "Silver",
    "GRY": "Gray",
    "GRE": "Gray",
    "GPH": "Graphite",
    "NAT": "Natural",
    "DES": "Desert",
    "UTR": "Ultramarine",
    "TEA": "Teal",
    "COR": "Coral",
    "CORG": "Coral",
    "CORANGE": "Orange",
    "MID": "Midnight",
    "MG": "Midnight Green",
    "STA": "Starlight",
    "SPA": "Space",
    "SG": "Space Gray",
    "TIT": "Titanium",
    "LAV": "Lavender",
    "SGE": "Sage",
    "ORN": "Orange",
    "YEL": "Yellow",
    "CRM": "Cream",
    "WHTE": "White",
}


def _strip_html_text(text: str) -> str:
    if not text:
        return ""
    plain = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    plain = re.sub(r"<[^>]+>", "", plain)
    plain = plain.replace("&quot;", '"').replace("&#34;", '"')
    plain = plain.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return plain


def _extract_result_json(text: str) -> Optional[dict[str, Any]]:
    """Tìm object JSON trong ghi chú / HTML (kết quả GSX/Sickw)."""
    if not text:
        return None
    plain = _strip_html_text(text)
    for candidate in (plain, text):
        start = candidate.find("{")
        if start == -1:
            continue
        fragment = candidate[start:]
        for end in range(len(fragment), 1, -1):
            if fragment[end - 1] != "}":
                continue
            try:
                parsed = json.loads(fragment[:end])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed:
                return parsed
    return None


def _json_field_value(blob: dict[str, Any], *keys: str) -> str:
    for key in keys:
        for candidate, value in blob.items():
            if str(candidate).strip().lower() == key.lower() and value not in (None, ""):
                return str(value).strip()
    return ""


def _trim_model_description(desc: str) -> str:
    cleaned = re.sub(r"\s+", " ", (desc or "").strip()).strip('"')
    if re.search(r"\bModel\s*:", cleaned, re.IGNORECASE):
        cleaned = re.split(r"\bModel\s*:", cleaned, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    return cleaned


def _is_plausible_model(model: str) -> bool:
    model = (model or "").strip()
    if len(model) < 6 or len(model) > 48:
        return False
    if "," in model or model.endswith("]") or re.fullmatch(r"[\d\]\[]+", model):
        return False
    if re.match(r"^iPhone\s+(?:\d{1,2}|XR|XS|SE|Air|mini)\b", model, re.IGNORECASE):
        return True
    return bool(re.match(r"^iPad\b", model, re.IGNORECASE))


def _parse_device_name(text: str) -> str:
    """Device: từ block HTML Active (vd. Device: iPhone XR)."""
    plain = _strip_html_text(text)
    m = re.search(r"Device\s*:\s*(.+?)(?:\n|<br|;|$)", plain, re.IGNORECASE)
    if not m:
        return ""
    raw = m.group(1).strip()
    if "," in raw:
        for part in raw.split(","):
            part = part.strip()
            if re.search(r"\biPhone\b|\biPad\b", part, re.IGNORECASE):
                return _finalize_model_name(part)
    return _finalize_model_name(raw)


def _normalize_model_description(desc: str) -> str:
    desc = (desc or "").strip()
    parts = [p.strip() for p in desc.split(",") if p.strip()]
    if parts and parts[0].upper() == "VIN" and len(parts) > 1:
        return ",".join(parts[1:])
    return desc


def _looks_like_gsx_comma_desc(desc: str) -> bool:
    desc = _normalize_model_description(desc)
    if not desc or "Model:" in desc or "[" in desc or "]" in desc:
        return False
    parts = [p.strip() for p in desc.split(",") if p.strip()]
    if len(parts) < 2 or len(parts) > 6:
        return False
    if not re.search(r"\bIPHONE\b|\bIPAD\b", parts[0], re.IGNORECASE):
        return False
    return any(re.search(r"\d+\s*(GB|TB)\b", part, re.IGNORECASE) for part in parts[1:])


def _parse_model_description(text: str) -> str:
    if not text:
        return ""
    blob = _extract_result_json(text)
    if blob:
        desc = _json_field_value(blob, "Model Description", "model_description", "Model")
        if desc:
            return _trim_model_description(desc)
    plain = _strip_html_text(text)
    for pattern in _MODEL_DESC_PATTERNS:
        m = re.search(pattern, plain, re.IGNORECASE | re.DOTALL)
        if m:
            desc = _trim_model_description(m.group(1))
            if desc:
                return desc
    return ""


# Các từ màu sắc thường gặp trong Model Description của Sickw/GSX.
_COLOR_WORDS = frozenset({
    "BLACK", "WHITE", "GOLD", "ROSE", "GRAY", "GREY", "SPACE", "RED",
    "YELLOW", "CORAL", "BLUE", "GREEN", "PURPLE", "MIDNIGHT", "STARLIGHT",
    "GRAPHITE", "SIERRA", "ALPINE", "PACIFIC", "DEEP", "NATURAL", "DESERT",
    "TITANIUM", "ULTRAMARINE", "TEAL", "PINK", "COSMIC", "ORANGE", "SILVER",
    "SAGE", "MIST", "LAVENDER", "CLOUD", "LIGHT", "SKY", "SOFT", "JET",
    "PRODUCT",
})

# Hậu tố vùng/quốc gia cần loại khỏi tên model.
_REGION_WORDS = frozenset({
    "USA", "US", "LL", "ZP", "ZA", "ZD", "CH", "VN", "TH", "KH", "JP", "VIE",
    "INTERNATIONAL", "GLOBAL", "NAUS", "CHNA", "SPR", "VZW", "TMO", "ATT",
})

_REGION_TOKEN_RE = re.compile(
    r"^(?:"
    r"[A-Z]{2,5}-(?:USA|US|A|LL|ZP|ZA|CH|VN|TH|KH|JP)"
    r"|[A-Z]{2,5}(?:USA|US)"
    r"|[A-Z]{2,5}"
    r")$",
    re.IGNORECASE,
)

_MODEL_TOKEN_MAP = {
    "IPHONE": "iPhone",
    "IPAD": "iPad",
    "PRO": "Pro",
    "MAX": "Max",
    "PLUS": "Plus",
    "MINI": "mini",
    "AIR": "Air",
    "SE": "SE",
    "ULTRA": "Ultra",
    "XR": "XR",
    "XS": "XS",
}


def _expand_color_code(code: str) -> str:
    word = re.sub(r"[^A-Za-z]", "", code or "").upper()
    if not word:
        return ""
    if word in _COLOR_CODES:
        return _COLOR_CODES[word]
    if word in _COLOR_WORDS:
        return word.capitalize()
    return ""


def _parse_color_phrase(text: str) -> str:
    """Màu nhiều từ: DEEP PURPLE, SPACE BLACK, NATURAL TITANIUM."""
    phrase = re.sub(r"\s+", " ", (text or "").strip())
    if not phrase:
        return ""
    single = _expand_color_code(phrase)
    if single:
        return single
    words = phrase.split()
    if not words:
        return ""
    parts: list[str] = []
    for token in words:
        word = re.sub(r"[^A-Za-z]", "", token).upper()
        if not word:
            return ""
        expanded = _expand_color_code(word)
        if expanded:
            parts.append(expanded)
        elif word in _COLOR_WORDS:
            parts.append(word.capitalize())
        else:
            return ""
    return " ".join(parts)


def _is_region_code(part: str) -> bool:
    return _is_region_token(part)


def _is_region_token(token: str) -> bool:
    raw = (token or "").strip().upper()
    if not raw:
        return False
    word = re.sub(r"[^A-Za-z]", "", raw)
    if word in _COLOR_WORDS or word in _COLOR_CODES:
        return False
    if word in _REGION_WORDS:
        return True
    if "-" in raw and _REGION_TOKEN_RE.match(raw):
        return True
    return bool(word.isalpha() and 2 <= len(word) <= 5 and word not in _MODEL_TOKEN_MAP)


def _split_comma_model_description(desc: str) -> tuple[str, str, str]:
    """GSX/Sickw: IPHONE 17 PRO MAX,NAUS,256GB,BLU hoặc ...,DEEP PURPLE"""
    desc = _normalize_model_description(desc)
    parts = [p.strip() for p in desc.split(",") if p.strip()]
    if len(parts) < 2:
        return "", "", ""

    model = _format_model_tokens(parts[0].split())
    capacity = ""
    color = ""

    for part in parts[1:]:
        cap_m = re.match(r"^(\d+)\s*(GB|TB)\b", part, re.IGNORECASE)
        if cap_m:
            capacity = f"{cap_m.group(1)} {cap_m.group(2).upper()}"
            continue
        color_val = _parse_color_phrase(part)
        if color_val:
            color = color_val
            continue
        if _is_region_code(part):
            continue

    return model, color, capacity


def _split_model_description(desc: str) -> tuple[str, str, str]:
    """Tách Model Description → (model gọn, màu, dung lượng)."""
    desc = re.sub(r"\s+", " ", _normalize_model_description(desc or "")).strip()
    if _looks_like_gsx_comma_desc(desc):
        model, color, capacity = _split_comma_model_description(desc)
        if model:
            return model, color, capacity

    capacity = ""
    color_words: list[str] = []
    model_tokens: list[str] = []
    tokens_list = desc.split()
    i = 0
    while i < len(tokens_list):
        token = tokens_list[i]
        cap_m = re.match(r"^(\d+)\s*(TB|GB)\b", token, re.IGNORECASE)
        if cap_m:
            capacity = f"{cap_m.group(1)} {cap_m.group(2).upper()}"
            i += 1
            continue

        if re.match(r"^A\d{4}(?:-[A-Z]{2,5})?$", token, re.IGNORECASE):
            i += 1
            continue

        if i + 1 < len(tokens_list):
            two = _parse_color_phrase(f"{token} {tokens_list[i + 1]}")
            if two:
                color_words.append(two)
                i += 2
                continue

        one = _parse_color_phrase(token)
        if one:
            color_words.append(one)
            i += 1
            continue

        word = re.sub(r"[^A-Za-z]", "", token).upper()
        if _is_region_token(token):
            i += 1
            continue
        if word and word in _REGION_WORDS:
            i += 1
            continue
        if not word and not any(ch.isdigit() for ch in token):
            i += 1
            continue
        model_tokens.append(token)
        i += 1

    model = _clean_model_suffixes(_format_model_tokens(model_tokens))
    color = color_words[-1] if color_words else ""
    return model, color, capacity


def _strip_trailing_color_codes(model: str) -> str:
    """Alias — dùng _clean_model_suffixes."""
    return _clean_model_suffixes(model)


def _format_model_tokens(tokens: list[str]) -> str:
    parts: list[str] = []
    for token in tokens:
        word = re.sub(r"[^A-Za-z]", "", token).upper()
        if word in _MODEL_TOKEN_MAP:
            parts.append(_MODEL_TOKEN_MAP[word])
        elif token.isdigit():
            parts.append(token)
        else:
            parts.append(token if token[:1].islower() else token.capitalize())
    return " ".join(parts).strip()


_SIMLOCK_KEYS = ("sim-lock status", "simlock status", "sim lock status")


def _parse_simlock_status(text: str) -> Optional[str]:
    """'Locked' nếu khóa mạng, 'Unlocked' nếu mở, None nếu không có field."""
    if not text:
        return None
    blob = _extract_result_json(text)
    if blob:
        value = _json_field_value(blob, "Sim-Lock Status", "Simlock Status", "Sim Lock Status")
        if value:
            low = value.lower()
            if "unlock" in low:
                return "Unlocked"
            if "lock" in low:
                return "Locked"
    plain = _strip_html_text(text)
    low = plain.lower()
    idx = -1
    klen = 0
    for key in _SIMLOCK_KEYS:
        idx = low.find(key)
        if idx != -1:
            klen = len(key)
            break
    if idx == -1:
        return None

    after = plain[idx + klen:]
    if ":" in after:
        after = after.split(":", 1)[1]
    value = after.split(";", 1)[0].splitlines()[0].strip().lower()

    if not value:
        return None
    if "unlock" in value:
        return "Unlocked"
    if "lock" in value:
        return "Locked"
    return None


_CARRIER_KEYS = ("locked carrier",)


_CARRIER_POLICY_SUFFIXES = (
    r"\s+Activation\s+Policy.*$",
    r"\s+Locked\s+Policy.*$",
    r"\s+Unlock(?:ed)?\s+Policy.*$",
)


def _clean_carrier_name(raw: str) -> str:
    """Chỉ giữ tên nhà mạng — bỏ mã policy, HTML, Sim-Lock Status."""
    if not raw:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    first = text.split("\n", 1)[0].split(";", 1)[0].strip()
    sim_idx = re.search(r"\bsim[- ]?lock\s*status\b", first, re.IGNORECASE)
    if sim_idx:
        first = first[:sim_idx.start()].strip().rstrip("-").strip()
    first = re.sub(r"^\d+\s*-\s*", "", first).strip()
    for pattern in _CARRIER_POLICY_SUFFIXES:
        first = re.sub(pattern, "", first, flags=re.IGNORECASE).strip()
    # GSX: "Japan SoftBank 2017 iPhone" → "Japan SoftBank"
    first = re.sub(
        r"\s+\d{4}\s+i(?:Phone|Pad)\b.*$",
        "",
        first,
        flags=re.IGNORECASE,
    ).strip()
    return first


def _parse_carrier(text: str) -> Optional[str]:
    """Tên nhà mạng từ Locked Carrier; None nếu không có field."""
    if not text:
        return None
    blob = _extract_result_json(text)
    if blob:
        value = _json_field_value(blob, "Locked Carrier", "Carrier")
        cleaned = _clean_carrier_name(value)
        if cleaned:
            return cleaned
    plain = _strip_html_text(text)
    low = plain.lower()
    raw_value = ""
    idx = -1
    klen = 0
    for key in _CARRIER_KEYS:
        idx = low.find(key)
        if idx != -1:
            klen = len(key)
            break
    if idx != -1:
        after = plain[idx + klen:]
        if ":" in after:
            after = after.split(":", 1)[1]
        raw_value = after.split("\n", 1)[0].split(";", 1)[0]
    else:
        m = re.search(
            r"\b\d+\s*-\s*.+?(?=\n|Sim-Lock\s*Status|;|$)",
            plain,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            raw_value = m.group(0)

    cleaned = _clean_carrier_name(raw_value)
    return cleaned or None


_FMI_KEYS = ("find my iphone", "find my ipad", "find my", "icloud lock", "fmi")


def _parse_fmi_status(text: str) -> Optional[str]:
    """'On' nếu FMI/iCloud đang bật, 'Off' nếu tắt, None nếu không có field."""
    if not text:
        return None
    blob = _extract_result_json(text)
    if blob:
        value = _json_field_value(
            blob,
            "iCloud Lock",
            "Find My iPhone",
            "Find My iPad",
            "Find My",
            "FMI",
        )
        if value:
            low = value.lower()
            if "off" in low or low in ("no", "clean", "unlocked"):
                return "Off"
            if "on" in low or low in ("yes", "locked", "lost"):
                return "On"
    plain = _strip_html_text(text)
    low = plain.lower()
    idx = -1
    klen = 0
    for key in _FMI_KEYS:
        idx = low.find(key)
        if idx != -1:
            klen = len(key)
            break
    if idx == -1:
        return None

    after = plain[idx + klen:]
    if ":" in after:
        after = after.split(":", 1)[1]
    value = after.split(";", 1)[0].splitlines()[0].strip().lower()

    if not value:
        return None
    if "off" in value or value in ("no", "clean", "unlocked"):
        return "Off"
    if "on" in value or value in ("yes", "locked", "lost"):
        return "On"
    return None


def _parse_replaced_notice(text: str) -> Optional[str]:
    """'replaced' nếu serial đã được thay thế (Notice GSX/Sickw)."""
    if not text:
        return None
    low = _strip_html_text(text).lower()
    if "has been replaced" in low and (
        "serial number for a product" in low or "notice:" in low
    ):
        return "replaced"
    return None


def _parse_activation_status(text: str) -> Optional[str]:
    """'Yes' nếu đã active, 'No' nếu chưa, None nếu không có field Activation Status."""
    if not text:
        return None
    plain = _strip_html_text(text)
    low = plain.lower()
    idx = low.find("activation status")
    if idx == -1:
        return None

    after = plain[idx + len("activation status"):]
    if ":" in after:
        after = after.split(":", 1)[1]
    value = after.split(";", 1)[0].splitlines()[0].strip().lower()

    if not value:
        return None
    if "not activated" in value or value in ("no", "not active", "inactive"):
        return "No"
    if "activated" in value or value in ("yes", "active"):
        return "Yes"
    return None


OnRecordResult = Callable[[DeviceRecord], None]
OnProgress = Callable[[str], None]


def _find_record_for_pending(
    records: list[DeviceRecord],
    row: PendingOrderRow,
) -> Optional[DeviceRecord]:
    by_id = {r.id: r for r in records if r.id is not None}
    if row.device_record_id in by_id:
        return by_id[row.device_record_id]

    serial = (row.serial or "").strip().upper()
    imei1 = (row.imei1 or "").strip()
    imei2 = (row.imei2 or "").strip()
    for record in records:
        if serial and (record.serial or "").strip().upper() == serial:
            return record
        if imei1 and (record.imei1 or "").strip() == imei1:
            return record
        if imei2 and (record.imei2 or "").strip() == imei2:
            return record
    return None


def _service_for_pending(row: PendingOrderRow) -> ServiceItem:
    service = find_service_by_id(row.service_id)
    if service is not None:
        return service
    return ServiceItem(
        server_id=row.service_id,
        name=row.service_name or f"Dịch vụ #{row.service_id}",
        credit=0,
    )


def _discover_server_pending(
    records: list[DeviceRecord],
    tracked_ids: set[int],
) -> list[tuple[PendingOrderRow, DeviceRecord, ServiceItem]]:
    res = list_imei_orders()
    if not res.ok or not res.orders:
        return []

    index: dict[str, list[DeviceRecord]] = {}
    for record in records:
        for key in _record_keys(record):
            index.setdefault(key, []).append(record)

    discovered: list[tuple[PendingOrderRow, DeviceRecord, ServiceItem]] = []
    consumed: set[int] = set()

    for order in res.orders:
        oid = int(order.get("id") or 0)
        status = int(order.get("status") or 0)
        if oid <= 0 or oid in tracked_ids or not _order_needs_polling(status):
            continue

        rec = _match_record(order, index, consumed)
        if rec is None or rec.id is None:
            continue

        service_id = int(order.get("service_id") or 0)
        service_name = str(order.get("service_name") or "").strip()
        service = find_service_by_id(service_id) if service_id else None
        if service is None:
            service = ServiceItem(
                server_id=service_id,
                name=service_name or f"Dịch vụ #{service_id}",
                credit=0,
            )

        timeout = service.provider_poll_timeout()
        created = str(order.get("created_at") or "").strip()
        row = PendingOrderRow(
            order_id=oid,
            device_record_id=rec.id,
            service_id=service.server_id,
            service_name=service.name,
            imei1=rec.imei1,
            imei2=rec.imei2,
            serial=rec.serial,
            started_at=created or datetime.now(timezone.utc).isoformat(),
            poll_timeout_sec=timeout,
        )
        _pending_db().save_pending_order(
            order_id=row.order_id,
            device_record_id=row.device_record_id,
            service_id=row.service_id,
            service_name=row.service_name,
            imei1=row.imei1,
            imei2=row.imei2,
            serial=row.serial,
            started_at=row.started_at,
            poll_timeout_sec=row.poll_timeout_sec,
        )
        discovered.append((row, rec, service))
        tracked_ids.add(oid)

    return discovered


def _resume_timeout_deadline(service: ServiceItem) -> float:
    """Mỗi lần mở lại app được chờ thêm một khoảng timeout đầy đủ."""
    return time.monotonic() + service.provider_poll_timeout()


_RESUME_STATUS_TIMEOUT_SEC = 120.0


def _handle_polled_order(
    order: dict[str, Any],
    pending: dict[int, tuple[DeviceRecord, ServiceItem, float]],
    db: DeviceDatabase,
    *,
    on_record_result: Optional[OnRecordResult] = None,
    allow_timeout: bool = True,
) -> bool:
    """Trả True nếu đơn đã xong và bỏ khỏi pending."""
    oid = int(order.get("id") or 0)
    item = pending.get(oid)
    if item is None or oid <= 0:
        return False

    record, svc, deadline = item
    status = int(order.get("status") or 0)

    if status in (ORDER_STATUS_DONE, ORDER_STATUS_DENIED):
        pending.pop(oid, None)
        db.delete_pending_order(oid)
        _finalize_order_note(record, svc, order)
        if on_record_result is not None:
            on_record_result(record)
        return True

    if allow_timeout and time.monotonic() >= deadline:
        if _order_needs_polling(status):
            _extend_resume_deadline(pending, oid, svc)
            _apply_resume_waiting_note(
                record,
                svc,
                order,
                on_record_result=on_record_result,
            )
        else:
            pending.pop(oid, None)
            db.delete_pending_order(oid)
            append_service_note(record, svc.name, "Hết thời gian chờ kết quả.")
            if on_record_result is not None:
                on_record_result(record)
        return False

    return False


def _fetch_missing_order_ids(
    requested: list[int],
    returned_orders: list[dict[str, Any]],
) -> list[int]:
    returned = {int(o.get("id") or 0) for o in returned_orders}
    return [oid for oid in requested if oid > 0 and oid not in returned]


def _poll_orders_status(
    order_ids: list[int],
    *,
    timeout: float = _RESUME_STATUS_TIMEOUT_SEC,
) -> ImeiOrderResult:
    if not order_ids:
        return ImeiOrderResult(ok=True, message="", orders=[])
    return fetch_orders_status(order_ids, timeout=timeout)


def _reconcile_pending_from_list(
    pending: dict[int, tuple[DeviceRecord, ServiceItem, float]],
    db: DeviceDatabase,
    *,
    on_record_result: Optional[OnRecordResult] = None,
) -> int:
    """Đồng bộ pending với GET /imei/orders — bắt đơn đã xong trên server."""
    res = list_imei_orders()
    if not res.ok or not res.orders:
        return 0

    by_id = {int(o.get("id") or 0): o for o in res.orders}
    done = 0
    for oid in list(pending.keys()):
        order = by_id.get(oid)
        if order is None:
            continue
        if _handle_polled_order(
            order,
            pending,
            db,
            on_record_result=on_record_result,
            allow_timeout=False,
        ):
            done += 1
    return done


def resume_pending_orders(
    records: list[DeviceRecord],
    *,
    on_record_result: Optional[OnRecordResult] = None,
    on_progress: Optional[OnProgress] = None,
) -> int:
    """Tiếp tục poll đơn chưa xong sau khi mở lại app. Chạy trên background thread."""
    cfg = load_api_config()
    if not cfg.enabled:
        return 0

    def report(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    db = _pending_db()
    stored = db.load_pending_orders()
    local_count = len(stored)
    tracked_ids = {row.order_id for row in stored}
    work: list[tuple[PendingOrderRow, DeviceRecord, ServiceItem, float]] = []

    for row in stored:
        record = _find_record_for_pending(records, row)
        if record is None:
            logger.info("Bỏ qua đơn #%s — không tìm thấy dòng IMEI local", row.order_id)
            db.delete_pending_order(row.order_id)
            report(f"Bỏ qua đơn #{row.order_id} — không còn dòng IMEI trên bảng.")
            continue
        service = _service_for_pending(row)
        timeout = service.provider_poll_timeout()
        db.save_pending_order(
            order_id=row.order_id,
            device_record_id=record.id or row.device_record_id,
            service_id=service.server_id,
            service_name=service.name,
            imei1=record.imei1,
            imei2=record.imei2,
            serial=record.serial,
            poll_timeout_sec=timeout,
        )
        work.append((row, record, service, _resume_timeout_deadline(service)))

    discovered = _discover_server_pending(records, tracked_ids)
    for row, record, service in discovered:
        timeout = service.provider_poll_timeout()
        db.save_pending_order(
            order_id=row.order_id,
            device_record_id=record.id or row.device_record_id,
            service_id=service.server_id,
            service_name=service.name,
            imei1=record.imei1,
            imei2=record.imei2,
            serial=record.serial,
            poll_timeout_sec=timeout,
        )
        work.append((row, record, service, _resume_timeout_deadline(service)))

    if not work:
        return 0

    pending: dict[int, tuple[DeviceRecord, ServiceItem, float]] = {
        row.order_id: (record, service, deadline)
        for row, record, service, deadline in work
    }

    logger.info("Tiếp tục %s đơn IMEI chưa xong", len(pending))
    extra = len(discovered)
    if extra > 0:
        report(
            f"Đang lấy kết quả {len(pending)} đơn IMEI "
            f"({local_count} local + {extra} từ server)…"
        )
    else:
        report(f"Đang lấy kết quả {len(pending)} đơn IMEI chưa xong…")

    bootstrap_ids = list(pending.keys())
    for j in range(0, len(bootstrap_ids), 500):
        chunk = bootstrap_ids[j:j + 500]
        bootstrap = _poll_orders_status(chunk)
        if not bootstrap.ok or not bootstrap.orders:
            continue
        for order in bootstrap.orders:
            if _handle_polled_order(
                order,
                pending,
                db,
                on_record_result=on_record_result,
                allow_timeout=False,
            ):
                continue
            oid = int(order.get("id") or 0)
            item = pending.get(oid)
            if item is None:
                continue
            record, svc, _ = item
            if _order_needs_polling(int(order.get("status") or 0)):
                _apply_resume_waiting_note(
                    record,
                    svc,
                    order,
                    on_record_result=on_record_result,
                )
    _reconcile_pending_from_list(pending, db, on_record_result=on_record_result)
    by_service: dict[int, list[int]] = {}
    for oid, (_, service, _) in pending.items():
        by_service.setdefault(service.server_id, []).append(oid)

    round_num = 0
    consecutive_failures = 0
    while pending:
        round_num += 1
        report(f"Đang poll {len(pending)} đơn IMEI — vòng {round_num}…")
        fetch_ok = False
        max_interval = 1.5

        for service_id, order_ids in by_service.items():
            active_ids = [oid for oid in order_ids if oid in pending]
            if not active_ids:
                continue
            _, service, _ = pending[active_ids[0]]
            max_interval = max(max_interval, service.provider_poll_interval())

            for j in range(0, len(active_ids), 500):
                chunk = active_ids[j:j + 500]
                res = _poll_orders_status(chunk)
                if not res.ok or not res.orders:
                    logger.warning(
                        "Resume poll lỗi (service %s): %s",
                        service_id,
                        res.message or "không có dữ liệu",
                    )
                    continue
                fetch_ok = True
                consecutive_failures = 0
                orders_out = list(res.orders or [])
                finished_round = 0
                for order in orders_out:
                    finished = _handle_polled_order(
                        order,
                        pending,
                        db,
                        on_record_result=on_record_result,
                    )
                    if finished:
                        finished_round += 1
                    if not finished and (round_num == 1 or round_num % 6 == 0):
                        oid = int(order.get("id") or 0)
                        item = pending.get(oid)
                        if item is not None:
                            record, svc, _ = item
                            if _order_needs_polling(int(order.get("status") or 0)):
                                _apply_resume_waiting_note(
                                    record,
                                    svc,
                                    order,
                                    on_record_result=on_record_result,
                                )
                missing = _fetch_missing_order_ids(chunk, orders_out)
                for k in range(0, len(missing), 50):
                    retry = _poll_orders_status(missing[k:k + 50])
                    if not retry.ok or not retry.orders:
                        continue
                    for order in retry.orders:
                        _handle_polled_order(
                            order,
                            pending,
                            db,
                            on_record_result=on_record_result,
                        )
                if finished_round > 0:
                    logger.info(
                        "Resume vòng %s: +%s kết quả, còn %s đơn",
                        round_num,
                        finished_round,
                        len(pending),
                    )
                    report(
                        f"Đã lấy {finished_round} kết quả — còn {len(pending)} đơn…"
                    )

        if not fetch_ok:
            consecutive_failures += 1
            report(
                f"Không lấy được trạng thái đơn — thử lại ({consecutive_failures})…"
            )
            time.sleep(min(30.0, 5.0 * consecutive_failures))
            if consecutive_failures >= 12:
                logger.error("Dừng resume sau %s lỗi poll liên tiếp", consecutive_failures)
                report("Dừng tiếp tục đơn — không kết nối được server.")
                break
            continue

        if round_num % 3 == 0:
            reconciled = _reconcile_pending_from_list(
                pending,
                db,
                on_record_result=on_record_result,
            )
            if reconciled > 0:
                report(f"Đã lấy {reconciled} kết quả từ danh sách server…")

        if pending:
            time.sleep(max_interval)

    return len(work)


def run_auto_services_batch(
    records: list[DeviceRecord],
    service_ids: list[int],
    *,
    on_record_result: OnRecordResult,
    poll_interval: float = 2.0,
    poll_timeout: float = 900.0,
    chunk_size: int = 100,
) -> None:
    """Chạy dịch vụ cho lô lớn: bulk submit + poll lô. Gọi từ background thread.

    `on_record_result(record)` được gọi mỗi khi một IMEI có kết quả mới (đã ghi
    vào note) để UI cập nhật dần.
    """
    cfg = load_api_config()
    if not cfg.enabled:
        logger.warning("Batch services: API chưa cấu hình")
        return

    for service_id in service_ids:
        service = find_service_by_id(service_id)
        if service is None:
            continue
        if service.is_save_imei:
            continue

        if service.is_simlock:
            for record in records:
                if not (record.imei1 or record.imei2 or record.serial):
                    continue
                line = _run_simlock(record, service)
                append_service_note(record, line.service_name, line.text)
                if line.ok:
                    simlock_val = _simlock_from_note_line(line.text)
                    if simlock_val:
                        record.simlock = simlock_val
                on_record_result(record)
            continue

        timeout = (
            service.provider_poll_timeout()
            if service.uses_external_provider
            else poll_timeout
        )
        _batch_order_service(
            records,
            service,
            on_record_result,
            poll_interval=poll_interval,
            poll_timeout=timeout,
            chunk_size=chunk_size,
        )


def _batch_order_service(
    records: list[DeviceRecord],
    service: ServiceItem,
    on_record_result: OnRecordResult,
    *,
    poll_interval: float,
    poll_timeout: float,
    chunk_size: int,
) -> None:
    valid = [r for r in records if (r.imei1 or r.imei2 or r.serial)]
    if not valid:
        return

    index: dict[str, list[DeviceRecord]] = {}
    for r in valid:
        for key in _record_keys(r):
            index.setdefault(key, []).append(r)

    consumed: set[int] = set()
    pending: dict[int, DeviceRecord] = {}

    for start in range(0, len(valid), chunk_size):
        chunk = valid[start:start + chunk_size]
        devices = [
            {"imei1": r.imei1, "imei2": r.imei2, "serial": r.serial} for r in chunk
        ]
        res = submit_imei_orders_bulk(devices, service_id=service.server_id)

        if not res.orders:
            detail = res.message or "Gửi lô thất bại."
            if res.errors:
                first = res.errors[0]
                if isinstance(first, dict) and first.get("message"):
                    detail = str(first["message"])
            for r in chunk:
                append_service_note(r, service.name, detail)
                on_record_result(r)
            continue

        for order in res.orders:
            oid = int(order.get("id") or 0)
            rec = _match_record(order, index, consumed)
            if rec is None or oid <= 0:
                continue
            status = int(order.get("status") or 0)
            if status in (ORDER_STATUS_DONE, ORDER_STATUS_DENIED):
                _finalize_order_note(rec, service, order)
                on_record_result(rec)
            else:
                pending[oid] = rec
                _track_pending_order(rec, service, oid, poll_timeout=poll_timeout)

    interval = service.provider_poll_interval()
    deadline = time.monotonic() + poll_timeout
    while pending and time.monotonic() < deadline:
        ids = list(pending.keys())
        for j in range(0, len(ids), 500):
            res = fetch_orders_status(ids[j:j + 500])
            if not res.ok or not res.orders:
                continue
            for order in res.orders:
                oid = int(order.get("id") or 0)
                rec = pending.get(oid)
                if rec is None:
                    continue
                status = int(order.get("status") or 0)
                if status in (ORDER_STATUS_DONE, ORDER_STATUS_DENIED):
                    pending.pop(oid, None)
                    _untrack_pending_order(oid)
                    _finalize_order_note(rec, service, order)
                    on_record_result(rec)
        if pending and time.monotonic() < deadline:
            time.sleep(interval)

    for oid, rec in list(pending.items()):
        _untrack_pending_order(oid)
        append_service_note(rec, service.name, "Hết thời gian chờ kết quả.")
        on_record_result(rec)


def _record_keys(record: DeviceRecord) -> list[str]:
    keys: list[str] = []
    if record.serial:
        keys.append(f"serial:{record.serial.upper()}")
    if record.imei1:
        keys.append(f"imei1:{record.imei1}")
    if record.imei2:
        keys.append(f"imei2:{record.imei2}")
    return keys


def _match_record(
    order: dict[str, Any],
    index: dict[str, list[DeviceRecord]],
    consumed: set[int],
) -> Optional[DeviceRecord]:
    keys: list[str] = []
    serial = str(order.get("serial") or "").upper()
    if serial:
        keys.append(f"serial:{serial}")
    if order.get("imei1"):
        keys.append(f"imei1:{order['imei1']}")
    if order.get("imei2"):
        keys.append(f"imei2:{order['imei2']}")
    primary = str(order.get("imei") or "")
    if primary:
        keys.append(f"serial:{primary.upper()}")
        keys.append(f"imei1:{primary}")

    for key in keys:
        for rec in index.get(key, []):
            if id(rec) not in consumed:
                consumed.add(id(rec))
                return rec
    return None


_SERVICE_FIELD_RULES: tuple[tuple[str, str], ...] = (
    ("simlock", "simlock"),
    ("activation", "active"),
    ("active", "active"),
    ("fmi", "fmi"),
    ("find my", "fmi"),
    ("icloud", "fmi"),
    ("carrier", "carrier"),
    ("nhà mạng", "carrier"),
    ("model", "model"),
    ("màu", "color"),
    ("color", "color"),
    ("storage", "storage_capacity"),
    ("dung lượng", "storage_capacity"),
    ("bộ nhớ", "storage_capacity"),
)


def service_target_field(service_name: str) -> Optional[str]:
    low = (service_name or "").strip().lower()
    if not low:
        return None
    for keyword, field in _SERVICE_FIELD_RULES:
        if keyword in low:
            return field
    return None


def _parsed_field_value(field: str, reason: str) -> str:
    if field == "active":
        return analyze_active(reason) or ""
    if field == "fmi":
        return analyze_fmi(reason) or ""
    if field == "simlock":
        return analyze_simlock(reason) or ""
    if field == "carrier":
        return analyze_carrier(reason) or ""
    if field == "model":
        return analyze_model(reason) or ""
    if field == "color":
        return analyze_color(reason) or ""
    if field == "storage_capacity":
        return analyze_storage(reason) or ""
    return ""


def apply_denial_to_field(
    record: DeviceRecord,
    service_name: str,
    reason: str,
) -> bool:
    field = service_target_field(service_name)
    if field is None:
        return False
    parsed = _parsed_field_value(field, reason)
    text = parsed or (reason or "Đơn bị từ chối.").strip()[:120]
    setattr(record, field, text)
    return True


def _apply_server_parsed(record: DeviceRecord, parsed: dict[str, Any]) -> bool:
    """Áp kết quả parse SẴN từ server (nguồn chân lý) vào record.

    Server đã parse theo quy tắc cấu hình được (rule động) ngay khi đơn có kết quả,
    nên app dùng thẳng thay vì parse lại cục bộ. Trả True nếu có thay đổi.
    """
    if not isinstance(parsed, dict) or not parsed:
        return False

    changed = False

    def _set(attr: str, raw: Any) -> None:
        nonlocal changed
        value = str(raw or "").strip()
        if value and getattr(record, attr, "") != value:
            setattr(record, attr, value)
            changed = True

    for attr in ("simlock", "fmi", "active", "carrier", "mdm", "color", "storage_capacity"):
        if attr in parsed:
            _set(attr, parsed.get(attr))

    if "model" in parsed:
        model_val = _finalize_model_name(str(parsed.get("model") or ""))
        if model_val:
            _set("model", model_val)
        elif record.model and not _is_plausible_model(record.model):
            record.model = ""
            changed = True

    # IMEI2/serial: cẩn trọng, không ghi đè nhầm định danh đang có.
    imei2_val = _clean_imei(str(parsed.get("imei2") or ""))
    if (
        imei2_val
        and imei2_val != (record.imei1 or "").strip()
        and _clean_imei(record.imei2) != imei2_val
    ):
        record.imei2 = imei2_val
        changed = True

    serial_val = _clean_serial(str(parsed.get("serial") or ""))
    if serial_val and _clean_serial(record.serial) != serial_val:
        record.serial = serial_val
        changed = True

    return changed


def apply_server_parsed_to_records(records: list[DeviceRecord]) -> set[int]:
    """Lấy `parsed` từ đơn IMEI trên server và điền cột check (nguồn chân lý)."""
    if not records or not load_api_config().enabled:
        return set()

    res = list_imei_orders()
    if not res.ok or not res.orders:
        return set()

    index: dict[str, list[DeviceRecord]] = {}
    for record in records:
        for key in _record_keys(record):
            index.setdefault(key, []).append(record)

    merged: dict[int, dict[str, Any]] = {}
    for order in sorted(res.orders, key=lambda o: int(o.get("id") or 0)):
        status = int(order.get("status") or 0)
        if status not in (ORDER_STATUS_DONE, ORDER_STATUS_DENIED):
            continue
        parsed = order.get("parsed")
        if not isinstance(parsed, dict) or not parsed:
            continue
        record = _match_record(order, index, set())
        if record is None:
            continue
        bucket = merged.setdefault(id(record), {})
        bucket.update(parsed)

    changed: set[int] = set()
    for record in records:
        parsed = merged.get(id(record))
        if parsed and _apply_server_parsed(record, parsed):
            changed.add(id(record))
    return changed


def analyze_records(records: list[DeviceRecord]) -> int:
    """Nút Phân tích: server `parsed` + model/màu/bộ nhớ/IMEI2/serial từ ghi chú."""
    if not records:
        return 0

    server_changed = apply_server_parsed_to_records(records)
    updated = 0
    for record in records:
        local_changed = apply_parsed_fields_to_record(record)
        if local_changed or id(record) in server_changed:
            updated += 1
    return updated


def apply_parsed_check_fields_from_note(record: DeviceRecord) -> bool:
    """Không parse cục bộ cột check — dùng `parsed` từ server qua `apply_order_result`."""
    return False


def apply_parsed_fields_to_record(record: DeviceRecord) -> bool:
    """Phân tích Ghi chú (nút Phân tích) → model, màu, bộ nhớ, cột check; IMEI2/serial."""
    source = (record.note or "").strip()
    if not source:
        return False

    changed = False
    model_val = analyze_model(source)
    if model_val:
        if model_val != record.model:
            record.model = model_val
            changed = True
    elif record.model and not _is_plausible_model(record.model):
        record.model = ""
        changed = True
    color_val = analyze_color(source)
    if color_val and color_val != record.color:
        record.color = color_val
        changed = True
    storage_val = analyze_storage(source)
    if storage_val and storage_val != record.storage_capacity:
        record.storage_capacity = storage_val
        changed = True
    imei2_val = analyze_imei2(source)
    if imei2_val and imei2_val != (record.imei1 or "").strip():
        if _clean_imei(record.imei2) != imei2_val:
            record.imei2 = imei2_val
            changed = True
    serial_val = analyze_serial(source)
    if serial_val and _clean_serial(record.serial) != serial_val:
        record.serial = serial_val
        changed = True
    return changed


def apply_order_result(
    record: DeviceRecord,
    service_name: str,
    order: dict[str, Any],
) -> None:
    status = int(order.get("status") or 0)
    text = _format_order_result(order.get("result"))
    parsed = order.get("parsed")
    if status == ORDER_STATUS_DENIED:
        text = text or str(order.get("status_label") or "").strip() or "Đơn bị từ chối."
        append_service_note(record, service_name, text)
        # Ưu tiên parse sẵn từ server; nếu không có thì trích từ lý do từ chối.
        if not (isinstance(parsed, dict) and parsed and _apply_server_parsed(record, parsed)):
            apply_denial_to_field(record, service_name, text)
        return
    if status == ORDER_STATUS_PROCESSING:
        append_service_note(
            record,
            service_name,
            text or str(order.get("status_label") or "").strip() or "Đang chờ nhà cung cấp…",
        )
        return
    if status == ORDER_STATUS_DONE and not text:
        text = "Hoàn thành (chưa có chi tiết kết quả)."
    elif not text:
        text = str(order.get("status_label") or "").strip() or "Đã gửi đơn."
    append_service_note(record, service_name, text)
    if isinstance(parsed, dict) and parsed:
        _apply_server_parsed(record, parsed)
    _supplement_identity_from_note(record)


def _supplement_identity_from_note(record: DeviceRecord) -> None:
    """Bổ sung IMEI2/model/màu/bộ nhớ từ toàn bộ ghi chú (gộp nhiều dịch vụ)."""
    source = (record.note or "").strip()
    if not source:
        return
    imei2_val = analyze_imei2(source)
    if (
        imei2_val
        and imei2_val != (record.imei1 or "").strip()
        and _clean_imei(record.imei2) != imei2_val
    ):
        record.imei2 = imei2_val
    model_val = analyze_model(source)
    if model_val:
        record.model = model_val
    color_val = analyze_color(source)
    if color_val:
        record.color = color_val
    storage_val = analyze_storage(source)
    if storage_val:
        record.storage_capacity = storage_val
    serial_val = analyze_serial(source)
    if serial_val and _clean_serial(record.serial) != serial_val:
        record.serial = serial_val


def _finalize_order_note(
    record: DeviceRecord, service: ServiceItem, order: dict[str, Any]
) -> None:
    apply_order_result(record, service.name, order)


def _run_one_service(
    record: DeviceRecord,
    service: ServiceItem,
    *,
    poll_interval: float,
    poll_timeout: float,
) -> Optional[AutoServiceLine]:
    if service.is_save_imei:
        return None

    if service.is_simlock:
        return _run_simlock(record, service)

    if service.uses_external_provider:
        return _run_provider_order(
            record,
            service,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
        )

    return _run_generic_order(record, service)


def _run_simlock(record: DeviceRecord, service: ServiceItem) -> AutoServiceLine:
    check = fetch_simlock(record)
    if check is None:
        return AutoServiceLine(
            service_id=service.server_id,
            service_name=service.name,
            ok=False,
            text="Thiếu Serial/IMEI 1 hoặc chưa đăng nhập API.",
        )

    if not check.ok:
        return AutoServiceLine(
            service_id=service.server_id,
            service_name=service.name,
            ok=False,
            text=check.message or "Kiểm tra simlock thất bại.",
        )

    simlock = (check.simlock or "").strip() or "Không xác định"
    return AutoServiceLine(
        service_id=service.server_id,
        service_name=service.name,
        ok=True,
        text=simlock,
    )


def _submit_order(record: DeviceRecord, service: ServiceItem) -> ImeiOrderResult:
    return submit_imei_order(
        imei1=record.imei1,
        imei2=record.imei2,
        serial=record.serial,
        service_id=service.server_id,
    )


def _poll_order_status(order_id: int) -> SickwOrderPollResult:
    res = fetch_orders_status([order_id])
    if not res.ok or not res.orders:
        return SickwOrderPollResult(
            ok=False,
            message=res.message or "Không lấy được trạng thái đơn.",
        )

    order = res.orders[0]
    status = int(order.get("status") or 0)
    result = order.get("result")

    return SickwOrderPollResult(
        ok=True,
        message=str(res.message or ""),
        completed=status == ORDER_STATUS_DONE,
        failed=status == ORDER_STATUS_DENIED,
        order=order,
        result=result,
        credits=int(res.credits or 0),
    )


def _finalize_service_order(
    record: DeviceRecord,
    service: ServiceItem,
    order: dict[str, Any],
    *,
    ok: bool,
    fallback_text: str = "",
) -> AutoServiceLine:
    apply_order_result(record, service.name, order)
    status = int(order.get("status") or 0)
    text = _format_order_result(order.get("result"))
    if not text:
        text = fallback_text or str(order.get("status_label") or "").strip()
    if status == ORDER_STATUS_DENIED and not text:
        text = "Đơn bị từ chối."
    return AutoServiceLine(
        service_id=service.server_id,
        service_name=service.name,
        ok=ok,
        text=text or "Hoàn thành.",
        record_updated=True,
    )


def _run_provider_order(
    record: DeviceRecord,
    service: ServiceItem,
    *,
    poll_interval: float,
    poll_timeout: float,
) -> AutoServiceLine:
    provider = service.provider_label()

    if not (record.imei1 or record.imei2 or record.serial):
        return AutoServiceLine(
            service_id=service.server_id,
            service_name=service.name,
            ok=False,
            text="Thiếu IMEI/Serial.",
        )

    submitted = _submit_order(record, service)
    if not submitted.ok or not submitted.order:
        return AutoServiceLine(
            service_id=service.server_id,
            service_name=service.name,
            ok=False,
            text=submitted.message or f"Gửi đơn {provider} thất bại.",
        )

    order = submitted.order
    order_id = int(order.get("id") or 0)
    status = int(order.get("status") or 0)

    if status == ORDER_STATUS_DONE:
        return _finalize_service_order(record, service, order, ok=True)

    if status == ORDER_STATUS_DENIED:
        return _finalize_service_order(
            record,
            service,
            order,
            ok=False,
            fallback_text=submitted.message or f"{provider} từ chối đơn.",
        )

    if order_id <= 0:
        return AutoServiceLine(
            service_id=service.server_id,
            service_name=service.name,
            ok=False,
            text="Server không trả ID đơn.",
        )

    interval = service.provider_poll_interval()
    deadline = time.monotonic() + poll_timeout
    last_message = submitted.message
    poll: SickwOrderPollResult | None = None
    _track_pending_order(record, service, order_id, poll_timeout=poll_timeout)

    try:
        while time.monotonic() < deadline:
            poll = _poll_order_status(order_id)
            last_message = poll.message or last_message

            if poll.failed:
                denied_order = poll.order or {"id": order_id, "status": ORDER_STATUS_DENIED, "result": poll.result}
                return _finalize_service_order(
                    record,
                    service,
                    denied_order,
                    ok=False,
                    fallback_text=last_message or f"{provider} từ chối đơn.",
                )

            if poll.completed:
                done_order = poll.order or {"id": order_id, "status": ORDER_STATUS_DONE, "result": poll.result}
                return _finalize_service_order(record, service, done_order, ok=True)

            time.sleep(interval)
    finally:
        _untrack_pending_order(order_id)

    return AutoServiceLine(
        service_id=service.server_id,
        service_name=service.name,
        ok=False,
        text=f"Hết thời gian chờ {provider} (#{order_id}). {last_message}".strip(),
    )


def _run_generic_order(record: DeviceRecord, service: ServiceItem) -> AutoServiceLine:
    if not (record.imei1 or record.imei2 or record.serial):
        return AutoServiceLine(
            service_id=service.server_id,
            service_name=service.name,
            ok=False,
            text="Thiếu IMEI/Serial.",
        )

    submitted = _submit_order(record, service)

    if not submitted.ok:
        return AutoServiceLine(
            service_id=service.server_id,
            service_name=service.name,
            ok=False,
            text=submitted.message or "Gửi đơn thất bại.",
        )

    order = submitted.order or {}
    status = int(order.get("status") or 0)
    result_raw = order.get("result")

    if status == ORDER_STATUS_DONE and result_raw:
        return _finalize_service_order(record, service, order, ok=True)

    if status == ORDER_STATUS_DENIED:
        return _finalize_service_order(
            record,
            service,
            order,
            ok=False,
            fallback_text=submitted.message or "Đơn bị từ chối.",
        )

    order_id = int(order.get("id") or 0)
    status_label = order.get("status_label") or f"status {status}"
    charged = "đã trừ VNĐ" if submitted.charged else "không trừ VNĐ"
    extra = ""
    if status == ORDER_STATUS_PENDING and not service.uses_external_provider:
        extra = " — chưa cấu hình SERVICE ID nhà cung cấp trên server (Filament → Dịch vụ)"
    if _order_needs_polling(status) and order_id > 0:
        _track_pending_order(
            record,
            service,
            order_id,
            poll_timeout=service.provider_poll_timeout(),
        )
    return AutoServiceLine(
        service_id=service.server_id,
        service_name=service.name,
        ok=True,
        text=f"Đơn #{order_id} — {status_label} ({charged}){extra}",
    )


def _format_order_result(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, dict):
        if "raw" in result and len(result) == 1:
            return str(result["raw"])
        parts = [f"{key}: {value}" for key, value in result.items() if value not in (None, "")]
        return "; ".join(parts)
    if isinstance(result, str):
        raw = result.strip()
        if raw.startswith("{") or raw.startswith("["):
            try:
                parsed = json.loads(raw)
                return _format_order_result(parsed)
            except json.JSONDecodeError:
                pass
        return raw
    return str(result)


def _simlock_from_note_line(text: str) -> str:
    if not text:
        return ""
    head = text.split("(", 1)[0].strip()
    return head if head and head not in ("Không xác định",) else ""
