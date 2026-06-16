# Taoden IMEI — API contract (v2)

**Server:** `Herd/imeitool` → production `https://tool.taoden.vn/api/v1` (dev `https://imeitool.test/api/v1`)  
**Client:** `src/api_client.py`

---

## Xác thực Sanctum (Laravel)

**Khuyến nghị — đăng nhập trình duyệt:** app mở `GET /auth/desktop?state&redirect_uri&device_name` → user đăng nhập Google → web cấp mã → app `POST /access/exchange` nhận `access_token`. Không cần copy mã kích hoạt.

**Mã kích hoạt** (`users.api_token`): copy từ web `/tai-khoan`, nhập tay vào app (dự phòng).

**Token thiết bị** (Sanctum): mọi request gửi `Authorization: Bearer {access_token}` (không gửi `X-Api-Token` khi đã có Bearer). **Hết hạn 7 ngày** — app tự mở đăng nhập Google lại. **Đăng xuất:** `POST /access/logout` (thu hồi token server) rồi xóa keyring local.

**Lưu trữ desktop:** token/email → keyring; settings → SQLite `devices.db` (không dùng JSON).

**Quota thiết bị:** `token_count` (mặc định 1) — số token Sanctum tối đa. Hết slot → thu hồi trên web `/tai-khoan/quan-ly-thiet-bi` hoặc admin tăng `token_count` (thu phí).

`POST /access/verify` không yêu cầu số dư. Endpoint trả phí cần **`credits` > 0** (UI hiển thị **VNĐ** có dấu phẩy: `5,000,000`).

**Ngoại lệ:** `POST /albert/simlock` — miễn phí, chỉ cần Bearer token (không yêu cầu credit).

**IP chặn brute-force:** Server vẫn chặn IP gọi API sai ≥ 10 lần/giờ (403). Không còn whitelist IP theo user.

```python
from src.api_client import verify_access, load_api_config
result = verify_access()
# result.valid, result.access_token (lần đầu), result.token_count / token_used / token_remaining
```

Mỗi lần cắm USB và đọc thiết bị, app tự `POST /imei/orders` với `service_id: 3` (Lưu IMEI). Không trừ credit nếu user đã lưu IMEI đó trước đó.

---

## Đặt IMEI từ Python

```python
from src.api_client import submit_imei_order, submit_imei_orders_bulk, sync_records
from src.models import DeviceRecord

# Một đơn
submit_imei_order(
    imei1="352099001761481",
    imei2="352099001761499",
    serial="F2LDXXXX",
    service_ref="CHECK_IMEI",
)

# Nhiều đơn
submit_imei_orders_bulk(
    [
        {"imei1": "352099001761481", "imei2": "", "serial": "F2LDAAAA"},
        {"imei1": "352099001761499", "imei2": "", "serial": "F2LDBBBB"},
    ],
    service_ref="CHECK_IMEI",
)

# Từ DeviceRecord (đặt đơn dịch vụ)
sync_records(records, service_ref="CHECK_IMEI")
```

Danh sách thiết bị lưu **chỉ local** (`devices.db`). Sau Run dịch vụ hoặc **Phân tích**, app đọc ghi chú (JSON/HTML GSX) và cập nhật **model**, **màu**, **bộ nhớ**, cột check (`simlock`, `fmi`, `active`, `carrier`). **IMEI2** và **serial** lấy từ ghi chú nếu khác giá trị hiện tại (ghi đè khi trống/sai). Không ghi đè `imei1`.

---

## Cấu hình desktop

- **Settings (SQLite):** `~/Library/Application Support/Taoden IMEI/devices.db` (macOS) hoặc `%APPDATA%\Taoden IMEI\devices.db` (Windows) — bảng `app_settings`, `license_cache`.
- **Token + email (keyring):** service `com.taoden.imeitool` — macOS Keychain / Windows Credential Manager.
- File `~/.taoden-imei-tool.json` **không còn dùng**; lần mở app đầu sẽ tự migrate sang DB + keyring.

Env (override dev): `TAODEN_API_URL`, `TAODEN_API_EMAIL`, `TAODEN_API_TOKEN` — email/token env **chỉ áp dụng** khi base URL là `*.test` / localhost, hoặc đặt `TAODEN_ALLOW_ENV_CREDENTIALS=1`.

