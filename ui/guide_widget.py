"""
Usage Guide Widget / Tab
PySide6 widget showing a short step-by-step user manual for Zalo -> Google Drive sync.
"""

from typing import Optional

try:
    from PySide6.QtWidgets import QTextBrowser
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False


_GUIDE_HTML = """
<html>
<head><style>
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; color: #E2E8F0; }
h1 { color: #38BDF8; font-size: 20px; border-bottom: 2px solid #334155; padding-bottom: 6px; }
h2 { color: #38BDF8; font-size: 15px; margin-top: 22px; }
h3 { color: #94A3B8; font-size: 13px; margin-top: 14px; }
ol, ul { margin: 6px 0 6px 0; padding-left: 22px; }
li { margin-bottom: 5px; }
code { background: #1E293B; border: 1px solid #334155; border-radius: 4px; padding: 1px 5px; color: #7DD3FC; }
.note { background: #0F172A; border-left: 4px solid #38BDF8; padding: 8px 12px; border-radius: 4px; margin: 10px 0; }
.box { background: #0F172A; border: 1px solid #334155; border-radius: 6px; padding: 10px 14px; margin: 8px 0; }
.version { margin-top: 30px; padding-top: 12px; border-top: 2px solid #334155; color: #94A3B8; }
</style></head>
<body>

<h1>Hướng dẫn sử dụng</h1>

<p>Ứng dụng tự động phát hiện <b>file mới</b> trong nhóm Zalo và tải lên
<b>Google Drive</b>. Mỗi lần có file mới trong nhóm, app sẽ tự tải về rồi
upload lên thư mục Drive đã cấu hình.</p>

<h2>1. Các bước cấu hình lần đầu</h2>

<h3>Bước 1: Đăng nhập Zalo</h3>
<ol>
  <li>Bấm <b>Đăng nhập Zalo</b> (góc phải trên hoặc trong tab Cài đặt).</li>
  <li>App hiện mã QR → dùng điện thoại <b>Zalo</b> quét mã.</li>
  <li>Sau khi quét xong, nút chuyển thành <b>"Zalo đã kết nối"</b>.
      Lần sau app <b>không cần quét lại</b> (đã lưu phiên).</li>
</ol>

<h3>Bước 2: Lấy Google Drive Folder ID</h3>
<ol>
  <li>Mở trình duyệt → vào <code>https://drive.google.com</code>.</li>
  <li><b>Tạo mới</b> hoặc chọn thư mục muốn đồng bộ lên.</li>
  <li>Nhấn vào thư mục đó, nhìn thanh địa chỉ, URL có dạng:
      <br><code>https://drive.google.com/drive/folders/1A2b3C4d5E6f7G8h9I0j</code></li>
  <li>Copy chuỗi <b>sau <code>folders/</code></b>
      (ví dụ <code>1A2b3C4d5E6f7G8h9I0j</code>) → dán vào ô
      <b>Google Drive Folder ID</b> trong Cài đặt.</li>
</ol>

<h3>Bước 3: Chọn nhóm Zalo</h3>
<ol>
  <li>Trong tab Cài đặt, bấm <b>Tải danh sách nhóm</b>.</li>
  <li>Chọn nhóm mong muốn từ danh sách. Tên nhóm được <b>lưu tự động</b>.</li>
</ol>

<h3>Bước 4: Chọn thư mục tải về</h3>
<p>Chọn nơi app lưu file tạm sau khi tải từ Zalo (trước khi upload lên Drive).</p>

<h3>Bước 5: Lưu & bắt đầu</h3>
<ol>
  <li>Bấm <b>Lưu cài đặt</b>.</li>
  <li>Bấm <b>Bắt đầu đồng bộ</b> để chạy tự động theo chu kỳ, hoặc <b>Đồng bộ ngay</b>
      để quét + upload một lần tức thời.</li>
  <li>File mới trong nhóm sẽ tự động được đồng bộ.</li>
</ol>

<div class="note">
<b>Mẹo:</b> App tự động <b>bắt kịp</b> các file xuất hiện khi app đang tắt. Chỉ cần mở
app lên, bấm <b>Đồng bộ ngay</b> là các file mới từ lần trước sẽ được nhận đầy đủ.
</div>

<h2>Lưu ý: Yêu cầu Node.js</h2>
<p>Ứng dụng sử dụng <b>Node.js</b> để kết nối Zalo. Máy tính cần cài sẵn
<b>Node.js</b> (bản LTS trở lên) thì app mới đồng bộ được.</p>
<ol>
  <li>Tải Node.js tại trang chủ: <code>https://nodejs.org</code>.</li>
  <li>Cài đặt với mặc định, sau đó <b>khởi động lại máy</b> (hoặc đóng/mở lại app).</li>
  <li>Kiểm tra thành công: mở <b>Command Prompt</b> gõ <code>node -v</code>,
      thấy số phiên bản (ví dụ <code>v22.x</code>) là đã cài xong.</li>
</ol>

<div class="version">
<b>Thông tin tác giả:</b> Nguyễn Tấn Lợi<br>
<b>Phiên bản:</b> 1.1<br>
<b>Phát hành:</b> 08/2026<br>
<b>App giành tặng anh em KS group "ĐAM MÊ HỒ SƠ NGÀNH XÂY DỰNG".</b>
</div>

</body></html>
"""


class GuideWidget(QTextBrowser if PYSIDE_AVAILABLE else object):
    """PySide6 Usage Guide tab with short step-by-step instructions."""

    def __init__(self, parent: Optional[QWidget] = None):
        if not PYSIDE_AVAILABLE:
            return
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; }"
        )
        self.setHtml(_GUIDE_HTML)
