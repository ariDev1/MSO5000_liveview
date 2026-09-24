"""Aspect-preserving scope display with no pixmap-driven layout feedback."""

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget


class ScopeDisplay(QWidget):
    def __init__(self, allow_upscale=True, parent=None):
        super().__init__(parent)
        self.image = QPixmap()
        self.allow_upscale = allow_upscale
        self.setMinimumSize(200, 90)
        self.setStyleSheet("background: #080f18; border: 1px solid #35455c;")

    def sizeHint(self):
        # QLabel's size hint follows its current pixmap and can squeeze the
        # splitter into a tiny strip; this widget never requests image size.
        return QSize(960, 500)

    def set_image(self, image):
        self.image = image
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#080f18"))
        if self.image.isNull():
            painter.setPen(QColor("#a6b8ca"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Waiting for VNC screenshot…")
            return
        size = self.image.size()
        bounds = self.size()
        if not self.allow_upscale:
            bounds.setWidth(min(bounds.width(), size.width()))
            bounds.setHeight(min(bounds.height(), size.height()))
        size.scale(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        x = (self.width() - size.width()) // 2
        y = (self.height() - size.height()) // 2
        painter.drawPixmap(x, y, size.width(), size.height(), self.image)


class DetachedDisplay(QDialog):
    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MSO5000 scope display")
        self.resize(1200, 760)
        self.display = ScopeDisplay(allow_upscale=True)
        self.display.set_image(image)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.display)
