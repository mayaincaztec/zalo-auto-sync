# Changelog

## [1.1.5] - 08/2026

### Performance (DB nhanh hơn rất nhiều)
- **Kết nối SQLite dùng lại một connection duy nhất**: trước đây mỗi lần thao tác DB (đọc/ghi lịch sử, check hash, cập nhật trạng thái) đều mở + đóng connection mới (~2.5ms/lần trên Windows). Giờ `DatabaseManager` tạo **1 connection tái sử dụng** cho cả vòng đời app (an toàn vì mọi thao tác đã serialize dưới `self._lock`).
  - Benchmark 5000 file: **36.9s → 0.45s (~81x)**.
  - Vòng quét 300 file (check + insert): **3.64s → 0.36s (~10x)**.
- Thêm `DatabaseManager.close()` để giải phóng connection khi đóng app/test.

### Bugfix
- **Migration schema cũ không bị crash**: `init_db` giờ thêm đầy đủ **tất cả** cột còn thiếu khi nâng cấp từ database legacy (trước chỉ thêm cột retry/resumable, nên tạo index trên `file_id`/`group_name` lỗi `no such column`).

### Test
- **314 tests pass** (tăng từ 211), non-UI coverage **99%**. Thêm test cho close()/connection reuse; các test dùng DB thật gọi `db.close()` trong teardown (tránh khoá file trên Windows).

## [1.1.4] - 08/2026

