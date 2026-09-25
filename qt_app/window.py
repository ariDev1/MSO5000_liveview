"""Qt shell and background I/O scheduler for the established scope backend."""

import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QLabel, QHBoxLayout, QMainWindow, QPushButton, QScrollArea, QSplitter,
    QTabWidget, QVBoxLayout, QWidget,
)

import app.app_state as app_state
import config
import version
from logger import longtime
from logger.longtime import stop_logging
from qt_app.advanced import BHCurveTab, HarmonicsTab, NoiseTab
from qt_app.backend import ScopeBackend
from qt_app.display import DetachedDisplay, ScopeDisplay
from qt_app.tabs import (ChannelsTab, LicensesTab, LoggingTab, PowerTab, SCPITab, SystemTab,
                         channel_color)
from utils.debug import debug_log, set_debug_level


STYLE = """
QMainWindow, QWidget { background: #0d1117; color: #dfe7ef; font-size: 12px; }
QLabel#appTitle { font-size: 18px; font-weight: bold; color: #f2f6fa; }
QLabel#sectionTitle { font-size: 14px; font-weight: bold; margin: 2px 0 4px 0; }
QLabel#headline { font-size: 26px; font-weight: bold; font-family: monospace;
                 color: #ffd75e; margin: 2px 0; }
QLabel#connection { color: #4f6; font-weight: bold; font-family: monospace; }
QGroupBox { border: 1px solid #2c3947; border-radius: 2px; margin-top: 10px;
            padding: 8px 6px 6px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QPushButton { background: #1b2634; border: 1px solid #3a4a5e; border-radius: 2px;
              padding: 4px 8px; }
QPushButton:hover { background: #24344a; border-color: #4a5d75; }
QPushButton:pressed { background: #0f1720; }
QPushButton:disabled { color: #5c6b7d; background: #131b25; }
QPushButton:checked { background: #3d2f14; border-color: #a97b1f; }
QPushButton#primaryButton { background: #0e4f4a; border-color: #1f8a80; }
QPushButton#primaryButton:hover { background: #12665f; }
QPushButton#primaryButton:pressed { background: #0a3a36; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #0a0f16; color: #e8f0f7; border: 1px solid #2c3947;
    border-radius: 2px; padding: 3px; selection-background-color: #1f8a80;
    font-family: monospace;
}
QPlainTextEdit, QTableWidget { font-family: monospace; }
QTableWidget { background: #0a0f16; color: #e8f0f7; gridline-color: #2c3947;
               selection-background-color: #1f4a44; alternate-background-color: #0e141d; }
QHeaderView::section { background: #1b2634; color: #dfe7ef; border: none; padding: 3px; }
QTabWidget::pane { border: 1px solid #2c3947; border-radius: 2px; }
QTabBar::tab { background: #131c27; padding: 6px 10px; margin-right: 2px;
               border-top-left-radius: 2px; border-top-right-radius: 2px; }
QTabBar::tab:selected { background: #1b2634; color: #ffd75e; }
QSplitter::handle { background: #2c3947; height: 3px; }
QCheckBox, QRadioButton { spacing: 4px; }
QScrollBar:vertical { background: #0d1117; width: 10px; }
QScrollBar::handle:vertical { background: #2c3947; min-height: 20px; }
"""


def style_sheet(scale=1.0):
    """Stylesheet with all px font sizes scaled (terminal-like UI zoom)."""
    sheet = STYLE
    for base in (12, 14, 18, 26):
        sheet = sheet.replace(f"font-size: {base}px",
                              f"font-size: {max(8, round(base * scale))}px")
    return sheet


ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.7, 1.6, 0.1


def _footer_rate(raw):
    """Human-friendly sample rate: '2.000000E+9' -> '2.00 GSa/s' (UI-only)."""
    import math
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError, AttributeError):
        text = str(raw).strip() if raw is not None else ""
        return text or "—"
    if not math.isfinite(value):
        return str(raw).strip()
    abs_val = abs(value)
    if abs_val >= 1e9:
        return f"{value / 1e9:.2f} GSa/s"
    if abs_val >= 1e6:
        return f"{value / 1e6:.2f} MSa/s"
    if abs_val >= 1e3:
        return f"{value / 1e3:.2f} kSa/s"
    return f"{value:.0f} Sa/s"


