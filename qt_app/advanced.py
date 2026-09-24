"""Qt presentation for the established harmonic, B-H and noise calculations."""

from pathlib import Path
import time

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import app.app_state as app_state
from qt_app.analysis import acquire, bh_curve, harmonics, noise, read_wave_csv, save_xy_csv
from qt_app.backend import channel_name
from qt_app.tabs import heading, readout


class Plot(QWidget):
    def __init__(self, three_d=False):
        super().__init__()
        self.figure = Figure(figsize=(6, 3), facecolor="#101722")
        self.axes = self.figure.add_subplot(111, projection="3d" if three_d else None)
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

    def style_axes(self, title, xlabel, ylabel):
        axes = self.axes
        axes.set_facecolor("#101722")
        axes.tick_params(colors="#d0dfec")
        for spine in axes.spines.values():
            spine.set_color("#758da8")
        axes.set_title(title, color="#e5edf6")
        axes.set_xlabel(xlabel, color="#e5edf6")
        axes.set_ylabel(ylabel, color="#e5edf6")
        axes.grid(True, color="#445469", alpha=0.5)
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def save_png(self, parent):
        path, _ = QFileDialog.getSaveFileName(parent, "Save plot", "oszi_csv/plot.png", "PNG (*.png)")
        if path:
            self.figure.savefig(path, dpi=150, facecolor=self.figure.get_facecolor())


def show_help(parent, filename):
    document = Path(__file__).resolve().parents[1] / "docs" / filename
    dialog = QDialog(parent)
    dialog.setWindowTitle(document.stem.replace("_", " "))
    dialog.resize(850, 640)
    layout = QVBoxLayout(dialog)
    text = readout()
    text.setPlainText(document.read_text(encoding="utf-8"))
    layout.addWidget(text)
    parent.help_dialog = dialog
    dialog.show()


class SurfaceHistory:
    """Detachable frequency / time / level view for successive spectra."""

    def __init__(self, parent):
        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle("Spectrum history · 3D")
        self.dialog.resize(900, 670)
        self.plot = Plot(three_d=True)
        layout = QVBoxLayout(self.dialog)
        layout.addWidget(self.plot)
        self.history = []

    def show(self):
        self.dialog.show()
        self.dialog.raise_()

    def push(self, x, y):
        x, y = np.asarray(x, float), np.asarray(y, float)
        if len(x) < 2 or len(x) != len(y):
            return
        axis = np.linspace(x.min(), x.max(), 250)
        self.history.append((axis, np.interp(axis, x, y)))
        self.history = self.history[-40:]
        ax = self.plot.axes
        ax.clear()
        for idx, (xx, yy) in enumerate(self.history):
            ax.plot(xx, np.full(len(xx), idx), yy, color="#54d5ae", alpha=0.7)
        ax.set_zlabel("Level", color="#e5edf6")
        self.plot.style_axes("Spectrum history", "Frequency (Hz)", "Acquisition")


