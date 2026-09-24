"""Core measurement controls for the alternative Qt viewer."""

import math
import time

import app.app_state as app_state
from logger.longtime import pause_resume, start_logging, stop_logging
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
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


class SystemTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Instrument status"))
        self.text = readout()
        layout.addWidget(self.text)

    def update_data(self, system, idn):
        self.text.setPlainText("Instrument\n" + idn + "\n\n" +
                               "\n".join(f"{key}: {value}" for key, value in system.items()))


class ChannelsTab(QWidget):
    def __init__(self, submit, backend, notify):
        super().__init__()
        self.submit, self.backend, self.notify = submit, backend, notify
        self.channels = {}
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Active channels"))
        self.text = readout()
        layout.addWidget(self.text)
        row = QHBoxLayout()
        copy = QPushButton("Copy settings")
        copy.clicked.connect(lambda: self.copy_settings())
        export = QPushButton("Export displayed channels to CSV")
        export.clicked.connect(self.export)
        row.addWidget(copy)
        row.addWidget(export)
        row.addStretch()
        layout.addLayout(row)

    def update_data(self, channels):
        self.channels = channels
        self.text.setPlainText("\n".join(
            f"{name}  " + "  |  ".join(f"{key}: {value}" for key, value in data.items())
            for name, data in channels.items()) or "No displayed channels")

    def copy_settings(self):
        from PySide6.QtWidgets import QApplication
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
                        lambda paths: self.notify("Exported: " + ", ".join(paths)))


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
        self.start_button = QPushButton("Start logging")
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop")
        self.start_button.clicked.connect(self.start)
        self.pause_button.clicked.connect(self.pause)
        self.stop_button.clicked.connect(self.stop)
        for button in (self.start_button, self.pause_button, self.stop_button):
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.status = readout()
        layout.addWidget(self.status)
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
        self.pause_button.setText("Resume" if paused else "Pause")
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
            self.pause_button.setText("Pause")


class PQPlot(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(280, 210)
        self.points = []

    def push(self, p, q):
        self.points.append((p, q))
        self.points = self.points[-30:]
        self.update()

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
            for index, (p, q) in enumerate(self.points):
                alpha = 60 + int(195 * (index + 1) / len(self.points))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(73, 208, 174, alpha))
                painter.drawEllipse(int(cx + p / limit_p * (cx - 28)) - 4,
                                    int(cy - q / limit_q * (cy - 26)) - 4, 8, 8)
        painter.setPen(QColor("#a6b8ca"))
        painter.drawText(22, self.height() - 6, "P (W) →")
        painter.drawText(8, 16, "Q (VAR) ↑")


class PowerTab(QWidget):
    def __init__(self, submit, backend, notify):
        super().__init__()
        self.submit, self.backend, self.notify = submit, backend, notify
        self.log = PowerLog()
        self.pending = False
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Power analysis"))
        group = QGroupBox("Measurement setup")
        grid = QGridLayout(group)
        self.voltage = QLineEdit("1")
        self.current = QLineEdit("2")
        self.probe_type = QComboBox()
        self.probe_type.addItems(["shunt", "clamp"])
        self.probe_value = QLineEdit("1.0")
        self.correction = QLineEdit("1.0")
        self.expected_power = QLineEdit()
        self.expected_power.setPlaceholderText("Optional reference W")
        self.method = QComboBox()
        self.method.addItem("Instantaneous (v·i mean)", "standard")
        self.method.addItem("Vrms × Irms × cos(φ)", "rms_cos_phi")
        self.remove_dc = QCheckBox("Remove DC")
        self.raw_v = QCheckBox("RAW voltage")
        self.raw_i = QCheckBox("RAW current")
        for row, (label, widget) in enumerate((
            ("Voltage channel", self.voltage), ("Current channel", self.current),
            ("Probe type", self.probe_type), ("Value (Ω or mV/A)", self.probe_value),
            ("Correction", self.correction), ("Formula", self.method),
        )):
            grid.addWidget(QLabel(label), row // 3, (row % 3) * 2)
            grid.addWidget(widget, row // 3, (row % 3) * 2 + 1)
        grid.addWidget(self.remove_dc, 2, 0)
        grid.addWidget(self.raw_v, 2, 2)
        grid.addWidget(self.raw_i, 2, 4)
        grid.addWidget(QLabel("Expected P (W)"), 3, 0)
        grid.addWidget(self.expected_power, 3, 1)
        calibration = QPushButton("Calibrate correction")
        calibration.clicked.connect(self.calibrate)
        grid.addWidget(calibration, 3, 2, 1, 2)
        layout.addWidget(group)
        controls = QHBoxLayout()
        self.measure_button = QPushButton("Measure")
        self.measure_button.setObjectName("primaryButton")
        self.measure_button.clicked.connect(self.measure)
        self.auto = QCheckBox("Auto-measure")
        self.period = QSpinBox()
        self.period.setRange(2, 60)
        self.period.setValue(5)
        self.period.setSuffix(" s")
        self.duration = QSpinBox()
        self.duration.setRange(0, 86400)
        self.duration.setSuffix(" s (0 = unlimited)")
        controls.addWidget(self.measure_button)
        controls.addWidget(self.auto)
        controls.addWidget(QLabel("Interval"))
        controls.addWidget(self.period)
        controls.addWidget(QLabel("Duration"))
        controls.addWidget(self.duration)
        controls.addStretch()
        layout.addLayout(controls)
        self.plot = PQPlot()
        self.results = readout()
        self.results.setMinimumHeight(180)
        layout.addWidget(self.plot, 2)
        layout.addWidget(self.results, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._auto_tick)
        self.timer.start(500)
        self.last_measurement = 0.0

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
            self.plot.push(average["P"], average["Q"])
            self.results.setPlainText(
                f"Instant P: {result['Real Power (P)']:.3f} W     Average P: {average['P']:.3f} W\n"
                f"S: {result['Apparent Power (S)']:.3f} VA     Q: {result['Reactive Power (Q)']:.3f} VAR\n"
                f"PF: {result['Power Factor']:.4f}     Phase: {result['Phase Angle (deg)']:.2f}°\n"
                f"Vrms: {result['Vrms']:.3f} V     Irms: {result['Irms']:.3f} A\n"
                f"Real energy: {energy[0]:.4f} Wh     Samples: {self.log.count}\n"
                f"CSV: {self.log.path}")

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
        button = QPushButton("Send")
        button.clicked.connect(self.send)
        row.addWidget(self.input)
        row.addWidget(button)
        layout.addLayout(row)
        self.output = readout()
        layout.addWidget(self.output)
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
