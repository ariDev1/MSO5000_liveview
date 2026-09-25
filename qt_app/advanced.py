"""Qt presentation for the established harmonic, B-H and noise calculations."""

import math
from collections import deque
from pathlib import Path
import time

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QHeaderView,
)

import app.app_state as app_state
from qt_app.analysis import acquire, bh_curve, harmonics, noise, read_wave_csv, save_xy_csv
from qt_app.backend import channel_name
from qt_app.tabs import (as_bool, channel_color, heading, pair_label_control, readout,
                         settings_store, tint_channel_combo)


class Plot(QWidget):
    def __init__(self, three_d=False):
        super().__init__()
        self.figure = Figure(figsize=(6, 3), facecolor="#101722")
        self.axes = self.figure.add_subplot(111, projection="3d" if three_d else None)
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        # 3D views with a color bar must not use tight_layout(): every
        # redraw would shrink the axes a little more. Constrained layout
        # stays stable across redraws and resizes.
        self.use_tight = not three_d
        if three_d:
            try:
                self.figure.set_layout_engine("constrained")
            except (AttributeError, ValueError):
                self.use_tight = True

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
        if self.use_tight:
            self.figure.tight_layout()
        self.canvas.draw_idle()

    def save_png(self, parent):
        path, _ = QFileDialog.getSaveFileName(parent, "Save plot", "oszi_csv/plot.png", "PNG (*.png)")
        if path:
            self.figure.savefig(path, dpi=150, facecolor=self.figure.get_facecolor())


def fold_setup(tab, key, expanded):
    """Fold/unfold a tab's setup container (same pattern as Power's ▾)."""
    tab.setup_box.setVisible(expanded)
    tab.setup_toggle.setText("▾" if expanded else "▸")
    QSettings("ariDev1", "MSO5000-Qt").setValue(key, bool(expanded))