class HarmonicsTab(QWidget):
    def __init__(self, submit, backend, notify):
        super().__init__()
        self.submit, self.backend, self.notify = submit, backend, notify
        self.pending = False
        self.last = None
        self.surface = None
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Harmonics / THD"))
        row = QHBoxLayout()
        self.channel = QComboBox()
        self.channel.addItems([f"CHAN{i}" for i in range(1, 5)] + [f"MATH{i}" for i in range(1, 5)])
        self.window = QComboBox()
        self.window.addItems(["hann", "rect", "flattop"])
        self.count = QSpinBox()
        self.count.setRange(2, 100)
        self.count.setValue(25)
        self.raw = QCheckBox("RAW")
        self.include_dc = QCheckBox("Include DC")
        self.auto = QCheckBox("Auto")
        button = QPushButton("Analyze")
        button.clicked.connect(self.run)
        csv_button = QPushButton("Export table")
        csv_button.clicked.connect(self.save_table)
        surface_button = QPushButton("3D history")
        surface_button.clicked.connect(self.show_surface)
        for widget in (QLabel("Channel"), self.channel, QLabel("Window"), self.window,
                       QLabel("Harmonics"), self.count, self.raw, self.include_dc,
                       self.auto, button, csv_button, surface_button):
            row.addWidget(widget)
        layout.addLayout(row)
        self.summary = QLabel("Select an enabled channel to analyze")
        layout.addWidget(self.summary)
        self.interharmonics = readout()
        self.interharmonics.setMaximumHeight(60)
        layout.addWidget(self.interharmonics)
        self.plot = Plot()
        layout.addWidget(self.plot, 3)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Order", "Frequency Hz", "RMS", "% of fundamental", "Phase °"])
        layout.addWidget(self.table, 2)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.run() if self.auto.isChecked() else None)
        self.timer.start(4000)

    def run(self):
        if self.pending or app_state.is_logging_active:
            return
        self.pending = True
        channel, raw, count = self.channel.currentText(), self.raw.isChecked(), self.count.value()
        window, include_dc = self.window.currentText(), self.include_dc.isChecked()

        def done(payload):
            self.pending = False
            if isinstance(payload, Exception):
                self.notify(f"Harmonics: {payload}")
                return
            result, freq, amplitude = payload
            self.last = result
            self.summary.setText(
                f"f₁ {result.f1_hz:.3f} Hz   Fundamental {result.v1_rms:.4g} RMS   "
                f"THD {result.thd * 100:.2f}%   THD+N {result.thdn * 100:.2f}%"
                if result.thdn is not None else f"f₁ {result.f1_hz:.3f} Hz   THD {result.thd * 100:.2f}%")
            if result.warnings:
                self.summary.setText(self.summary.text() + "   ·   " + "; ".join(result.warnings))
            self.table.setRowCount(len(result.rows))
            for idx, item in enumerate(result.rows):
                for col, val in enumerate((item.k, item.f_hz, item.mag_rms, item.percent, item.phase_deg)):
                    self.table.setItem(idx, col, QTableWidgetItem(f"{val:.5g}"))
            self.plot.axes.clear()
            self.plot.axes.plot(freq, amplitude, color="#54d5ae", linewidth=1)
            from scipy.signal import find_peaks
            df = freq[1] - freq[0] if len(freq) > 1 else 0
            peaks, _ = find_peaks(amplitude, height=max(result.v1_rms * 0.02, 1e-12))
            tol = max(0.015 * result.f1_hz, 2 * df)
            extra = [(freq[idx], amplitude[idx]) for idx in peaks
                     if freq[idx] > result.f1_hz and
                     all(abs(freq[idx] - k * result.f1_hz) > tol for k in range(1, count + 1))]
            extra = sorted(extra, key=lambda pair: pair[1], reverse=True)[:8]
            self.interharmonics.setPlainText(
                "Interharmonic lines: " + (", ".join(f"{f:.3g} Hz ({a:.3g} RMS)" for f, a in extra)
                                           if extra else "none above 2% of fundamental"))
            for line, _ in extra:
                self.plot.axes.axvline(line, color="#eead68", linestyle=":", alpha=0.7)
            self.plot.style_axes("Harmonic spectrum", "Frequency (Hz)", "Amplitude (RMS)")
            if self.surface is not None:
                self.surface.push(freq, amplitude)

        self.submit(lambda: harmonics(self.backend._connected(), channel, raw, count, window, include_dc), done)

    def save_table(self):
        if self.last is None:
            self.notify("Run harmonic analysis before exporting")
            return
        import csv
        import os
        from datetime import datetime
        os.makedirs("oszi_csv", exist_ok=True)
        path = f"oszi_csv/harmonics_{datetime.now():%Y%m%d_%H%M%S}.csv"
        with open(path, "w", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["Order", "Frequency (Hz)", "RMS", "% of fundamental", "Phase (deg)"])
            writer.writerows((item.k, item.f_hz, item.mag_rms, item.percent, item.phase_deg)
                             for item in self.last.rows)
        self.notify(f"Harmonic spectrum saved: {path}")

    def show_surface(self):
        if self.surface is None:
            self.surface = SurfaceHistory(self)
        self.surface.show()


