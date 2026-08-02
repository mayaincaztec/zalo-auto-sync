import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\AI")

from PySide6.QtCore import Qt, QRectF, QPointF, QByteArray
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QIcon, QImageWriter,
                           QLinearGradient, QPainter, QPainterPath, QPixmap, QPen)


def draw_icon(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    s = float(size)
    # Rounded square background with vertical gradient
    grad = QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0.0, QColor("#1E3A5F"))
    grad.setColorAt(1.0, QColor("#0B1220"))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.22, s * 0.22)

    # Two circular sync arrows (light + accent) forming an infinity-like loop
    pen = QPen()
    pen.setWidthF(s * 0.075)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)

    cy = s * 0.46
    r = s * 0.30
    gap = s * 0.16

    # Left arrow (sky blue)
    pen.setColor(QColor("#38BDF8"))
    p.setPen(pen)
    arc_l = QRectF(s * 0.16, cy - r, r, r)
    p.drawArc(arc_l, 45 * 16, 270 * 16)

    # Right arrow (emerald)
    pen.setColor(QColor("#34D399"))
    p.setPen(pen)
    arc_r = QRectF(s * 0.54, cy - r, r, r)
    p.drawArc(arc_r, 225 * 16, 270 * 16)

    # Arrow heads
    def arrow_head(cx, cy_, angle_deg, color):
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        a = angle_deg * 3.14159265 / 180.0
        tip = QPointF(cx + gap / 2 * 0.9 * (1 if 0 <= angle_deg < 180 else -1),
                      cy_ - r - s * 0.02)
        head = QPainterPath()
        head.moveTo(tip)
        head.lineTo(tip.x() - s * 0.07, tip.y() + s * 0.10)
        head.lineTo(tip.x() + s * 0.07, tip.y() + s * 0.10)
        head.closeSubpath()
        p.drawPath(head)

    arrow_head(s * 0.16, cy, 0, QColor("#38BDF8"))
    arrow_head(s * 0.84, cy, 180, QColor("#34D399"))

    # Center chip with "Z"
    p.setBrush(QColor("#0B1220"))
    p.setPen(QPen(QColor("#334155"), s * 0.02))
    p.drawEllipse(QPointF(s * 0.5, cy), s * 0.16, s * 0.16)

    f = QFont("Segoe UI", int(s * 0.16), QFont.Bold)
    p.setFont(f)
    p.setPen(QColor("#F8FAFC"))
    p.drawText(QRectF(0, cy - s * 0.17, s, s * 0.34), Qt.AlignCenter, "Z")

    p.end()
    return pm


def main():
    app = QGuiApplication(sys.argv)
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    png_path = os.path.join(out_dir, "app_icon.png")
    ico_path = os.path.join(out_dir, "app_icon.ico")

    pm = draw_icon(256)
    pm.save(png_path, "PNG")

def write_ico(pixmap: QPixmap, path: str) -> bool:
    """Write a 256px pixmap as a PNG-compressed ICO (Vista+ format)."""
    from PySide6.QtCore import QBuffer, QIODevice
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    pixmap.save(buf, "PNG")
    buf.close()
    png = bytes(ba.data())
    header = bytes([0, 0, 1, 0, 1, 0])  # ICONDIR
    width = 0
    height = 0
    bpp = 32
    size = len(png)
    offset = 6 + 16
    entry = bytes([width, height, 0, 0, 1, 0, bpp, 0]) + \
        size.to_bytes(4, "little") + offset.to_bytes(4, "little")
    with open(path, "wb") as f:
        f.write(header + entry + png)
    return True


def main():
    app = QGuiApplication(sys.argv)
    out_dir = os.path.dirname(os.path.abspath(__file__))
    png_path = os.path.join(out_dir, "app_icon.png")
    ico_path = os.path.join(out_dir, "app_icon.ico")

    pm = draw_icon(256)
    pm.save(png_path, "PNG")

    icon = QIcon(pm)
    for px in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(draw_icon(px))
    write_ico(draw_icon(256), ico_path)
    print("Wrote:", png_path, "|", ico_path)
    print("Wrote:", png_path, "|", ico_path)


if __name__ == "__main__":
    main()
