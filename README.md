# Zalo PC Auto Download

Ứng dụng Windows bằng **Python 3.12** và **PySide6** để theo dõi một nhóm Zalo,
phát hiện file mới và tải trực tiếp vào thư mục local do người dùng chọn.

Thư mục đích có thể là thư mục OneDrive đã đồng bộ với SharePoint. Khi đó
OneDrive Desktop tự tải file lên cloud; ứng dụng **không dùng Google Drive,
không cần OAuth và không cần `credentials.json`**.

## Tính năng

- Kết nối Zalo bằng QR hoặc phiên đăng nhập đã lưu.
- Quét file mới theo `file_id` và lưu lịch sử trong SQLite.
- Tải thẳng vào folder local/OneDrive/SharePoint.
- Xử lý trùng tên theo ba chế độ: đổi tên, bỏ qua hoặc ghi đè.
- Kiểm tra SHA-256 và chống xử lý lại cùng một file Zalo.
- Chạy định kỳ, chạy nền trong System Tray và hỗ trợ lịch hoạt động.

## Yêu cầu

- Windows 10/11.
- Python 3.10+; khuyến nghị Python 3.12.
- Node.js LTS trở lên.
- OneDrive Desktop đã đăng nhập nếu thư mục đích là SharePoint.

## Cài đặt

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cd node_bridge
npm ci
cd ..
```

## Chạy ứng dụng

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

Trong tab **Cài đặt**:

1. Kết nối Zalo và chọn nhóm.
2. Chọn **Thư mục SharePoint/local**. Ví dụ:
   `C:\Users\YourName\OneDrive\SharePoint\Zalo Docs`.
3. Chọn cách xử lý trùng tên và bấm **Lưu cài đặt**.
4. Bấm **Tải file mới ngay** hoặc **Bắt đầu tự động tải**.

## Kiểm thử

```powershell
python -m pytest -q
```

## Build `.exe`

```powershell
pyinstaller main.spec
```

File build nằm tại `dist/ZaloPCAutoDownload.exe`.
