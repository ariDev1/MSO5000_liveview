"""Qt shell and background I/O scheduler for the established scope backend."""

import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QLabel, QHBoxLayout, QMainWindow, QPushButton, QScrollArea, QSplitter,
    QTabWidget, QVBoxLayout, QWidget,
)

import app.app_state as app_state
import config
import version
from logger.longtime import stop_logging
from qt_app.advanced import BHCurveTab, HarmonicsTab, NoiseTab
from qt_app.backend import ScopeBackend
from qt_app.display import DetachedDisplay, ScopeDisplay
from qt_app.tabs import ChannelsTab, LicensesTab, LoggingTab, PowerTab, SCPITab, SystemTab
from utils.debug import debug_log, set_debug_level


STYLE = """
QMainWindow, QWidget { background: #101722; color: #e5edf6; font-size: 13px; }
QLabel#appTitle { font-size: 21px; font-weight: bold; color: #f5f9ff; }
QLabel#sectionTitle { font-size: 17px; font-weight: bold; margin: 4px 0 8px 0; }
QLabel#connection { color: #54d5ae; font-weight: bold; }
QGroupBox { border: 1px solid #35455c; border-radius: 9px; margin-top: 14px;
            padding: 14px 9px 9px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QPushButton { background: #25354a; border: 1px solid #3b526d; border-radius: 7px;
              padding: 8px 13px; }
QPushButton:hover { background: #354d67; }
QPushButton:disabled { color: #748398; background: #192433; }
QPushButton#primaryButton { background: #147d79; border-color: #28a19a; }
QPushButton#primaryButton:hover { background: #18988f; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #192434; color: #f1f6fc; border: 1px solid #35455c;
    border-radius: 6px; padding: 5px; selection-background-color: #187d85;
}
QTabWidget::pane { border: 1px solid #35455c; border-radius: 7px; }
QTabBar::tab { background: #192434; padding: 10px 16px; margin-right: 3px;
               border-top-left-radius: 7px; border-top-right-radius: 7px; }
QTabBar::tab:selected { background: #253c4b; color: #66e5c2; }
QSplitter::handle { background: #35455c; height: 3px; }
"""


def style_sheet(scale=1.0):
    """Stylesheet with all px font sizes scaled (terminal-like UI zoom)."""
    sheet = STYLE
    for base in (13, 17, 21):
        sheet = sheet.replace(f"font-size: {base}px",
                              f"font-size: {max(8, round(base * scale))}px")
    return sheet


ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.7, 1.6, 0.1


class Events(QObject):
    completed = Signal(object, object)
    message = Signal(str)


