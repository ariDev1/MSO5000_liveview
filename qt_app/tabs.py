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
        copy = QPushButton("Copy system info")
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
        from version import VERSION, GIT_COMMIT, BUILD_DATE
        import psutil
        free = shutil.disk_usage(Path.cwd()).free / (1024 ** 3)
        info = (f"MSO5000 Liveview {VERSION}  ·  {GIT_COMMIT}  ·  {BUILD_DATE}\n"
                f"Host: {platform.system()} {platform.release()} ({platform.machine()})\n"
                f"Python: {sys.version.split()[0]}    CPU: {psutil.cpu_percent()}%    "
                f"RAM: {psutil.virtual_memory().percent}%    Disk free: {free:.1f} GiB\n"
                f"Logging: {app_state.is_logging_active}  Power: {app_state.is_power_analysis_active}\n\n"
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
        button = QPushButton("Refresh licenses")
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
            else:
                self.text.setPlainText("\n".join(
                    f"{item['code']:<12} {item['status']:<15} {item['desc']}" for item in options)
                    or "No license data received")

        self.submit(lambda: get_license_options(self.ip), done, image=True)


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
        copy_csv = QPushButton("Copy waveform CSV")
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
            p, q = self.points[-1]
            px = int(cx + p / limit_p * (cx - 28))
            qy = int(cy - q / limit_q * (cy - 26))
            painter.setPen(QPen(QColor("#eead68"), 2, Qt.PenStyle.DashLine))
            painter.drawLine(int(cx), int(cy), px, qy)
            painter.setPen(QPen(QColor("#65b9eb"), 1))
            painter.drawLine(int(cx), int(cy), px, int(cy))
            painter.setPen(QPen(QColor("#a7e88d"), 1))
            painter.drawLine(px, int(cy), px, qy)
            for index, (p, q) in enumerate(self.points):
                alpha = 60 + int(195 * (index + 1) / len(self.points))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(73, 208, 174, alpha))
                painter.drawEllipse(int(cx + p / limit_p * (cx - 28)) - 4,
                                    int(cy - q / limit_q * (cy - 26)) - 4, 8, 8)
        painter.setPen(QColor("#a6b8ca"))
        painter.drawText(22, self.height() - 6, "P (W) →")
        painter.drawText(8, 16, "Q (VAR) ↑")
        if self.points:
            p, q = self.points[-1]
            magnitude = math.hypot(p, q)
            painter.drawText(self.rect().adjusted(8, 8, -12, -8),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                             f"P {p:.3g} W   Q {q:.3g} VAR\n"
                             f"|P+jQ| {magnitude:.3g} VA   θ {math.degrees(math.atan2(q, p)):.1f}°")


class PowerTab(QWidget):
    def __init__(self, submit, backend, notify):
        super().__init__()
        self.submit, self.backend, self.notify = submit, backend, notify
        self.log = PowerLog()
        self.pending = False
        self.context = ({}, {})
        self.pq3d = None
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
        self.scale_info = QLabel("Effective current scale: 1 A/V")
        grid.addWidget(self.scale_info, 3, 4, 1, 2)
        for control in (self.probe_value, self.correction):
            control.textChanged.connect(self.update_scale)
        self.probe_type.currentIndexChanged.connect(self.update_scale)
        self.update_scale()
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
        view3d = QPushButton("3D PQ view")
        view3d.clicked.connect(self.show_3d)
        plot_last = QPushButton("Plot last log")
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

    def update_scale(self):
        try:
            scale = current_scale(self.probe_type.currentText(), self.probe_value.text(),
                                  self.correction.text())
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
            self.setup_status.setText(
                f"Frequency reference: {system.get('Frequency reference', 'N/A')}   "
                f"Current unit: {i_info.get('Unit', 'N/A')}   "
                f"Scope probe: {i_info.get('Probe', 'N/A')}×   "
                f"Deskew Δt(V−I): {skew:+.1f} ns" +
                ("   ⚠ Channel offset active" if
                 any(abs(numeric(info.get("Offset"))) > 0.01
                     for info in (v_info, i_info)) else ""))
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
            if self.pq3d is not None:
                _, view, canvas = self.pq3d
                view.push(time.time(), average["P"], average["Q"])
                view.draw()
                canvas.draw_idle()
            self.results.setPlainText(
                f"{'Metric':<24} {'Instant':>14}  {'Average':>14}\n"
                f"{'Real power (W)':<24} {result['Real Power (P)']:>14.4g}  {average['P']:>14.4g}\n"
                f"{'Apparent power (VA)':<24} {result['Apparent Power (S)']:>14.4g}  {average['S']:>14.4g}\n"
                f"{'Reactive power (VAR)':<24} {result['Reactive Power (Q)']:>14.4g}  {average['Q']:>14.4g}\n"
                f"{'Power factor':<24} {result['Power Factor']:>14.4f}  {average['PF']:>14.4f}\n"
                f"{'Vrms (V)':<24} {result['Vrms']:>14.4g}  {average['Vrms']:>14.4g}\n"
                f"{'Irms (A)':<24} {result['Irms']:>14.4g}  {average['Irms']:>14.4g}\n"
                f"Phase angle: {result['Phase Angle (deg)']:.2f}°   "
                f"Impedance: {result['Vrms'] / result['Irms'] if result['Irms'] else 0:.3g} Ω\n"
                f"Real energy: {energy[0]:.4f} Wh  Apparent: {energy[1]:.4f} VAh  "
                f"Reactive: {energy[2]:.4f} VARh\nSamples: {self.log.count}\n"
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
        selftest = QPushButton("Run self-test")
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
        if app_state.is_logging_active:
            self.notify("Self-test unavailable during long-time logging")
            return
        self.submit(self.backend.self_test,
                    lambda result: self.output.appendPlainText(f"Self-test:\n{result}\n"))
