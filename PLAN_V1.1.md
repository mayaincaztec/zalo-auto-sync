# Plan Nâng cấp v1.1 — Resume Session

> Lưu ngày: 31/07/2026
> Mục tiêu: tiếp tục triển khai các ý tưởng nâng cấp cho **phiên bản 1.1**

---

## 1. Trạng thái hiện tại (đã xong — v1.0.0 phát hành)

- **Release v1.0.0 (08/2026)** đã build + verify + đóng gói tại `releases/v1.0.0/` + `releases/ZaloPCSyncDrive-v1.0.0.zip` (64.6 MB).
- Workspace **KHÔNG phải git repo** → release tag thay bằng `RELEASE-TAG.txt` (không có git tag).
- **190 tests pass**, non-UI coverage 89% (`.coveragerc` loại ui/, utils/, main.py).
- App đang chạy bản cuối từ `dist\ZaloPCSyncDrive.exe`.

### Đã hoàn thành trong v1.0.0
1. Real-time detection: `selfListen: true` trong `zalo_bridge.js` (cả QR + cookie login).
2. Upload hết kẹt: `httplib2.Http(timeout=60)` trong `gdrive_service.py`.
3. Perf: delta sync (`since_msg_id`), poll 1s + fast-exit, batch `get_processed_file_ids`.
4. File lớn: download nền (bridge trả `started` ngay, emit `download_complete`), timeout scale theo dung lượng.
5. UI: tab **Hướng dẫn sử dụng** (`ui/guide_widget.py`), tác giả Nguyễn Tấn Lợi, v1.0, 08/2026.
6. Single-instance: `QSharedMemory` + `_activate_existing_instance()` trong `main.py`.
7. Giảm dung lượng: gỡ `sharp`/`@img`/`zalo-api-final`, node_bridge không nhúng exe, UPX nén. exe 86.8→62.7MB, tổng 114.8→70.5MB.
8. Clean code: **bỏ toàn bộ import kép** (10 file) — đây là **ý tưởng #7 đã xong**.

---

## 2. 10 Ý tưởng nâng cấp (đã phân tích kỹ — chỉ làm cho v1.1)

### Ưu tiên & lộ trình đề xuất
| Ưu tiên | Ý tưởng | Công sức | Ghi chú |
|---|---|---|---|
| **P0 — làm sớm** | **#9 bounded cache** + `--max-old-space-size` | Thấp | `messageCache` là Map không giới hạn — cap LRU ~300 msg/group |
| **P0** | **#3 upload resumable** | Trung bình | Đã `resumable=True` + `next_chunk()` nhưng retry tải lại từ 0 — cần lưu `resumable_uri` vào DB |
| **P1** | **#4 dashboard** | Thấp | `ui/dashboard_widget.py` (164 dòng) tồn tại NHƯNG chưa wire vào `main_window.py` → **đã XÓA** (duplicate với stat cards trong main_window) |
| **P1** | **#1 sync đa nhóm** | Trung bình–Cao | Config chỉ 1 `group_name` (`config_manager.py:13`); DB đã có cột `group_name` |
| **P2** | **#6 export báo cáo CSV** | Thấp | `get_stats()` + `get_all_items()` đã có; CSV stdlib không thêm dep |
| **P2** | **#2 routing theo loại file** | Thấp–TB | Local subfolder trước, Drive subfolder sau (gdrive_service đã có folder lookup) |
| **P3** | **#8 protocol ZaloGateway** | Trung bình | Test hiện mock `_send_command` (dễ vỡ); đổi sang fake theo behavior |
| **P3** | **#9 Range download + test JS** | Trung bình | Retry theo `Range: bytes=<offset>-`; `node --test` cần refactor bridge export hàm thuần |
| **P4** | **#10 mã hóa phiên** | Trung bình | `cookie.json` + `token.json` plaintext; chỉ làm DPAPI cho token trước |
| **P4** | **#5 auto-update** | TB–Cao | Cần hosting (GitHub releases/URL); thiết kế manifest version trước |

### Chuỗi triển khai đề xuất
**#9-bounded → #3 resumable → #4 dashboard → #6 export → #1 đa nhóm → #2 routing → #8 → #9-Range/JS-test → #10 → #5**

---