### Added — Upload resumable + giới hạn RAM bridge
- **Upload Drive resumable (#3)**: trước đây khi retry upload gọi lại từ byte 0. Giờ lưu `resumable_uri` + `resumable_progress` vào DB (`download_history` 2 cột mới), sau mỗi chunk upload lưu session và khi lỗi/retry **tiếp tục từ byte đã tải** thay vì tải lại. Khi app khởi động lại và quét lại file lỗi, engine tự kế thừa session cũ (`get_resumable_state`).
- **Giới hạn RAM bridge (P0 #9 còn lại)**: `_start_bridge` thêm `--max-old-space-size=2048` (Node heap cap 2GB) — bổ sung cho bounded `messageCache` đã có.

### Test
- 211 tests pass (thêm test resumable: DB roundtrip, queue truyền URI khi retry, gdrive_service resume + callback trên exception).

## [1.1.3] - 08/2026

### Bugfix
- **Sửa upload Drive lỗi "name: drive  version: v3"**: đây là `UnknownApiNameOrVersion` — `build('drive','v3')` raise vì EXE không có discovery doc (`static_discovery=True` mặc định, không tải mạng khi thiếu). Giữ lại **chỉ 1 file** `googleapiclient/discovery_cache/documents/drive.v3.json` (~198KB) trong EXE thay vì loại bỏ toàn bộ cache 30MB. Dung lượng tăng không đáng kể (30.62 → 30.65MB) và app không cần internet để build Drive client.

## [1.1.2] - 08/2026

### Added — Catch-up file không bỏ sót
- **Lưu cursor đồng bộ bền vững**: `_last_seen_msg_id` mỗi nhóm giờ được ghi vào `config.json` (`last_seen_msg_ids`) khi scan, và được khôi phục khi khởi động lại — app không còn bỏ lỡ các file xuất hiện trong lúc app tắt.
- **Catch-up sâu qua bridge**: `request_old_messages` giờ gửi `count: 300` + `lastMsgId` cursor. Bridge thử lấy lịch sử nhóm qua HTTP (`getGroupChatHistory`, count tăng gấp đôi mỗi vòng tới `MAX_CACHE_PER_GROUP=5000`) để lấp khoảng trống về quá khứ; nếu HTTP lỗi (vd endpoint trả 404) sẽ tự fallback về WebSocket (`requestOldMessages(lastMsgId)`) để lấy các tin cũ hơn cursor.

### Performance (giảm RAM / CPU / lag)
- **Giảm tần suất poll bridge**: `_send_command` 0.05s → 0.1s, `_wait_for_event` 0.1s → 0.25s.
- **Giới hạn bộ nhớ sự kiện**: reader thread chỉ lưu các sự kiện cần thiết (`_CONSUMED_EVENTS`) thay vì cả dòng `new_message` tần suất cao; giới hạn `_MAX_EVENTS=200` (trim đầu), `_message_url_map` tự prune khi vượt `_MAX_URL_MAP=2000` entry.
- **DB tối ưu**: bật WAL mode trong `init_db` (reader/writer đồng thời), `synchronous=NORMAL`; `get_stats()` gộp 6 query → 1 query; `filter_unprocessed()` mới dùng IN-clause batch thay `get_processed_file_ids` (giảm query trong scan).
- **Queue bảng bớt tốn RAM**: giới hạn `_MAX_ROWS=500` dòng (`_prune_rows` xóa dòng cũ nhất).
- **Đồng bộ ngay không block UI**: `sync_now` chạy scan trong thread daemon thay vì chặn giao diện.
- **Giảm spam popup tray**: notify file completed được debounce 5 giây (`_TRAY_NOTIFY_DEBOUNCE_S`).

### Bugfix
- **Icon "ma" trên system tray**: sửa vòng lặp đệ quy `force_exit()` ↔ `closeEvent()` gây app không thoát sạch → ghost/zombie icon. `closeEvent` tự accept khi tray đã ẩn.
- **Nhiều instance app**: `main.py` giờ kiểm tra kết quả `single_instance.create(1)` — nếu instance khác đang chạy sẽ thoát ngay thay vì chạy song song.

### UI
- **Canh giữa cột hàng đợi**: cột ID, Trạng thái, Thử lại căn giữa cả text lẫn header.
- **Rút gọn hướng dẫn sử dụng**: bỏ mục "Thông số" / "Kiểm tra" / "Lưu ý", thêm mẹo về catch-up file.
- Ghi nhận: "App giành tặng anh em KS group 'ĐAM MÊ HỒ SƠ NGÀNH XÂY DỰNG'".

## [1.1.1] - 08/2026

### Refactor (không đổi hành vi)
- **`ui/settings_dialog.py`**: bỏ import chết `QSpinBox`; gom chuỗi style lặp lại thành hằng số `_HINT_STYLE`/`_HINT_STYLE_NO_BOLD`; hằng số `_DEFAULT_TIMEOUT`/`_TIMEOUT_MIN`/`_TIMEOUT_MAX` thay hardcode; bỏ `if PYSIDE_AVAILABLE` thừa trong `__init__`; trích helper `_start_worker()` cho việc tạo QThread nền (dùng chung cho đăng nhập Zalo và tải danh sách nhóm) — bỏ trùng lặp code. 197 tests vẫn pass, build EXE vẫn chạy.

## [1.1.0] - 08/2026

Nâng cấp toàn diện về độ ổn định và trải nghiệm.

### Optimize (giảm kích thước EXE 62.7MB → 30.4MB, -52%)
- **Loại Qt thừa**: `main.spec` thêm `excludes` + filter `binaries/datas` giữ lại chỉ QtCore/Gui/Widgets + plugin nền tảng Windows. Cắt: **Qt6WebEngineCore.dll (205MB)**, Qml/Quick/Pdf/Designer/opengl32sw, toàn bộ translations, resource, plugin thừa.
- **Bỏ discovery cache Google**: `googleapiclient/discovery_cache/documents/*.json` (~30MB) không cần vì app dùng `cache_discovery=False`.
- **Fix runtime sau tối ưu**: filter Qt phải giữ cả `shiboken6.abi3.dll` (QtCore.pyd phụ thuộc), nếu không app crash ngay khi import PySide6 (`Slot` undefined).
- App vẫn chạy đầy đủ tính năng sau khi giảm dung lượng.

### Added
- **Biểu tượng (icon) đặc trưng cho app**: vẽ bằng PySide6 (`icons/generate_icon.py`) — nền gradient xanh biển bo tròn, 2 mũi tên đồng bộ (cyan + emerald) vòng ngược chiều, chấm tròn trung tâm có chữ "Z". Được dùng cho: cửa sổ app, khay hệ thống, và nhúng vào EXE (taskbar/Explorer). Resource path xử lý cả chế độ dev lẫn frozen (`utils/resources.py`).
- **Header thiết kế lại chuyên nghiệp**: icon app 34px + tên app đậm + phụ đề "Đồng bộ tự động nhóm Zalo lên Google Drive", nền gradient, bo tròn 12px. Trạng thái `● Đã dừng / ● Đang đồng bộ` là **pill badge** (xanh khi active, đỏ khi dừng) thay cho text thường.
- **Stat cards đồng bộ QSS**: dùng objectName + gradient + bo tròn 10px thay cho inline style, tự thích ứng dark/light theme.
- **Đăng nhập Zalo độc lập**: nút "Đăng nhập Zalo" ở header và trong tab Cài đặt, đồng bộ trạng thái kết nối giữa cả hai nơi.
- **Flow mới**: Quét QR → Chỉnh thông số (chọn nhóm, Drive ID, ...) → Đồng bộ. Chọn nhóm từ danh sách **tự lưu ngay** vào cấu hình.
- **Nút "Đồng bộ ngay"** trên header: quét + upload một lần tức thời.
- **Button menu (segmented control)** trên header: `🔗 Kết nối Zalo` (xanh lá khi đã kết nối), `↻ Đồng bộ ngay`, `▶ Bắt đầu / ■ Dừng đồng bộ` (đỏ khi active). Nâng cấp: cursor pointer, tooltip, hover/pressed, bo tròn hai đầu menu.
- **Tab Cài đặt — Hiệu suất**: bố trí lại thành **grid 2×2** (chu kỳ kiểm tra / số luồng / số lần thử lại / giao diện, label trên control dưới) + checkbox "Chạy cùng Windows" riêng 1 hàng có tooltip — cân đối và gọn hơn dạng 5 cột.
- **Tab Cài đặt — Chiến lược file trùng**: chuyển từ dropdown sang **3 checkbox loại trừ nhau** (Đổi tên / Bỏ qua / Ghi đè), nhất quán với checkbox "Chạy cùng Windows".
- **Tab Cài đặt — Hiệu suất**: bỏ QSpinBox (nút tăng/giảm) → chuyển sang **QComboBox** (chu kỳ 30–600 giây / số luồng 1–8 / số lần thử 1–10), xếp **3 mục thành 1 hàng** (label trên, control dưới), gọn gàng hơn. **Fix**: nếu giá trị config cũ nằm ngoài danh sách preset (vd chu kỳ 90s) sẽ tự chèn thêm option thay vì bị reset về mặc định — không mất dữ liệu cấu hình (`_set_combo_keep`).
- **Giao diện sáng/tối thành nút bấm trên menu chính**: nút `🌙/☀️` ở cuối button menu header (sau nút Bắt đầu), nhấn để đổi theme ngay lập tức; bỏ combo chọn giao diện trong Cài đặt. **Fix hiển thị**: thay emoji text (không render rõ trên Windows Qt) bằng **icon vẽ bằng QPainter** (lưỡi liềm vàng / mặt trời vàng có tia), hiển thị sắc nét mọi độ phân giải.
- **Giao diện sáng/tối**: bỏ hẳn nút chuyển theme và theme sáng — **cố định 1 màu tối** duy nhất, giảm lựa chọn, giao diện nhất quán. Xóa LIGHT_THEME khỏi `styles.py` (~300 dòng QSS dư).
- **Thời gian chờ tải**: bỏ Spin Button → chuyển thành ô **gõ số** (QLineEdit + validator 10–600), mặc định **300**, không nhập/lỗi sẽ tự về 300.

### Performance (giảm lag)
- **Log widget batch flush**: log được gom lại flush mỗi 120ms thay vì insert từng dòng, chỉ auto-scroll khi đang ở cuối, giới hạn 5000 dòng.
- **Debounce refresh stats**: khi nhiều item đổi trạng thái cùng lúc, chỉ query DB 1 lần mỗi 300ms (thay thế signal `refresh_signal` spam).
- **Upload progress**: chỉ emit cập nhật khi % thay đổi, tránh spam signal trong quá trình upload chunk.
- **Validation khi lưu cài đặt**: cảnh báo thiếu Drive Folder ID / nhóm / extensions; tự tạo thư mục tải về nếu chưa tồn tại.
- **QR dialog** giữ reference, tự đóng khi đăng nhập thành công.
- Chống **orphan bridge**: app tự kill process `node zalo_bridge.js` còn sót từ lần chạy trước khi khởi động bridge mới.

### Fixed
- **Spam lỗi `request_old_messages ... 404`**: bridge nhớ group đã fail HTTP và chuyển hẳn sang WebSocket (giảm log nhiễu mỗi chu kỳ scan).
- **Upload file local bị xoá**: đánh dấu FAILED rõ ràng thay vì retry vô ích.
- Cảnh báo rõ ràng khi thiếu `gdrive_folder_id` hoặc nhóm không mở được.
- Chuỗi tiếng Việt hardcode chuyển sang i18n.
- **Clean code**: xóa `ui/dashboard_widget.py` (chưa dùng, duplicate với stat cards), dọn imports dư thừa (main_window, settings_dialog, tray_icon, queue_widget, log_widget).

## [1.0.0] - 08/2026

Phiên bản phát hành đầu tiên.

### Added
- Tự động phát hiện file mới trong nhóm Zalo (bao gồm file do chính tài khoản đăng nhập gửi) và tải lên Google Drive.
- Tab **Hướng dẫn sử dụng** mới: hướng dẫn từng bước lấy Google Drive Folder ID, xác nhận đăng nhập Zalo/Google, ý nghĩa các thông số cài đặt, thông tin tác giả.
- Chỉ cho phép **một cửa sổ ứng dụng** tại một thời điểm (single-instance). Mở lần thứ hai sẽ đưa cửa sổ đang chạy lên phía trước.
- Thông tin tác giả: Nguyễn Tấn Lợi, phiên bản 1.0, phát hành 08/2026.

### Fixed
- **Phát hiện file thời gian thực**: kích hoạt `selfListen` trong zca-js để nhận tin nhắn file do chính tài khoản gửi (trước đây bị bỏ qua).
- **Upload kẹt vô hạn**: thêm timeout cho HTTP client (`httplib2` 60s) để upload lỗi sẽ retry thay vì treo mãi.
- **File lớn không sync được**: download chạy nền (không block bridge), chờ hoàn tất bằng event với timeout scale theo dung lượng file.

### Performance
- **Delta sync**: `get_group_messages` chỉ trả về tin nhắn mới hơn cursor thay vì toàn bộ cache.
- **Giảm độ trễ scan**: poll 1s thay vì 2s, thoát sớm khi cache không đổi (chu kỳ scan giảm từ ~6s xuống ~1-2s).
- **Batch kiểm tra DB**: 1 truy vấn/scan thay vì 1 truy vấn/file để lọc file đã xử lý.
- Tự động kết nối lại WebSocket và khởi động lại bridge khi process chết.

### Release Engineering
- **Giảm dung lượng bản build ~40%**: gỡ `sharp` + `@img/*` + `zalo-api-final` (zca-js 2.x không còn cần; bridge chỉ dùng `zca-js`) — `node_modules` 27.7MB → 7.5MB; `node_bridge` không nhúng vào exe (ship folder riêng); nén bằng **UPX**.
  Kết quả: exe 86.8MB → 62.7MB, tổng gói 114.8MB → 70.5MB.
- **Clean code**: bỏ toàn bộ pattern `try/except` import kép (`zalo_drive_sync.*` / fallback cục bộ), chuẩn hoá import theo package.

### Notes
- Phân phối dưới dạng portable: `ZaloPCSyncDrive.exe` + thư mục `node_bridge` (bắt buộc để cạnh nhau).
- Test: 190 unit tests, non-UI coverage 89%.