class BHCurveTab(QWidget):
    def __init__(self, submit, backend, notify):
        super().__init__()
        self.submit, self.backend, self.notify = submit, backend, notify
        self.pending, self.last = False, None
        self.history = []
        layout = QVBoxLayout(self)
        layout.addWidget(heading("B–H curve / hysteresis"))
        grid = QGridLayout()
        self.voltage = QComboBox()
        self.current = QComboBox()
        for selector in (self.voltage, self.current):
            selector.addItems([f"CHAN{i}" for i in range(1, 5)] + [f"MATH{i}" for i in range(1, 5)])
        self.current.setCurrentIndex(1)
        self.turns = QSpinBox()
        self.turns.setRange(1, 100000)
        self.turns.setValue(20)
        self.area = QDoubleSpinBox()
        self.area.setRange(0.001, 1e9)
        self.area.setValue(25)
        self.length = QDoubleSpinBox()
        self.length.setRange(0.001, 1e9)
        self.length.setValue(50)
        self.probe_type = QComboBox()
        self.probe_type.addItems(["shunt", "clamp"])
        self.probe_value = QDoubleSpinBox()
        self.probe_value.setDecimals(6)
        self.probe_value.setRange(0.000001, 1e6)
        self.probe_value.setValue(0.1)
        self.deskew = QDoubleSpinBox()
        self.deskew.setRange(-1e6, 1e6)
        self.cycle_ref = QComboBox()
        self.cycle_ref.addItems(["I", "V"])
        self.avg_cycles = QSpinBox()
        self.avg_cycles.setRange(1, 50)
        self.raw = QCheckBox("RAW")
        self.dc = QCheckBox("Remove DC")
        self.dc.setChecked(True)
        self.detrend = QCheckBox("Detrend")
        self.cycle = QCheckBox("Average cycles")
        self.cycle.setChecked(True)
        self.auto = QCheckBox("Auto")
        self.overlay = QCheckBox("Trail")
        controls = (("Voltage", self.voltage), ("Current", self.current), ("Turns", self.turns),
                    ("Ae (mm²)", self.area), ("le (mm)", self.length), ("Probe", self.probe_type),
                    ("Probe value", self.probe_value), ("Deskew (µs)", self.deskew),
                    ("Cycle reference", self.cycle_ref), ("Cycle count", self.avg_cycles))
        for idx, (name, widget) in enumerate(controls):
            grid.addWidget(QLabel(name), idx // 5, idx % 5 * 2)
            grid.addWidget(widget, idx // 5, idx % 5 * 2 + 1)
        layout.addLayout(grid)
        row = QHBoxLayout()
        button = QPushButton("Acquire B–H")
        button.clicked.connect(self.run)
        png = QPushButton("Save PNG")
        png.clicked.connect(lambda: self.plot.save_png(self))
        csv = QPushButton("Save CSV")
        csv.clicked.connect(self.save_csv)
        help_button = QPushButton("Guide")
        help_button.clicked.connect(lambda: show_help(self, "bh-curve_help.md"))
        clear = QPushButton("Reset trail")
        clear.clicked.connect(self.clear_trail)
        for widget in (self.raw, self.dc, self.detrend, self.cycle, self.auto,
                       self.overlay, button, clear, png, csv, help_button):
            row.addWidget(widget)
        layout.addLayout(row)
        self.plot = Plot()
        layout.addWidget(self.plot, 3)
        self.details = readout()
        self.details.setMaximumHeight(100)
        layout.addWidget(self.details)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.run() if self.auto.isChecked() else None)
        self.timer.start(4000)

    def run(self):
        if self.pending or app_state.is_logging_active:
            return
        self.pending = True
        values = (self.voltage.currentText(), self.current.currentText(),
                  self.turns.value(), self.area.value(), self.length.value(),
                  self.probe_type.currentText(), self.probe_value.value(),
                  self.raw.isChecked(), self.dc.isChecked(), self.cycle.isChecked(),
                  self.cycle_ref.currentText(), self.avg_cycles.value(), self.deskew.value(),
                  self.detrend.isChecked())

        def done(payload):
            self.pending = False
            if isinstance(payload, Exception):
                self.notify(f"B–H: {payload}")
                return
            h, b, dt = payload
            self.last = payload
            if not self.overlay.isChecked():
                self.history.clear()
            self.history.append((h[::max(1, len(h) // 5000)], b[::max(1, len(b) // 5000)]))
            self.history = self.history[-30:]
            self.plot.axes.clear()
            for idx, (old_h, old_b) in enumerate(self.history):
                self.plot.axes.plot(old_h, old_b, color="#54d5ae", linewidth=1.5,
                                    alpha=0.25 + 0.75 * (idx + 1) / len(self.history))
            self.plot.style_axes("Hysteresis loop", "H (A/m)", "B (T)")
            def crossing(x, y):
                indices = np.flatnonzero(np.diff(np.signbit(y)))
                if not indices.size:
                    return float("nan")
                idx = indices[0]
                return float(x[idx] - y[idx] * (x[idx + 1] - x[idx]) / (y[idx + 1] - y[idx]))

            f = np.fft.rfftfreq(len(h), dt)
            spectrum = np.abs(np.fft.rfft(h - np.mean(h)))
            k1 = 1 + int(np.argmax(spectrum[1:])) if len(spectrum) > 1 else 0
            f0 = f[k1] if k1 else 0
            hc, br = crossing(h, b), crossing(b, h)
            with np.errstate(divide="ignore", invalid="ignore"):
                permeability = np.abs(b[np.abs(h) > 1e-4] / h[np.abs(h) > 1e-4]) / (4 * np.pi * 1e-7)
            mu_max = float(np.max(permeability)) if len(permeability) else float("nan")
            self.details.setPlainText(f"Points: {len(h)}  dt: {dt:.3g} s\n"
                                      f"fs: {1/dt:.4g} Hz  f₀: {f0:.4g} Hz\n"
                                      f"Peak |H|: {max(abs(h)):.4g} A/m   Peak |B|: {max(abs(b)):.4g} T\n"
                                      f"Hc: {hc:.4g} A/m  Br: {br:.4g} T  Max μr: {mu_max:.4g}\n"
                                      f"Loop area: {abs(np.trapezoid(b, h)):.4g} J/m³")

        self.submit(lambda: bh_curve(self.backend._connected(), *values), done)

    def save_csv(self):
        if self.last is not None:
            h, b, _ = self.last
            path = save_xy_csv("oszi_csv/bh-curve", "bhcurve", h, b, "H (A/m)", "B (T)")
            self.notify(f"B–H exported: {path}")

    def clear_trail(self):
        self.history.clear()
        self.plot.axes.clear()
        self.plot.canvas.draw_idle()


class NoiseTab(QWidget):
    METHODS = ("PSD+CFAR", "Spectrogram", "MSC", "Multitaper", "Spectral Kurtosis",
               "Cepstrum", "Matched Filter", "AR Spectrum", "Cyclostationary", "Bicoherence")

    def __init__(self, submit, backend, notify):
        super().__init__()
        self.submit, self.backend, self.notify = submit, backend, notify
        self.pending, self.last = False, None
        self.surface = None
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Noise Inspector"))
        row = QHBoxLayout()
        self.channel = QComboBox()
        self.other = QComboBox()
        for combo in (self.channel, self.other):
            combo.addItems([f"CHAN{i}" for i in range(1, 5)] + [f"MATH{i}" for i in range(1, 5)])
        self.other.setCurrentIndex(1)
        self.method = QComboBox()
        self.method.addItems(self.METHODS)
        self.preset = QComboBox()
        self.preset.addItems(["Default", "Fast scan", "High resolution"])
        self.preset.currentIndexChanged.connect(self.apply_preset)
        self.nfft = QSpinBox()
        self.nfft.setRange(128, 65536)
        self.nfft.setValue(4096)
        self.hop = QSpinBox()
        self.hop.setRange(64, 65536)
        self.hop.setValue(2048)
        self.overlap = QDoubleSpinBox()
        self.overlap.setRange(0, 0.95)
        self.overlap.setSingleStep(0.05)
        self.overlap.setValue(0.5)
        self.pfa = QDoubleSpinBox()
        self.pfa.setDecimals(5)
        self.pfa.setRange(0.00001, 0.2)
        self.pfa.setValue(0.001)
        self.topk = QSpinBox()
        self.topk.setRange(1, 100)
        self.topk.setValue(8)
        self.csv_path = QLineEdit()
        self.csv_path.setPlaceholderText("Optional waveform CSV / matched template")
        browse = QPushButton("Browse")
        browse.clicked.connect(self.browse)
        self.auto = QCheckBox("Auto")
        run = QPushButton("Analyze noise")
        run.clicked.connect(self.run)
        for widget in (QLabel("Channel"), self.channel, QLabel("Other"), self.other,
                       self.method, self.preset, QLabel("NFFT"), self.nfft, self.csv_path,
                       browse, self.auto, run):
            row.addWidget(widget)
        layout.addLayout(row)
        params = QHBoxLayout()
        for widget in (QLabel("Hop"), self.hop, QLabel("Overlap"), self.overlap,
                       QLabel("Pfa"), self.pfa, QLabel("Top K"), self.topk):
            params.addWidget(widget)
        params.addStretch()
        layout.addLayout(params)
        self.plot = Plot()
        layout.addWidget(self.plot, 3)
        self.detections = readout()
        self.detections.setMaximumHeight(65)
        layout.addWidget(self.detections)
        self.table = QTableWidget()
        layout.addWidget(self.table, 2)
        self.auto_log = QCheckBox("Log detections automatically")
        self.auto_log.setChecked(True)
        layout.addWidget(self.auto_log)
        exports = QHBoxLayout()
        save_png = QPushButton("Save PNG")
        save_png.clicked.connect(lambda: self.plot.save_png(self))
        save_csv = QPushButton("Save detections CSV")
        save_csv.clicked.connect(self.save_csv)
        surface = QPushButton("3D history")
        surface.clicked.connect(self.show_surface)
        help_button = QPushButton("Guide")
        help_button.clicked.connect(lambda: show_help(self, "Noise_Inspector_Operator_Guide.md"))
        exports.addWidget(save_png)
        exports.addWidget(save_csv)
        exports.addWidget(surface)
        exports.addWidget(help_button)
        exports.addStretch()
        layout.addLayout(exports)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.run() if self.auto.isChecked() else None)
        self.timer.start(4000)

    def apply_preset(self):
        values = {"Default": (4096, 2048, 0.5), "Fast scan": (2048, 1024, 0.25),
                  "High resolution": (8192, 2048, 0.75)}
        nfft, hop, overlap = values[self.preset.currentText()]
        self.nfft.setValue(nfft)
        self.hop.setValue(hop)
        self.overlap.setValue(overlap)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Waveform CSV", "oszi_csv", "CSV (*.csv)")
        if path:
            self.csv_path.setText(path)

    def run(self):
        if self.pending or app_state.is_logging_active:
            return
        self.pending = True
        channel, second = self.channel.currentText(), self.other.currentText()
        method, path, nfft = self.method.currentText(), self.csv_path.text().strip(), self.nfft.value()
        params = {"nfft": nfft, "seglen": nfft, "hop": self.hop.value(),
                  "overlap": self.overlap.value(), "pfa": self.pfa.value(),
                  "topk": self.topk.value()}

        def operation():
            if path and method != "Matched Filter":
                y, fs = read_wave_csv(path)
            else:
                _, y, fs = acquire(self.backend._connected(), channel)
            other = None
            if method == "MSC":
                t2, other, fs2 = acquire(self.backend._connected(), second)
                if abs(fs2 - fs) / fs > 1e-6:
                    raise ValueError("Channels have different sample rates")
                count = min(len(other), len(y))
                y, other = y[:count], other[:count]
            return noise(y, fs, method, params, other, path)

        def done(result):
            self.pending = False
            if isinstance(result, Exception):
                self.notify(f"Noise Inspector: {result}")
                return
            self.last = result
            ax = self.plot.axes
            ax.clear()
            if result.get("image") is not None:
                ax.imshow(result["image"], origin="lower", aspect="auto",
                          extent=result.get("extent") or None, cmap="magma")
            elif result.get("plot_x") is not None:
                ax.plot(result["plot_x"], result["plot_y"], color="#54d5ae")
                if self.surface is not None:
                    self.surface.push(result["plot_x"], result["plot_y"])
            self.plot.style_axes(method, result.get("xlabel", "Frequency (Hz)"),
                                 result.get("ylabel", "Level"))
            rows = result.get("detections", [])
            self.detections.setPlainText(
                f"{method}   Resolution: {result.get('df_Hz', 'N/A')} Hz   "
                f"Detections: {len(rows)}")
            columns = list(dict.fromkeys(key for row in rows for key in row))
            self.table.setColumnCount(len(columns))
            self.table.setHorizontalHeaderLabels(columns)
            self.table.setRowCount(len(rows))
            for row_idx, row in enumerate(rows):
                for col_idx, key in enumerate(columns):
                    self.table.setItem(row_idx, col_idx, QTableWidgetItem(str(row.get(key, ""))))
            if self.auto.isChecked() and self.auto_log.isChecked() and result.get("detections"):
                self.save_csv()

        self.submit(operation, done)

    def show_surface(self):
        if self.surface is None:
            self.surface = SurfaceHistory(self)
        self.surface.show()

    def save_csv(self):
        if not self.last:
            return
        import csv
        import os
        from datetime import datetime
        rows = self.last.get("detections", [])
        if not rows:
            self.notify("No detections to export")
            return
        os.makedirs("oszi_csv", exist_ok=True)
        path = f"oszi_csv/noise_{datetime.now():%Y%m%d_%H%M%S}.csv"
        columns = list(dict.fromkeys(key for row in rows for key in row))
        with open(path, "w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        self.notify(f"Noise detections saved: {path}")