## 3. Ghi chú kỹ thuật để resume nhanh

### Lệnh chuẩn
```powershell
# Test (từ D:\AI\zalo_drive_sync)
python -m pytest tests -q --cov=zalo_drive_sync --cov-config=.coveragerc

# Build exe (phải kill app đang chạy trước — exe bị lock)
Get-Process | Where-Object { $_.ProcessName -like "ZaloPCSyncDrive*" -or $_.ProcessName -eq "node" } | Stop-Process -Force
$env:PATH = "C:\Users\TANLOI\AppData\Local\upx\upx-4.2.4-win64;" + $env:PATH
python -m PyInstaller main.spec --noconfirm
```

### Cấu trúc deploy (bắt buộc)
- `dist\ZaloPCSyncDrive.exe` + thư mục **`dist\node_bridge\`** đặt cạnh nhau (node_bridge KHÔNG nhúng exe).
- Khi sync node_bridge vào dist: **giữ `cookie.json`** (phiên đăng nhập), chỉ cập nhật `zalo_bridge.js`, `package.json`, `node_modules`.
- `node_modules` đã gọn còn ~7.5MB (chỉ `zca-js` + deps, không sharp).
- Version metadata: `version_info.txt` + `main.spec` (`version='version_info.txt'`).

### Môi trường
- Windows, Python 3.14, PySide6, PyInstaller. UPX 4.2.4 tại `C:\Users\TANLOI\AppData\Local\upx\upx-4.2.4-win64`.
- Test import package dạng `zalo_drive_sync.*` — chỉ resolve được khi có path cha (pytest tự thêm; `main.py` thêm `PARENT_DIR`).

### File chính
- Bridge: `node_bridge/zalo_bridge.js` (delta sync, download nền, WS reconnect, selfListen).
- Controller: `services/zalo_controller.py` (`_send_command`, `_poll_group_messages` fast-exit, `_wait_for_download_event`, `_last_seen_msg_id`).
- Engine: `core/sync_engine.py` (`_scan_single_group` batch DB check, interval).
- Upload: `services/gdrive_service.py` (httplib2 60s), `core/upload_queue.py`.
- UI: `ui/main_window.py` (tabs: Queue/Logs/Settings/Guide). `ui/dashboard_widget.py` đã xóa (không dùng).
- Release: `CHANGELOG.md`, `releases/v1.0.0/`, `RELEASE-TAG.txt`.

---

## 4. Việc tiếp theo (phiên sau)

1. ~~**P0**: bounded `messageCache` trong bridge + `--max-old-space-size` trong `_start_bridge`~~ ✅ **Đã xong (1.1.4)**: cache bounded (MAX_CACHE_PER_GROUP=5000, có sẵn từ 1.1.2) + `--max-old-space-size=2048` thêm vào `_start_bridge_locked` (`zalo_controller.py:148`).
2. ~~**#3 resumable upload**: lưu `resumable_uri` vào DB, dùng lại khi retry~~ ✅ **Đã xong (1.1.4)**: DB thêm cột `resumable_uri`/`resumable_progress`, `gdrive_service.upload_file` nhận URI + `resume_callback` persist sau mỗi chunk, `upload_queue` truyền URI khi retry, engine kế thừa session khi quét lại file lỗi.
3. Sau đó lần lượt theo chuỗi triển khai: **#6 export CSV → #1 đa nhóm → #2 routing → #8 → #9-Range/JS-test → #10 → #5**.

---

## 5. Cập nhật release (02/08/2026)

- **Release v1.1.5 (08/2026)** đã build + verify + đóng gói tại `releases/v1.1.5/` + `releases/ZaloPCSyncDrive-v1.1.5.zip` (38.4 MB).
- **Tối ưu DB**: `DatabaseManager` dùng 1 persistent connection thay vì mở/đóng mỗi thao tác → seed 5000 file **36.9s → 0.45s (~81x)**, scan 300 file **3.64s → 0.36s (~10x)**. Thêm `close()`.
- **Bugfix**: `init_db` migration giờ thêm đủ tất cả cột còn thiếu (legacy DB không còn crash khi tạo index).
- **314 tests pass**, non-UI coverage **99%**.
- EXE: 36.2 MB, file version 1.1.5.
