#!/usr/bin/env python3
"""Tạo PDF hướng dẫn sử dụng Taoden IMEI Tool (Pillow)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = PROJECT_ROOT / "docs" / "Huong-dan-su-dung.pdf"

PAGE_W = 1240
PAGE_H = 1754
MARGIN_X = 72
MARGIN_Y = 80
MARGIN_BOTTOM = 72
LINE_GAP = 8

COLOR_TITLE = (26, 115, 232)
COLOR_HEADING = (33, 37, 41)
COLOR_BODY = (55, 65, 81)
COLOR_MUTED = (107, 114, 128)
COLOR_ACCENT = (180, 83, 9)


def _font_paths() -> list[Path]:
    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates += [
            Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
            Path("/System/Library/Fonts/PingFang.ttc"),
            Path("/Library/Fonts/Arial Unicode.ttf"),
        ]
    elif sys.platform == "win32":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        candidates += [
            windir / "Fonts" / "arial.ttf",
            windir / "Fonts" / "segoeui.ttf",
        ]
    else:
        candidates += [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
        ]
    return candidates


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _font_paths():
        if not path.is_file():
            continue
        try:
            if path.suffix.lower() == ".ttc":
                return ImageFont.truetype(str(path), size=size, index=0)
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if font.getlength(trial) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


class _Paginator:
    def __init__(self) -> None:
        self.pages: list[Image.Image] = []
        self._new_page()
        self.body_font = _load_font(20)
        self.bold_font = _load_font(20, bold=True)
        self.heading_font = _load_font(26)
        self.title_font = _load_font(34)
        self.small_font = _load_font(16)
        self.max_w = PAGE_W - 2 * MARGIN_X
        self.y = MARGIN_Y

    def _new_page(self) -> None:
        page = Image.new("RGB", (PAGE_W, PAGE_H), "white")
        self.pages.append(page)
        self.draw = ImageDraw.Draw(page)
        self.y = MARGIN_Y

    def _ensure(self, height: int) -> None:
        if self.y + height > PAGE_H - MARGIN_BOTTOM:
            self._new_page()

    def title(self, text: str) -> None:
        self._ensure(60)
        self.draw.text((MARGIN_X, self.y), text, fill=COLOR_TITLE, font=self.title_font)
        self.y += 52

    def subtitle(self, text: str) -> None:
        self._ensure(36)
        self.draw.text((MARGIN_X, self.y), text, fill=COLOR_MUTED, font=self.small_font)
        self.y += 40

    def heading(self, text: str) -> None:
        self._ensure(44)
        self.y += 12
        self.draw.text((MARGIN_X, self.y), text, fill=COLOR_HEADING, font=self.heading_font)
        self.y += 38

    def paragraph(self, text: str) -> None:
        for line in _wrap(text, self.body_font, self.max_w):
            self._ensure(28)
            self.draw.text((MARGIN_X, self.y), line, fill=COLOR_BODY, font=self.body_font)
            self.y += 24 + LINE_GAP
        self.y += 4

    def bullet(self, text: str) -> None:
        indent = MARGIN_X + 22
        bullet_w = self.max_w - 22
        lines = _wrap(text, self.body_font, bullet_w)
        for i, line in enumerate(lines):
            self._ensure(28)
            if i == 0:
                self.draw.text((MARGIN_X + 4, self.y), "•", fill=COLOR_ACCENT, font=self.body_font)
            self.draw.text((indent, self.y), line, fill=COLOR_BODY, font=self.body_font)
            self.y += 24 + LINE_GAP
        self.y += 2

    def shortcut(self, keys: str, action: str) -> None:
        self._ensure(28)
        self.draw.text((MARGIN_X + 4, self.y), keys, fill=COLOR_TITLE, font=self.bold_font)
        key_w = self.bold_font.getlength(keys + "  ")
        self.draw.text((MARGIN_X + 4 + key_w, self.y), action, fill=COLOR_BODY, font=self.body_font)
        self.y += 28 + LINE_GAP

    def footer_note(self) -> None:
        note = "Taoden.vn · tool.taoden.vn · Hỗ trợ Zalo: 0967609909"
        for page in self.pages:
            d = ImageDraw.Draw(page)
            d.text((MARGIN_X, PAGE_H - 48), note, fill=COLOR_MUTED, font=self.small_font)


def _content(p: _Paginator) -> None:
    p.title("Taoden IMEI Tool")
    p.subtitle("Hướng dẫn sử dụng · Phiên bản 1.0")

    p.paragraph(
        "Phần mềm giúp cửa hàng đọc IMEI, Serial, Model thiết bị Apple qua USB hoặc "
        "ảnh chụp màn hình, chạy dịch vụ check thông tin, xuất Excel/Text và in nhãn có mã vạch."
    )

    p.heading("1. Cài đặt và mở app lần đầu")
    p.bullet("macOS: kéo Taoden IMEI Tool.app vào Applications, double-click để mở.")
    p.bullet("Lần đầu macOS có thể chặn Gatekeeper: chuột phải → Open → Open.")
    p.bullet("Windows: giải nén thư mục, chạy Taoden IMEI Tool.exe.")
    p.bullet("Cắm iPhone cần driver Apple (iTunes hoặc Apple Devices trên Windows).")

    p.heading("2. Giao diện chính")
    p.bullet("Bảng giữa: danh sách máy (IMEI, Serial, Model, Simlock, FMI, …).")
    p.bullet("Panel phải: chi tiết dòng đang chọn, nút In nhãn.")
    p.bullet("Thanh lọc trên bảng: tìm kiếm, lọc Simlock / FMI / Active.")
    p.bullet("Cột tick (☑): chọn dòng để in, xuất hoặc xóa.")
    p.bullet("Dữ liệu tự lưu — tắt app vẫn giữ danh sách.")

    p.heading("3. Tài khoản API (bắt buộc cho dịch vụ online)")
    p.bullet("Menu Cài đặt → Tài khoản API…")
    p.bullet("Nhập email và mã kích hoạt (API token) lấy từ website tool.taoden.vn.")
    p.bullet("Đăng nhập Google trên web → copy token → dán vào app.")
    p.bullet("Sau khi xác thực, thanh trạng thái hiện shop và số dư VNĐ.")

    p.heading("4. Đọc qua USB (khuyên dùng)")
    p.bullet("Mở app, cắm iPhone/iPad bằng cáp.")
    p.bullet("Trên iPhone: mở khóa → bấm Tin cậy máy tính này.")
    p.bullet("Vài giây sau, dòng mới xuất hiện (Nguồn: USB).")
    p.bullet("Cắm lại cùng máy: app cập nhật dòng cũ, không tạo trùng serial.")
    p.bullet("Rút cáp: dữ liệu vẫn giữ trong bảng.")

    p.heading("5. Nhập liệu khác")
    p.shortcut("⌘I / Ctrl+I", "Nhập liệu → Đọc từ ảnh…")
    p.paragraph(
        "Chụp màn hình Cài đặt → Cài đặt chung → Giới thiệu (có IMEI & Serial). "
        "Chọn ảnh hoặc dán ảnh (⌘V), app OCR tự đọc."
    )
    p.shortcut("⌘T / Ctrl+T", "Nhập liệu → Phân tích văn bản…")
    p.paragraph("Dán text copy từ màn hình iPhone hoặc tin nhắn.")
    p.shortcut("⌘L / Ctrl+L", "Nhập liệu → Thêm theo dòng…")
    p.paragraph("Dán nhiều dòng IMEI/Serial, mỗi dòng một máy.")

    p.heading("6. Làm việc với bảng")
    p.bullet("Click ô để sửa trực tiếp (Model, Hình thức, Ghi chú…).")
    p.bullet("Click tiêu đề cột để sắp xếp; click cột tick để chọn/bỏ chọn tất cả.")
    p.bullet("Shift+click: chọn dải dòng. Ctrl/⌘+click: tick từng dòng.")
    p.bullet("Chuột phải trên bảng: Xóa dòng đã tick / Xóa tất cả.")
    p.bullet("Menu Bảng → Cột bảng & in nhãn…: ẩn/hiện cột.")

    p.heading("7. Dịch vụ check thông tin")
    p.bullet("Dịch vụ → Check Lock Quốc Tế Miễn Free: check simlock Albert (có quota miễn phí).")
    p.bullet("Tick dòng cần check → mở hộp thoại → Chạy.")
    p.bullet("Dịch vụ → Dịch vụ khác: chọn dịch vụ trả phí (iCloud, bảo hành, nhà mạng…).")
    p.bullet("Kết quả ghi vào cột bảng và mục Ghi chú; đơn chạy nền, tắt app vẫn tiếp tục khi mở lại.")
    p.paragraph("Dòng đang xử lý có thể nhấp nháy; xong sẽ tự dừng.")

    p.heading("8. Xuất dữ liệu")
    p.shortcut("Tệp → Xuất Text…", "Chọn cột cần xuất, file tab-separated.")
    p.shortcut("⌘E / Ctrl+E", "Tệp → Xuất Excel… — chọn cột, có header.")
    p.paragraph("Chỉ xuất các dòng đã tick (hoặc tất cả nếu không tick dòng nào).")

    p.heading("9. In nhãn")
    p.shortcut("⌘P / Ctrl+P", "Tệp → In đã tick…")
    p.bullet("Tick máy cần in → Tệp → In đã tick.")
    p.bullet("Tệp → Tùy chọn in nhãn… (hoặc Cài đặt): chọn nội dung trên nhãn.")
    p.bullet("App tạo PDF — mỗi máy một trang, có mã vạch IMEI.")
    p.bullet("macOS mở Preview; in từ Preview như PDF thông thường.")

    p.heading("10. Xử lý sự cố thường gặp")
    p.bullet("USB không đọc: kiểm tra Tin cậy trên iPhone, thử cáp/cổng khác.")
    p.bullet("OCR sai: crop sát vùng Giới thiệu; ảnh rõ, không mờ.")
    p.bullet("Dịch vụ lỗi: kiểm tra Tài khoản API, số dư VNĐ, kết nối mạng.")
    p.bullet("iPad Wi‑Fi có thể không có IMEI — bình thường.")
    p.bullet("Log lỗi macOS: ~/Library/Logs/IMEI-Tool-crash.log")

    p.heading("Liên hệ")
    p.paragraph("Website: https://tool.taoden.vn")
    p.paragraph("Zalo hỗ trợ: 0967609909")


def generate(path: Path | None = None) -> Path:
    import os

    out = path or OUT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)

    logo = PROJECT_ROOT / "assets" / "logo_128.png"
    paginator = _Paginator()
    if logo.is_file():
        try:
            img = Image.open(logo).convert("RGBA")
            img.thumbnail((96, 96), Image.Resampling.LANCZOS)
            paginator.pages[0].paste(img, (PAGE_W - MARGIN_X - 96, MARGIN_Y - 8), img)
        except OSError:
            pass

    _content(paginator)
    paginator.footer_note()

    paginator.pages[0].save(
        out,
        "PDF",
        resolution=150.0,
        save_all=True,
        append_images=paginator.pages[1:] if len(paginator.pages) > 1 else [],
    )
    return out


def main() -> int:
    path = generate()
    print(f"==> User guide PDF: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
