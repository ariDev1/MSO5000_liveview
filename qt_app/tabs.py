"""Core measurement controls for the alternative Qt viewer."""

import math
import platform
import shutil
import sys
import time
from pathlib import Path

import app.app_state as app_state
from logger.longtime import pause_resume, start_logging, stop_logging
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget, QDialog,
)

from qt_app.backend import PowerLog, channel_name, current_scale, logging_channels


def heading(text):
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def readout():
    widget = QPlainTextEdit()
    widget.setReadOnly(True)
    return widget


# Rigol-style channel palette, shared by all Qt tabs for traceability.
CHANNEL_COLORS = {"CHAN1": "#ffd200", "CHAN2": "#00eaff",
                  "CHAN3": "#d946ff", "CHAN4": "#4f6"}


def channel_color(name, default="#e8f0f7"):
    """Hex color for a channel name (accepts 1, CH1, CHAN1, MATH1, …)."""
    text = str(name).strip().upper()
    if text.startswith("MATH"):
        return "#9aa7b4"
    if text.startswith("CH") and not text.startswith("CHAN"):
        text = "CHAN" + text[2:]
    return CHANNEL_COLORS.get(text, default)


def tint_channel_combo(combo):
    """Paint each CHANx dropdown entry in its channel color (display-only)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    model = combo.model()
    for row in range(combo.count()):
        color = channel_color(combo.itemText(row), None)
        if color is not None:
            model.setData(model.index(row, 0), QColor(color), Qt.ItemDataRole.ForegroundRole)


def settings_store():
    """Per-user Qt settings (UI state only; never scope or lab data)."""
    from PySide6.QtCore import QSettings
    return QSettings("ariDev1", "MSO5000-Qt")


def as_bool(value, default=False):
    if isinstance(value, str):
        return value.lower() not in ("false", "0", "no", "")
    return bool(value) if value is not None else default


def format_si(value, unit):
    """Engineer-style SI formatting mirroring the Tk power tab (UI-only)."""
    try:
        abs_val = abs(float(value))
    except (TypeError, ValueError):
        return f"n/a {unit}".strip()
    if abs_val >= 1e6:
        return f"{value / 1e6:.3f} M{unit}"
    if abs_val >= 1e3:
        return f"{value / 1e3:.3f} k{unit}"
    if abs_val >= 1:
        return f"{value:.3f} {unit}"
    if abs_val >= 1e-3:
        return f"{value / 1e-3:.3f} m{unit}"
    if abs_val >= 1e-6:
        return f"{value / 1e-6:.3f} µ{unit}"
    return f"{value:.3e} {unit}"


class SystemTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Instrument status"))
        row = QHBoxLayout()
        self.docs = QComboBox()
        self.docs.addItem("Documentation…", None)
        for document in sorted((Path(__file__).resolve().parents[1] / "docs").glob("*.md")):
            self.docs.addItem(document.stem, document)
        self.docs.currentIndexChanged.connect(self.show_document)
        copy = QPushButton("COPY SYSTEM INFO")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        row.addWidget(self.docs, 1)
        row.addWidget(copy)
        layout.addLayout(row)
        self.text = readout()
        layout.addWidget(self.text)
        self.system = {}
        self.idn = "N/A"
        self.document_path = None
        self.document_text = ""

    def update_data(self, system, idn):
        self.system, self.idn = system, idn
        self.show_document()

    def show_document(self):
        from version import VERSION, GIT_COMMIT, BUILD_DATE, AUTHOR, PROJECT_URL
        import psutil
        try:
            import numpy as _np
            numpy_v = _np.__version__
        except Exception:
            numpy_v = "-"
        try:
            import matplotlib as _mpl
            matplotlib_v = _mpl.__version__
        except Exception:
            matplotlib_v = "-"
        try:
            import pandas as _pd
            pandas_v = _pd.__version__
        except Exception:
            pandas_v = "-"
        try:
            import scipy as _sp
            scipy_v = _sp.__version__
        except Exception:
            scipy_v = "-"
        try:
            import pyvisa as _visa
            visa_v = _visa.__version__
        except Exception:
            visa_v = "-"
        free = shutil.disk_usage(Path.cwd()).free / (1024 ** 3)
        info = (f"MSO5000 Liveview {VERSION}  ·  {GIT_COMMIT}  ·  {BUILD_DATE}  ·  {AUTHOR}\n"
                f"{PROJECT_URL}\n"
                f"Host: {platform.system()} {platform.release()} ({platform.machine()})\n"
                f"Python: {sys.version.split()[0]}  | NumPy {numpy_v}, Matplotlib {matplotlib_v}, "
                f"Pandas {pandas_v}, SciPy {scipy_v}\n"
                f"PyVISA: {visa_v}    CPU: {psutil.cpu_percent()}%    "
                f"RAM: {psutil.virtual_memory().percent}%    Disk free: {free:.1f} GiB\n"
                f"Logging: {app_state.is_logging_active}  Power: {app_state.is_power_analysis_active}  "
                f"SCPI busy: {app_state.is_scpi_busy}  Shutdown: {app_state.is_shutting_down}\n\n"
                f"Instrument: {self.idn}\n\n" +
                "\n".join(f"{key:<22}: {value}" for key, value in self.system.items()))
        document = self.docs.currentData()
        if document:
            if document != self.document_path:
                self.document_text = document.read_text(encoding="utf-8")[:200000]
            info += f"\n\n--- {document.name} ---\n{self.document_text}"
        self.document_path = document
        if self.text.toPlainText() != info:
            scroll = self.text.verticalScrollBar()
            position = scroll.value()
            self.text.setPlainText(info)
            scroll.setValue(position)


class LicensesTab(QWidget):
    def __init__(self, submit, ip):
        super().__init__()
        self.submit, self.ip = submit, ip
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Licensed options"))
        self.text = readout()
        layout.addWidget(self.text)
        button = QPushButton("REFRESH")
        button.clicked.connect(self.refresh)
        layout.addWidget(button)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(15000)

    def refresh(self):
        from scpi.licenses import get_license_options

        def done(options):
            if isinstance(options, Exception):
                self.text.setPlainText(f"License query failed: {options}")
                return
            if not options:
                self.text.setPlainText("No license data received")
                return
            lines = ["LICENSED OPTIONS:", "=" * 60]
            for item in options:
                status = item["status"]
                symbol = "✅" if status == "Forever" else "🕑" if "Trial" in status else "❌"
                lines.append(f"{symbol} {item['code']:10s} | {status:12s} | {item['desc']}")
            self.text.setPlainText("\n".join(lines))

        self.submit(lambda: get_license_options(self.ip), done, image=True)


class ChannelsTab(QWidget):
    # GAP (Tk parity, recorded): the Tk tab renders compact one-line channel
    # summaries from its own channel cache and opens a fresh connection per
    # export. Qt shows the full polled snapshot detail and exports through
    # the shared backend instead — same files, no shared code touched.
    def __init__(self, submit, backend, notify):
        super().__init__()
        self.submit, self.backend, self.notify = submit, backend, notify
        self.channels = {}
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Active channels"))
        self.text = readout()
        layout.addWidget(self.text)
        row = QHBoxLayout()
        copy = QPushButton("COPY SETTINGS")
        copy.clicked.connect(lambda: self.copy_settings())
        export = QPushButton("EXPORT CHANNELS CSV")
        export.clicked.connect(self.export)
        copy_csv = QPushButton("COPY WAVEFORM CSV")
        copy_csv.clicked.connect(self.copy_csv)
        row.addWidget(copy)
        row.addWidget(export)
        row.addWidget(copy_csv)
        row.addStretch()
        layout.addLayout(row)

    def update_data(self, channels):
        self.channels = channels
        value = "\n\n".join(
            name + "\n" + "\n".join(f"  {key:<16} {value}" for key, value in data.items())
            for name, data in channels.items()) or "No displayed channels"
        if self.text.toPlainText() != value:
            scroll = self.text.verticalScrollBar()
            position = scroll.value()
            self.text.setPlainText(value)
            scroll.setValue(position)

    def copy_settings(self):
        QApplication.clipboard().setText(self.text.toPlainText())
        self.notify("Channel settings copied")

    def export(self):
        if app_state.is_logging_active:
            self.notify("Stop long-time logging before exporting channels")
        elif not self.channels:
            self.notify("No displayed channels to export")
        else:
            names = list(self.channels)
            self.submit(lambda: self.backend.export(names),
                        lambda paths: self.notify(f"Export failed: {paths}" if isinstance(paths, Exception)
                                                  else "Exported: " + ", ".join(paths)))

    def copy_csv(self):
        if app_state.is_logging_active or not self.channels:
            self.notify("Select displayed channels and stop logging before copying CSV")
            return
        names = list(self.channels)

        def finished(paths):
            if isinstance(paths, Exception):
                self.notify(f"CSV copy failed: {paths}")
                return
            QApplication.clipboard().setText("\n\n".join(
                Path(path).read_text(encoding="utf-8") for path in paths))
            self.notify("Waveform CSV copied to clipboard")

        self.submit(lambda: self.backend.export(names), finished)


class LoggingTab(QWidget):
    def __init__(self, backend, notify):
        super().__init__()
        self.backend, self.notify = backend, notify
        self.running = False
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Long-time measurement"))
        group = QGroupBox("Session settings")
        form = QFormLayout(group)
        self.channels = QLineEdit("1,2")
        self.duration = QDoubleSpinBox()
        self.duration.setRange(0.001, 100000)
        self.duration.setDecimals(3)
        self.duration.setValue(0.1)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.1, 3600)
        self.interval.setValue(5)
        self.vavg = QCheckBox("Include average")
        self.vrms = QCheckBox("Include RMS")
        form.addRow("Channels (1,2,MATH1)", self.channels)
        form.addRow("Duration (hours)", self.duration)
        form.addRow("Interval (seconds)", self.interval)
        form.addRow(self.vavg, self.vrms)
        layout.addWidget(group)
        row = QHBoxLayout()
        self.start_button = QPushButton("START")
        self.pause_button = QPushButton("PAUSE")
        self.stop_button = QPushButton("STOP")
        self.start_button.clicked.connect(self.start)
        self.pause_button.clicked.connect(self.pause)
        self.stop_button.clicked.connect(self.stop)
        for button in (self.start_button, self.pause_button, self.stop_button):
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.status = readout()
        layout.addWidget(self.status)
        tip = QLabel("Performance: use ≥1 s for 1–2 channels and ≥2 s for 3–4 channels. "
                     "The logger writes one timestamped CSV per session.")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def start(self):
        if self.backend.scope is None:
            self.notify("Scope is not connected")
            return
        try:
            channels = logging_channels(self.channels.text())
            if not channels:
                raise ValueError("Select at least one channel")
        except ValueError as error:
            self.notify(str(error))
            return
        if app_state.is_power_analysis_active:
            self.notify("Wait for power analysis to finish")
            return
        if app_state.is_logging_active:
            self.notify("A logging session is already running")
            return
        # The existing logger uses a background thread; its callback only emits a Qt signal.
        start_logging(None, self.backend.ip, channels, self.duration.value(),
                      self.interval.value(), self.vavg.isChecked(), self.vrms.isChecked(),
                      self.notify)
        self.running = app_state.is_logging_active
        if self.running:
            self.status.appendPlainText("Logging started in oszi_csv/")
        self.refresh()

    def pause(self):
        paused = pause_resume()
        self.pause_button.setText("RESUME" if paused else "PAUSE")
        self.status.appendPlainText("Paused" if paused else "Resumed")

    def stop(self):
        stop_logging()
        self.status.appendPlainText("Stop requested")

    def refresh(self):
        active = app_state.is_logging_active
        if self.running and not active:
            self.status.appendPlainText("Logging session ended")
        self.running = active
        self.start_button.setEnabled(not active)
        self.pause_button.setEnabled(active)
        self.stop_button.setEnabled(active)
        if not active:
            self.pause_button.setText("PAUSE")


class PQPlot(QWidget):
    """2D PQ operating-point plot mirroring the Tk tab's power triangle.

    GAP (Tk parity, recorded): the Tk tab draws this with Matplotlib and
    saves a ``*_summary.png`` on auto-refresh stop; the Qt viewer keeps a
    lightweight QPainter rendering and does not write a summary PNG, so the
    CSV log remains the lab record in both viewers.
    """

    def __init__(self):
        super().__init__()
        self.setMinimumSize(280, 210)
        self.points = []
        self.summary = {"S": 0.0, "PF": 0.0, "theta": 0.0, "Z": 0.0}

    def push(self, p, q, metadata=None):
        self.points.append((p, q))
        self.points = self.points[-30:]
        if metadata:
            try:
                self.summary = {
                    "S": float(metadata.get("S", 0.0) or 0.0),
                    "PF": float(metadata.get("PF", 0.0) or 0.0),
                    "theta": float(metadata.get("theta", 0.0) or 0.0),
                    "Z": float(metadata.get("Z", 0.0) or 0.0),
                }
            except (TypeError, ValueError):
                pass
        self.update()

    def _quadrant(self, p, q):
        if p >= 0 and q >= 0:
            return 1
        if p < 0 and q >= 0:
            return 2
        if p < 0 and q < 0:
            return 3
        return 4

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#171e2b"))
        cx, cy = self.width() / 2, self.height() / 2
        painter.setPen(QPen(QColor("#445469"), 1))
        painter.drawLine(20, int(cy), self.width() - 20, int(cy))
        painter.drawLine(int(cx), 18, int(cx), self.height() - 20)
        if self.points:
            limit_p = max(1, *(abs(p) * 1.5 for p, _ in self.points))
            limit_q = max(1, *(abs(q) * 1.5 for _, q in self.points))

            def to_xy(p, q):
                return (int(cx + p / limit_p * (cx - 28)),
                        int(cy - q / limit_q * (cy - 26)))

            # Fading trail matching the Tk tab's 30-point history.
            for index, (p, q) in enumerate(self.points):
                alpha = 60 + int(195 * (index + 1) / len(self.points))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(136, 136, 136, alpha // 3))
                px, qy = to_xy(p, q)
                painter.drawEllipse(px - 3, qy - 3, 6, 6)
            p, q = self.points[-1]
            px, qy = to_xy(p, q)
            # Power triangle: S (hypotenuse), P (adjacent), Q (opposite).
            painter.setPen(QPen(QColor("#eead68"), 2, Qt.PenStyle.DashLine))
            painter.drawLine(int(cx), int(cy), px, qy)
            painter.setPen(QPen(QColor("#65b9eb"), 1))
            painter.drawLine(int(cx), int(cy), px, int(cy))
            painter.setPen(QPen(QColor("#a7e88d"), 1))
            painter.drawLine(px, int(cy), px, qy)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(73, 208, 174, 255))
            painter.drawEllipse(px - 4, qy - 4, 8, 8)
            quadrant = self._quadrant(p, q)
            painter.setPen(QColor("#bbbbbb"))
            for label, x, y in (("I", 0.90, 0.10), ("II", 0.10, 0.10),
                                ("III", 0.10, 0.90), ("IV", 0.90, 0.90)):
                painter.drawText(int(self.width() * x), int(self.height() * y), label)
        painter.setPen(QColor("#a6b8ca"))
        painter.drawText(22, self.height() - 6, "P (W) →")
        painter.drawText(8, 16, "Q (VAR) ↑")
        if self.points:
            p, q = self.points[-1]
            summary = self.summary
            painter.drawText(self.rect().adjusted(8, 8, -12, -8),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                             f"P {p:.3g} W   Q {q:.3g} VAR\n"
                             f"S {summary['S']:.3g} VA   θ {summary['theta']:.1f}°   "
                             f"PF {summary['PF']:.3f}   Z {summary['Z']:.3g} Ω")


class PowerTab(QWidget):
    def __init__(self, submit, backend, notify):
        super().__init__()
        self.submit, self.backend, self.notify = submit, backend, notify
        self.log = PowerLog()
        self.pending = False
        self.context = ({}, {})
        self.pq3d = None
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(heading("Power analysis"))
        header.addStretch()
        self.setup_toggle = QPushButton("SETUP ▾")
        self.setup_toggle.setCheckable(True)
        self.setup_toggle.setToolTip("Fold/unfold the measurement setup to give the plot more room.")
        header.addWidget(self.setup_toggle)
        layout.addLayout(header)
        group = QGroupBox("Measurement setup")
        grid = QGridLayout(group)
        grid.setSpacing(4)
        grid.setContentsMargins(6, 6, 6, 6)
        self.voltage = QLineEdit("1")
        self.current = QLineEdit("2")
        # Dense sizing: single-character channels need no wide fields, but
        # "MATH1" (5 chars) must still fit.
        for field in (self.voltage, self.current):
            field.setFixedWidth(60)
        for field in (self.voltage, self.current):
            field.textChanged.connect(self._tint_fields)
            field.returnPressed.connect(self.measure)
        self._tint_fields()
        self.probe_type = QComboBox()
        self.probe_type.addItems(["shunt", "clamp"])
        self.probe_type.setFixedWidth(95)
        self.probe_value = QLineEdit("1.0")
        self.correction = QLineEdit("1.0")
        for field in (self.probe_value, self.correction):
            field.setFixedWidth(60)
        self.expected_power = QLineEdit()
        self.expected_power.setPlaceholderText("Ref W")
        self.expected_power.setFixedWidth(70)
        self.method = QComboBox()
        self.method.addItem("Instantaneous (v·i mean)", "standard")
        self.method.addItem("Vrms × Irms × cos(φ)", "rms_cos_phi")
        self.remove_dc = QCheckBox("Remove DC")
        self.remove_dc.setToolTip("DC Offset removal — when ON, results exclude the DC component.")
        # Tk labels these "25M[v]" / "25M[i]" (full 25 Mpts memory depth per
        # channel); keep the same meaning here without touching shared code.
        self.raw_v = QCheckBox("25M[v]")
        self.raw_v.setToolTip("Fetch full 25 Mpts memory depth for the voltage channel.")
        self.raw_i = QCheckBox("25M[i]")
        self.raw_i.setToolTip("Fetch full 25 Mpts memory depth for the current channel.")
        labels = (("Voltage Ch", "Channel for the voltage probe (e.g. 1, MATH1)"),
                  ("Current Ch", "Channel for the current probe (e.g. 2, MATH1)"),
                  ("Probe", "Current probe type"),
                  ("Value", "Shunt Ω (e.g. 0.01 for 10 mΩ) or clamp value"),
                  ("Corr ×", "Multiplicative correction factor"),
                  ("Formula", "Power formula"))
        for col, ((text, tip), widget) in enumerate(zip(labels, (
                self.voltage, self.current, self.probe_type, self.probe_value,
                self.correction, self.method))):
            label = QLabel(text)
            label.setToolTip(tip)
            grid.addWidget(label, 0, col * 2)
            grid.addWidget(widget, 0, col * 2 + 1)
        grid.addWidget(self.remove_dc, 1, 0, 1, 2)
        grid.addWidget(self.raw_v, 1, 2, 1, 2)
        grid.addWidget(self.raw_i, 1, 4, 1, 2)
        expected_label = QLabel("Expected P (W)")
        expected_label.setToolTip("Optional reference power for calibration")
        grid.addWidget(expected_label, 1, 6)
        grid.addWidget(self.expected_power, 1, 7)
        calibration = QPushButton("CALIBRATE")
        calibration.setToolTip("Calibrate the correction factor from the expected power")
        calibration.clicked.connect(self.calibrate)
        grid.addWidget(calibration, 1, 8, 1, 2)
        self.scale_info = QLabel("Effective current scale: 1 A/V")
        grid.addWidget(self.scale_info, 1, 10, 1, 2)
        grid.setColumnStretch(11, 1)
        for control in (self.probe_value, self.correction):
            control.textChanged.connect(self.update_scale)
        self.probe_type.currentIndexChanged.connect(self.update_scale)
        self.update_scale()
        tip = QLabel("Tip: UNIT:V → set Value to shunt Ω (e.g., 0.01 for 10 mΩ). "
                     "UNIT:A → set Value = 1.0. For better power accuracy, enable the "
                     "20 MHz BW limit on the scope channels. Avoid >20 MHz unless needed.")
        tip.setWordWrap(True)
        self.setup_group = group
        self.setup_tip = tip
        layout.addWidget(group)
        layout.addWidget(tip)
        # Fold state persists per user (same QSettings as the UI zoom).
        from PySide6.QtCore import QSettings
        self.setup_settings = QSettings("ariDev1", "MSO5000-Qt")
        expanded = self.setup_settings.value("powerSetupExpanded", True)
        expanded = str(expanded).lower() not in ("false", "0", "no")
        self.setup_toggle.toggled.connect(self._toggle_setup)
        self.setup_toggle.setChecked(expanded)
        self._toggle_setup(expanded)
        controls = QHBoxLayout()
        self.measure_button = QPushButton("MEASURE")
        self.measure_button.setObjectName("primaryButton")
        self.measure_button.setToolTip("Single power measurement with the current setup.")
        self.measure_button.clicked.connect(self.measure)
        self.auto = QCheckBox("Auto-measure")
        self.period = QSpinBox()
        self.period.setRange(2, 60)
        self.period.setValue(5)
        self.period.setSuffix(" s")
        self.duration = QSpinBox()
        self.duration.setRange(0, 86400)
        self.duration.setSuffix(" s (0 = unlimited)")
        # GAP (Tk parity, recorded): the Tk tab uses a "3D View (P,Q,t)"
        # checkbox that owns the pop-out window lifecycle; Qt uses a button
        # opening the same PQ3DView backend in a dialog. Same backend module,
        # no shared-code change.
        view3d = QPushButton("3D PQ VIEW")
        view3d.clicked.connect(self.show_3d)
        plot_last = QPushButton("PLOT LAST LOG")
        plot_last.clicked.connect(self.plot_last)
        controls.addWidget(self.measure_button)
        controls.addWidget(self.auto)
        controls.addWidget(QLabel("Interval"))
        controls.addWidget(self.period)
        controls.addWidget(QLabel("Duration"))
        controls.addWidget(self.duration)
        controls.addWidget(view3d)
        controls.addWidget(plot_last)
        controls.addStretch()
        layout.addLayout(controls)
        self.headline = QLabel("P —")
        self.headline.setObjectName("headline")
        layout.addWidget(self.headline)
        self.plot = PQPlot()
        self.results = readout()
        self.results.setMinimumHeight(180)
        layout.addWidget(self.plot, 2)
        layout.addWidget(self.results, 1)
        self.setup_status = QLabel("Select a voltage and current channel")
        self.setup_status.setWordWrap(True)
        layout.addWidget(self.setup_status)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._auto_tick)
        self.timer.start(500)
        self.last_measurement = 0.0
        self._restore_setup()
        for control in (self.voltage, self.current, self.probe_value,
                        self.correction, self.expected_power):
            control.textChanged.connect(lambda _=None: self._save_setup())
        for box in (self.probe_type, self.method):
            box.currentIndexChanged.connect(lambda _=None: self._save_setup())
        for check in (self.remove_dc, self.raw_v, self.raw_i):
            check.toggled.connect(lambda _=None: self._save_setup())
        for spin in (self.period, self.duration):
            spin.valueChanged.connect(lambda _=None: self._save_setup())

    def _save_setup(self):
        store = settings_store()
        store.beginGroup("power")
        store.setValue("voltage", self.voltage.text())
        store.setValue("current", self.current.text())
        store.setValue("probeType", self.probe_type.currentIndex())
        store.setValue("probeValue", self.probe_value.text())
        store.setValue("correction", self.correction.text())
        store.setValue("method", self.method.currentIndex())
        store.setValue("expected", self.expected_power.text())
        store.setValue("removeDC", self.remove_dc.isChecked())
        store.setValue("rawV", self.raw_v.isChecked())
        store.setValue("rawI", self.raw_i.isChecked())
        store.setValue("period", self.period.value())
        store.setValue("duration", self.duration.value())
        store.endGroup()

    def _restore_setup(self):
        store = settings_store()
        store.beginGroup("power")
        for widget in (self, self.voltage, self.current, self.probe_type,
                       self.probe_value, self.correction, self.method,
                       self.expected_power, self.remove_dc, self.raw_v,
                       self.raw_i, self.period, self.duration):
            widget.blockSignals(True)
        try:
            self.voltage.setText(store.value("voltage", "1"))
            self.current.setText(store.value("current", "2"))
            self.probe_type.setCurrentIndex(
                min(max(0, int(store.value("probeType", 0))), self.probe_type.count() - 1))
            self.probe_value.setText(store.value("probeValue", "1.0"))
            self.correction.setText(store.value("correction", "1.0"))
            self.method.setCurrentIndex(
                min(max(0, int(store.value("method", 0))), self.method.count() - 1))
            self.expected_power.setText(store.value("expected", ""))
            self.remove_dc.setChecked(as_bool(store.value("removeDC"), False))
            self.raw_v.setChecked(as_bool(store.value("rawV"), False))
            self.raw_i.setChecked(as_bool(store.value("rawI"), False))
            self.period.setValue(int(store.value("period", 5)))
            self.duration.setValue(int(store.value("duration", 0)))
        except (TypeError, ValueError):
            pass
        finally:
            for widget in (self, self.voltage, self.current, self.probe_type,
                           self.probe_value, self.correction, self.method,
                           self.expected_power, self.remove_dc, self.raw_v,
                           self.raw_i, self.period, self.duration):
                widget.blockSignals(False)
        store.endGroup()
        self.update_scale()
        self._tint_fields()

    def _toggle_setup(self, expanded):
        self.setup_group.setVisible(expanded)
        self.setup_tip.setVisible(expanded)
        self.setup_toggle.setText("SETUP ▾" if expanded else "SETUP ▸")
        self.setup_settings.setValue("powerSetupExpanded", bool(expanded))

    def _tint_fields(self):
        # Channel-colored input text for traceability (display-only).
        for field in (self.voltage, self.current):
            try:
                channel_name(field.text())
            except ValueError:
                continue
            field.setStyleSheet(f"color: {channel_color(field.text())};")

    def update_scale(self):
        try:
            # The Tk tab coerces an empty correction back to 1.0; mirror that
            # locally so clearing the field never breaks scaling.
            correction = self.correction.text().strip() or "1.0"
            scale = current_scale(self.probe_type.currentText(), self.probe_value.text(),
                                  correction)
            self.scale_info.setText(f"Effective current scale: {scale:.4g} A/V")
        except ValueError:
            self.scale_info.setText("Enter a valid probe value and correction")

    def update_context(self, system, channels):
        self.context = (system, channels)

        def numeric(value):
            try:
                return float(value or 0)
            except (ValueError, TypeError):
                return 0.0

        try:
            v = channel_name(self.voltage.text()).replace("CHAN", "CH")
            i = channel_name(self.current.text()).replace("CHAN", "CH")
            v_info, i_info = channels.get(v, {}), channels.get(i, {})
            skew = (numeric(v_info.get("Deskew (s)")) -
                    numeric(i_info.get("Deskew (s)"))) * 1e9
            unit = str(i_info.get("Unit", "N/A"))
            probe = str(i_info.get("Probe", "N/A"))
            try:
                scope_probe = float(i_info.get("Probe", 1.0))
            except (TypeError, ValueError):
                scope_probe = None
            warning = ""
            if scope_probe is not None:
                if self.probe_type.currentText() == "shunt" and abs(scope_probe - 1.0) > 0.5:
                    warning = (f"   ℹ Scope probe {scope_probe:.1f}× with shunt: "
                               "results stay correct; 1× may improve SNR")
                elif self.probe_type.currentText() == "clamp" and scope_probe < 2.0:
                    warning = (f"   ⚠ Mismatch: scope={scope_probe:.1f}× — "
                               "clamp probes often need 10×+")
            self.setup_status.setText(
                f"Frequency reference: {system.get('Frequency reference', 'N/A')}   "
                f"Current unit: {unit}   "
                f"Scope probe: {probe}×   "
                f"Deskew Δt(V−I): {skew:+.1f} ns" +
                ("   ⚠ Channel offset active" if
                 any(abs(numeric(info.get("Offset"))) > 0.01
                     for info in (v_info, i_info)) else "   ✓ No active offset") +
                warning +
                ("   DC removal ON" if self.remove_dc.isChecked()
                 else "   DC removal OFF — full waveform analyzed"))
        except (ValueError, TypeError):
            pass

    def show_3d(self):
        if self.pq3d is not None:
            self.pq3d[0].raise_()
            return
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from gui.power.pq3d_view import PQ3DView
        dialog = QDialog(self)
        dialog.setWindowTitle("PQ 3D — (P,Q,t)")
        dialog.resize(900, 670)
        view = PQ3DView(max_age_s=120, max_points=20000)
        canvas = FigureCanvasQTAgg(view.fig)
        layout = QVBoxLayout(dialog)
        layout.addWidget(canvas)
        dialog.finished.connect(lambda _: setattr(self, "pq3d", None))
        self.pq3d = (dialog, view, canvas)
        dialog.show()

    def plot_last(self):
        # GAP (Tk parity, recorded): the Tk tab launches
        # utils/plot_rigol_csv.py as an external process. The Qt viewer keeps
        # an embedded P/Q-versus-sample dialog over the same
        # oszi_csv/power_log_*.csv files instead, so no subprocess or shared
        # code is involved.
        import pandas as pd
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
        files = list(Path("oszi_csv").glob("power_log_*.csv"))
        if not files:
            self.notify("No power log CSV found")
            return
        path = max(files, key=lambda file: file.stat().st_mtime)
        try:
            data = pd.read_csv(path, comment="#")
            p, q = data["P (W)"], data["Q (VAR)"]
            figure = Figure(figsize=(8, 5), facecolor="#101722")
            axes = figure.add_subplot(111)
            axes.plot(p, label="P (W)")
            axes.plot(q, label="Q (VAR)")
            axes.legend()
            axes.set_xlabel("Sample")
            axes.set_title(path.name)
            dialog = QDialog(self)
            dialog.setWindowTitle("Power log")
            dialog.resize(900, 600)
            canvas = FigureCanvasQTAgg(figure)
            box = QVBoxLayout(dialog)
            box.addWidget(canvas)
            dialog.show()
            self.last_dialog = dialog
        except Exception as error:
            self.notify(f"Could not plot log: {error}")

    def _auto_tick(self):
        if self.auto.isChecked() and not self.pending and not app_state.is_logging_active:
            if self.duration.value() and self.log.started is not None:
                if time.time() - self.log.started >= self.duration.value():
                    self.auto.setChecked(False)
                    self.notify("Auto-measure duration reached")
                    return
            if time.monotonic() - self.last_measurement >= self.period.value():
                self.measure()

    def calibrate(self):
        # Mirrors the Tk auto-calibration: one uncorrected ("standard") probe
        # shot establishes the correction factor, then a full measurement with
        # the selected formula follows. Shared measurement code is untouched.
        if self.pending or app_state.is_logging_active:
            self.notify("Wait for the active measurement to finish")
            return
        try:
            reference = float(self.expected_power.text())
            if not math.isfinite(reference) or reference == 0:
                raise ValueError
            voltage = channel_name(self.voltage.text())
            current = channel_name(self.current.text())
            scale = current_scale(self.probe_type.currentText(), self.probe_value.text(), 1)
        except ValueError:
            self.notify("Enter a non-zero expected power and valid probe settings")
            return
        self.pending = True
        app_state.is_power_analysis_active = True
        self.measure_button.setEnabled(False)
        dc = self.remove_dc.isChecked()

        def finished(result):
            self.pending = False
            app_state.is_power_analysis_active = False
            self.measure_button.setEnabled(True)
            if isinstance(result, Exception):
                self.notify(f"Calibration failed: {result}")
                return
            measured = result["Real Power (P)"]
            if measured <= 0:
                self.notify("Calibration requires positive measured power")
                return
            self.correction.setText(f"{reference / measured:.4f}")
            self.measure()

        self.submit(lambda: self.backend.measure(
            voltage, current, scale, dc, "standard", False, False), finished)

    def measure(self):
        if self.pending or app_state.is_logging_active:
            self.notify("Measurement unavailable while logging")
            return
        try:
            voltage = channel_name(self.voltage.text())
            current = channel_name(self.current.text())
            probe_type, value, correction = (self.probe_type.currentText(),
                                              self.probe_value.text(), self.correction.text())
            scale = current_scale(probe_type, value, correction)
        except ValueError as error:
            self.notify(str(error))
            return
        method = self.method.currentData()
        dc = self.remove_dc.isChecked()
        raw_v, raw_i = self.raw_v.isChecked(), self.raw_i.isChecked()
        # GAP (Tk parity, recorded): the Tk CSV header also carries "# Created"
        # and FrequencyRef comment rows. Qt keeps its established comment rows
        # unchanged (CSV schema frozen) and shows the frequency reference in
        # the setup status and results instead.
        details = {"VoltageCh": voltage, "CurrentCh": current, "Method": method,
                   "ProbeType": probe_type, "ProbeValue": value, "CurrentScale(A/V)": scale,
                   "CorrectionFactor": correction, "RemoveDC": dc}
        self.pending = True
        app_state.is_power_analysis_active = True
        self.measure_button.setEnabled(False)

        def finished(result):
            self.pending = False
            app_state.is_power_analysis_active = False
            self.last_measurement = time.monotonic()
            self.measure_button.setEnabled(True)
            if isinstance(result, Exception):
                self.notify(f"Power measurement failed: {result}")
                return
            average, energy = self.log.add(result, details)
            impedance = result["Vrms"] / result["Irms"] if result["Irms"] else 0.0
            avg_pf = average["PF"]
            try:
                if math.isfinite(avg_pf):
                    pf_angle = math.degrees(math.acos(max(min(avg_pf, 1.0), -1.0)))
                else:
                    pf_angle = float(result["Phase Angle (deg)"])
            except (ValueError, TypeError, KeyError):
                try:
                    pf_angle = float(result["Phase Angle (deg)"])
                except (ValueError, TypeError, KeyError):
                    pf_angle = 0.0
            self.plot.push(average["P"], average["Q"],
                           {"S": average["S"], "PF": avg_pf,
                            "theta": pf_angle, "Z": impedance})
            if self.pq3d is not None:
                _, view, canvas = self.pq3d
                view.push(time.time(), average["P"], average["Q"])
                view.draw()
                canvas.draw_idle()
            try:
                elapsed_sec = int(time.time() - self.log.started)
            except TypeError:
                elapsed_sec = 0
            elapsed_hms = time.strftime("%H:%M:%S", time.gmtime(elapsed_sec))
            freq_ref = self.context[0].get("Frequency reference", "N/A")
            correction = (self.correction.text().strip() or "1.0")
            self.results.setPlainText(
                f"Correction Factor: ×{correction}\n\n"
                f"{'Metric':<22} {'Instant':>12}    {'Average':>12}\n"
                f"{'-' * 50}\n"
                f"{'Real power (P)':<22}: {format_si(result['Real Power (P)'], 'W'):<12} | "
                f"{format_si(average['P'], 'W'):<12}\n"
                f"{'Apparent power (S)':<22}: {format_si(result['Apparent Power (S)'], 'VA'):<12} | "
                f"{format_si(average['S'], 'VA'):<12}\n"
                f"{'Reactive power (Q)':<22}: {format_si(result['Reactive Power (Q)'], 'VAR'):<12} | "
                f"{format_si(average['Q'], 'VAR'):<12}\n"
                f"{'Power factor':<22}: {result['Power Factor']:>12.4f}  | {average['PF']:>12.6f}\n"
                f"{'Vrms (V)':<22}: {format_si(result['Vrms'], 'V'):<12} | "
                f"{format_si(average['Vrms'], 'V'):<12}\n"
                f"{'Irms (A)':<22}: {format_si(result['Irms'], 'A'):<12} | "
                f"{format_si(average['Irms'], 'A'):<12}\n\n"
                f"{'Impedance (Z)':<22}: {format_si(impedance, 'Ω'):<12}\n"
                f"{'Frequency (ref)':<22}: {str(freq_ref).strip():<12}  (used for θ, PF)\n"
                f"{'PF Angle (θ)':<22}: {pf_angle:>10.2f} °\n"
                f"{'Real Energy':<22}: {format_si(energy[0], 'Wh'):<12}\n"
                f"{'Apparent Energy':<22}: {format_si(energy[1], 'VAh'):<12}\n"
                f"{'Reactive Energy':<22}: {format_si(energy[2], 'VARh'):<12}\n"
                f"\nIterations: {self.log.count}    Elapsed: {elapsed_hms}\n"
                f"CSV: {self.log.path}")
            self.headline.setText(
                f"P {format_si(result['Real Power (P)'], 'W')}   "
                f"AVG {format_si(average['P'], 'W')}")

        self.submit(lambda: self.backend.measure(voltage, current, scale, dc, method, raw_v, raw_i),
                    finished)


class SCPITab(QWidget):
    def __init__(self, submit, backend, notify):
        super().__init__()
        self.submit, self.backend, self.notify = submit, backend, notify
        layout = QVBoxLayout(self)
        layout.addWidget(heading("SCPI console"))
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Enter a SCPI command, e.g. *IDN?")
        self.input.returnPressed.connect(self.send)
        button = QPushButton("SEND")
        button.clicked.connect(self.send)
        selftest = QPushButton("SELF-TEST")
        selftest.clicked.connect(self.self_test)
        row.addWidget(self.input)
        row.addWidget(button)
        row.addWidget(selftest)
        layout.addLayout(row)
        columns = QHBoxLayout()
        self.output = readout()
        columns.addWidget(self.output, 3)
        self.commands = QListWidget()
        path = Path(__file__).resolve().parents[1] / "scpi_command_list.txt"
        if path.is_file():
            self.commands.addItems(line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                                   if line.strip())
        self.commands.itemClicked.connect(lambda item: self.input.setText(item.text()))
        columns.addWidget(self.commands, 1)
        layout.addLayout(columns)
        layout.addWidget(QLabel("Commands can change acquisition settings. Use with care."))

    def send(self):
        text = self.input.text().strip()
        if not text:
            return
        if app_state.is_logging_active:
            self.notify("SCPI console unavailable during long-time logging")
            return

        def finished(response):
            self.output.appendPlainText(f"> {text}\n{response}\n")

        self.submit(lambda: self.backend.command(text), finished)

    def self_test(self):
        # GAP (Tk parity, recorded): the Tk self-test stops acquisition,
        # probes channels and runs a power check (intrusive by design). The
        # Qt self-test stays read-only and never changes acquisition state.
        if app_state.is_logging_active:
            self.notify("Self-test unavailable during long-time logging")
            return
        self.submit(self.backend.self_test,
                    lambda result: self.output.appendPlainText(f"Self-test:\n{result}\n"))
