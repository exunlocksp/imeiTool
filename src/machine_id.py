"""ID máy ổn định — dùng cho kích hoạt license."""

from __future__ import annotations

import hashlib
import sys
import uuid
from pathlib import Path

_CACHE_PATH = Path.home() / ".taoden-imei-machine-id"


def get_machine_id() -> str:
    cached = _read_cached()
    if cached:
        return cached

    raw = _platform_fingerprint()
    machine_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    try:
        _CACHE_PATH.write_text(machine_id, encoding="utf-8")
    except OSError:
        pass
    return machine_id


def _read_cached() -> str:
    try:
        text = _CACHE_PATH.read_text(encoding="utf-8").strip()
        return text if len(text) >= 16 else ""
    except OSError:
        return ""


def _platform_fingerprint() -> str:
    parts: list[str] = [sys.platform]
    if sys.platform == "darwin":
        try:
            import subprocess

            out = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            for line in out.stdout.splitlines():
                if "IOPlatformUUID" in line:
                    parts.append(line.strip())
                    break
        except Exception:
            parts.append(str(uuid.getnode()))
    elif sys.platform == "win32":
        try:
            import winreg  # type: ignore[import-untyped]

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            ) as key:
                parts.append(str(winreg.QueryValueEx(key, "MachineGuid")[0]))
        except Exception:
            parts.append(str(uuid.getnode()))
    else:
        parts.append(str(uuid.getnode()))
    return "|".join(parts)
