"""Qt port of the Tk scrolling marquee ticker (promo chrome, no lab function).

Mirrors gui/marquee.py behavior: lines from a remote URL with local
marquee.txt fallback, scrolling text, and periodic rotation with occasional
"Tesla thoughts" in gold italic. Timers are children of the widget, so they
stop automatically when the widget is destroyed; slots also honor
app_state.is_shutting_down.
"""

import random
import secrets
import threading
import urllib.request

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

import app.app_state as app_state
from utils.debug import log_debug

TESLA_THOUGHTS = [
    "This frequency... it resonates.",
    "The Earth rings like a bell at 7.83 Hz.",
    "I can feel the power... but can you measure it?",
    "You call this noise? I call it music.",
    "Vibrations. Always vibrations.",
    "The energy is not lost. It's hiding behind sinewave.",
    "If you want to understand the universe, think in terms of energy and frequency.",
]


class MarqueeBar(QWidget):
    # Emitted from the background fetch thread when web lines arrive;
    # applied on the GUI thread so web content shows immediately.
    _remote_loaded = Signal()

    def __init__(self, parent=None, file_path="marquee.txt",
                 url="https://aether-research.institute/MSO5000/marquee.txt",
                 speed=2, rotate_interval=60000):
        super().__init__(parent)
        self._speed = max(1, int(speed))
        self._lines = self._load_local(file_path)
        self._text = secrets.choice(self._lines)
        self._tesla = False
        self._x = 0.0
        self._normal_font = QFont("Courier", 11, QFont.Weight.Bold)
        self._tesla_font = QFont("Times New Roman", 11, QFont.Weight.Normal,
                                 italic=True)
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if url:
            self._remote_loaded.connect(self._apply_remote)
            thread = threading.Thread(target=self._fetch_remote, args=(url,),
                                      daemon=True)
            thread.start()
        self._scroll_timer = QTimer(self)
        self._scroll_timer.timeout.connect(self._scroll)
        self._scroll_timer.start(50)
        self._rotate_timer = QTimer(self)
        self._rotate_timer.timeout.connect(self._rotate)
        self._rotate_timer.start(max(1000, int(rotate_interval)))

    @staticmethod
    def _load_local(file_path):
        try:
            with open(file_path, encoding="utf-8") as handle:
                lines = [line.strip() for line in handle if line.strip()]
            if lines:
                log_debug(f"📁 Marquee loaded locally — {len(lines)} lines")
                return lines
        except Exception as error:
            log_debug(f"❌ Failed to read local marquee.txt: {error}")
        return ["⚠️ Could not load marquee.txt"]

    def _fetch_remote(self, url):
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                data = response.read().decode("utf-8").strip()
            lines = [line.strip() for line in data.splitlines() if line.strip()]
            if lines:
                self._lines = lines
                log_debug(f"🌐 Marquee fetched from URL — {len(lines)} lines")
                try:
                    self._remote_loaded.emit()
                except (AttributeError, RuntimeError):
                    pass
        except Exception as error:
            log_debug(f"⚠️ Failed to fetch marquee.txt from server: {error}")

    def _apply_remote(self):
        """Show a random web line right away (like Tk, which web-loads first)."""
        try:
            self._text = secrets.choice(self._lines)
            self._tesla = False
            self._x = float(self.width())
            self.update()
        except (AttributeError, RuntimeError, IndexError):
            pass

    def _quitting(self):
        try:
            return bool(getattr(app_state, "is_shutting_down", False))
        except Exception:
            return False

    def _stop(self):
        for timer in (getattr(self, "_scroll_timer", None),
                      getattr(self, "_rotate_timer", None)):
            try:
                if timer is not None:
                    timer.stop()
            except (AttributeError, RuntimeError):
                pass

    def _scroll(self):
        if self._quitting():
            self._stop()
            return
        try:
            self._x -= self._speed
            width = self.fontMetrics().horizontalAdvance(self._text)
            if self._x + width < 0:
                self._x = float(self.width())
            self.update()
        except (AttributeError, RuntimeError):
            self._stop()

    def _rotate(self):
        if self._quitting():
            self._stop()
            return
        try:
            is_tesla = random.random() < 0.2
            pool = TESLA_THOUGHTS if is_tesla else self._lines
            candidate = secrets.choice(pool)
            if candidate == self._text and self._lines:
                candidate = secrets.choice(self._lines)
                is_tesla = False
            self._text = candidate
            self._tesla = is_tesla
            self._x = float(self.width())
            self.update()
        except (AttributeError, RuntimeError, IndexError):
            self._stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        font = self._tesla_font if self._tesla else self._normal_font
        painter.setFont(font)
        color = "#ffcc00" if self._tesla else "#00ffcc"
        painter.setPen(color)
        metrics = painter.fontMetrics()
        baseline = (self.height() + metrics.ascent() - metrics.descent()) // 2
        painter.drawText(int(self._x), baseline, self._text)