def _footer_time(raw):
    """Human-friendly timebase: '2.000000E-04' -> '200 µs/div' (UI-only)."""
    import math
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError, AttributeError):
        text = str(raw).strip() if raw is not None else ""
        return text or "—"
    if not math.isfinite(value):
        return str(raw).strip()
    abs_val = abs(value)
    if abs_val >= 1:
        return f"{value:.3f} s/div"
    if abs_val >= 1e-3:
        return f"{value / 1e-3:.2f} ms/div"
    if abs_val >= 1e-6:
        return f"{value / 1e-6:.1f} µs/div"
    if abs_val >= 1e-9:
        return f"{value / 1e-9:.1f} ns/div"
    return f"{value:.3e} s/div"


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
    def __init__(self, ip, no_marquee=False):
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
        title = QLabel("MSO5000  /  LIVE VIEW")
        title.setObjectName("appTitle")
        self.connection = QLabel("… CONNECTING")
        self.connection.setObjectName("connection")
        self.retry = QPushButton("RECONNECT")
        self.retry.clicked.connect(self.connect_scope)
        self.hide_image = QPushButton("HIDE")
        self.hide_image.clicked.connect(self.toggle_image)
        enlarge = QPushButton("ENLARGE")
        enlarge.clicked.connect(self.enlarge_image)
        bar.addWidget(title)
        # Scrolling marquee ticker, as in the Tk top bar (promo chrome, no
        # lab function). Timers live on the widget and stop with it.
        if no_marquee:
            bar.addStretch()
            self.marquee = None
        else:
            from qt_app.marquee import MarqueeBar
            self.marquee = MarqueeBar()
            bar.addWidget(self.marquee, 1)
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
        for level, label in (("FULL", "FULL"), ("MINIMAL", "MINIMAL")):
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
        QTimer.singleShot(0, self._default_splitter_sizes)
        self.statusBar().showMessage("Qt viewer • shared SCPI measurement backend")
        # Left: persistent last notification (click → Debug Log).
        self.last_event = QLabel("Ready")
        self.last_event.setToolTip("Last notification — click to open Debug Log")
        self.statusBar().addWidget(self.last_event, 1)
        self._clickable(self.last_event, lambda: self._goto_tab(self.debug))
        # Right, permanent: job state, channel dots, data age, instrument, build.
        self.activity = QLabel("□ IDLE")
        self.activity.setToolTip("Active job — click to open its tab")
        self.statusBar().addPermanentWidget(self.activity)
        self._clickable(self.activity, self._goto_job)
        self.channels_bar = QLabel()
        self.channels_bar.setTextFormat(Qt.TextFormat.RichText)
        self.channels_bar.setToolTip("Displayed channels — click to open Channel Data")
        self.statusBar().addPermanentWidget(self.channels_bar)
        self._clickable(self.channels_bar, lambda: self._goto_tab(self.channels))
        self.data_age = QLabel("DATA —")
        self.data_age.setStyleSheet("font-family: monospace;")
        self.data_age.setToolTip("Age of the last successful scope poll")
        self.statusBar().addPermanentWidget(self.data_age)
        self.scope_info = QLabel("SR — · TRIG — · TB —")
        self.scope_info.setStyleSheet("font-family: monospace;")
        self.scope_info.setToolTip("Instrument identity (see System Info tab)")
        self.statusBar().addPermanentWidget(self.scope_info)
        self._clickable(self.scope_info, lambda: self._goto_tab(self.system))
        self.build = QLabel(f"{version.VERSION} {version.GIT_COMMIT}")
        self.build.setStyleSheet("font-family: monospace;")
        self.build.setToolTip(f"{version.APP_NAME} {version.VERSION} · "
                              f"{version.GIT_COMMIT} · {version.BUILD_DATE} · "
                              f"{version.AUTHOR}\n{version.PROJECT_URL}")
        self.statusBar().addPermanentWidget(self.build)
        self._clickable(self.build, lambda: self._goto_tab(self.system))
        self._last_poll = None
        self._last_activity = (None, None)
        self._last_data_text, self._last_data_tint = None, None
        self._last_build_text = None
        self._last_debug_text = None
        self._update_channels_bar({})
        # Workspace restore (same per-user store as zoom and fold states).
        self.workspace = QSettings("ariDev1", "MSO5000-Qt")
        geometry = self.workspace.value("mainGeometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        try:
            tab_index = int(self.workspace.value("tabIndex", 0))
        except (TypeError, ValueError):
            tab_index = 0
        if 0 <= tab_index < self.tabs.count():
            self.tabs.setCurrentIndex(tab_index)
        splitter = self.workspace.value("splitterSizes")
        if splitter is not None:
            self.splitter.restoreState(splitter)
        # Keyboard operation: F5 measures on the visible analysis tab,
        # Ctrl+1..9 jumps between tabs.
        go = QShortcut(QKeySequence("F5"), self)
        go.setContext(Qt.ShortcutContext.ApplicationShortcut)
        go.activated.connect(self._measure_current)
        for number in range(1, min(10, self.tabs.count() + 1)):
            jump = QShortcut(QKeySequence(f"Ctrl+{number}"), self)
            jump.setContext(Qt.ShortcutContext.ApplicationShortcut)
            jump.activated.connect(
                lambda checked=False, idx=number - 1: self.tabs.setCurrentIndex(idx))

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

    def _default_splitter_sizes(self):
        # Only for a fresh workspace; a restored splitter state wins.
        if self.workspace.value("splitterSizes") is None and not self.closing:
            self.splitter.setSizes([self.height() * 65 // 100,
                                    self.height() * 35 // 100])

    def _measure_current(self):
        # F5: measure on the visible analysis tab (tabs guard when busy).
        scroll = self.tabs.currentWidget()
        inner = scroll.widget() if hasattr(scroll, "widget") else None
        for action in ("measure", "run"):
            if hasattr(inner, action):
                getattr(inner, action)()
                return

    def notify(self, message):
        # Called both from Qt and from the established logger's background thread.
        self.events.message.emit(str(message))

    def _message(self, message):
        if not self.closing:
            self.statusBar().showMessage(message, 10000)
            self.last_event.setText(message[:140])
            self.logging.status.appendPlainText(message)

    @staticmethod
    def _clickable(label, slot):
        label.setCursor(Qt.CursorShape.PointingHandCursor)
        label.mousePressEvent = lambda event: slot()

    def _goto_tab(self, inner):
        for idx in range(self.tabs.count()):
            page = self.tabs.widget(idx)
            if hasattr(page, "widget") and page.widget() is inner:
                self.tabs.setCurrentIndex(idx)
                return

    def _goto_job(self):
        if app_state.is_logging_active:
            self._goto_tab(self.logging)
        elif app_state.is_power_analysis_active:
            self._goto_tab(self.power)

    @staticmethod
    def _norm_channel(name):
        text = str(name).upper().replace(" ", "")
        if text.startswith("MATH"):
            return text
        if text.startswith("CHAN"):
            return text
        if text.startswith("CH"):
            return "CHAN" + text[2:]
        if text.isdigit():
            return "CHAN" + text
        return text

    def _update_channels_bar(self, channels):
        present = {self._norm_channel(key) for key in channels}
        dots = "".join(
            f"<span style=\"color:{channel_color(chan)}\">●</span>"
            if chan in present else "<span style=\"color:#3a4a5e\">○</span>"
            for chan in ("CHAN1", "CHAN2", "CHAN3", "CHAN4"))
        names = ", ".join(sorted(present)) or "none"
        self.channels_bar.setText(dots)
        self.channels_bar.setToolTip(f"Displayed channels: {names} — click to open Channel Data")

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

    def _set_connection(self, text, color):
        self.connection.setText(text)
        self.connection.setStyleSheet(f"color: {color}; font-weight: bold; font-family: monospace;")

    def connect_scope(self):
        if self.closing or self.polling or app_state.is_logging_active:
            return
        self.polling = True
        self._set_connection("… CONNECTING", "#fd0")
        self.retry.setEnabled(False)

        def done(response):
            self.polling = False
            self.retry.setEnabled(True)
            if isinstance(response, Exception):
                self._set_connection("□ NO LINK", "#e44")
                self.notify(f"Connection failed: {response}")
                return
            self.idn = response
            self._set_connection("■ LINK", "#4f6")
            self.connection.setToolTip(response)
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
                self._set_connection("□ NO LINK", "#e44")
                self.notify(f"Status read failed: {response}")
                return
            system, channels = response
            self._set_connection("■ LINK", "#4f6")
            self._last_poll = time.monotonic()
            self.scope_info.setText(
                f"SR {_footer_rate(system.get('Sample rate', '—'))} · "
                f"TRIG {str(system.get('Trigger', '—')).strip()} · "
                f"TB {_footer_time(system.get('Timebase', '—'))}")
            self.scope_info.setToolTip(f"{self.idn}\n"
                                       f"Freq ref: {system.get('Frequency reference', 'N/A')}\n"
                                       f"Raw SR: {system.get('Sample rate', 'N/A')} · "
                                       f"Raw TB: {system.get('Timebase', 'N/A')}")
            self._update_channels_bar(channels)
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
        self.hide_image.setText("HIDE" if hidden else "SHOW")
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
        debug_text = "\n".join(list(debug_log)[-500:])
        if debug_text != self._last_debug_text:
            self._last_debug_text = debug_text
            self.debug_text.setPlainText(debug_text)
        # Activity indicator mirroring the Tk LED meter's inputs, extended
        # with job detail (pause state, power iterations).
        if app_state.is_logging_active:
            paused = bool(getattr(longtime, "pause_flag", False))
            state, color = ("⏸ LOG-PAUSED", "#fd0") if paused else ("■ LOG", "#e44")
        elif app_state.is_power_analysis_active:
            try:
                iterations = int(getattr(getattr(self.power, "log", None), "count", 0))
            except (TypeError, ValueError):
                iterations = 0
            state, color = (f"■ PWR ×{iterations}", "#fd0")
        elif app_state.is_scpi_busy:
            state, color = "■ SCPI", "#4f6"
        else:
            state, color = "□ IDLE", "#5c6b7d"
        if (state, color) != self._last_activity:
            self._last_activity = (state, color)
            self.activity.setText(state)
            self.activity.setStyleSheet(f"color: {color}; font-weight: bold;")
        # Data age: green when fresh, amber when stale, red on lost poll.
        if self._last_poll is None:
            data_text, tint = "DATA —", "#5c6b7d"
        else:
            age = time.monotonic() - self._last_poll
            if age < 5:
                tint = "#4f6"
            elif age < 15:
                tint = "#fd0"
            else:
                tint = "#e44"
            data_text = f"DATA {age:.0f}s"
        if data_text != self._last_data_text:
            self._last_data_text = data_text
            self.data_age.setText(data_text)
        if tint != self._last_data_tint:
            self._last_data_tint = tint
            self.data_age.setStyleSheet(f"font-family: monospace; color: {tint};")
        # Build tag + UTC clock for screenshot/CSV traceability.
        build_text = (f"{version.VERSION} {version.GIT_COMMIT} · "
                      f"{datetime.now(timezone.utc):%H:%M:%S}Z")
        if build_text != self._last_build_text:
            self._last_build_text = build_text
            self.build.setText(build_text)

    def closeEvent(self, event):
        self.closing = True
        app_state.is_shutting_down = True
        try:
            self.workspace.setValue("mainGeometry", self.saveGeometry())
            self.workspace.setValue("splitterSizes", self.splitter.saveState())
            self.workspace.setValue("tabIndex", self.tabs.currentIndex())
        except (AttributeError, RuntimeError):
            pass
        stop_logging()
        self.poll_timer.stop()
        self.image_timer.stop()
        self.debug_timer.stop()
        self.executor.submit(self.backend.close)
        self.executor.shutdown(wait=False)
        self.images.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)
