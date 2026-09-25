"""Qt presentation for the ferrite magnetics analyzer (Phase 1).

Phase 1 covers the core loop: V&I, B-H loop with plasma trail, B(t), H(t),
headline scalars and a readout. Materials UI, decomposition window, hover
cursors and CSV logging arrive in Phase 2. Calculation core is shared
(gui/magnetic/magnetics.py); acquisition uses the shared _fetch_wave path
via qt_app.analysis.magnetics (never the Tk tab's exclusive reader).
"""

import math
from collections import deque
from datetime import datetime

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

import app.app_state as app_state
from gui.magnetic.magnetics import (
    AL_from_geometry, BUILTIN_MATERIAL_NAMES, MATERIALS, MATERIAL_NAMES,
    _get_material, _save_user_materials, toroid_Ae, toroid_le,
)
from qt_app.advanced import wire_setup_fold
from qt_app.analysis import magnetics
from qt_app.tabs import (as_bool, heading, pair_label_control, readout,
                         settings_store, tint_channel_combo)

# Trace colors carried over from the Tk magnetics tab (display-only).
C_V, C_I, C_B, C_H = "#00d4ff", "#ff6b35", "#00ff88", "#ffd700"


class MagneticsTab(QWidget):
    def __init__(self, submit, backend, notify):
        super().__init__()
        self.submit, self.backend, self.notify = submit, backend, notify
        self.pending, self.last = False, None
        self.history = []
        self._last_ae, self._last_le, self._last_bsat = 50e-6, 0.05, 290.0
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(heading("Magnetics"))
        header.addStretch()
        self.setup_toggle = QPushButton("▾")
        self.setup_toggle.setCheckable(True)
        self.setup_toggle.setToolTip("Fold/unfold the setup to give the plots more room.")
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
            selector.addItems([f"CHAN{i}" for i in range(1, 5)]
                              + [f"MATH{i}" for i in range(1, 5)])
            tint_channel_combo(selector)
        self.current.setCurrentIndex(1)
        self.turns = QSpinBox()
        self.turns.setRange(1, 100000)
        self.turns.setValue(10)
        self.dim_mode = QComboBox()
        self.dim_mode.addItems(["Toroid OD/ID/HT", "Direct Ae/le"])
        self.dim_mode.currentIndexChanged.connect(self._toggle_dims)
        self.od = QDoubleSpinBox()
        self.od.setRange(0.01, 1e6)
        self.od.setValue(25.0)
        self.od.setSuffix(" mm")
        self.odim = QDoubleSpinBox()
        self.odim.setRange(0.01, 1e6)
        self.odim.setValue(15.0)
        self.odim.setSuffix(" mm")
        self.ht = QDoubleSpinBox()
        self.ht.setRange(0.01, 1e6)
        self.ht.setValue(10.0)
        self.ht.setSuffix(" mm")
        self.area = QDoubleSpinBox()
        self.area.setRange(0.0001, 1e9)
        self.area.setValue(25.0)
        self.area.setSuffix(" mm²")
        self.length = QDoubleSpinBox()
        self.length.setRange(0.0001, 1e9)
        self.length.setValue(50.0)
        self.length.setSuffix(" mm")
        self.deskew = QDoubleSpinBox()
        self.deskew.setRange(-1e6, 1e6)
        self.deskew.setToolTip("Deskew Δt (V−I) in µs, same convention as B-H.")
        self.material = QComboBox()
        self.material.addItems(MATERIAL_NAMES)
        self.material.setToolTip("Core material preset (reference μi/Bsat + stored geometry).")
        self.material.currentIndexChanged.connect(self._on_material)
        self.mui = QDoubleSpinBox()
        self.mui.setRange(1.0, 1e6)
        self.mui.setValue(800.0)
        self.mui.setDecimals(0)
        self.mui.setToolTip("Initial relative permeability (reference only).")
        self.bsat = QDoubleSpinBox()
        self.bsat.setRange(1.0, 1e5)
        self.bsat.setValue(290.0)
        self.bsat.setDecimals(0)
        self.bsat.setSuffix(" mT")
        self.bsat.setToolTip("Saturation flux density; drawn as limit lines on B(t).")
        self.preset_name = QLineEdit()
        self.preset_name.setPlaceholderText("Preset name")
        self.preset_name.setToolTip("Name for saving μi/Bsat + geometry as a preset.")
        self.r_winding = QDoubleSpinBox()
        self.r_winding.setRange(0.0, 1e6)
        self.r_winding.setDecimals(4)
        self.r_winding.setSuffix(" Ω")
        self.r_winding.setToolTip("Primary winding resistance; 0 disables loss separation.")
        self.secondaries = []
        for default in (0, 0):
            chan = QComboBox()
            chan.addItems(["OFF"] + [f"CHAN{i}" for i in range(1, 5)]
                          + [f"MATH{i}" for i in range(1, 5)])
            chan.setCurrentIndex(default)
            turns = QSpinBox()
            turns.setRange(1, 100000)
            turns.setValue(1)
            self.secondaries.append((chan, turns))
        (self.i2_chan, self.n2), (self.i3_chan, self.n3) = self.secondaries
        self.raw = QCheckBox("RAW")
        self.raw.setToolTip("Full-memory fetch via the shared scope path.")
        self.auto = QCheckBox("Auto")
        self.interval = QSpinBox()
        self.interval.setRange(1, 60)
        self.interval.setValue(5)
        self.interval.setSuffix(" s")
        self.interval.valueChanged.connect(self._retime)
        self.trail = QCheckBox("Trail")
        self.trail.setToolTip("Keep past loops as a plasma heat-trail (as in B-H).")
        self.cursors = QCheckBox("Cursors")
        self.cursors.setChecked(True)
        self.cursors.setToolTip("Hover the plots to read values.")
        self.save_preset_button = QPushButton("SAVE PRESET")
        self.save_preset_button.setToolTip("Save μi/Bsat + geometry as a material preset.")
        self.save_preset_button.clicked.connect(self.save_preset)

        pairs = [pair_label_control("Voltage", self.voltage),
                 pair_label_control("Current", self.current),
                 pair_label_control("Turns N", self.turns),
                 pair_label_control("Geometry", self.dim_mode),
                 pair_label_control("OD", self.od),
                 pair_label_control("ID", self.odim),
                 pair_label_control("HT", self.ht),
                 pair_label_control("Ae", self.area),
                 pair_label_control("le", self.length),
                 pair_label_control("Deskew (µs)", self.deskew),
                 pair_label_control("Material", self.material),
                 pair_label_control("μi", self.mui),
                 pair_label_control("Bsat", self.bsat),
                 pair_label_control("Preset name", self.preset_name),
                 pair_label_control("R winding", self.r_winding),
                 pair_label_control("I2 chan", self.i2_chan),
                 pair_label_control("N2", self.n2),
                 pair_label_control("I3 chan", self.i3_chan),
                 pair_label_control("N3", self.n3)]
        for idx, widget in enumerate(pairs):
            grid.addWidget(widget, idx // 5, idx % 5)
        grid.setColumnStretch(5, 1)
        setup_layout.addWidget(grid_widget)
        opts_widget = QWidget()
        opts_widget.setContentsMargins(0, 0, 0, 0)
        opts = QHBoxLayout(opts_widget)
        opts.setContentsMargins(0, 0, 0, 0)
        opts.setSpacing(10)
        for widget in (self.raw, self.auto,
                       pair_label_control("Interval", self.interval),
                       self.trail, self.cursors, self.save_preset_button):
            opts.addWidget(widget)
        opts.addStretch(1)
        setup_layout.addWidget(opts_widget)
        layout.addWidget(self.setup_box)
        wire_setup_fold(self, "magneticsSetupExpanded")

        actions = QHBoxLayout()
        actions.setSpacing(10)
        button = QPushButton("MEASURE")
        button.clicked.connect(self.run)
        decomp_button = QPushButton("DECOMP")
        decomp_button.setToolTip("Winding-current decomposition and loss separation.")
        decomp_button.clicked.connect(self.show_decomp)
        csv_button = QPushButton("EXPORT CSV")
        csv_button.setToolTip("Export time series + scalars to CSV.")
        csv_button.clicked.connect(self.export_csv)
        png = QPushButton("SAVE PNG")
        png.clicked.connect(self.save_png)
        clear = QPushButton("RESET TRAIL")
        clear.clicked.connect(self.clear_trail)
        for widget in (button, decomp_button, csv_button, png, clear):
            actions.addWidget(widget)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.headline = QLabel("LOOP —")
        self.headline.setObjectName("headline")
        layout.addWidget(self.headline)
        self.figure = Figure(figsize=(9, 7), facecolor="#101722")
        self.canvas = FigureCanvasQTAgg(self.figure)
        flat = self.figure.subplots(3, 3).flat
        (self.ax_vi, self.ax_bh, self.ax_mud, self.ax_b, self.ax_h,
         self.ax_l, self.ax_mu, self.ax_bphi, self.ax_bi) = flat
        self._plot_axes = (self.ax_vi, self.ax_bh, self.ax_mud, self.ax_b,
                           self.ax_h, self.ax_l, self.ax_mu, self.ax_bphi,
                           self.ax_bi)
        for axes in self._plot_axes:
            axes.set_facecolor("#101722")
            axes.tick_params(colors="#d0dfec", labelsize=7)
            for spine in axes.spines.values():
                spine.set_color("#758da8")
            axes.grid(True, color="#445469", alpha=0.5)
        self.ax_vi2 = self.ax_vi.twinx()
        self.ax_vi2.tick_params(colors="#d0dfec", labelsize=7)
        self.ax_phi2 = self.ax_bphi.twinx()
        self.ax_phi2.tick_params(colors="#d0dfec", labelsize=7)
        layout.addWidget(self.canvas, 3)
        self.cursor = QLabel("Hover a plot to read values")
        self.cursor.setStyleSheet("font-family: monospace; color: #5c6b7d;")
        layout.addWidget(self.cursor)
        self._hover = None
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)
        self.details = readout()
        self.details.setMaximumHeight(110)
        layout.addWidget(self.details)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.run() if self.auto.isChecked() else None)
        self.auto.toggled.connect(lambda on: self.run() if on else None)
        self._retime()
        self._toggle_dims()
        self._restore_setup()
        for box in (self.voltage, self.current, self.dim_mode, self.material,
                      self.i2_chan, self.i3_chan):
            box.currentIndexChanged.connect(lambda _=None: self._save_setup())
        for spin in (self.turns, self.od, self.odim, self.ht, self.area,
                     self.length, self.deskew, self.mui, self.bsat,
                     self.r_winding, self.n2, self.n3, self.interval):
            spin.valueChanged.connect(lambda _=None: self._save_setup())
        self.preset_name.textChanged.connect(lambda _=None: self._save_setup())
        for check in (self.raw, self.auto, self.trail, self.cursors):
            check.toggled.connect(lambda _=None: self._save_setup())

    def _toggle_dims(self):
        toroid = self.dim_mode.currentIndex() == 0
        for widget in (self.od, self.odim, self.ht):
            widget.parentWidget().setVisible(toroid)
        for widget in (self.area, self.length):
            widget.parentWidget().setVisible(not toroid)

    def _geometry_si(self):
        """Effective (Ae m², le m, label) from the active geometry mode."""
        if self.dim_mode.currentIndex() == 0:
            od, oid, ht = self.od.value(), self.odim.value(), self.ht.value()
            if od <= oid or oid <= 0 or ht <= 0:
                raise ValueError("Toroid needs 0 < ID < OD and HT > 0")
            ae = toroid_Ae(od, oid, ht)
            le = toroid_le(od, oid)
            label = f"Toroid OD {od:g}/ID {oid:g}/HT {ht:g} mm"
        else:
            ae_mm2, le_mm = self.area.value(), self.length.value()
            if ae_mm2 <= 0 or le_mm <= 0:
                raise ValueError("Ae and le must be positive")
            ae, le = ae_mm2 * 1e-6, le_mm * 1e-3
            label = f"Ae {ae_mm2:g} mm² le {le_mm:g} mm"
        return ae, le, label

    def _retime(self):
        self.timer.start(max(1, self.interval.value()) * 1000)

    def _save_setup(self):
        store = settings_store()
        store.beginGroup("magnetics")
        store.setValue("voltage", self.voltage.currentIndex())
        store.setValue("current", self.current.currentIndex())
        store.setValue("turns", self.turns.value())
        store.setValue("dimMode", self.dim_mode.currentIndex())
        store.setValue("od", self.od.value())
        store.setValue("id", self.odim.value())
        store.setValue("ht", self.ht.value())
        store.setValue("area", self.area.value())
        store.setValue("length", self.length.value())
        store.setValue("deskew", self.deskew.value())
        store.setValue("material", self.material.currentText())
        store.setValue("mui", self.mui.value())
        store.setValue("bsat", self.bsat.value())
        store.setValue("presetName", self.preset_name.text())
        store.setValue("rWinding", self.r_winding.value())
        store.setValue("i2", self.i2_chan.currentIndex())
        store.setValue("n2", self.n2.value())
        store.setValue("i3", self.i3_chan.currentIndex())
        store.setValue("n3", self.n3.value())
        store.setValue("raw", self.raw.isChecked())
        store.setValue("auto", self.auto.isChecked())
        store.setValue("trail", self.trail.isChecked())
        store.setValue("cursors", self.cursors.isChecked())
        store.setValue("interval", self.interval.value())
        store.endGroup()

    def _restore_setup(self):
        store = settings_store()
        store.beginGroup("magnetics")
        fresh = store.contains("mui") is False
        tracked = (self.voltage, self.current, self.turns, self.dim_mode,
                   self.od, self.odim, self.ht, self.area, self.length,
                   self.deskew, self.material, self.mui, self.bsat,
                   self.r_winding, self.i2_chan, self.n2, self.i3_chan,
                   self.n3, self.raw, self.auto, self.trail, self.cursors,
                   self.interval)
        for widget in tracked:
            widget.blockSignals(True)
        try:
            self.voltage.setCurrentIndex(
                min(max(0, int(store.value("voltage", 0))), self.voltage.count() - 1))
            self.current.setCurrentIndex(
                min(max(0, int(store.value("current", 1))), self.current.count() - 1))
            self.turns.setValue(int(store.value("turns", 10)))
            self.dim_mode.setCurrentIndex(
                min(max(0, int(store.value("dimMode", 0))), self.dim_mode.count() - 1))
            self.od.setValue(float(store.value("od", 25.0)))
            self.odim.setValue(float(store.value("id", 15.0)))
            self.ht.setValue(float(store.value("ht", 10.0)))
            self.area.setValue(float(store.value("area", 25.0)))
            self.length.setValue(float(store.value("length", 50.0)))
            self.deskew.setValue(float(store.value("deskew", 0.0)))
            saved_material = str(store.value("material", ""))
            if saved_material and saved_material in MATERIAL_NAMES:
                self.material.setCurrentText(saved_material)
            self.mui.setValue(float(store.value("mui", 800.0)))
            self.bsat.setValue(float(store.value("bsat", 290.0)))
            self.preset_name.setText(str(store.value("presetName", "")))
            self.r_winding.setValue(float(store.value("rWinding", 0.0)))
            self.i2_chan.setCurrentIndex(
                min(max(0, int(store.value("i2", 0))), self.i2_chan.count() - 1))
            self.n2.setValue(int(store.value("n2", 1)))
            self.i3_chan.setCurrentIndex(
                min(max(0, int(store.value("i3", 0))), self.i3_chan.count() - 1))
            self.n3.setValue(int(store.value("n3", 1)))
            self.raw.setChecked(as_bool(store.value("raw"), False))
            self.auto.setChecked(as_bool(store.value("auto"), False))
            self.trail.setChecked(as_bool(store.value("trail"), False))
            self.cursors.setChecked(as_bool(store.value("cursors"), True))
            self.interval.setValue(min(max(1, int(store.value("interval", 5))), 60))
        except (TypeError, ValueError):
            pass
        finally:
            for widget in tracked:
                widget.blockSignals(False)
        store.endGroup()
        self._toggle_dims()
        if fresh:
            # First run: align μi/Bsat with the default preset (as the Tk
            # tab does on build) instead of keeping the widget defaults.
            self._on_material()
        self._retime()

    def _on_material(self):
        """Fill μi/Bsat (+ stored geometry) from the selected preset."""
        entry = _get_material(self.material.currentText())
        if entry is None:
            return
        for widget in (self.material, self.mui, self.bsat, self.od, self.odim,
                       self.ht, self.area, self.length, self.turns,
                       self.dim_mode, self.preset_name):
            widget.blockSignals(True)
        try:
            if entry.get("mu_i") is not None:
                self.mui.setValue(float(entry["mu_i"]))
            if entry.get("bsat_mT") is not None:
                self.bsat.setValue(float(entry["bsat_mT"]))
            loaded = []
            for key, widget, factor in (("OD_mm", self.od, 1.0),
                                        ("ID_mm", self.odim, 1.0),
                                        ("HT_mm", self.ht, 1.0),
                                        ("Ae_cm2", self.area, 100.0),
                                        ("le_cm", self.length, 10.0)):
                if entry.get(key) is not None:
                    widget.setValue(float(entry[key]) * factor)
                    loaded.append(key)
            if entry.get("N") is not None:
                self.turns.setValue(int(entry["N"]))
            if entry.get("dim_mode") in ("toroid", "direct"):
                self.dim_mode.setCurrentIndex(
                    0 if entry["dim_mode"] == "toroid" else 1)
            if loaded:
                self.notify(f"Preset loaded: {self.material.currentText()} "
                            f"(+ {', '.join(loaded)})")
        except (TypeError, ValueError):
            pass
        finally:
            for widget in (self.material, self.mui, self.bsat, self.od,
                           self.odim, self.ht, self.area, self.length,
                           self.turns, self.dim_mode, self.preset_name):
                widget.blockSignals(False)
        self._toggle_dims()
        self._save_setup()

    def save_preset(self):
        """Save μi/Bsat + current geometry as a named material preset."""
        name = self.preset_name.text().strip() or self.material.currentText().strip()
        if not name:
            self.notify("Enter a preset name first")
            return
        if name in BUILTIN_MATERIAL_NAMES:
            self.notify(f"'{name}' is a built-in, choose a different name")
            return
        entry = {"mu_i": self.mui.value(), "bsat_mT": self.bsat.value(),
                 "desc": f"User: μi={self.mui.value():.0f}, "
                         f"Bsat={self.bsat.value():.0f} mT"}
        if self.dim_mode.currentIndex() == 0:
            entry.update({"OD_mm": self.od.value(), "ID_mm": self.odim.value(),
                          "HT_mm": self.ht.value(), "dim_mode": "toroid"})
        else:
            entry.update({"Ae_cm2": self.area.value() / 100.0,
                          "le_cm": self.length.value() / 10.0,
                          "dim_mode": "direct"})
        entry["N"] = self.turns.value()
        MATERIALS[name] = entry
        if not _save_user_materials():
            self.notify("Preset kept for this session (file save failed)")
            return
        if name not in MATERIAL_NAMES:
            MATERIAL_NAMES.append(name)
        self.material.blockSignals(True)
        try:
            if self.material.findText(name) < 0:
                self.material.addItem(name)
            self.material.setCurrentText(name)
        finally:
            self.material.blockSignals(False)
        self._save_setup()
        self.notify(f"Preset saved: {name}")

    def run(self):
        if self.pending or app_state.is_logging_active:
            return
        try:
            ae, le, geom_label = self._geometry_si()
        except ValueError as error:
            self.notify(str(error))
            return
        self.pending = True
        i2 = None if self.i2_chan.currentIndex() == 0 else self.i2_chan.currentText()
        i3 = None if self.i3_chan.currentIndex() == 0 else self.i3_chan.currentText()
        r_winding = self.r_winding.value() or None
        args = (self.voltage.currentText(), self.current.currentText(),
                self.turns.value(), ae, le, self.raw.isChecked(),
                self.deskew.value(), i2, self.n2.value(), i3,
                self.n3.value(), r_winding)
        values = (geom_label, self.material.currentText(), ae, le,
                  self.mui.value(), self.bsat.value())

        def done(payload):
            self.pending = False
            if isinstance(payload, Exception):
                self.notify(f"Magnetics: {payload}")
                return
            result = payload
            self.last = result
            self._last_ae, self._last_le = ae, le
            self._last_bsat = self.bsat.value()
            decomp = result.get("decomp", {})
            headline = (f"Bpk {result['B_peak_mT']:.3g} mT   "
                        f"Hpk {result['H_peak']:.4g} A/m   "
                        f"L {decomp.get('L_true_peak_uH', float('nan')):.4g} µH   "
                        f"f {result['f_fund_kHz']:.4g} kHz")
            self.headline.setText(headline)
            self._render(result)
            self._render_details(result, values)

        self.submit(lambda: magnetics(self.backend._connected(), *args), done)

    def _render(self, result):
        from matplotlib import colormaps
        t_us = np.asarray(result["t"], float) * 1e6
        v, i = np.asarray(result["V"], float), np.asarray(result["I"], float)
        b_mt = np.asarray(result["B"], float) * 1e3
        h = np.asarray(result["H"], float)
        mu_r = np.asarray(result["mu_r"], float)
        l_uh = np.asarray(result["L_H"], float) * 1e6
        mu_diff = np.asarray(result["mu_diff"], float)
        phi_uwb = np.asarray(result["B"], float) * self._last_ae * 1e6
        bsat = self._last_bsat
        for axes in self._plot_axes:
            axes.clear()
            axes.set_facecolor("#101722")
            axes.grid(True, color="#445469", alpha=0.5)
        self._hover = {"t_us": t_us, "V": v, "I": i, "B_mT": b_mt, "H": h,
                       "mu_r": mu_r, "L_uH": l_uh, "Phi_uWb": phi_uwb}
        self.ax_vi.plot(t_us, v, color=C_V, linewidth=1.2, label="V")
        self.ax_vi.set_xlabel("Time (µs)", color="#e5edf6", fontsize=7)
        self.ax_vi.set_ylabel("V (V)", color=C_V, fontsize=7)
        self.ax_vi2.clear()
        self.ax_vi2.plot(t_us, i, color=C_I, linewidth=1.2, label="I")
        self.ax_vi2.set_ylabel("I (A)", color=C_I, fontsize=7)
        self.ax_vi.set_title("Primary Voltage & Current", color="#e5edf6", fontsize=8)
        if self.trail.isChecked():
            self.history.append((h[::max(1, len(h) // 5000)],
                                 b_mt[::max(1, len(b_mt) // 5000)]))
            self.history = self.history[-30:]
        else:
            self.history = [(h, b_mt)]
        if len(self.history) > 1:
            cmap = colormaps["plasma"]
            for idx, (old_h, old_b) in enumerate(self.history[:-1]):
                self.ax_bh.plot(old_h, old_b, color=cmap(idx / (len(self.history) - 2 + 1e-6)),
                                linewidth=1.3, alpha=0.7)
        self.ax_bh.plot(h, b_mt, color="yellow", linewidth=1.6, alpha=0.95)
        self.ax_bh.set_xlabel("H (A/m)", color="#e5edf6", fontsize=7)
        self.ax_bh.set_ylabel("B (mT)", color="#e5edf6", fontsize=7)
        self.ax_bh.set_title("B–H Hysteresis Loop", color="#e5edf6", fontsize=8)
        finite = np.isfinite(b_mt) & np.isfinite(mu_diff)
        self.ax_mud.plot(b_mt[finite], mu_diff[finite], color="#b44fff",
                         linewidth=1.0, alpha=0.9)
        self.ax_mud.set_xlabel("B (mT)", color="#e5edf6", fontsize=7)
        self.ax_mud.set_ylabel("μdiff", color="#e5edf6", fontsize=7)
        self.ax_mud.set_title("Differential Permeability", color="#e5edf6", fontsize=8)
        self.ax_b.plot(t_us, b_mt, color=C_B, linewidth=1.2)
        if bsat and bsat > 0:
            self.ax_b.axhline(bsat, color="#ff4444", linewidth=0.8,
                              linestyle=":", alpha=0.7)
            self.ax_b.axhline(-bsat, color="#ff4444", linewidth=0.8,
                              linestyle=":", alpha=0.7)
            self.ax_b.text(t_us[0], bsat, f" Bsat {bsat:g} mT", color="#ff4444",
                           fontsize=7, va="bottom")
        self.ax_b.set_xlabel("Time (µs)", color="#e5edf6", fontsize=7)
        self.ax_b.set_ylabel("B (mT)", color=C_B, fontsize=7)
        self.ax_b.set_title("Magnetic Flux Density B(t)", color="#e5edf6", fontsize=8)
        self.ax_h.plot(t_us, h, color=C_H, linewidth=1.2)
        self.ax_h.set_xlabel("Time (µs)", color="#e5edf6", fontsize=7)
        self.ax_h.set_ylabel("H (A/m)", color=C_H, fontsize=7)
        self.ax_h.set_title("Magnetic Field Intensity H(t)", color="#e5edf6", fontsize=8)
        self.ax_l.plot(t_us, l_uh, color="#ff4d8d", linewidth=1.0, alpha=0.9)
        self.ax_l.set_xlabel("Time (µs)", color="#e5edf6", fontsize=7)
        self.ax_l.set_ylabel("L (µH)", color="#e5edf6", fontsize=7)
        self.ax_l.set_title("Apparent Inductance L(t)", color="#e5edf6", fontsize=8)
        self.ax_mu.plot(t_us, mu_r, color="#b44fff", linewidth=1.0, alpha=0.9)
        self.ax_mu.set_xlabel("Time (µs)", color="#e5edf6", fontsize=7)
        self.ax_mu.set_ylabel("μr'", color="#e5edf6", fontsize=7)
        self.ax_mu.set_title("Apparent Permeability μr'(t)", color="#e5edf6", fontsize=8)
        self.ax_bphi.plot(t_us, b_mt, color=C_B, linewidth=1.2, label="B")
        self.ax_bphi.set_xlabel("Time (µs)", color="#e5edf6", fontsize=7)
        self.ax_bphi.set_ylabel("B (mT)", color=C_B, fontsize=7)
        self.ax_phi2.clear()
        self.ax_phi2.plot(t_us, phi_uwb, color=C_H, linewidth=1.2,
                          linestyle="--", label="Φ")
        self.ax_phi2.set_ylabel("Φ (µWb)", color=C_H, fontsize=7)
        self.ax_bphi.set_title("B(t) & Flux Φ(t)", color="#e5edf6", fontsize=8)
        self.ax_bi.plot(i, b_mt, color=C_B, linewidth=1.0, alpha=0.9)
        self.ax_bi.set_xlabel("I (A)", color="#e5edf6", fontsize=7)
        self.ax_bi.set_ylabel("B (mT)", color="#e5edf6", fontsize=7)
        self.ax_bi.set_title("B vs I", color="#e5edf6", fontsize=8)
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _render_details(self, result, values):
        geom_label, material, ae, le, mui, bsat = values
        decomp = result.get("decomp", {})
        al = AL_from_geometry(mui, ae, le)

        def fmt(value, digits=4):
            return "—" if value is None or not math.isfinite(value) else f"{value:.{digits}g}"

        mode = ("open-secondary" if decomp.get("open_secondary", True)
                else f"loaded N2={decomp.get('N2', '?')} N3={decomp.get('N3', '?')}")
        lines = [
            f"Core: {geom_label}  N={self.turns.value()}  {material}  ({mode})",
            f"Bpk {fmt(result['B_peak_mT'])} mT  Hpk {fmt(result['H_peak'])} A/m  "
            f"Br {fmt(result['Br_mT'])} mT  Hc {fmt(result['Hc_Am'])} A/m",
            f"μr'@peak {fmt(result['mu_at_peak'])}  Pavg {fmt(result['P_avg_W'])} W  "
            f"f {fmt(result['f_fund_kHz'])} kHz",
            f"L peak {fmt(decomp.get('L_true_peak_uH', float('nan')))} µH "
            f"(phasor {fmt(decomp.get('L_phasor_uH', float('nan')))} / "
            f"slope {fmt(decomp.get('L_slope_uH', float('nan')))} / "
            f"energy {fmt(decomp.get('L_energy_uH', float('nan')))} / "
            f"harmfit {fmt(decomp.get('L_harmfit_uH', float('nan')))} / "
            f"μ-model {fmt(decomp.get('L_mu_uH', float('nan')))})",
            f"Reluctance {fmt(decomp.get('reluc_true_MA', float('nan')))} MA/Wb  "
            f"AL≈{fmt(al)} nH/N² (μi={mui:g})",
            f"Loss: Ptot {fmt(decomp.get('P_total_W', float('nan')))} W  "
            f"Pcu {fmt(decomp.get('P_cu_W', float('nan')))} W  "
            f"Pcore {fmt(decomp.get('P_core_W', float('nan')))} W  "
            f"({fmt(decomp.get('P_core_density_kWm3', float('nan')))} kW/m³)",
        ]
        self.details.setPlainText("\n".join(lines))

    def _on_hover(self, event):
        if (not self.cursors.isChecked() or self._hover is None
                or event.inaxes is None or event.xdata is None):
            return
        try:
            cache = self._hover
            if event.inaxes in (self.ax_bh, self.ax_bi):
                x, y = (cache["H"], cache["B_mT"]) if event.inaxes is self.ax_bh \
                    else (cache["I"], cache["B_mT"])
                idx = int(np.argmin((x - event.xdata) ** 2 + (y - event.ydata) ** 2))
                self.cursor.setText(
                    f"t {cache['t_us'][idx]:.2f} µs   I {cache['I'][idx]:.4g} A   "
                    f"H {cache['H'][idx]:.4g} A/m   B {cache['B_mT'][idx]:.4g} mT")
            else:
                idx = int(np.argmin(np.abs(cache["t_us"] - event.xdata)))
                self.cursor.setText(
                    f"t {cache['t_us'][idx]:.2f} µs   V {cache['V'][idx]:.4g} V   "
                    f"I {cache['I'][idx]:.4g} A   B {cache['B_mT'][idx]:.4g} mT   "
                    f"H {cache['H'][idx]:.4g} A/m   μr' {cache['mu_r'][idx]:.4g}   "
                    f"L {cache['L_uH'][idx]:.4g} µH   Φ {cache['Phi_uWb'][idx]:.4g} µWb")
        except (TypeError, ValueError, IndexError):
            pass

    def show_decomp(self):
        """Winding-current decomposition and loss separation (Phase 2)."""
        if self.last is None:
            self.notify("Run a measurement before opening decomposition")
            return
        result, decomp = self.last, self.last.get("decomp", {})

        def fmt(value, digits=4):
            return "—" if value is None or not math.isfinite(value) else f"{value:.{digits}g}"

        per_harm = "\n".join(
            f"  n={n}  {freq:.1f} Hz  L={lux:.3f} µH (|V|={mag:.3f} V)"
            for n, freq, lux, mag in decomp.get("L_per_harmonic", [])[:8])
        dialog = QDialog(self)
        dialog.setWindowTitle("Magnetics decomposition")
        dialog.resize(620, 520)
        layout = QVBoxLayout(dialog)
        text = readout()
        text.setPlainText("\n".join([
            f"Mode: {'open-secondary' if decomp.get('open_secondary', True) else 'loaded'}"
            f"   cycles={decomp.get('n_cycles', '—')}   f={fmt(decomp.get('f_fund_Hz', float('nan')))} Hz",
            f"I_mag ripple {fmt(decomp.get('Imag_ripple_A', float('nan')))} A   "
            f"I1_rms {fmt(decomp.get('I1_rms_A', float('nan')))} A",
            f"Phase vs V: I1 {fmt(decomp.get('phi_I1_deg', float('nan')))}°  "
            f"Imag {fmt(decomp.get('phi_Imag_deg', float('nan')))}°  "
            f"I2 {fmt(decomp.get('phi_I2_deg', float('nan')))}°  "
            f"I3 {fmt(decomp.get('phi_I3_deg', float('nan')))}°",
            f"Phasor power: P1 {fmt(decomp.get('P1_phasor_W', float('nan')))} W  "
            f"P2 {fmt(decomp.get('P2_phasor_W', float('nan')))} W  "
            f"P3 {fmt(decomp.get('P3_phasor_W', float('nan')))} W",
            f"L methods (µH): true {fmt(decomp.get('L_true_peak_uH', float('nan')))}  "
            f"phasor {fmt(decomp.get('L_phasor_uH', float('nan')))}  "
            f"slope {fmt(decomp.get('L_slope_uH', float('nan')))}",
            f"  energy {fmt(decomp.get('L_energy_uH', float('nan')))}  "
            f"μ-model {fmt(decomp.get('L_mu_uH', float('nan')))}  "
            f"harmfit {fmt(decomp.get('L_harmfit_uH', float('nan')))}",
            "Per-harmonic L:" if per_harm else "Per-harmonic L: —",
            per_harm,
            f"μ': {fmt(decomp.get('mu_prime', float('nan')))}  "
            f"μ'': {fmt(decomp.get('mu_dbl_prime', float('nan')))}  "
            f"tanδ {fmt(decomp.get('tan_delta', float('nan')))}  "
            f"μr'@peak {fmt(result['mu_at_peak'])}",
            f"Loss: Ptot {fmt(decomp.get('P_total_W', float('nan')))} W  "
            f"Pcu {fmt(decomp.get('P_cu_W', float('nan')))} W  "
            f"Pcore {fmt(decomp.get('P_core_W', float('nan')))} W  "
            f"({fmt(decomp.get('P_core_density_kWm3', float('nan')))} kW/m³)",
            f"BH smoothing: {decomp.get('bh_smooth_factor', '—')}",
        ]))
        layout.addWidget(text)
        self.decomp_dialog = dialog
        dialog.show()

    def export_csv(self):
        """Export time series + scalars (per-run, Qt convention)."""
        import csv
        import os
        if self.last is None:
            self.notify("Run a measurement before exporting")
            return
        result, decomp = self.last, self.last.get("decomp", {})
        os.makedirs("oszi_csv", exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export magnetics CSV",
            f"oszi_csv/magnetics_{datetime.now():%Y%m%d_%H%M%S}.csv",
            "CSV (*.csv)")
        if not path:
            return
        n = len(result["t"])
        stride = max(1, n // 100000)
        sel = slice(0, n, stride)
        t_us = (np.asarray(result["t"], float) * 1e6)[sel]
        cols = {"V (V)": np.asarray(result["V"], float)[sel],
                "I (A)": np.asarray(result["I"], float)[sel],
                "B (mT)": (np.asarray(result["B"], float) * 1e3)[sel],
                "H (A/m)": np.asarray(result["H"], float)[sel],
                "mu_r": np.asarray(result["mu_r"], float)[sel],
                "L (uH)": (np.asarray(result["L_H"], float) * 1e6)[sel]}
        with open(path, "w", newline="", encoding="utf-8") as output:
            output.write(f"# Magnetics {datetime.now().isoformat()}  rows={len(t_us)}"
                         f"{' (decimated)' if stride > 1 else ''}\n")
            output.write(f"# N={self.turns.value()} material={self.material.currentText()} "
                         f"Bpk_mT={result['B_peak_mT']:.6g} Hpk={result['H_peak']:.6g} "
                         f"L_uH={decomp.get('L_true_peak_uH', float('nan')):.6g} "
                         f"f_kHz={result['f_fund_kHz']:.6g}\n")
            writer = csv.writer(output)
            writer.writerow(["t_us", *cols])
            writer.writerows(zip(t_us, *cols.values()))
        self.notify(f"Magnetics exported: {path} ({len(t_us)} rows)")

    def save_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save plot",
                                              "oszi_csv/magnetics.png", "PNG (*.png)")
        if path:
            self.figure.savefig(path, dpi=150, facecolor=self.figure.get_facecolor())

    def clear_trail(self):
        self.history.clear()
        for axes in self._plot_axes:
            axes.clear()
        self.ax_vi2.clear()
        self.ax_phi2.clear()
        self.canvas.draw_idle()
