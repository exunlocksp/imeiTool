# Taoden IMEI — reference

## Order status (desktop + server)

| Status | Ý nghĩa |
|--------|---------|
| 1 | Pending — chưa gửi server |
| 2 | Processing — đã gửi, đang poll |
| 3 | Denied — server từ chối |
| 4 | Done — có kết quả + `parsed` |

## API routes (`/api/v1`)

- `GET /health`
- Auth (throttle `api-auth`): `/access/verify`, `/access/exchange`, `/access/client-ip`
- General (throttle `api-general` + Bearer): `/services`, `/imei/orders/*`, `/devices/*`
- Albert (throttle `api-albert`): `/albert/simlock`, `/albert/simlock/quota`

## Desktop storage

| Dữ liệu | Nơi lưu |
|---------|---------|
| Token, email | Keychain / Credential Manager |
| Bảng IMEI, app_orders | SQLite `devices.db` |
| Cache dịch vụ | `services.json` (user data dir) |

## Build env vars

| Biến | Desktop |
|------|---------|
| `TAODEN_API_URL` | Override base URL (dev) |
| `SKIP_PYARMOR` / `REUSE_OBF` / `OBF_ONLY` | Build macOS |
| `PYARMOR_PLATFORM` | `darwin.arm64` / `darwin.x86_64` / `windows.x86_64` |

## Server env (production)

`TRUSTED_PROXIES`, `CORS_ALLOWED_ORIGINS`, `API_TRUST_CLIENT_PUBLIC_IP=false`, rate limit keys trong `config/api.php`.

## Deploy VPS

```bash
SSH: deploy@14.225.210.228
Key: ~/.ssh/imeitool_vps
Path: /var/www/imeitool
./scripts/deploy-remote.sh --fast   # PHP thuần
```

## Filament admin

`/admin` — User, dịch vụ, đơn IMEI, quy tắc parse kết quả.

Quy tắc bảng: Resource kế thừa base class → `FilamentTableDefaults`, pagination 100.

## Không làm

- Hardcode master API token trong source desktop
- Commit `.env`, pyarmor regfile
- Parse simlock/FMI/active local khi server đã có `parsed`
- Ghi IMEI list lên server (chỉ local + đơn dịch vụ)