def capture(ip):
    """Fetch one VNC screenshot without blocking the GUI or sharing a fixed filename."""
    descriptor, path = tempfile.mkstemp(suffix=".png", prefix="mso5000-qt-")
    os.close(descriptor)
    try:
        subprocess.run(["vncdo", "-s", ip, "capture", path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                       check=True, timeout=10)
        with open(path, "rb") as image:
            return image.read()
    finally:
        os.unlink(path)


class MainWindow(QMainWindow):
    def __init__(self, ip):
        super().__init__()
        self.backend = ScopeBackend(ip)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qt-scope")
        self.images = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qt-vnc")
        self.events = Events(self)
        self.events.completed.connect(self._deliver)
        self.events.message.connect(self._message)
        self.closing = False
        self.polling = False
        self.capturing = False
        self.pixmap = None
        self.idn = "N/A"
        self.setWindowTitle(f"{version.APP_NAME} — Qt {version.VERSION} — {ip}")
        self.resize(1280, 860)
        self.setMinimumSize(850, 600)
        # Terminal-like UI zoom (Ctrl + / Ctrl - / Ctrl 0), persisted per user.
        # QSettings lives outside the repo, so no shared config file is touched.
        self.zoom_settings = QSettings("ariDev1", "MSO5000-Qt")
        try:
            self.zoom = float(self.zoom_settings.value("uiZoom", 1.0))
        except (TypeError, ValueError):
            self.zoom = 1.0
        self.zoom = min(ZOOM_MAX, max(ZOOM_MIN, self.zoom))
        self.setStyleSheet(style_sheet(self.zoom))
        for keys, slot in ((("Ctrl++", "Ctrl+="), self._zoom_in),
                           (("Ctrl+-",), self._zoom_out),
                           (("Ctrl+0",), self._zoom_reset)):
            for key in keys:
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
                shortcut.activated.connect(slot)

        content = QWidget()
        self.setCentralWidget(content)
        layout = QVBoxLayout(content)
        bar = QHBoxLayout()
        # GAP (Tk parity, recorded): the Tk top bar carries a scrolling
        # marquee ticker (promo chrome, no lab function). Qt keeps a static
        # title instead.
        title = QLabel("MSO5000  /  LIVE VIEW")
        title.setObjectName("appTitle")
        self.connection = QLabel("Connecting…")
        self.connection.setObjectName("connection")
        self.retry = QPushButton("Reconnect")
        self.retry.clicked.connect(self.connect_scope)
        self.hide_image = QPushButton("Hide display")
        self.hide_image.clicked.connect(self.toggle_image)
        enlarge = QPushButton("Enlarge display")
        enlarge.clicked.connect(self.enlarge_image)
        bar.addWidget(title)
        bar.addStretch()
        bar.addWidget(self.connection)
        bar.addWidget(self.retry)
        bar.addWidget(self.hide_image)
        bar.addWidget(enlarge)
        layout.addLayout(bar)

        self.display = ScopeDisplay(allow_upscale=config.SCOPE_IMAGE_ALLOW_UPSCALE)
        self.detached = None
        self.tabs = QTabWidget()
        self.system = SystemTab()
        self.licenses = LicensesTab(self.submit, ip)
        self.channels = ChannelsTab(self.submit, self.backend, self.notify)
        self.logging = LoggingTab(self.backend, self.notify)
        self.power = PowerTab(self.submit, self.backend, self.notify)
        self.console = SCPITab(self.submit, self.backend, self.notify)
        self.bh = BHCurveTab(self.submit, self.backend, self.notify) if config.ENABLE_BH_CURVE else None
        self.harmonics = HarmonicsTab(self.submit, self.backend, self.notify) if config.ENABLE_HARMONICS else None
        self.noise = NoiseTab(self.submit, self.backend, self.notify) if config.ENABLE_NOISE_INSPECTOR else None
        self.debug = QWidget()
        debug_layout = QVBoxLayout(self.debug)
        from qt_app.tabs import readout
        from PySide6.QtWidgets import QRadioButton
        level_row = QHBoxLayout()
        level_row.addWidget(QLabel("Debug Output Level:"))
        for level, label in (("FULL", "🛠 Full"), ("MINIMAL", "⚠️ Minimal")):
            option = QRadioButton(label)
            option.setChecked(level == "FULL")
            option.toggled.connect(
                lambda checked, lv=level: set_debug_level(lv) if checked else None)
            level_row.addWidget(option)
        level_row.addStretch()
        debug_layout.addLayout(level_row)
        self.debug_text = readout()
        debug_layout.addWidget(self.debug_text)
        # Tab order and titles mirror the Tk viewer (Debug Log sits third).
        for title, tab in (("System Info", self.system), ("Licenses", self.licenses),
                           ("Debug Log", self.debug), ("Channel Data", self.channels),
                           ("Long-Time Measurement", self.logging),
                           ("Power Analysis", self.power), ("SCPI", self.console)):
            self.add_tab(title, tab)
        for title, tab in (("BH Curve", self.bh), ("Harmonics", self.harmonics),
                           ("Noise Inspector", self.noise)):
            if tab is not None:
                self.add_tab(title, tab)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.display)
        self.splitter.addWidget(self.tabs)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        layout.addWidget(self.splitter)
        QTimer.singleShot(0, lambda: self.splitter.setSizes([self.height() * 65 // 100,
                                                              self.height() * 35 // 100]))
        self.statusBar().showMessage("Qt viewer • shared SCPI measurement backend")
        self.activity = QLabel("○ idle")
        self.statusBar().addPermanentWidget(self.activity)

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start(max(1, int(config.INTERVALL_SCPI)) * 1000)
        self.image_timer = QTimer(self)
        self.image_timer.timeout.connect(self.capture_image)
        self.image_timer.start(max(1, int(config.INTERVALL_BILD)) * 1000)
        self.debug_timer = QTimer(self)
        self.debug_timer.timeout.connect(self.show_debug)
        self.debug_timer.start(1000)
        QTimer.singleShot(0, self.connect_scope)
        QTimer.singleShot(100, self.licenses.refresh)

    def add_tab(self, title, tab):
        # Complex tabs scroll internally rather than dictating the splitter's
        # minimum height and shrinking the live scope to a narrow strip.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(tab)
        self.tabs.addTab(scroll, title)

    def _apply_zoom(self):
        self.setStyleSheet(style_sheet(self.zoom))
        self.zoom_settings.setValue("uiZoom", self.zoom)
        self.statusBar().showMessage(
            f"UI scale {round(self.zoom * 100)}% — Ctrl + / Ctrl - adjust, Ctrl 0 resets",
            5000)

    def _zoom_in(self):
        if self.zoom < ZOOM_MAX:
            self.zoom = min(ZOOM_MAX, round(self.zoom + ZOOM_STEP, 2))
            self._apply_zoom()

    def _zoom_out(self):
        if self.zoom > ZOOM_MIN:
            self.zoom = max(ZOOM_MIN, round(self.zoom - ZOOM_STEP, 2))
            self._apply_zoom()

    def _zoom_reset(self):
        self.zoom = 1.0
        self._apply_zoom()

    def notify(self, message):
        # Called both from Qt and from the established logger's background thread.
        self.events.message.emit(str(message))

    def _message(self, message):
        if not self.closing:
            self.statusBar().showMessage(message, 10000)
            self.logging.status.appendPlainText(message)

    def submit(self, operation, done, *, image=False):
        executor = self.images if image else self.executor
        future = executor.submit(operation)

        def completed(fut):
            try:
                result = fut.result()
            except Exception as error:
                result = error
            self.events.completed.emit(done, result)

        future.add_done_callback(completed)

    def _deliver(self, done, result):
        if self.closing:
            return
        try:
            done(result)
        except Exception as error:
            self.notify(f"UI update failed: {error}")

    def connect_scope(self):
        if self.closing or self.polling or app_state.is_logging_active:
            return
        self.polling = True
        self.connection.setText("Connecting…")
        self.retry.setEnabled(False)

        def done(response):
            self.polling = False
            self.retry.setEnabled(True)
            if isinstance(response, Exception):
                self.connection.setText("Disconnected")
                self.notify(f"Connection failed: {response}")
                return
            self.idn = response
            self.connection.setText("Connected")
            self.notify(f"Connected: {response}")
            self.poll()
            self.capture_image()

        self.submit(self.backend.connect, done)

    def poll(self):
        if self.closing or self.polling or self.backend.scope is None or app_state.is_logging_active:
            return
        self.polling = True

        def done(response):
            self.polling = False
            if isinstance(response, Exception):
                self.connection.setText("Scope unavailable")
                self.notify(f"Status read failed: {response}")
                return
            system, channels = response
            self.connection.setText("Connected")
            self.system.update_data(system, self.idn)
            self.channels.update_data(channels)
            self.power.update_context(system, channels)

        self.submit(self.backend.snapshot, done)

    def capture_image(self):
        if self.closing or self.capturing or (self.display.isHidden() and self.detached is None):
            return
        self.capturing = True

        def done(response):
            self.capturing = False
            if isinstance(response, Exception):
                self.notify(f"VNC screenshot failed: {response}")
                return
            image = QPixmap()
            if image.loadFromData(response):
                self.pixmap = image
                self.display.set_image(image)
                if self.detached is not None:
                    self.detached.display.set_image(image)

        self.submit(lambda: capture(self.backend.ip), done, image=True)

    def toggle_image(self):
        hidden = self.display.isHidden()
        self.display.setVisible(hidden)
        self.hide_image.setText("Hide display" if hidden else "Show display")
        if hidden:
            self.capture_image()

    def enlarge_image(self):
        if self.detached is not None:
            self.detached.raise_()
            self.detached.activateWindow()
            return
        self.detached = DetachedDisplay(self.pixmap if self.pixmap is not None else QPixmap(), self)
        self.detached.finished.connect(lambda _: setattr(self, "detached", None))
        self.detached.show()

    def show_debug(self):
        self.debug_text.setPlainText("\n".join(list(debug_log)[-500:]))
        # Activity indicator mirroring the Tk LED meter's inputs.
        if app_state.is_logging_active:
            state, color = "● LOG", "#e44"
        elif app_state.is_power_analysis_active:
            state, color = "● PWR", "#fd0"
        elif app_state.is_scpi_busy:
            state, color = "● SCPI", "#4f6"
        else:
            state, color = "○ idle", "#748398"
        self.activity.setText(state)
        self.activity.setStyleSheet(f"color: {color}; font-weight: bold;")

    def closeEvent(self, event):
        self.closing = True
        app_state.is_shutting_down = True
        stop_logging()
        self.poll_timer.stop()
        self.image_timer.stop()
        self.debug_timer.stop()
        self.executor.submit(self.backend.close)
        self.executor.shutdown(wait=False)
        self.images.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)
