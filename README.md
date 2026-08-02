# Ứng Dụng Quản Lý Tự Động Đồng Bộ File Zalo PC Lên Google Drive

Ứng dụng Windows bằng **Python 3.12** & **PySide6 (Qt6)** giúp tự động theo dõi thư mục nhận file của **Zalo PC**, kiểm tra tính hợp lệ và tải file tự động lên **Google Drive**.

---

## 🌟 Tính Năng Nổi Bật

- 🚀 **Giao diện PySide6 hiện đại**: Thiết kế giao diện phẳng, hỗ trợ chế độ **Light Mode** & **Dark Mode**.
- 🔍 **Theo dõi thư mục thời gian thực (Watchdog)**: Tự động phát hiện khi Zalo PC tải xong file mới.
- 🛡️ **Chống trùng lặp thông minh (SHA-256 & SQLite)**: Sử dụng băm SHA-256 và cơ sở dữ liệu SQLite `download_history` để bỏ qua các file đã upload.
- ⚡ **Hàng chờ upload đa luồng (Multi-threading Queue)**: Upload file tuần tự/song song với cơ chế Retry (thử lại tự động khi mất mạng), exponential backoff và hiển thị tiến độ (Progress Bar).
- ☁️ **Google Drive API v3 chính thức**: Tích hợp OAuth2 chính thức, tự động lưu và làm mới Token (`token.json`). Hỗ trợ chọn chiến lược khi trùng tên file (`rename`, `skip`, `overwrite`).
- 🔔 **Chạy nền & System Tray**: Thu nhỏ xuống khay hệ thống, hiển thị thông báo popup Windows khi hoàn thành upload.
- 🔌 **Tùy chọn khởi động cùng Windows**: Tự động đăng ký Registry (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).
- 📜 **Loguru System Logging**: Ghi log hệ thống theo ngày (`logs/zalo_sync_YYYY-MM-DD.log`) và hiển thị trực tiếp lên bảng Live Log Console.

---

## 📁 Cấu Trúc Dự Án (Modular Clean Architecture)

```
zalo_drive_sync/
├── main.py                     # Entry point chính của ứng dụng
├── main.spec                   # File cấu hình PyInstaller để đóng gói EXE
├── config.json                 # Cấu hình cài đặt ứng dụng
├── requirements.txt            # Danh sách thư viện phụ thuộc
├── README.md                   # Hướng dẫn chi tiết
├── config/
│   ├── __init__.py
│   └── config_manager.py       # Quản lý cấu hình thread-safe
├── core/
│   ├── __init__.py
│   ├── file_monitor.py         # Theo dõi thư mục Zalo bằng Watchdog
│   ├── upload_queue.py         # Hàng chờ xử lý upload đa luồng
│   ├── scheduler.py            # Lịch trình quét định kỳ
│   └── hasher.py               # Tính toán SHA-256 file
├── database/
│   ├── __init__.py
│   ├── db_manager.py           # Quản lý SQLite database
│   └── models.py               # Data Models & Enums
├── services/
│   ├── __init__.py
│   ├── gdrive_service.py       # Tích hợp Google Drive API OAuth2
│   └── zalo_service.py         # Nhận diện thư mục Zalo & khóa file
├── ui/
│   ├── __init__.py
│   ├── main_window.py          # Cửa sổ chính PySide6 QMainWindow
│   ├── styles.py               # QSS Stylesheet (Light & Dark Theme)
│   ├── tray_icon.py            # System Tray Icon & Popup Notifications
│   ├── log_widget.py           # Widget hiển thị log trực tiếp
│   ├── queue_widget.py         # Bảng hiển thị tiến độ hàng chờ
│   └── settings_dialog.py      # Tab cài đặt thông số
├── utils/
│   ├── __init__.py
│   ├── logger.py               # Cấu hình Loguru & Redirect sang UI
│   └── startup.py              # Đăng ký Windows Registry Auto Start
└── tests/                      # Bộ Unit Test (pytest / unittest)
    ├── test_config.py
    ├── test_database.py
    ├── test_hasher.py
    └── test_queue.py
```

---

## 🛠️ Hướng Dẫn Cài Đặt & Chạy Phát Triển

### 1. Yêu Cầu Môi Trường
- **Python 3.12** hoặc Python 3.10+
- Hệ điều hành **Windows 10 / 11**

### 2. Cài Đặt Thư Viện
Mở Terminal hoặc Command Prompt tại thư mục dự án và chạy:
```bash
pip install -r requirements.txt
```

### 3. Cấu HÌnh Google Drive API (OAuth 2.0)
1. Truy cập [Google Cloud Console](https://console.cloud.google.com/).
2. Tạo một dự án mới và bật **Google Drive API**.
3. Vào mục **Credentials** -> chọn **Create Credentials** -> **OAuth client ID**.
4. Chọn loại ứng dụng: **Desktop App**.
5. Tải file credential dạng JSON về, đổi tên thành `credentials.json` và đặt vào thư mục gốc của dự án (`zalo_drive_sync/credentials.json`).

### 4. Chạy Ứng Dụng
```bash
python main.py
```

---

## 🧪 Chạy Kiểm Thử (Unit Tests)

Dự án bao gồm bộ Unit Test kiểm tra toàn bộ các module lõi:
```bash
python -m unittest discover -s tests
```
Hoặc dùng `pytest`:
```bash
pytest
```

---

## 📦 Hướng Dẫn Build Thành File Standalone `.exe` Bằng PyInstaller

Để đóng gói ứng dụng thành 1 file executable duy nhất chạy trên Windows không cần cài Python:

### Bước 1: Cài đặt PyInstaller
```bash
pip install pyinstaller
```

### Bước 2: Chạy lệnh Build từ file `main.spec`
```bash
pyinstaller main.spec
```

Hoặc build trực tiếp bằng lệnh CLI:
```bash
pyinstaller --noconfirm --onedir --windowed --name "ZaloPCSyncDrive" --add-data "config.json;." main.py
```

Sau khi build xong, file chạy `.exe` sẽ nằm trong thư mục `dist/ZaloPCSyncDrive/ZaloPCSyncDrive.exe`.

---

## 🔒 Cam Kết Bảo Mật & Tuân Thủ
Ứng dụng **không truy cập trái phép** dữ liệu hoặc API nội bộ của Zalo. Ứng dụng chỉ hoạt động thông qua cơ chế theo dõi thư mục tập tin công khai được Zalo PC ghi ra ổ đĩa theo cấu hình người dùng, đảm bảo an toàn tuyệt đối và tuân thủ chính sách nền tảng.
