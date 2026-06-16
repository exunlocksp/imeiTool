# AGENTS.md — Taoden IMEI Tool

Hướng dẫn cho AI agent làm việc trên dự án.

## Workspace

Multi-root: **desktop** (`imeiTool`) + **server** (`Herd/imeitool`). Mở `taoden-imei.code-workspace`.

## Bắt đầu

1. Đọc skill: `.cursor/skills/taoden-imei/SKILL.md`
2. Rules luôn áp dụng: `.cursor/rules/taoden-overview.mdc`
3. Contract API: `docs/api.md`

## Repo desktop

| Việc | Rule / file |
|------|-------------|
| GUI PySide6 | `python-desktop-gui.mdc` |
| API client | `python-desktop-api.mdc` |
| SQLite / export | `python-desktop-data.mdc` |
| Build PyArmor | `python-desktop-build.mdc` |
| macOS USB/OCR | `python-desktop-macos.mdc` |

Chạy dev: `source .venv/bin/activate && python main.py`

Build: `./build_mac.sh` → `dist/Taoden IMEI Tool.app` + `dist/Huong-dan-su-dung.pdf`

## Repo server

| Việc | Rule |
|------|------|
| API Laravel | `laravel-api.mdc` |
| Đơn IMEI / parsed | `laravel-imei-orders.mdc` |
| Bảo mật | `laravel-security.mdc` |
| Filament | `filament-tables.mdc` |
| Sau sửa Herd | `laravel-reset-after-change.mdc` |
| Deploy VPS | `laravel-deploy-after-change.mdc` |

## Nguyên tắc

- Đổi API → `docs/api.md` + Laravel + `api_client.py`
- Server-side là nguồn đúng cho quota, parsed, auth
- Không commit secrets; chỉ commit khi user yêu cầu
