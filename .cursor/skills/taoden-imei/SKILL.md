---
name: taoden-imei
description: >-
  Hệ thống Taoden IMEI Tool (desktop PySide6 + Laravel API). Dùng khi sửa
  feature USB/OCR/dịch vụ/đơn IMEI, contract API, build PyArmor, deploy VPS,
  Filament admin, hoặc bảo mật app↔server.
---

# Taoden IMEI — skill dự án

## Kiến trúc

```
[Desktop PySide6]  HTTPS + Bearer   [Laravel tool.taoden.vn]
     devices.db          API              imei_orders → Sickw/Dhru/Albert
     order_sync poll     /parsed            Horizon jobs
```

| Repo | Entry | Doc |
|------|-------|-----|
| Desktop | `main.py` → `gui.run_app()` | `docs/api.md`, `README.md` |
| Server | `routes/api.php` | `docs/api.md` (server copy) |

Workspace: `taoden-imei.code-workspace` (2 folder).

## Workflow agent

### Sửa API / auth

1. Đọc `desktop/docs/api.md`
2. Sửa Laravel (`routes/api.php`, `app/Services/`, controllers)
3. Sửa `desktop/src/api_client.py` (+ `api_config.py` nếu cấu hình)
4. `php artisan test` (server)
5. Local: rule `laravel-reset-after-change` (Herd)
6. Production: `./scripts/deploy-remote.sh --fast` + `curl …/health`

### Sửa desktop UI / USB

- GUI: `src/gui.py` — worker → UI qua `self._post(fn)`
- Flash dòng đang xử lý: key theo **record id**, không index dòng (sort an toàn)
- In nhãn: PDF + `open`/`startfile`, không AppKit print trực tiếp

### Build phát hành desktop

```bash
./build_mac.sh                    # PyArmor + PyInstaller + PDF hướng dẫn
SKIP_PYARMOR=1 ./build_mac.sh     # khi Pyarmor lỗi mạng
REUSE_OBF=1 ./build_mac.sh        # giữ build/obf
```

Output: `dist/Taoden IMEI Tool.app`, `dist/Huong-dan-su-dung.pdf`

PyArmor basic cần **internet** lúc `pyarmor gen`. Regfile: `pyarmor-regfile-9722.zip` (gitignore).

### Chỉ sửa desktop

**Không** deploy VPS.

### Chỉ sửa server

Deploy bắt buộc sau khi xong (rule `laravel-deploy-after-change`).

## Module desktop quan trọng

| Module | Mục đích |
|--------|----------|
| `gui.py` | Cửa sổ chính, bảng, menu, USB monitor |
| `usb_reader.py` | pymobiledevice3, thread poll |
| `order_sync.py` | Gửi/poll đơn IMEI status 1–4 |
| `auto_services.py` | Ghi chú, parsed, model suffix |
| `api_client.py` | Mọi HTTP API |
| `settings_store.py` | SQLite settings + migrate URL cũ |
| `print_labels.py` | PDF nhãn + barcode |

## Module server quan trọng

| Module | Mục đích |
|--------|----------|
| `AccessService` | Verify, deny không leak shop/credits |
| `ApiActivationTokenService` | HMAC `api_token_lookup` |
| `ImeiOrderController` | store/bulk/status |
| `DeviceRecordResultParser` | `parsed` + model API tao02 |
| `ImeiModelLookupService` | `tao02.site/model.php` |

## Bảo mật

- TLS đủ cho transport; **không** thêm encrypt body tùy biến
- Server: rate limit, CORS, `TRUSTED_PROXIES`, token lookup HMAC
- App: keyring token; env cred dev-only; SSL verify production

## Test nhanh

```bash
# Server
cd ~/Herd/imeitool && php artisan test

# Health production
curl -sf https://tool.taoden.vn/api/v1/health

# Desktop dev
cd ~/Documents/imeiTool && source .venv/bin/activate && python main.py
```

## Chi tiết

Xem `reference.md` trong cùng thư mục skill.
