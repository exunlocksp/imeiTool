# Taoden IMEI Tool

Ứng dụng Python đọc **IMEI**, **Serial** và **Model** thiết bị Apple qua:

1. **USB** — cắm iPhone/iPad, bấm **Tin cậy**, tự động đọc (không đọc trùng serial).
2. **Ảnh / dán** — upload ảnh màn hình Cài đặt, dán ảnh (⌘V / Ctrl+V) hoặc dán văn bản để OCR.

Ưu tiên **macOS**. Windows sẽ bổ sung sau (cần driver Apple / iTunes).

## Yêu cầu (macOS)

- Python 3.10+
- [libimobiledevice / usbmuxd](https://libimobiledevice.org/) — trên Mac thường có sẵn khi cài Xcode hoặc `brew install libimobiledevice`
- **OCR ảnh:** dùng **Vision / Live Text có sẵn trên macOS** (không cần cài thêm). Tesseract chỉ dự phòng khi chạy trên Windows hoặc `BUNDLE_TESSERACT=1` lúc build.

## Cài đặt

```bash
cd imeiTool
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Chạy

```bash
source .venv/bin/activate
python main.py
```

## Hướng dẫn sử dụng

File PDF kèm hình minh họa: **[Hướng dẫn.pdf](Hướng%20dẫn.pdf)**

## Sử dụng (tóm tắt)

### USB

1. Mở app, cắm iPhone bằng cáp.
2. Trên iPhone: **Tin cậy** máy tính này.
3. Dòng mới xuất hiện trong bảng khi đọc xong.
4. Rút cắm máy khác — mỗi **serial** chỉ ghi một lần (xóa dòng trong bảng nếu muốn đọc lại).

### Ảnh / dán

1. Chụp màn hình **Cài đặt → Cài đặt chung → Giới thiệu** (có IMEI & Serial).
2. **Chọn ảnh** hoặc **dán ảnh** (⌘V / Ctrl+V) → **Phân tích OCR**.
3. Hoặc copy text từ màn hình và dán vào ô văn bản → **Phân tích văn bản**.

### Xuất Excel

Menu **Tệp → Xuất Excel** hoặc nút **Xuất Excel**. Cột: Thời gian, Nguồn, IMEI 1, IMEI 2, Serial, Model, Ghi chú.

## Ghi chú kỹ thuật

- USB dùng [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) (lockdown + MobileGestalt khi có).
- iPad Wi‑Fi có thể không có IMEI.
- iOS 17.4+ có thể hạn chế MobileGestalt; IMEI vẫn lấy qua lockdown khi thiết bị đã tin cậy.

## Đóng gói macOS (một file `.app`)

Build ra **`dist/Taoden IMEI Tool.app`** — kéo vào Applications, double-click để chạy. Python, thư viện và **OCR macOS Vision** đã nhúng sẵn (app nhẹ hơn, không cần Tesseract).

```bash
./build_mac.sh
```

Yêu cầu khi build (máy dev):

- macOS 11+ (OCR: macOS 10.15+, Live Text: macOS 14+)
- Nhúng Tesseract dự phòng (tùy chọn): `BUNDLE_TESSERACT=1 ./build_mac.sh`

Sau khi build:

- Mở lần đầu: **chuột phải → Open** (bỏ qua Gatekeeper nếu chưa ký code).
- **USB** vẫn cần `usbmuxd` trên máy người dùng (có sẵn trên macOS khi cắm iPhone; hoặc `brew install libimobiledevice`).

File phát hành gọn (chỉ app):

```bash
# Tạo file zip để gửi cho người khác
cd dist && zip -r "../Taoden-IMEI-Tool-macOS.zip" "Taoden IMEI Tool.app"
```

## Cấu trúc

```
imeiTool/
  main.py
  build_mac.sh
  imei_tool.spec
  requirements.txt
  scripts/prepare_tesseract_bundle.py
  src/
    gui.py
    usb_reader.py
    ocr_parser.py
    excel_export.py
    bundle_paths.py
    models.py
    product_map.py
```
