"""Usage guide for downloading Zalo group files to a local/SharePoint folder."""

from typing import Optional

try:
    from PySide6.QtWidgets import QTextBrowser, QWidget
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False


_GUIDE_HTML = r"""
<html>
<head><style>
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; color: #E2E8F0; }
h1 { color: #38BDF8; font-size: 20px; border-bottom: 2px solid #334155; padding-bottom: 6px; }
h2 { color: #38BDF8; font-size: 15px; margin-top: 22px; }
h3 { color: #94A3B8; font-size: 13px; margin-top: 14px; }
ol, ul { margin: 6px 0; padding-left: 22px; }
li { margin-bottom: 5px; }
code { background: #1E293B; border: 1px solid #334155; border-radius: 4px; padding: 1px 5px; color: #7DD3FC; }
.note { background: #0F172A; border-left: 4px solid #38BDF8; padding: 8px 12px; border-radius: 4px; margin: 10px 0; }
.version { margin-top: 30px; padding-top: 12px; border-top: 2px solid #334155; color: #94A3B8; }
</style></head>
<body>

<h1>Hướng dẫn tải file Zalo về SharePoint</h1>

<p>Ứng dụng phát hiện file mới trong nhiều nhóm Zalo và tải thẳng vào thư mục
local bạn chọn. Nếu đó là thư mục đã được OneDrive đồng bộ với SharePoint,
OneDrive sẽ tự đưa file lên cloud — ứng dụng không cần kết nối Google Drive.</p>

<h2>1. Cấu hình lần đầu</h2>

<h3>Bước 1: Kết nối Zalo</h3>
<ol>
  <li>Bấm <b>Kết nối Zalo</b>.</li>
  <li>Dùng Zalo trên điện thoại quét mã QR.</li>
  <li>Phiên đăng nhập được lưu để các lần sau không cần quét lại.</li>
</ol>

<h3>Bước 2: Chọn nhóm Zalo</h3>
<ol>
  <li>Bấm <b>Tải danh sách nhóm</b> trong tab Cài đặt.</li>
  <li>Đánh dấu một hoặc nhiều nhóm cần theo dõi.</li>
  <li>Có thể dùng <b>Chọn tất cả</b>, <b>Bỏ chọn</b> hoặc thêm tên nhóm thủ công.</li>
</ol>

<h3>Bước 3: Chọn thư mục SharePoint/local</h3>
<ol>
  <li>Bấm <b>Chọn...</b> tại ô Thư mục SharePoint/local.</li>
  <li>Chọn một thư mục đang được OneDrive đồng bộ, ví dụ:<br>
      <code>C:\Users\YourName\OneDrive\SharePoint\Zalo Docs</code></li>
  <li>App sẽ lưu file trực tiếp vào thư mục này.</li>
</ol>

<div class="note">
<b>Lưu ý:</b> Trạng thái đồng bộ lên SharePoint do ứng dụng OneDrive trên Windows
quản lý. Hãy bảo đảm OneDrive đang đăng nhập và thư mục đích có biểu tượng đồng bộ bình thường.
</div>

<h3>Bước 4: Chọn cách xử lý trùng tên</h3>
<ul>
  <li><b>Đổi tên:</b> giữ cả hai file bằng hậu tố <code>(1)</code>, <code>(2)</code>…</li>
  <li><b>Bỏ qua:</b> không tải file mới nếu tên đã tồn tại.</li>
  <li><b>Ghi đè:</b> thay file đang có bằng file mới.</li>
</ul>

<h3>Bước 5: Lưu và chạy</h3>
<ol>
  <li>Chọn lịch tự động: lặp mỗi <b>1, 3, 6 hoặc 12 giờ</b>; hoặc chọn
      <b>1–3 mốc giờ cố định hằng ngày</b>.</li>
  <li>Bấm <b>Lưu cài đặt</b>.</li>
  <li>Bấm <b>Tải file mới ngay</b> để quét một lần, hoặc
      <b>Bắt đầu tự động tải</b> để theo dõi định kỳ.</li>
</ol>

<h2>2. Yêu cầu Node.js</h2>
<p>Ứng dụng dùng Node.js để kết nối Zalo. Máy cần cài Node.js LTS trở lên.
Kiểm tra trong Command Prompt bằng lệnh <code>node -v</code>.</p>

<div class="version">
<b>Chế độ:</b> Local / OneDrive / SharePoint folder<br>
<b>Phiên bản:</b> 1.3
</div>

</body></html>
"""


class GuideWidget(QTextBrowser if PYSIDE_AVAILABLE else object):
    """PySide6 guide tab for the local-download workflow."""

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