def wire_setup_fold(tab, key):
    """Hook a tab's setup_toggle/setup_box pair with a persisted fold state."""
    value = QSettings("ariDev1", "MSO5000-Qt").value(key, True)
    expanded = str(value).lower() not in ("false", "0", "no")
    tab.setup_toggle.toggled.connect(lambda on, k=key: fold_setup(tab, k, on))
    tab.setup_toggle.setChecked(expanded)
    fold_setup(tab, key, expanded)


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
    """Detachable frequency / time / level view for successive spectra.

    Control bar mirrors the Tk 3D-surface window (Last N, Log Z, render
    mode, stride, points per line, Apply, Clear). Colors always encode the
    spectrum level (shared viridis scale + color bar), never the age of a
    trace; the newest trace is only drawn slightly bolder. Panes stay
    transparent with faint edges, as in the Tk window. One deliberate
    difference: Log Z stays opt-in here because Qt feeds both linear
    (harmonics) and already-logged (noise dB) spectra into the same view.
    """

    def __init__(self, parent):
        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle("Spectrum history · 3D")
        self.dialog.resize(900, 670)
        self.plot = Plot(three_d=True)
        layout = QVBoxLayout(self.dialog)
        bar = QHBoxLayout()
        self.last_n = QSpinBox()
        self.last_n.setRange(10, 500)
        self.last_n.setValue(40)
        self.log_z = QCheckBox("Log Z")
        self.mode = QComboBox()
        self.mode.addItems(["lines", "wire", "surface"])
        self.stride = QSpinBox()
        self.stride.setRange(1, 10)
        self.stride.setValue(1)
        self.pts = QSpinBox()
        self.pts.setRange(50, 2000)
        self.pts.setValue(250)
        apply = QPushButton("APPLY")
        apply.clicked.connect(self.apply_opts)
        clear = QPushButton("CLEAR")
        clear.clicked.connect(self.clear)
        for widget in (QLabel("Last N"), self.last_n, self.log_z,
                       QLabel("Mode"), self.mode, QLabel("Stride"), self.stride,
                       QLabel("Pts/line"), self.pts, apply, clear):
            bar.addWidget(widget)
        bar.addStretch()
        layout.addLayout(bar)
        layout.addWidget(self.plot)
        self.history = []
        self._seen = 0
        self.apply_opts()

    def show(self):
        self.dialog.show()
        self.dialog.raise_()
        try:
            self._redraw()
        except RuntimeError:
            pass

    def apply_opts(self):
        # Cache plain values so background pushes never touch live widgets.
        self.max_lines = max(10, self.last_n.value())
        self.use_log = self.log_z.isChecked()
        self.render_mode = self.mode.currentText()
        self.stride_n = max(1, self.stride.value())
        self.pts_n = max(50, self.pts.value())
        self.history = self.history[-self.max_lines:]
        self._redraw()

    def clear(self):
        self.history.clear()
        self._seen = 0
        self._redraw()

    def push(self, x, y):
        x, y = np.asarray(x, float), np.asarray(y, float)
        if len(x) < 2 or len(x) != len(y):
            return
        self._seen += 1
        if (self._seen - 1) % self.stride_n != 0:
            return
        axis = np.linspace(x.min(), x.max(), self.pts_n)
        self.history.append((axis, np.interp(axis, x, y)))
        self.history = self.history[-self.max_lines:]
        try:
            visible = self.dialog.isVisible()
        except RuntimeError:
            return  # parent torn down; data stays cached in history
        if visible:
            self._redraw()

    def _redraw(self):
        from matplotlib import colormaps
        from matplotlib.colors import Normalize
        from mpl_toolkits.mplot3d.art3d import Line3DCollection
        if not self.history:
            self.plot.axes.clear()
            self.plot.canvas.draw_idle()
            return
        if getattr(self, "_colorbar", None) is not None:
            try:
                self._colorbar.remove()
            except (AttributeError, ValueError):
                pass
            self._colorbar = None
        ax = self.plot.axes
        ax.clear()
        # Transparent cube walls with faint edges, subtle grid (as in Tk).
        for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            try:
                axis.pane.fill = False
                axis.pane.set_edgecolor((1, 1, 1, 0.15))
                axis._axinfo["grid"]["color"] = (1, 1, 1, 0.12)
                axis._axinfo["grid"]["linewidth"] = 0.8
            except (AttributeError, KeyError, TypeError):
                pass
        try:
            ax.set_proj_type("persp")
        except (AttributeError, ValueError):
            pass
        values = [yy if not self.use_log
                  else np.log10(np.clip(yy, 1e-12, None)) for _, yy in self.history]
        stacked = np.concatenate(values) if values else np.array([0.0, 1.0])
        vmin, vmax = float(np.min(stacked)), float(np.max(stacked))
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
            vmin, vmax = vmin - 0.5, vmax + 0.5
        norm = Normalize(vmin=vmin, vmax=vmax)
        cmap = colormaps["viridis"]
        if self.render_mode == "lines":
            # One collection: every segment colored by its level value.
            segments, colors, widths = [], [], []
            for idx, ((xx, _), zz) in enumerate(zip(self.history, values)):
                points = np.column_stack([xx, np.full(len(xx), idx), zz])
                segments.extend(zip(points[:-1], points[1:]))
                mid = 0.5 * (zz[:-1] + zz[1:])
                colors.extend(cmap(norm(mid)).tolist())
                widths.extend([1.8 if idx == len(self.history) - 1 else 1.1]
                              * max(0, len(xx) - 1))
            collection = Line3DCollection(segments, colors=colors,
                                          linewidths=widths, alpha=0.95)
            ax.add_collection3d(collection)
            ax.set_xlim(float(np.min([x.min() for x, _ in self.history])),
                        float(np.max([x.max() for x, _ in self.history])))
            ax.set_ylim(-0.5, len(self.history) - 0.5)
            ax.set_zlim(vmin, vmax)
        else:
            xx = self.history[0][0]
            rows = len(self.history)
            grid_x, grid_y = np.meshgrid(xx, np.arange(rows))
            grid_z = np.vstack(values)
            if self.render_mode == "wire":
                ax.plot_wireframe(grid_x, grid_y, grid_z, color="#7aa5ff",
                                  linewidth=0.4, alpha=0.65)
            else:
                ax.plot_surface(grid_x, grid_y, grid_z, cmap="viridis",
                                norm=norm, alpha=0.9, shade=True)
        from matplotlib.cm import ScalarMappable
        self._colorbar = self.plot.figure.colorbar(
            ScalarMappable(norm=norm, cmap=cmap), ax=ax, shrink=0.7, pad=0.08)
        self._colorbar.set_label("log₁₀(Level)" if self.use_log else "Level",
                                 color="#e5edf6")
        self._colorbar.ax.yaxis.set_tick_params(color="#e5edf6", labelcolor="#e5edf6")
        ax.set_zlabel("log₁₀(Level)" if self.use_log else "Level",
                      color="#e5edf6")
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
        self._last_freq = None
        self._last_amplitude = None
        self._last_count = 25
        self._last_channel = "CHAN1"
        # Persistence trail (same as Noise Inspector): past spectra kept
        # while Auto is on, drawn faded behind the current one.
        self._trail = deque(maxlen=12)
        self._trail_key = None
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(heading("Harmonics / THD"))
        header.addStretch()
        self.setup_toggle = QPushButton("▾")
        self.setup_toggle.setCheckable(True)
        self.setup_toggle.setToolTip("Fold/unfold the setup row to give the plot more room.")
        header.addWidget(self.setup_toggle)
        layout.addLayout(header)
        self.setup_box = QWidget()
        self.setup_box.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout(self.setup_box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.channel = QComboBox()
        self.channel.addItems([f"CHAN{i}" for i in range(1, 5)] + [f"MATH{i}" for i in range(1, 5)])
        tint_channel_combo(self.channel)
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
        self.interval = QSpinBox()
        self.interval.setRange(1, 60)
        self.interval.setValue(4)
        self.interval.setSuffix(" s")
        self.interval.setToolTip("Auto-measure cadence (Tk re-arms ~2 s).")
        self.interval.valueChanged.connect(self._retime)
        button = QPushButton("MEASURE")
        button.clicked.connect(self.run)
        csv_button = QPushButton("EXPORT TABLE")
        csv_button.clicked.connect(self.save_table)
        png_button = QPushButton("SAVE PNG")
        png_button.clicked.connect(lambda: self.plot.save_png(self))
        md_button = QPushButton("COPY MARKDOWN")
        md_button.clicked.connect(self.copy_markdown)
        surface_button = QPushButton("3D HISTORY")
        surface_button.clicked.connect(self.show_surface)
        for widget in (pair_label_control("Channel", self.channel), pair_label_control("Window", self.window),
                       pair_label_control("Harmonics", self.count), self.raw, self.include_dc,
                       self.auto, pair_label_control("Interval", self.interval),
                       button, csv_button, png_button, md_button,
                       surface_button):
            row.addWidget(widget)
        row.addStretch(1)
        layout.addWidget(self.setup_box)
        wire_setup_fold(self, "harmonicsSetupExpanded")
        self.summary = QLabel("Select an enabled channel to analyze")
        layout.addWidget(self.summary)
        self.headline = QLabel("THD —")
        self.headline.setObjectName("headline")
        layout.addWidget(self.headline)
        self.interharmonics = readout()
        self.interharmonics.setMaximumHeight(60)
        layout.addWidget(self.interharmonics)
        self.plot = Plot()
        self.columns = ("k", "f_hz", "f_pred", "df_hz", "mag_rms", "dBr1",
                        "percent", "cumTHD_pct", "phase_deg")
        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels(list(self.columns))
        self.table.setAlternatingRowColors(True)
        self.table.cellClicked.connect(self._on_table_select)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        # Same arrangement as Noise Inspector: plot left (~75%), table
        # right (~25%) in one resizable row. Content-sized columns with a
        # measurement fills the available width.
        header = self.table.horizontalHeader()
        for col in range(len(self.columns) - 1):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(len(self.columns) - 1, QHeaderView.Stretch)
        body = QSplitter(Qt.Orientation.Horizontal)
        body.addWidget(self.plot)
        body.addWidget(self.table)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 1)
        body.setSizes([750, 250])
        self.table.setMinimumWidth(260)
        layout.addWidget(body, 1)
        self.body = body
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.run() if self.auto.isChecked() else None)
        # Operator-settable cadence (Tk re-arms ~2 s; Qt defaults to a
        # gentler 4 s but the interval spinbox reaches the same range).
        self._retime()
        self._restore_setup()
        self.channel.currentIndexChanged.connect(lambda _=None: self._save_setup())
        self.window.currentIndexChanged.connect(lambda _=None: self._save_setup())
        self.count.valueChanged.connect(lambda _=None: self._save_setup())
        self.raw.toggled.connect(lambda _=None: self._save_setup())
        self.include_dc.toggled.connect(lambda _=None: self._save_setup())
        self.interval.valueChanged.connect(lambda _=None: self._save_setup())
        self.auto.toggled.connect(lambda on: self.run() if on else None)

    def _retime(self):
        self.timer.start(max(1, self.interval.value()) * 1000)

    def _save_setup(self):
        store = settings_store()
        store.beginGroup("harmonics")
        store.setValue("channel", self.channel.currentIndex())
        store.setValue("window", self.window.currentIndex())
        store.setValue("count", self.count.value())
        store.setValue("raw", self.raw.isChecked())
        store.setValue("includeDC", self.include_dc.isChecked())
        store.setValue("interval", self.interval.value())
        store.endGroup()

    def _restore_setup(self):
        store = settings_store()
        store.beginGroup("harmonics")
        for widget in (self.channel, self.window, self.count, self.raw,
                       self.include_dc, self.interval):
            widget.blockSignals(True)
        try:
            self.channel.setCurrentIndex(
                min(max(0, int(store.value("channel", 0))), self.channel.count() - 1))
            self.window.setCurrentIndex(
                min(max(0, int(store.value("window", 0))), self.window.count() - 1))
            self.count.setValue(min(max(5, int(store.value("count", 25))), 80))
            self.raw.setChecked(as_bool(store.value("raw"), True))
            self.include_dc.setChecked(as_bool(store.value("includeDC"), False))
            self.interval.setValue(min(max(1, int(store.value("interval", 4))), 60))
        except (TypeError, ValueError):
            pass
        finally:
            for widget in (self.channel, self.window, self.count, self.raw,
                           self.include_dc, self.interval):
                widget.blockSignals(False)
        store.endGroup()
        self._retime()

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
            self._last_freq = np.asarray(freq, float)
            self._last_amplitude = np.asarray(amplitude, float)
            self._last_count = count
            self._last_channel = channel
            base = (f"f₁ {result.f1_hz:.3f} Hz   Fundamental {result.v1_rms:.4g} RMS   "
                    f"THD {result.thd * 100:.2f}%")
            if result.thdn is not None:
                base += f"   THD+N {result.thdn * 100:.2f}%"
            base += f"   cycles={result.coherence_cycles:.2f}"
            if result.warnings:
                base += "   ·   " + "; ".join(result.warnings)
            self.summary.setText(base)
            self.headline.setText(
                f"THD {result.thd * 100:.2f}%   f₁ {result.f1_hz:.2f} Hz")
            self._render_table(result)
            # Persistence trail, as in the Noise Inspector: reset on
            # setup change, accumulate only in Auto mode.
            key = f"{channel}|{window}|{count}"
            if key != self._trail_key:
                self._trail_key = key
                self._trail.clear()
            if self.auto.isChecked():
                self._trail.append((np.asarray(freq), np.asarray(amplitude)))
            self._render_plot(result, freq, amplitude, count, channel_color(channel))
            if self.surface is not None:
                self.surface.push(freq, amplitude)

        self.submit(lambda: harmonics(self.backend._connected(), channel, raw, count, window, include_dc), done)

    def _on_table_select(self, row, _col):
        """Mirror the Tk tab: remember the selected harmonic for the plot marker."""
        self._apply_table_selection(row)
        self._refresh_selection_marker()

    def _on_table_selection_changed(self):
        """Same marker update for keyboard navigation (arrow keys)."""
        row = self.table.currentRow()
        if row < 0:
            return
        # Avoid double work when cellClicked already handled this row.
        if self.table.item(row, 0) is None:
            return
        try:
            freq = float(self.table.item(row, 1).text())
        except (TypeError, ValueError, AttributeError):
            return
        if freq == self._selected_freq:
            return
        self._apply_table_selection(row)
        self._refresh_selection_marker()

    def _apply_table_selection(self, row):
        try:
            self._selected_k = int(float(self.table.item(row, 0).text()))
            self._selected_freq = float(self.table.item(row, 1).text())
        except (TypeError, ValueError, AttributeError):
            self._selected_k = None
            self._selected_freq = None

    def _refresh_selection_marker(self):
        """Re-draw the cached spectrum so the blue k-marker moves instantly."""
        if self.last is None or self._last_freq is None or self._last_amplitude is None:
            return
        self._render_plot(self.last, self._last_freq, self._last_amplitude,
                          self._last_count, channel_color(self._last_channel))

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
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight |
                                      Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(idx, col, item)
        self.table.resizeColumnsToContents()

    def _render_plot(self, result, freq, amplitude, count, trace="#d0ff00"):
        import matplotlib.lines as mlines
        import matplotlib.patches as mpatches
        from scipy.signal import find_peaks
        self.plot.axes.clear()
        # Historical spectra first (oldest faintest), current on top.
        for idx, (old_x, old_y) in enumerate(self._trail):
            alpha = 0.12 + 0.35 * ((idx + 1) / len(self._trail)) ** 1.5
            self.plot.axes.plot(old_x, old_y, linewidth=1.0, alpha=alpha,
                                color=trace, zorder=1)
        self.plot.axes.plot(freq, amplitude, color=trace, linewidth=1.4, label="Spectrum", zorder=3)
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
        # Auto-zoom to the interesting part: the highest table harmonic
        # plus margin, instead of the full 0..fs/2 capture span.
        if len(freq) > 1:
            f_end = float(freq[-1])
            tops = [float(item.f_hz) for item in result.rows]
            if result.f1_hz > 0:
                tops.append(float(result.f1_hz))
            if tops:
                self.plot.axes.set_xlim(0, min(max(max(tops) * 1.1, 1e-12), f_end))
        self.plot.axes.legend(
            handles=[mlines.Line2D([], [], linewidth=1.4, label="Spectrum", color=trace),
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
        header = QHBoxLayout()
        header.addWidget(heading("B–H curve / hysteresis"))
        header.addStretch()
        self.setup_toggle = QPushButton("▾")
        self.setup_toggle.setCheckable(True)
        self.setup_toggle.setToolTip("Fold/unfold the parameter grid to give the plot more room.")
        header.addWidget(self.setup_toggle)
        layout.addLayout(header)
        self.setup_box = QWidget()
        self.setup_box.setContentsMargins(0, 0, 0, 0)
        setup_layout = QVBoxLayout(self.setup_box)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        setup_layout.setSpacing(4)
        grid_widget = QWidget()
        grid_widget.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        self.voltage = QComboBox()
        self.current = QComboBox()
        for selector in (self.voltage, self.current):
            selector.addItems([f"CHAN{i}" for i in range(1, 5)] + [f"MATH{i}" for i in range(1, 5)])
            tint_channel_combo(selector)
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
            grid.addWidget(pair_label_control(name, widget), idx // 5, idx % 5)
        grid.setColumnStretch(5, 1)
        setup_layout.addWidget(grid_widget)
        opts_widget = QWidget()
        opts_widget.setContentsMargins(0, 0, 0, 0)
        opts = QHBoxLayout(opts_widget)
        opts.setContentsMargins(0, 0, 0, 0)
        opts.setSpacing(10)
        for widget in (self.raw, self.dc, self.detrend, self.cycle, self.auto,
                       pair_label_control("Interval", self.interval), self.equal_aspect, self.tight,
                       self.data, self.overlay):
            opts.addWidget(widget)
        opts.addStretch(1)
        setup_layout.addWidget(opts_widget)
        layout.addWidget(self.setup_box)
        wire_setup_fold(self, "bhSetupExpanded")
        actions = QHBoxLayout()
        actions.setSpacing(10)
        button = QPushButton("ACQUIRE & PLOT")
        button.clicked.connect(self.run)
        png = QPushButton("SAVE PNG")
        png.clicked.connect(lambda: self.plot.save_png(self))
        csv = QPushButton("SAVE CSV")
        csv.clicked.connect(self.save_csv)
        help_button = QPushButton("GUIDE")
        help_button.clicked.connect(lambda: show_help(self, "bh-curve_help.md"))
        clear = QPushButton("RESET TRAIL")
        clear.clicked.connect(self.clear_trail)
        for widget in (button, clear, png, csv, help_button):
            actions.addWidget(widget)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.headline = QLabel("LOOP —")
        self.headline.setObjectName("headline")
        layout.addWidget(self.headline)
        self.plot = Plot()
        layout.addWidget(self.plot, 3)
        self.details = readout()
        self.details.setMaximumHeight(100)
        layout.addWidget(self.details)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.run() if self.auto.isChecked() else None)
        self.auto.toggled.connect(lambda on: self.run() if on else None)
        self._retime()
        self._toggle_data(True)
        self._restore_setup()
        for box in (self.voltage, self.current, self.probe_type, self.cycle_ref):
            box.currentIndexChanged.connect(lambda _=None: self._save_setup())
        for spin in (self.turns, self.area, self.length, self.probe_value,
                     self.deskew, self.avg_cycles, self.interval):
            spin.valueChanged.connect(lambda _=None: self._save_setup())
        for check in (self.raw, self.dc, self.detrend, self.cycle,
                      self.equal_aspect, self.tight, self.overlay):
            check.toggled.connect(lambda _=None: self._save_setup())

    def _save_setup(self):
        store = settings_store()
        store.beginGroup("bh")
        store.setValue("voltage", self.voltage.currentIndex())
        store.setValue("current", self.current.currentIndex())
        store.setValue("turns", self.turns.value())
        store.setValue("area", self.area.value())
        store.setValue("length", self.length.value())
        store.setValue("probeType", self.probe_type.currentIndex())
        store.setValue("probeValue", self.probe_value.value())
        store.setValue("deskew", self.deskew.value())
        store.setValue("cycleRef", self.cycle_ref.currentIndex())
        store.setValue("avgCycles", self.avg_cycles.value())
        store.setValue("raw", self.raw.isChecked())
        store.setValue("dc", self.dc.isChecked())
        store.setValue("detrend", self.detrend.isChecked())
        store.setValue("cycle", self.cycle.isChecked())
        store.setValue("equal", self.equal_aspect.isChecked())
        store.setValue("tight", self.tight.isChecked())
        store.setValue("overlay", self.overlay.isChecked())
        store.setValue("interval", self.interval.value())
        store.endGroup()

    def _restore_setup(self):
        store = settings_store()
        store.beginGroup("bh")
        tracked = (self.voltage, self.current, self.turns, self.area,
                   self.length, self.probe_type, self.probe_value, self.deskew,
                   self.cycle_ref, self.avg_cycles, self.raw, self.dc,
                   self.detrend, self.cycle, self.equal_aspect, self.tight,
                   self.overlay, self.interval)
        for widget in tracked:
            widget.blockSignals(True)
        try:
            self.voltage.setCurrentIndex(
                min(max(0, int(store.value("voltage", 0))), self.voltage.count() - 1))
            self.current.setCurrentIndex(
                min(max(0, int(store.value("current", 2))), self.current.count() - 1))
            self.turns.setValue(int(store.value("turns", 20)))
            self.area.setValue(float(store.value("area", 25)))
            self.length.setValue(float(store.value("length", 50)))
            self.probe_type.setCurrentIndex(
                min(max(0, int(store.value("probeType", 0))), self.probe_type.count() - 1))
            self.probe_value.setValue(float(store.value("probeValue", 0.1)))
            self.deskew.setValue(float(store.value("deskew", 0.0)))
            self.cycle_ref.setCurrentIndex(
                min(max(0, int(store.value("cycleRef", 0))), self.cycle_ref.count() - 1))
            self.avg_cycles.setValue(min(max(1, int(store.value("avgCycles", 1))), 10))
            self.raw.setChecked(as_bool(store.value("raw"), False))
            self.dc.setChecked(as_bool(store.value("dc"), True))
            self.detrend.setChecked(as_bool(store.value("detrend"), False))
            self.cycle.setChecked(as_bool(store.value("cycle"), False))
            self.equal_aspect.setChecked(as_bool(store.value("equal"), False))
            self.tight.setChecked(as_bool(store.value("tight"), True))
            self.overlay.setChecked(as_bool(store.value("overlay"), False))
            self.interval.setValue(min(max(1, int(store.value("interval", 5))), 60))
        except (TypeError, ValueError):
            pass
        finally:
            for widget in tracked:
                widget.blockSignals(False)
        store.endGroup()
        self._retime()

    def _retime(self):
        self.timer.start(max(1, self.interval.value()) * 1000)

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
            # Heatmap-like trail (Tk parity): older loops run through the
            # plasma colormap by age, current loop stays yellow on top.
            if len(self.history) > 1:
                from matplotlib import colormaps
                cmap = colormaps["plasma"]
                for idx, (old_h, old_b) in enumerate(self.history[:-1]):
                    tcol = idx / (len(self.history) - 2 + 1e-6)
                    self.plot.axes.plot(old_h, old_b, color=cmap(tcol),
                                        linewidth=1.3, alpha=0.7)
            if self.history:
                old_h, old_b = self.history[-1]
                self.plot.axes.plot(old_h, old_b, color="yellow",
                                    linewidth=1.8, alpha=0.95)
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
            loop_area = abs(np.trapezoid(b, h))
            self.headline.setText(f"∮ {loop_area:.4g} J/m³   Hc {hc:.4g} A/m")
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
                f"Loop area: {loop_area:.4g} J/m³"
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
        # Persistence trail for the heat-map-like history view (as in Tk).
        self._trail = deque(maxlen=12)
        self._trail_key = None
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(heading("Noise Inspector"))
        header.addStretch()
        self.setup_toggle = QPushButton("▾")
        self.setup_toggle.setCheckable(True)
        self.setup_toggle.setToolTip("Fold/unfold the setup rows to give the plot more room.")
        header.addWidget(self.setup_toggle)
        layout.addLayout(header)
        self.setup_box = QWidget()
        self.setup_box.setContentsMargins(0, 0, 0, 0)
        box = QVBoxLayout(self.setup_box)
        box.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.channel = QComboBox()
        self.other = QComboBox()
        for combo in (self.channel, self.other):
            combo.addItems([f"CHAN{i}" for i in range(1, 5)] + [f"MATH{i}" for i in range(1, 5)])
            tint_channel_combo(combo)
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
        browse = QPushButton("BROWSE")
        browse.clicked.connect(self.browse)
        self.auto = QCheckBox("Auto")
        self.interval = QSpinBox()
        self.interval.setRange(1, 60)
        self.interval.setValue(4)
        self.interval.setSuffix(" s")
        self.interval.setToolTip("Auto-measure cadence (Tk re-arms ~2 s).")
        self.interval.valueChanged.connect(self._retime)
        run = QPushButton("ANALYZE")
        run.clicked.connect(self.run)
        self.other_label = QLabel("Other")
        for widget in (QLabel("Channel"), self.channel, self.other_label, self.other,
                       self.method, self.preset, QLabel("NFFT"), self.nfft, self.csv_path,
                       browse, self.auto, QLabel("Interval"), self.interval, run):
            row.addWidget(widget)
        box.addLayout(row)
        params = QHBoxLayout()
        for widget in (QLabel("Hop"), self.hop, QLabel("SegLen"), self.seglen,
                       QLabel("SmoothBins"), self.smooth_bins, QLabel("Overlap"), self.overlap,
                       QLabel("Pfa"), self.pfa, QLabel("Top K"), self.topk):
            params.addWidget(widget)
        params.addStretch()
        box.addLayout(params)
        layout.addWidget(self.setup_box)
        wire_setup_fold(self, "noiseSetupExpanded")
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
        # Inside the foldable setup container: folding Setup hides the
        # advanced row too instead of leaving it floating alone on top.
        box.addWidget(self.advanced)
        self.plot = Plot()
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.cellClicked.connect(self.on_table_select)
        # Fill the available width: content-sized columns + stretched last
        # visible column, so no empty viewport remains on the right.
        self.table.horizontalHeader().setStretchLastSection(True)
        # Plot left (~75%), hits table right (~25%) in one resizable row
        # instead of stacked full-width widgets leaving empty space.
        self.headline = QLabel("0 HITS")
        self.headline.setObjectName("headline")
        layout.addWidget(self.headline)
        self.detections = readout()
        self.detections.setMaximumHeight(65)
        layout.addWidget(self.detections)
        body = QSplitter(Qt.Orientation.Horizontal)
        body.addWidget(self.plot)
        body.addWidget(self.table)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 1)
        body.setSizes([750, 250])
        self.table.setMinimumWidth(220)
        layout.addWidget(body, 1)
        self.body = body
        self.auto_log = QCheckBox("Log detections automatically")
        self.auto_log.setChecked(True)
        layout.addWidget(self.auto_log)
        exports = QHBoxLayout()
        save_png = QPushButton("SAVE PNG")
        save_png.clicked.connect(lambda: self.plot.save_png(self))
        save_csv = QPushButton("SAVE DETECTIONS")
        save_csv.clicked.connect(self.save_csv)
        surface = QPushButton("3D HISTORY")
        surface.clicked.connect(self.show_surface)
        advanced_toggle = QPushButton("ADVANCED ▾")
        advanced_toggle.setCheckable(True)
        advanced_toggle.toggled.connect(self._toggle_advanced)
        help_button = QPushButton("GUIDE")
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
        self.auto.toggled.connect(lambda on: self.run() if on else None)
        # Operator-settable cadence (Tk re-arms ~2 s; Qt defaults to a
        # gentler 4 s but the interval spinbox reaches the same range).
        self._retime()
        self._update_channel_visibility()
        self._restore_setup()
        for box in (self.channel, self.other, self.method, self.preset):
            box.currentIndexChanged.connect(lambda _=None: self._save_setup())
        for spin in (self.nfft, self.seglen, self.smooth_bins, self.hop,
                     self.topk, self.msc_thr, self.k_tapers, self.sk_thr,
                     self.qmin_ms, self.qmax_ms, self.cep_topk, self.ar_order,
                     self.interval):
            spin.valueChanged.connect(lambda _=None: self._save_setup())
        self.overlap.valueChanged.connect(lambda _=None: self._save_setup())
        self.pfa.valueChanged.connect(lambda _=None: self._save_setup())

    def _save_setup(self):
        store = settings_store()
        store.beginGroup("noise")
        store.setValue("channel", self.channel.currentIndex())
        store.setValue("other", self.other.currentIndex())
        store.setValue("method", self.method.currentText())
        store.setValue("nfft", self.nfft.value())
        store.setValue("seglen", self.seglen.value())
        store.setValue("smooth", self.smooth_bins.value())
        store.setValue("hop", self.hop.value())
        store.setValue("overlap", self.overlap.value())
        store.setValue("pfa", self.pfa.value())
        store.setValue("topk", self.topk.value())
        store.setValue("mscThr", self.msc_thr.value())
        store.setValue("kTapers", self.k_tapers.value())
        store.setValue("skThr", self.sk_thr.value())
        store.setValue("qmin", self.qmin_ms.value())
        store.setValue("qmax", self.qmax_ms.value())
        store.setValue("cepTopk", self.cep_topk.value())
        store.setValue("arOrder", self.ar_order.value())
        store.setValue("interval", self.interval.value())
        store.endGroup()

    def _restore_setup(self):
        store = settings_store()
        store.beginGroup("noise")
        tracked = (self.channel, self.other, self.method, self.nfft,
                   self.seglen, self.smooth_bins, self.hop, self.overlap,
                   self.pfa, self.topk, self.msc_thr, self.k_tapers,
                   self.sk_thr, self.qmin_ms, self.qmax_ms, self.cep_topk,
                   self.ar_order, self.interval)
        for widget in tracked:
            widget.blockSignals(True)
        try:
            self.channel.setCurrentIndex(
                min(max(0, int(store.value("channel", 0))), self.channel.count() - 1))
            self.other.setCurrentIndex(
                min(max(0, int(store.value("other", 1))), self.other.count() - 1))
            saved_method = str(store.value("method", self.METHODS[0]))
            if saved_method in self.METHODS:
                self.method.setCurrentText(saved_method)
        except (TypeError, ValueError):
            pass
        finally:
            for widget in (self.channel, self.other, self.method):
                widget.blockSignals(False)
        # Presets first (they reset spins to method defaults), saved spins after.
        self.refresh_presets()
        for widget in tracked[3:]:
            widget.blockSignals(True)
        try:
            self.nfft.setValue(int(store.value("nfft", 4096)))
            self.seglen.setValue(int(store.value("seglen", 4096)))
            self.smooth_bins.setValue(int(store.value("smooth", 31)))
            self.hop.setValue(int(store.value("hop", 2048)))
            self.overlap.setValue(float(store.value("overlap", 0.5)))
            self.pfa.setValue(float(store.value("pfa", 0.001)))
            self.topk.setValue(int(store.value("topk", 8)))
            self.msc_thr.setValue(float(store.value("mscThr", 0.5)))
            self.k_tapers.setValue(int(store.value("kTapers", 6)))
            self.sk_thr.setValue(float(store.value("skThr", 2.5)))
            self.qmin_ms.setValue(float(store.value("qmin", 0.02)))
            self.qmax_ms.setValue(float(store.value("qmax", 5.0)))
            self.cep_topk.setValue(int(store.value("cepTopk", 3)))
            self.ar_order.setValue(int(store.value("arOrder", 32)))
            self.interval.setValue(min(max(1, int(store.value("interval", 4))), 60))
        except (TypeError, ValueError):
            pass
        finally:
            for widget in tracked[3:]:
                widget.blockSignals(False)
        store.endGroup()
        self._retime()

    def _retime(self):
        self.timer.start(max(1, self.interval.value()) * 1000)

    def _toggle_advanced(self, open):
        self.advanced.setVisible(open)
        self.advanced_toggle.setText("ADVANCED ▴" if open else "ADVANCED ▾")

    def refresh_presets(self):
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItems(list(self.PRESETS.get(self.method.currentText(), {"Default": {}})))
        self.preset.blockSignals(False)
        self.apply_preset()
        self._update_channel_visibility()

    def _update_channel_visibility(self):
        """Show the second channel selector only for MSC (Tk: pair only for MSC)."""
        needs_pair = self.method.currentText() == "MSC"
        self.other.setVisible(needs_pair)
        self.other_label.setVisible(needs_pair)

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
        channel, second = self.channel.currentText(), self.other.currentText()
        method, path, nfft = self.method.currentText(), self.csv_path.text().strip(), self.nfft.value()
        if method == "MSC" and second == channel:
            self.notify("MSC needs two different channels")
            return
        self.pending = True
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
                x, y = np.asarray(result["plot_x"], float), np.asarray(result["plot_y"], float)
                trace = channel_color(channel)
                # Persistence trail, as in the Tk tab: reset on method/channel
                # change, accumulate only in Auto mode to keep single runs clean.
                key = f"{method}|{channel}"
                if key != self._trail_key:
                    self._trail_key = key
                    self._trail.clear()
                if self.auto.isChecked() and len(x) == len(y) and len(x) > 1:
                    self._trail.append((x, y))
                for idx, (old_x, old_y) in enumerate(self._trail):
                    alpha = 0.12 + 0.35 * ((idx + 1) / len(self._trail)) ** 1.5
                    ax.plot(old_x, old_y, linewidth=1.0, alpha=alpha,
                            color=trace, zorder=1)
                ax.plot(x, y, linewidth=0.9, color=trace, zorder=3)
                for row in result.get("detections", []):
                    freq = row.get("f0_Hz", row.get("f_Hz"))
                    if freq is not None:
                        try:
                            ax.axvline(float(freq), linestyle="--", linewidth=0.8,
                                       color="#ffcc33")
                        except (TypeError, ValueError):
                            pass
                # Always record history (hidden until opened), as in the Tk
                # tab — opening "3D history" later still shows past runs.
                if self.surface is None:
                    self.surface = SurfaceHistory(self)
                self.surface.push(result["plot_x"], result["plot_y"])
            ax.xaxis.set_major_formatter(EngFormatter(unit="Hz"))
            hint = self.HINTS.get(method, "")
            title = f"{method} — {hint}" if hint else method
            self.plot.style_axes(title, result.get("xlabel", "Frequency (Hz)"),
                                 result.get("ylabel", "Level"))
            rows = result.get("detections", [])
            elapsed = getattr(self, "_last_elapsed", None)
            top = ""
            if rows:
                first = rows[0]
                freq = first.get("f0_Hz", first.get("f_Hz", first.get("f1_Hz")))
                if freq is not None:
                    try:
                        top = f"   TOP {float(freq):.3g} Hz"
                    except (TypeError, ValueError):
                        pass
            self.headline.setText(f"{len(rows)} HITS{top}")
            self.detections.setPlainText(
                f"{method}   Resolution: {result.get('df_Hz', 'N/A')} Hz   "
                f"Detections: {len(rows)}" +
                (f"   Elapsed: {elapsed:.2f} s" if elapsed is not None else ""))
            def _cell_text(value):
                # Display-only compaction: full precision stays in the CSV
                # export; the table shows 6 significant digits so long
                # floats (e.g. MSC 0.998618874034408) don't widen columns.
                if isinstance(value, float):
                    return f"{value:.6g}"
                return str(value if value is not None else "")

            # Drop columns that carry no information (e.g. empty 'notes'
            # for MSC). They are removed rather than hidden: the header's
            # stretch-last-section only fills the viewport when the last
            # section is visible.
            columns = [key for key in dict.fromkeys(k for row in rows for k in row)
                       if any(_cell_text(r.get(key, "")).strip() for r in rows)]
            self.table.setColumnCount(len(columns))
            self.table.setHorizontalHeaderLabels(columns)
            self.table.setRowCount(len(rows))

            for row_idx, row in enumerate(rows):
                for col_idx, key in enumerate(columns):
                    text = _cell_text(row.get(key, ""))
                    item = QTableWidgetItem(text)
                    try:
                        float(text)
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight |
                                              Qt.AlignmentFlag.AlignVCenter)
                    except (TypeError, ValueError):
                        pass
                    self.table.setItem(row_idx, col_idx, item)
            # Content-sized columns with a stretching last column, enforced
            # via resize modes (not a one-shot resizeColumnsToContents):
            # modes re-apply on every data change, so a narrower follow-up
            # measurement still fills the available width.
            header = self.table.horizontalHeader()
            for col_idx in range(max(0, len(columns) - 1)):
                header.setSectionResizeMode(col_idx, QHeaderView.ResizeToContents)
            if columns:
                header.setSectionResizeMode(len(columns) - 1, QHeaderView.Stretch)
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
