# Zalo PC Auto Download

Ứng dụng Windows bằng **Python 3.12** và **PySide6** để theo dõi đồng thời nhiều
nhóm Zalo, phát hiện file mới và tải trực tiếp vào thư mục local do người dùng chọn.

Thư mục đích có thể là thư mục OneDrive đã đồng bộ với SharePoint. Khi đó
OneDrive Desktop tự tải file lên cloud; ứng dụng **không dùng Google Drive,
không cần OAuth và không cần `credentials.json`**.

## Tính năng

- Kết nối Zalo bằng QR hoặc phiên đăng nhập đã lưu.
- Chọn và quét nhiều nhóm Zalo trong cùng một lượt tải.
- Quét file mới theo `file_id` và lưu lịch sử trong SQLite.
- Tải thẳng vào folder local/OneDrive/SharePoint.
- Xử lý trùng tên theo ba chế độ: đổi tên, bỏ qua hoặc ghi đè.
- Kiểm tra SHA-256 và chống xử lý lại cùng một file Zalo.
- Tự động tải mỗi 1/3/6/12 giờ hoặc tại tối đa 3 mốc giờ cố định hằng ngày.
- Chạy nền trong System Tray.

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

1. Kết nối Zalo, tải danh sách nhóm và đánh dấu một hoặc nhiều nhóm cần theo dõi.
2. Chọn **Thư mục SharePoint/local**. Ví dụ:
   `C:\Users\YourName\OneDrive\SharePoint\Zalo Docs`.
3. Chọn cách xử lý trùng tên.
4. Chọn lịch tự động: mỗi **1/3/6/12 giờ** hoặc **1–3 mốc giờ hằng ngày**.
5. Bấm **Lưu cài đặt**, sau đó chọn **Tải file mới ngay** hoặc
   **Bắt đầu tự động tải**.

## Kiểm thử

```powershell
python -m pytest -q
```

## Build `.exe`

```powershell
pyinstaller main.spec
```

File build nằm tại `dist/ZaloPCAutoDownload.exe`.