## Check Simlock (Albert — miễn phí)

```python
from src.api_client import check_simlock, fetch_simlock_quota, load_api_config

quota = fetch_simlock_quota()
# quota.simlock_count, quota.simlock_used, quota.simlock_remaining

result = check_simlock(serial="MQV66RK0G4", imei1="357164764054188")
# result.ok, result.simlock, result.attempts
```

Gọi `POST /albert/simlock` — miễn phí theo `simlock_count` trên server (mặc định 10).

- **Đã dùng** = tổng đơn `service_id=3`, `status=4`.
- Chỉ kết quả Locked/Unlocked mới lưu đơn (tăng đã dùng).

```python
from src.api_client import get_simlock_quota
limit, used, remaining = get_simlock_quota()
```

---

## Dịch vụ — cache local (`services.json`)

Sau `GET /services`, desktop lưu `server_id` (ID Laravel), `api_id`, `api_route`, `api_type`.
Khi Run / tự động USB: desktop đẩy đơn vào engine nền (`order_sync`) → `POST /imei/orders/bulk` (100 đơn/lần) rồi poll `POST /imei/orders/status` mỗi 5 giây cho tới khi server trả `status: 4` (done) hoặc `status: 3` (denied). App lưu trạng thái 1/2/3/4 vào SQLite để resume khi mở lại. Dịch vụ khác «Lưu IMEI» luôn tạo đơn mới, nhận cả IMEI trùng.

Dịch vụ KHÔNG có nhà cung cấp (`api` rỗng, không `api_id`) bị từ chối ngay khi đặt (`store` → 422; `bulk` → `errors` theo từng đơn), **không trừ tiền và không tạo đơn** — tránh đơn kẹt PENDING vĩnh viễn. Dịch vụ có `api` nhưng tạm chưa resolve được `api_id` vẫn tạo PENDING; engine `imei:sync` tự suy ra `api_id` và gửi đi.

## Nhà cung cấp (Sickw / Dhru)

Luồng khuyến nghị (Horizon jobs):

1. `POST /imei/orders` + `service_id` (dịch vụ có `api` + `api_id` Sickw hoặc Dhru) → server dispatch job
2. Poll kết quả qua `GET /imei/orders` hoặc `POST /imei/orders/status` (đơn lẻ có thể trả `status: 4` ngay nếu nhà cung cấp tức thời)

Poll đơn (Sickw/Dhru/…): `POST /imei/orders/status` với `ids` — desktop dùng endpoint này, không gọi `/sickw/orders` cho Dhru.

### `parsed` — server parse sẵn (nguồn chân lý)

Mọi response chứa đơn (`store`/`bulk`/`status`/`index`) đều kèm `parsed`: object server tự trích từ `result` **ngay khi đơn có kết quả**, theo quy tắc cấu hình được (admin sửa ở Filament → "Quy tắc đọc kết quả"), không cần đổi code.

**Model (`parsed.model`):** server tra `GET https://tao02.site/model.php?imei={imei1}` trước; nếu API trả rỗng/lỗi thì parse từ `Model Description` / GSX trong `result`. Màu và bộ nhớ vẫn chỉ từ GSX.

```json
{ "id": 123, "status": 4, "result": "Model: iPhone XS Max 64GB Gold ...",
  "parsed": { "model": "iPhone XS Max", "color": "Gold", "storage_capacity": "64GB",
              "serial": "G6TXL1MKKPHF", "imei2": "357...", "fmi": "Off",
              "simlock": "Unlocked", "carrier": "...", "active": "Yes" } }
```

Desktop dùng thẳng `parsed` để điền cột (`auto_services._apply_server_parsed`); **không** parse cục bộ cột check (carrier, simlock, fmi, active). `null` nếu chưa trích được field nào. Field chỉ có khi trích được giá trị.

Sickw legacy: `POST /sickw/create`, `GET /sickw/orders/{id}`.

Dhru: admin đồng bộ catalog (`imeiservicelist`) vào bảng `api_catalog_services`, chọn khi tạo dịch vụ shop; desktop không gọi Dhru trực tiếp.

Chi tiết đầy đủ: `Herd/imeitool/docs/api.md`
