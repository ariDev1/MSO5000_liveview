"""Qt presentation for the established harmonic, B-H and noise calculations."""

import math
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
    # GAP (Tk parity, recorded): the Tk tab shades a 15-spectra persistence
    # heat-map trail and streams into the shared gui/surface3d window. The Qt
    # viewer keeps its own "3D history" dialog (40 spectra) instead, so no
    # Tk widget code or shared acquisition path is touched.
    # GAP (Tk parity, recorded): the Tk "THD+N" checkbox is never read — the
    # shared calculation always runs with compute_thdn=True. Qt therefore
    # omits the toggle and shows THD+N whenever the result carries it.
    # GAP (Tk parity, recorded): the Tk status line reports the fetch mode,
    # point count and capture span from its own exclusive RAW/NORM reader.
    # Qt reuses the shared _fetch_wave path, so its summary shows result
    # metrics only (f₁, V₁, THD, THD+N, cycles, warnings).
    # Known lab lines, duplicated here (not imported) because importing the
    # Tk tab module would pull in tkinter.
    KNOWN_LINES_HZ = [50.0, 100.0, 150.0, 200.0, 16.67]

    def __init__(self, submit, backend, notify):
        super().__init__()
        self.submit, self.backend, self.notify = submit, backend, notify
        self.pending = False
        self.last = None
        self.surface = None
        self._selected_k = None
        self._selected_freq = None
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Harmonics / THD"))
        row = QHBoxLayout()
        self.channel = QComboBox()
        self.channel.addItems([f"CHAN{i}" for i in range(1, 5)] + [f"MATH{i}" for i in range(1, 5)])
        self.window = QComboBox()
        self.window.addItem("Hann", "hann")
        self.window.addItem("Rect", "rect")
        self.window.addItem("Flat-top", "flattop")
        self.count = QSpinBox()
        self.count.setRange(5, 80)
        self.count.setValue(25)
        self.raw = QCheckBox("RAW if possible")
        self.raw.setChecked(True)
        self.include_dc = QCheckBox("Include DC")
        self.auto = QCheckBox("Auto")
        button = QPushButton("Measure")
        button.clicked.connect(self.run)
        csv_button = QPushButton("Export table")
        csv_button.clicked.connect(self.save_table)
        png_button = QPushButton("Save PNG")
        png_button.clicked.connect(lambda: self.plot.save_png(self))
        md_button = QPushButton("Copy Markdown")
        md_button.clicked.connect(self.copy_markdown)
        surface_button = QPushButton("3D history")
        surface_button.clicked.connect(self.show_surface)
        for widget in (QLabel("Channel"), self.channel, QLabel("Window"), self.window,
                       QLabel("Harmonics"), self.count, self.raw, self.include_dc,
                       self.auto, button, csv_button, png_button, md_button,
                       surface_button):
            row.addWidget(widget)
        layout.addLayout(row)
        self.summary = QLabel("Select an enabled channel to analyze")
        layout.addWidget(self.summary)
        self.interharmonics = readout()
        self.interharmonics.setMaximumHeight(60)
        layout.addWidget(self.interharmonics)
        self.plot = Plot()
        layout.addWidget(self.plot, 3)
        self.columns = ("k", "f_hz", "f_pred", "df_hz", "mag_rms", "dBr1",
                        "percent", "cumTHD_pct", "phase_deg")
        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels(list(self.columns))
        self.table.cellClicked.connect(self._on_table_select)
        layout.addWidget(self.table, 2)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.run() if self.auto.isChecked() else None)
        # GAP (Tk parity, recorded): the Tk tab re-arms ~2 s after each
        # acquisition; Qt polls on a fixed 4 s cadence (gentler on the scope).
        self.timer.start(4000)

    def run(self):
        if self.pending or app_state.is_logging_active:
            return
        self.pending = True
        channel, raw, count = self.channel.currentText(), self.raw.isChecked(), self.count.value()
        window, include_dc = self.window.currentData(), self.include_dc.isChecked()

        def done(payload):
            self.pending = False
            if isinstance(payload, Exception):
                self.notify(f"Harmonics: {payload}")
                return
            result, freq, amplitude = payload
            self.last = result
            base = (f"f₁ {result.f1_hz:.3f} Hz   Fundamental {result.v1_rms:.4g} RMS   "
                    f"THD {result.thd * 100:.2f}%")
            if result.thdn is not None:
                base += f"   THD+N {result.thdn * 100:.2f}%"
            base += f"   cycles={result.coherence_cycles:.2f}"
            if result.warnings:
                base += "   ·   " + "; ".join(result.warnings)
            self.summary.setText(base)
            self._render_table(result)
            self._render_plot(result, freq, amplitude, count)
            if self.surface is not None:
                self.surface.push(freq, amplitude)

        self.submit(lambda: harmonics(self.backend._connected(), channel, raw, count, window, include_dc), done)

    def _on_table_select(self, row, _col):
        """Mirror the Tk tab: remember the selected harmonic for the plot marker."""
        try:
            self._selected_k = int(float(self.table.item(row, 0).text()))
            self._selected_freq = float(self.table.item(row, 1).text())
        except (TypeError, ValueError, AttributeError):
            self._selected_k = None
            self._selected_freq = None

    @staticmethod
    def _cell(value):
        return "—" if value is None or (isinstance(value, float)
                                        and not math.isfinite(value)) else f"{value}"

    def _derived_rows(self, result):
        """Harmonic table rows with the Tk tab's derived columns (display-only)."""
        f1, v1 = float(result.f1_hz), float(result.v1_rms)
        rows, running = [], 0.0
        for item in result.rows:
            k = int(item.k)
            f_meas, v_k = float(item.f_hz), float(item.mag_rms)
            f_pred = k * f1 if f1 > 0 else float("nan")
            df_hz = f_meas - f_pred if f1 > 0 else float("nan")
            if v1 > 0 and v_k > 0:
                dbr1 = 20.0 * math.log10(v_k / v1)
            else:
                dbr1 = float("nan")
            if k >= 2:
                running += v_k * v_k
            cum = (100.0 * math.sqrt(running) / v1) if (v1 > 0 and running > 0) \
                else (0.0 if k < 2 else float("nan"))
            rows.append((k, f"{f_meas:.3f}",
                         f"{f_pred:.3f}" if math.isfinite(f_pred) else "—",
                         f"{df_hz:.3f}" if math.isfinite(df_hz) else "—",
                         f"{v_k:.6g}", f"{dbr1:.1f}" if math.isfinite(dbr1) else "—",
                         f"{item.percent:.3f}" if math.isfinite(item.percent) else "—",
                         f"{cum:.3f}" if math.isfinite(cum) else "—",
                         f"{item.phase_deg:.2f}" if math.isfinite(item.phase_deg) else "—"))
        return rows

    def _render_table(self, result):
        rows = self._derived_rows(result)
        self.table.setRowCount(len(rows))
        for idx, values in enumerate(rows):
            for col, val in enumerate(values):
                self.table.setItem(idx, col, QTableWidgetItem(str(val)))

    def _render_plot(self, result, freq, amplitude, count):
        import matplotlib.lines as mlines
        import matplotlib.patches as mpatches
        from scipy.signal import find_peaks
        self.plot.axes.clear()
        self.plot.axes.plot(freq, amplitude, color="#d0ff00", linewidth=1.4, label="Spectrum")
        for item in result.rows:
            self.plot.axes.axvline(item.f_hz, linestyle="--", alpha=0.25)
        if result.f1_hz > 0:
            self.plot.axes.axvline(result.f1_hz, color="#bbbbbb", alpha=0.6)
        df = freq[1] - freq[0] if len(freq) > 1 else 0
        tol = max(0.015 * result.f1_hz, 2 * df)
        if result.f1_hz > 0 and len(freq) > 1:
            f_min, f_max = float(freq[0]), float(freq[-1])
            for k in range(1, count + 1):
                center = k * result.f1_hz
                if center + tol < f_min or center - tol > f_max:
                    continue
                self.plot.axes.axvspan(max(center - tol, f_min), min(center + tol, f_max),
                                       alpha=0.06, label="Harmonic window (±tol)" if k == 1 else None)
        peaks, _ = find_peaks(amplitude, height=max(result.v1_rms * 0.02, 1e-12))
        extra = [(freq[idx], amplitude[idx]) for idx in peaks
                 if freq[idx] > result.f1_hz and
                 all(abs(freq[idx] - k * result.f1_hz) > tol for k in range(1, count + 1))]
        extra = sorted(extra, key=lambda pair: pair[1], reverse=True)[:8]
        fund = max(float(amplitude[int(np.clip(round(result.f1_hz / df), 0, len(freq) - 1))])
                   if df > 0 else 1.0, 1e-20) if len(freq) else 1.0
        lines = []
        for line, level in extra:
            self.plot.axes.axvline(line, color="#eead68", linestyle=":", alpha=0.7)
            self.plot.axes.plot([line], [level], marker="v", markersize=5,
                                color="#eead68", alpha=0.9)
            lines.append(f"{line / 1000:.1f} kHz ({20.0 * math.log10(max(level, 1e-20) / fund):.1f} dBr₁)"
                         if line >= 1000 else
                         f"{line:.1f} Hz ({20.0 * math.log10(max(level, 1e-20) / fund):.1f} dBr₁)")
        known = []
        if df > 0:
            for target in self.KNOWN_LINES_HZ:
                idx = int(np.argmin(np.abs(freq - target)))
                if abs(freq[idx] - target) <= 2 * df:
                    level = 20.0 * math.log10(max(float(amplitude[idx]), 1e-20) / fund)
                    if level > -80.0:
                        known.append((float(target), level))
                        self.plot.axes.plot([freq[idx]], [max(float(amplitude[idx]),
                                                                float(amplitude.min()) if len(amplitude) else 0.0)],
                                            marker="s", markersize=5, color="#eead68", alpha=0.9)
        self.interharmonics.setPlainText(
            "Non-harmonic lines (dBr₁): " + (", ".join(lines) if lines else "(none ≥ threshold)") +
            ("   ·   Known/house lines: " +
             ", ".join(f"{fk:.2f} Hz ({db:.1f} dBr₁)" for fk, db in known) if known else ""))
        if self._selected_freq is not None:
            self.plot.axes.axvline(self._selected_freq, color="#00eaff", linewidth=1.5, alpha=0.9)
            self.plot.axes.text(self._selected_freq, max(amplitude) if len(amplitude) else 0,
                                f"k={self._selected_k}", color="#00eaff", fontsize=9,
                                ha="center", va="bottom")
        self.plot.axes.legend(
            handles=[mlines.Line2D([], [], linewidth=1.4, label="Spectrum", color="#d0ff00"),
                     mlines.Line2D([], [], linestyle=":", linewidth=1.2,
                                   label="Interharmonic", color="#eead68"),
                     mpatches.Patch(alpha=0.10, label="Harmonic window (±tol)")],
            loc="upper right", fontsize="small", framealpha=0.45,
            facecolor="#222222", edgecolor="#444444", labelcolor="#DDDDDD")
        self.plot.style_axes("Harmonic spectrum", "Frequency (Hz)", "Amplitude (RMS)")

    def save_table(self):
        # GAP (Tk parity, recorded): the Tk tab writes oszi_csv/harmonics/
        # with channel/timestamp filenames, metadata comment rows and a
        # spectrum PNG next to it. The Qt export path and columns below are
        # the established Qt output and stay frozen (CSV schema constraint).
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

    def copy_markdown(self):
        """Copy a Markdown summary of the last analysis (mirrors the Tk tab)."""
        from PySide6.QtWidgets import QApplication
        if self.last is None:
            self.notify("Run harmonic analysis before copying")
            return
        result = self.last
        lines = ["**Harmonics summary**  ",
                 f"Channel: `{self.channel.currentText()}` | "
                 f"Window: `{self.window.currentText()}` | "
                 f"f₁ = {result.f1_hz:.6g} Hz | V₁,rms = {result.v1_rms:.6g} | "
                 f"THD = {result.thd * 100:.3f}%", "",
                 "| " + " | ".join(self.columns) + " |",
                 "|" + "|".join(["---:"] * len(self.columns)) + "|"]
        for row in range(self.table.rowCount()):
            lines.append("| " + " | ".join(
                self.table.item(row, col).text() if self.table.item(row, col) else "—"
                for col in range(len(self.columns))) + " |")
        if self.interharmonics.toPlainText().strip():
            lines += ["", self.interharmonics.toPlainText().strip()]
        QApplication.clipboard().setText("\n".join(lines))
        self.notify("Harmonics Markdown summary copied to clipboard")

    def show_surface(self):
        if self.surface is None:
            self.surface = SurfaceHistory(self)
        self.surface.show()


class BHCurveTab(QWidget):
    # GAP (Tk parity, recorded): the Tk tab drives its own NORM/RAW sampler
    # (point count, Stop/Fetch) through an exclusive SCPI reader. Qt reuses
    # the shared fetch path (RAW checkbox only) — point counts stay under
    # scope configuration, no shared code touched.
    # GAP (Tk parity, recorded): the Tk tab appends every run to a session
    # bhcurve_log CSV and offers a detailed V/I/H/B export plus an auto-path
    # PNG with an IDN footer. Qt keeps its established per-save H/B CSV and
    # dialog-based PNG instead (CSV schema frozen).
    # GAP (Tk parity, recorded): the Tk data panel reports THD(I)/THD(V)
    # from the raw acquisition waves, which the shared-fetch adapter does
    # not surface. Qt shows f₀, fs/f₀ warnings and H/B samples from the
    # computed loop instead.
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
        self.current.setCurrentIndex(2)
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
        self.deskew.setToolTip("Deskew Δt (V−I) in µs, same convention as Power Analysis.")
        self.cycle_ref = QComboBox()
        self.cycle_ref.addItems(["I", "V", "Auto"])
        self.avg_cycles = QSpinBox()
        self.avg_cycles.setRange(1, 10)
        self.raw = QCheckBox("RAW")
        self.raw.setToolTip("Full-memory fetch via the shared scope path.")
        self.dc = QCheckBox("Remove DC")
        self.dc.setChecked(True)
        self.detrend = QCheckBox("Detrend")
        self.cycle = QCheckBox("Average cycles")
        self.equal_aspect = QCheckBox("Equal aspect")
        self.tight = QCheckBox("Tight fit")
        self.tight.setChecked(True)
        self.data = QCheckBox("Data")
        self.data.setChecked(True)
        self.data.toggled.connect(self._toggle_data)
        self.auto = QCheckBox("Auto")
        self.interval = QSpinBox()
        self.interval.setRange(1, 60)
        self.interval.setValue(5)
        self.interval.setSuffix(" s")
        self.interval.valueChanged.connect(self._retime)
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
        button = QPushButton("▶ Acquire & Plot")
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
                       QLabel("Interval"), self.interval, self.equal_aspect, self.tight,
                       self.data, self.overlay, button, clear, png, csv, help_button):
            row.addWidget(widget)
        layout.addLayout(row)
        self.plot = Plot()
        layout.addWidget(self.plot, 3)
        self.details = readout()
        self.details.setMaximumHeight(100)
        layout.addWidget(self.details)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.run() if self.auto.isChecked() else None)
        self._retime()
        self._toggle_data(True)

    def _retime(self):
        self.timer.setInterval(max(1, self.interval.value()) * 1000)

    def _toggle_data(self, visible):
        self.details.setVisible(bool(visible))

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
            try:
                if self.tight.isChecked():
                    hmin, hmax = float(np.min(h)), float(np.max(h))
                    bmin, bmax = float(np.min(b)), float(np.max(b))
                    if hmax == hmin:
                        hmin -= 1.0
                        hmax += 1.0
                    if bmax == bmin:
                        bmin -= 1e-3
                        bmax += 1e-3
                    self.plot.axes.set_xlim(hmin - 0.08 * (hmax - hmin),
                                            hmax + 0.08 * (hmax - hmin))
                    self.plot.axes.set_ylim(bmin - 0.08 * (bmax - bmin),
                                            bmax + 0.08 * (bmax - bmin))
                else:
                    hx, bx = float(np.max(np.abs(h))), float(np.max(np.abs(b)))
                    if hx > 0 and bx > 0:
                        self.plot.axes.set_xlim(-1.1 * hx, 1.1 * hx)
                        self.plot.axes.set_ylim(-1.1 * bx, 1.1 * bx)
                self.plot.axes.set_aspect("equal" if self.equal_aspect.isChecked() else "auto",
                                           adjustable="datalim")
            except (TypeError, ValueError):
                pass
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
            fs, ratio = 1 / dt, (1 / dt) / f0 if f0 > 0 else 0
            peak_h, peak_b = float(max(abs(h))), float(max(abs(b)))
            warnings = []
            if peak_h < 1.0 or peak_b < 1e-4:
                warnings.append("⚠️ Low signal — results may be noisy")
            if f0 > 0 and ratio < 20:
                warnings.append(f"⚠️ fs/f₀={ratio:.1f} < 20 — increase sample rate")
            samples = (f"H (A/m): {np.array2string(h[:8], precision=3, separator=', ')}"
                       f"{' ... ' + np.array2string(h[-8:], precision=3, separator=', ') if len(h) > 16 else ''}\n"
                       f"B (T):   {np.array2string(b[:8], precision=5, separator=', ')}"
                       f"{' ... ' + np.array2string(b[-8:], precision=5, separator=', ') if len(b) > 16 else ''}")
            self.details.setPlainText(
                f"Points: {len(h)}  dt: {dt:.3g} s\n"
                f"fs: {fs:.4g} Hz  f₀: {f0:.4g} Hz  fs/f₀: {ratio:.1f}\n"
                f"Peak |H|: {peak_h:.4g} A/m   Peak |B|: {peak_b:.4g} T\n"
                f"Hc: {hc:.4g} A/m  Br: {br:.4g} T  Max μr: {mu_max:.4g}\n"
                f"Loop area: {abs(np.trapezoid(b, h)):.4g} J/m³"
                + ("".join(f"\n{warning}" for warning in warnings)) + f"\n{samples}")

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

    HINTS = {
        "PSD+CFAR": "Adaptive detector that flags narrowband lines buried in noise.",
        "Spectrogram": "Time–frequency view; reveals transients, chirps, and drifting tones.",
        "MSC": "Coherence vs. frequency between two channels; needs a channel pair.",
        "Multitaper": "Lower-variance PSD using DPSS tapers; stabilizes weak peaks in noise.",
        "Spectral Kurtosis": "Measures non-Gaussian bursts; ideal for impulsive/transient detection.",
        "Cepstrum": "Finds periodic spacing of harmonics; useful for modulated/mechanical tones.",
        "Matched Filter": "Maximizes SNR for a known template; use when the waveform is known.",
        "AR Spectrum": "Model-based spectrum with sharp peaks; use when resolution matters most.",
        "Cyclostationary": "Exposes periodic modulations (α-components); good for hidden carriers/comms.",
        "Bicoherence": "Detects quadratic phase coupling; reveals nonlinear mixing among tones.",
    }

    # Per-method operator presets mirroring the Tk tab (keys applied only to
    # fields this viewer exposes; shared-code defaults fill the rest).
    PRESETS = {
        "PSD+CFAR": {"Default": {"nfft": 4096, "seglen": 4096, "overlap": 0.5,
                                 "smooth_bins": 31},
                     "Fast scan": {"nfft": 2048, "seglen": 2048, "overlap": 0.25,
                                   "smooth_bins": 31},
                     "High resolution": {"nfft": 16384, "seglen": 16384, "overlap": 0.75,
                                         "smooth_bins": 41}},
        "Spectrogram": {"Default": {"nfft": 4096, "hop": 2048, "smooth_bins": 31, "topk": 8},
                        "Fast scan": {"nfft": 2048, "hop": 1024, "smooth_bins": 21, "topk": 6},
                        "High resolution": {"nfft": 8192, "hop": 2048, "smooth_bins": 41,
                                            "topk": 10}},
        "MSC": {"Default": {"nfft": 4096, "seglen": 512, "overlap": 0.5, "msc_thr": 0.5},
                "Deep": {"nfft": 8192, "seglen": 1024, "overlap": 0.75, "msc_thr": 0.6},
                "Fast scan": {"nfft": 2048, "seglen": 256, "overlap": 0.25, "msc_thr": 0.5}},
        "Multitaper": {"Default": {"k_tapers": 6, "nfft": 4096, "seglen": 4096,
                                   "overlap": 0.5, "smooth_bins": 31},
                       "High resolution": {"k_tapers": 8, "nfft": 8192, "seglen": 8192,
                                           "overlap": 0.75, "smooth_bins": 41},
                       "Fast scan": {"k_tapers": 4, "nfft": 2048, "seglen": 2048,
                                     "overlap": 0.25, "smooth_bins": 31}},
        "Spectral Kurtosis": {"Default": {"nfft": 4096, "hop": 2048, "sk_thr": 2.5},
                              "Transient hunt": {"nfft": 4096, "hop": 1024, "sk_thr": 2.0},
                              "Strict": {"nfft": 4096, "hop": 2048, "sk_thr": 3.5}},
        "Cepstrum": {"Default": {"nfft": 4096, "qmin_ms": 0.02, "qmax_ms": 5.0, "cep_topk": 3},
                     "Low rate": {"nfft": 4096, "qmin_ms": 1.0, "qmax_ms": 50.0, "cep_topk": 3},
                     "Wide search": {"nfft": 8192, "qmin_ms": 0.02, "qmax_ms": 50.0,
                                     "cep_topk": 5}},
        "AR Spectrum": {"Default": {"ar_order": 32, "nfft": 4096},
                        "Sharp peaks": {"ar_order": 64, "nfft": 8192},
                        "Fast scan": {"ar_order": 24, "nfft": 2048}},
        "Matched Filter": {"Default": {}},
        "Cyclostationary": {"Default": {"nfft": 4096, "hop": 2048},
                            "Deep": {"nfft": 8192, "hop": 2048},
                            "Fast": {"nfft": 2048, "hop": 1024}},
        "Bicoherence": {"Default": {"nfft": 512, "overlap": 0.75},
                        "Fast": {"nfft": 256, "overlap": 0.5}},
    }
    # GAP (Tk parity, recorded): the Tk tab also offers capture-Length
    # trimming (0.5–5 s), a daily auto-log CSV, Bicoherence accumulation
    # across runs with a vmax control, and cyclostationary α_max/dB-floor
    # controls. Qt analyzes the full shared-fetch capture, reuses its
    # established per-run detections CSV, keeps a one-shot Bicoherence view,
    # and leaves cyclo extras at shared defaults — no shared code is touched
    # to close these. 1-D spectra stream to Qt's own 3D-history dialog rather
    # than the shared surface3d window the Tk tab feeds in Auto mode.
    # GAP (Tk parity, recorded): MSC in the Tk tab fetches both channels
    # under one exclusive SCPI window; Qt acquires via two shared fetches
    # and only checks that the sample rates agree.

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
        self.method.currentIndexChanged.connect(self.refresh_presets)
        self.preset = QComboBox()
        self.preset.currentIndexChanged.connect(self.apply_preset)
        self.nfft = QSpinBox()
        self.nfft.setRange(128, 65536)
        self.nfft.setValue(4096)
        self.seglen = QSpinBox()
        self.seglen.setRange(128, 65536)
        self.seglen.setValue(4096)
        self.seglen.setToolTip("Welch segment length (samples). Often same as NFFT.")
        self.smooth_bins = QSpinBox()
        self.smooth_bins.setRange(1, 501)
        self.smooth_bins.setValue(31)
        self.smooth_bins.setToolTip("Pre-CFAR bin smoothing for PSD/Spectrogram.")
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
        self.msc_thr = QDoubleSpinBox()
        self.msc_thr.setRange(0.01, 1.0)
        self.msc_thr.setSingleStep(0.05)
        self.msc_thr.setValue(0.5)
        self.msc_thr.setToolTip("Magnitude-squared coherence threshold (0..1). Higher = stricter.")
        self.k_tapers = QSpinBox()
        self.k_tapers.setRange(1, 24)
        self.k_tapers.setValue(6)
        self.k_tapers.setToolTip("Number of DPSS tapers (multitaper PSD).")
        self.sk_thr = QDoubleSpinBox()
        self.sk_thr.setRange(0.5, 10.0)
        self.sk_thr.setSingleStep(0.1)
        self.sk_thr.setValue(2.5)
        self.sk_thr.setToolTip("Spectral kurtosis threshold; higher emphasizes rare bursts.")
        self.qmin_ms = QDoubleSpinBox()
        self.qmin_ms.setDecimals(3)
        self.qmin_ms.setRange(0.001, 1000.0)
        self.qmin_ms.setValue(0.02)
        self.qmax_ms = QDoubleSpinBox()
        self.qmax_ms.setDecimals(3)
        self.qmax_ms.setRange(0.001, 1000.0)
        self.qmax_ms.setValue(5.0)
        self.cep_topk = QSpinBox()
        self.cep_topk.setRange(1, 20)
        self.cep_topk.setValue(3)
        self.ar_order = QSpinBox()
        self.ar_order.setRange(1, 256)
        self.ar_order.setValue(32)
        self.ar_order.setToolTip("AR spectrum model order. Higher sharpens lines, risks overfit.")
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
        for widget in (QLabel("Hop"), self.hop, QLabel("SegLen"), self.seglen,
                       QLabel("SmoothBins"), self.smooth_bins, QLabel("Overlap"), self.overlap,
                       QLabel("Pfa"), self.pfa, QLabel("Top K"), self.topk):
            params.addWidget(widget)
        params.addStretch()
        layout.addLayout(params)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        adv_row = QHBoxLayout()
        for widget in (QLabel("MSC_thr"), self.msc_thr, QLabel("K_tapers"), self.k_tapers,
                       QLabel("SK_thr"), self.sk_thr, QLabel("qmin_ms"), self.qmin_ms,
                       QLabel("qmax_ms"), self.qmax_ms, QLabel("Cepstrum TopK"), self.cep_topk,
                       QLabel("AR_order"), self.ar_order):
            adv_row.addWidget(widget)
        adv_row.addStretch()
        advanced_layout.addLayout(adv_row)
        self.advanced.setVisible(False)
        layout.addWidget(self.advanced)
        self.plot = Plot()
        layout.addWidget(self.plot, 3)
        self.detections = readout()
        self.detections.setMaximumHeight(65)
        layout.addWidget(self.detections)
        self.table = QTableWidget()
        self.table.cellClicked.connect(self.on_table_select)
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
        advanced_toggle = QPushButton("Advanced ▾")
        advanced_toggle.setCheckable(True)
        advanced_toggle.toggled.connect(self._toggle_advanced)
        help_button = QPushButton("Guide")
        help_button.clicked.connect(lambda: show_help(self, "Noise_Inspector_Operator_Guide.md"))
        exports.addWidget(save_png)
        exports.addWidget(save_csv)
        exports.addWidget(surface)
        exports.addWidget(advanced_toggle)
        exports.addWidget(help_button)
        exports.addStretch()
        layout.addLayout(exports)
        self.advanced_toggle = advanced_toggle
        self.refresh_presets()
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.run() if self.auto.isChecked() else None)
        # GAP (Tk parity, recorded): the Tk tab re-arms ~2 s after each run;
        # Qt polls on a fixed 4 s cadence (gentler on the scope).
        self.timer.start(4000)

    def _toggle_advanced(self, open):
        self.advanced.setVisible(open)
        self.advanced_toggle.setText("Advanced ▴" if open else "Advanced ▾")

    def refresh_presets(self):
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItems(list(self.PRESETS.get(self.method.currentText(), {"Default": {}})))
        self.preset.blockSignals(False)
        self.apply_preset()

    def apply_preset(self):
        values = self.PRESETS.get(self.method.currentText(), {}).get(self.preset.currentText(), {})
        if not values:
            return
        targets = {"nfft": self.nfft, "seglen": self.seglen, "hop": self.hop,
                   "overlap": self.overlap, "smooth_bins": self.smooth_bins,
                   "topk": self.topk, "msc_thr": self.msc_thr, "k_tapers": self.k_tapers,
                   "sk_thr": self.sk_thr, "qmin_ms": self.qmin_ms, "qmax_ms": self.qmax_ms,
                   "cep_topk": self.cep_topk, "ar_order": self.ar_order}
        for key, value in values.items():
            if key in targets:
                targets[key].setValue(value)

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
        params = {"nfft": nfft, "seglen": self.seglen.value(), "hop": self.hop.value(),
                  "overlap": self.overlap.value(), "pfa": self.pfa.value(),
                  "topk": self.topk.value(), "smooth_bins": self.smooth_bins.value(),
                  "msc_thr": self.msc_thr.value(), "k_tapers": self.k_tapers.value(),
                  "sk_thr": self.sk_thr.value(), "qmin_ms": self.qmin_ms.value(),
                  "qmax_ms": self.qmax_ms.value(), "cep_topk": self.cep_topk.value(),
                  "ar_order": self.ar_order.value()}

        def operation():
            started = time.monotonic()
            try:
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
            finally:
                self._last_elapsed = time.monotonic() - started

        def done(result):
            self.pending = False
            if isinstance(result, Exception):
                self.notify(f"Noise Inspector: {result}")
                return
            self.last = result
            from matplotlib.ticker import EngFormatter
            ax = self.plot.axes
            ax.clear()
            if result.get("image") is not None:
                ax.imshow(result["image"], origin="lower", aspect="auto",
                          extent=result.get("extent") or None, cmap="magma")
            elif result.get("plot_x") is not None:
                ax.plot(result["plot_x"], result["plot_y"], color="#54d5ae")
                for row in result.get("detections", []):
                    freq = row.get("f0_Hz", row.get("f_Hz"))
                    if freq is not None:
                        try:
                            ax.axvline(float(freq), linestyle="--", linewidth=0.8,
                                       color="#ffcc33")
                        except (TypeError, ValueError):
                            pass
                if self.surface is not None:
                    self.surface.push(result["plot_x"], result["plot_y"])
            ax.xaxis.set_major_formatter(EngFormatter(unit="Hz"))
            hint = self.HINTS.get(method, "")
            title = f"{method} — {hint}" if hint else method
            self.plot.style_axes(title, result.get("xlabel", "Frequency (Hz)"),
                                 result.get("ylabel", "Level"))
            rows = result.get("detections", [])
            elapsed = getattr(self, "_last_elapsed", None)
            self.detections.setPlainText(
                f"{method}   Resolution: {result.get('df_Hz', 'N/A')} Hz   "
                f"Detections: {len(rows)}" +
                (f"   Elapsed: {elapsed:.2f} s" if elapsed is not None else ""))
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

    def on_table_select(self, row, _col):
        """Mirror the Tk tab: mark the selected detection on the plot."""
        if self.last is None or self.last.get("image") is not None:
            return
        try:
            item = self.table.item(row, 0)
            columns = [self.table.horizontalHeaderItem(c).text()
                       for c in range(self.table.columnCount())]
            values = {key: self.table.item(row, idx).text()
                      for idx, key in enumerate(columns) if self.table.item(row, idx)}
        except (AttributeError, ValueError):
            return
        freq = values.get("f0_Hz", values.get("f_Hz"))
        if freq is None:
            return
        try:
            self.plot.axes.axvline(float(freq), linestyle="-", linewidth=1.2,
                                   color="#ff6666")
        except (TypeError, ValueError):
            return
        self.plot.canvas.draw_idle()

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
