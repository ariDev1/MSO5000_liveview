"""GPU 3D spectrum-history view (pyqtgraph OpenGL).

Why this exists: matplotlib's mplot3d renders on the CPU, which costs
~600 ms per frame at 40 traces x 250 points (~1.5 fps rotation) for a
per-segment collection and still ~100 ms per frame for plain lines. This
module draws the same waterfall as GPU vertex buffers instead: each data
update only re-uploads a few kilobytes, and rotation/pan/zoom then run at
display refresh with no per-frame Python work.

Backend selection (see ``select_backend``): ``MSO5000_3D=gl|mpl|auto``
(default ``auto`` = GPU when pyqtgraph + PyOpenGL import, else matplotlib).
``MSO5000_3D=gl`` raises a clear error when the GPU stack is missing so a
broken install is visible instead of silently slow.
"""

import math
import os

import numpy as np

try:
    import pyqtgraph as pg
    import pyqtgraph.opengl as gl
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QVector3D
    from PySide6.QtWidgets import (
        QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton,
        QSpinBox, QVBoxLayout, QWidget,
    )
    _IMPORT_ERROR = None
    GL_AVAILABLE = True
except Exception as exc:  # pragma: no cover - import probe
    pg = None
    gl = None
    _IMPORT_ERROR = exc
    GL_AVAILABLE = False

if GL_AVAILABLE:
    from matplotlib import colormaps as _colormaps

    # Shared viridis table so GPU colors match the matplotlib fallback
    # exactly for the same normalized level.
    VIRIDIS_LUT = _colormaps["viridis"](np.linspace(0.0, 1.0, 256)).astype(
        np.float32
    )
else:  # pragma: no cover - import probe
    VIRIDIS_LUT = None


# Platforms where Qt cannot provide GL at all (headless CI, offscreen
# testing): QOpenGLWidget reports "not supported on this platform" there,
# so auto mode honestly falls back to matplotlib instead of picking a
# backend that can neither render nor tear down cleanly.
_HEADLESS_PLATFORMS = ("offscreen", "minimal")


def select_backend():
    """Return 'gl' or 'mpl' honoring MSO5000_3D (gl|mpl|auto)."""
    want = os.environ.get("MSO5000_3D", "auto").strip().lower()
    if want == "gl":
        if not GL_AVAILABLE:
            raise RuntimeError(
                "MSO5000_3D=gl requested but the GPU stack is missing "
                f"({_IMPORT_ERROR}); pip install pyqtgraph PyOpenGL "
                "or use MSO5000_3D=mpl."
            )
        return "gl"
    if want == "mpl":
        return "mpl"
    if want not in ("auto", ""):
        raise ValueError("MSO5000_3D must be one of: gl, mpl, auto")
    if not GL_AVAILABLE:
        return "mpl"
    if os.environ.get("QT_QPA_PLATFORM", "").strip().lower() in _HEADLESS_PLATFORMS:
        return "mpl"
    return "gl"


_shared_stage = None


def get_shared_stage():
    """Return the single 3D history window (created on first use)."""
    global _shared_stage
    if _shared_stage is None:
        if not GL_AVAILABLE:
            raise RuntimeError(
                "GPU 3D view needs pyqtgraph + PyOpenGL "
                f"({_IMPORT_ERROR}); pip install pyqtgraph PyOpenGL "
                "or run with MSO5000_3D=mpl."
            )
        _shared_stage = SharedHistoryStage()
    return _shared_stage


def drop_shared_stage():
    """Forget the shared window (tests only)."""
    global _shared_stage
    _shared_stage = None


def format_hz(value):
    """Compact frequency axis label (view-only)."""
    aval = abs(float(value))
    if aval >= 1e6:
        return f"{value / 1e6:.3g} MHz"
    if aval >= 1e3:
        return f"{value / 1e3:.3g} kHz"
    return f"{value:.3g} Hz"


def prepare_values(raw_rows, use_log):
    """Apply optional Log-Z with a self-healing fallback.

    Returns (values, log_active, scale_note). Log is only meaningful for
    positive linear-scale data; all-non-positive input (e.g. dB spectra
    with Log Z ticked) would clip every point to one flat level and kill
    the view, so linear data is returned with an explanatory note instead.
    """
    rows = [np.asarray(row, dtype=float) for row in raw_rows]
    if use_log and any(bool((row > 0).any()) for row in rows):
        return [np.log10(np.clip(row, 1e-12, None)) for row in rows], True, ""
    if use_log:
        return rows, False, " · Log Z needs positive data — linear shown"
    return rows, False, ""


def range_hint(vmin, vmax, use_log):
    """Short hint when a linear Z scale crushes the data flat.

    Returns "" when the scale is fine or already logarithmic.
    """
    if use_log:
        return ""
    try:
        vmin_f, vmax_f = float(vmin), float(vmax)
    except (TypeError, ValueError):
        return ""
    if not vmin_f > 0 or not vmax_f > vmin_f:
        return ""
    ratio = vmax_f / vmin_f
    if ratio > 1e6:
        decades = f"{math.log10(ratio):.0f}" if math.isfinite(ratio) else "many"
        return f" · Z spans {decades} decades — try Log Z"
    return ""


if GL_AVAILABLE:  # pragma: no cover - needs a display/GL context to run

    _BG = "#101722"  # match the Qt Plot facecolor
    _GRID_COLOR = (255, 255, 255, 40)
    _CUBE_COLOR = (255, 255, 255, 70)
    _TEXT_COLOR = (200, 200, 200, 230)
    # Orbit pivot: the cube center (data are normalized to the unit cube).
    # The GLViewWidget default pivots at the origin corner, which swings
    # the cube wildly and makes navigation feel broken.
    _HOME_CENTER = (0.5, 0.5, 0.5)
    _HOME_DISTANCE = 2.6
    _HOME_ELEVATION = 18
    _HOME_AZIMUTH = -60

    # 12 edges of the unit cube as endpoint pairs (static reference frame).
    _CUBE_EDGES = (
        ((0, 0, 0), (1, 0, 0)), ((1, 0, 0), (1, 1, 0)),
        ((1, 1, 0), (0, 1, 0)), ((0, 1, 0), (0, 0, 0)),
        ((0, 0, 1), (1, 0, 1)), ((1, 0, 1), (1, 1, 1)),
        ((1, 1, 1), (0, 1, 1)), ((0, 1, 1), (0, 0, 1)),
        ((0, 0, 0), (0, 0, 1)), ((1, 0, 0), (1, 0, 1)),
        ((1, 1, 0), (1, 1, 1)), ((0, 1, 0), (0, 1, 1)),
    )

    class SpectrumGLView(QWidget):
        """GPU waterfall area for SurfaceHistory (same dialog, same data).

        Data are normalized to a unit cube (mplot3d autoscales each axis
        the same way), so the camera never depends on raw Hz/level
        magnitudes and real axis ranges are shown in the info line plus
        the static 2D color legend (zero per-frame cost, unlike a 3D
        color bar that re-renders every rotation frame).
        """

        def __init__(self, parent=None):
            super().__init__(parent)
            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)

            left = QVBoxLayout()
            left.setContentsMargins(0, 0, 0, 0)
            left.setSpacing(4)

            self.view = gl.GLViewWidget()
            self.view.setBackgroundColor(_BG)
            self.view.setCameraPosition(
                pos=QVector3D(*_HOME_CENTER),
                distance=_HOME_DISTANCE,
                elevation=_HOME_ELEVATION,
                azimuth=_HOME_AZIMUTH,
            )
            self._grid = gl.GLGridItem(
                size=None, color=_GRID_COLOR, antialias=True,
            )
            self._grid.setSize(x=1.0, y=1.0, z=1.0)
            self._grid.setSpacing(x=0.1, y=0.1, z=1.0)
            self.view.addItem(self._grid)
            # Static unit-cube frame + axis/tick captions (screen-space
            # text stays readable at any rotation; positions are updated
            # per redraw in _update_axes).
            cube_pos = np.array(
                [p for edge in _CUBE_EDGES for p in edge],
                dtype=np.float32,
            )
            self._cube = gl.GLLinePlotItem(
                pos=cube_pos, mode="lines", color=_CUBE_COLOR,
                width=1.0, glOptions="translucent",
            )
            self.view.addItem(self._cube)
            self._texts = {}
            for key in ("x0", "x1", "x2", "y0", "y1",
                        "z0", "z1", "z2", "tx", "ty", "tz"):
                item = gl.GLTextItem(color=_TEXT_COLOR)
                self.view.addItem(item)
                self._texts[key] = item
            left.addWidget(self.view, 1)

            bottom = QHBoxLayout()
            bottom.setContentsMargins(0, 0, 0, 0)
            self.info = QLabel("GPU view — no data yet")
            self.info.setObjectName("surfaceGlInfo")
            bottom.addWidget(self.info, 1)
            reset = QPushButton("RESET VIEW")
            reset.setToolTip("Restore the default 3D camera.")
            reset.clicked.connect(self.reset_view)
            bottom.addWidget(reset)
            self.spin_button = QPushButton("SPIN")
            self.spin_button.setCheckable(True)
            self.spin_button.setToolTip(
                "Turntable: slowly orbit the cube. Drag to take over.")
            self.spin_button.toggled.connect(self._set_spin)
            bottom.addWidget(self.spin_button)
            self._spin_timer = QTimer(self)
            self._spin_timer.setInterval(40)
            self._spin_timer.timeout.connect(self._spin_step)
            left.addLayout(bottom)

            layout.addLayout(left, 1)

            legend_host = pg.GraphicsLayoutWidget()
            legend_host.setFixedWidth(96)
            legend_host.setBackground(_BG)
            self._bar = pg.ColorBarItem(
                values=(0.0, 1.0),
                colorMap=pg.ColorMap(
                    pos=np.linspace(0.0, 1.0, 256),
                    color=(VIRIDIS_LUT * 255).astype(np.uint8),
                ),
                label="Level",
                width=20,
            )
            legend_host.addItem(self._bar)
            layout.addWidget(legend_host)

            self._mode = None
            self._trace_items = []
            self._surf_item = None

        # -- public API used by SurfaceHistory ---------------------------

        def reset_view(self):
            self.view.setCameraPosition(
                pos=QVector3D(*_HOME_CENTER),
                distance=_HOME_DISTANCE,
                elevation=_HOME_ELEVATION,
                azimuth=_HOME_AZIMUTH,
            )

        def _set_spin(self, on):
            if on:
                self._spin_timer.start()
            else:
                self._spin_timer.stop()

        def _spin_step(self):
            try:
                self.view.orbit(1.5, 0.0)
            except Exception:
                pass

        def set_level_label(self, text):
            # Vertical ColorBarItem carries its label on the 'left' axis
            # (see ColorBarItem.__init__); PlotItem.setLabel needs the
            # axis name and cannot take a bare string.
            self._bar.getAxis("left").setLabel(text)

        def clear(self, note=None):
            self._drop_data_items()
            self.info.setText(note if note is not None else "GPU view — cleared")

        def redraw(self, history, values, *, render_mode, vmin, vmax,
                   level_label, range_hint="", scale_note="", source=""):
            """Re-upload vertex buffers for the current history.

            ``history`` is [(x, y)] rows and ``values`` the matching level
            rows (log already applied by the caller when enabled).
            """
            n = len(history)
            if n == 0:
                self.clear()
                return
            if n < 2 and render_mode == "surface":
                # A single-row mesh has no faces to draw; show lines so
                # the first run is visible instead of an empty cube.
                render_mode = "lines"
            if render_mode != self._mode:
                self._drop_data_items()
                self._mode = render_mode

            xmin = min(float(x[0]) for x, _ in history)
            xmax = max(float(x[-1]) for x, _ in history)
            xspan = (xmax - xmin) or 1.0
            yspan = float(n - 1) or 1.0
            zspan = float(vmax - vmin) or 1.0

            if render_mode == "surface":
                self._draw_surface(history, values, xmin, xspan, yspan,
                                   vmin, zspan)
            else:
                self._draw_traces(history, values, xmin, xspan, yspan,
                                  vmin, zspan,
                                  single_color=(render_mode == "wire"))

            self._update_axes(xmin, xmax, n, vmin, vmax, level_label)
            self._bar.setLevels((float(vmin), float(vmax)))
            self.set_level_label(level_label)
            peak = max(float(np.max(zz)) for zz in values)
            head = f"{source} · " if source else ""
            self.info.setText(
                f"{head}X {format_hz(xmin)}–{format_hz(xmax)}  ·  "
                f"{n} traces (older → newer)  ·  "
                f"Z peak {peak:.3g} {level_label}{range_hint}{scale_note}"
            )
            self.info.setToolTip(
                "Drag = rotate · wheel = zoom · right-drag = pan")

        def _update_axes(self, xmin, xmax, n, vmin, vmax, level_label):
            """Refresh cube captions with real data ranges (view-only)."""
            mid_hz = format_hz(0.5 * (xmin + xmax))
            zmid = 0.5 * (vmin + vmax)
            labels = {
                "x0": ((0.0, -0.045, 0.0), format_hz(xmin)),
                "x1": ((0.5, -0.045, 0.0), mid_hz),
                "x2": ((1.0, -0.045, 0.0), format_hz(xmax)),
                "y0": ((0.0, 0.0, 0.0), "older"),
                "y1": ((0.0, 1.0, 0.0), "newer"),
                "z0": ((-0.045, 0.0, 0.0), f"{vmin:.3g}"),
                "z1": ((-0.045, 0.0, 0.5), f"{zmid:.3g}"),
                "z2": ((-0.045, 0.0, 1.0), f"{vmax:.3g}"),
                "tx": ((0.5, -0.10, 0.0), "Frequency (Hz)"),
                "ty": ((-0.10, 0.5, 0.0), "Acquisition"),
                "tz": ((-0.045, 0.0, 1.07), level_label),
            }
            for key, (pos, text) in labels.items():
                self._texts[key].setData(pos=pos, text=text)

        # -- internals ---------------------------------------------------

        def _drop_data_items(self):
            for item in self._trace_items:
                try:
                    self.view.removeItem(item)
                except Exception:
                    pass
            self._trace_items = []
            if self._surf_item is not None:
                try:
                    self.view.removeItem(self._surf_item)
                except Exception:
                    pass
                self._surf_item = None

        def _row_norm(self, x, zz, idx, xmin, xspan, yspan, vmin, zspan):
            xn = (np.asarray(x, dtype=np.float64) - xmin) / xspan
            pos = np.empty((len(xn), 3), dtype=np.float32)
            pos[:, 0] = xn
            pos[:, 1] = float(idx) / yspan
            pos[:, 2] = (np.asarray(zz, dtype=np.float64) - vmin) / zspan
            return pos

        def _draw_traces(self, history, values, xmin, xspan, yspan,
                         vmin, zspan, single_color):
            n = len(history)
            if len(self._trace_items) != n or self._surf_item is not None:
                self._drop_data_items()
                for _ in range(n):
                    item = gl.GLLinePlotItem(glOptions="translucent")
                    self.view.addItem(item)
                    self._trace_items.append(item)
            for idx, ((x, _), zz) in enumerate(zip(history, values)):
                pos = self._row_norm(x, zz, idx, xmin, xspan, yspan,
                                     vmin, zspan)
                # Per-point level colors in both modes (free on the GPU):
                # wire rows share the legend scale like lines do, only
                # thinner, slightly transparent, without the newest-bold.
                zt = np.clip(
                    (np.asarray(zz, dtype=np.float64) - vmin) / zspan,
                    0.0, 1.0,
                )
                color = VIRIDIS_LUT[(zt * 255.0).astype(int)].copy()
                if single_color:
                    color[:, 3] = 0.8
                    width = 1.0
                else:
                    width = 2.0 if idx == n - 1 else 1.1
                self._trace_items[idx].setData(
                    pos=pos, color=color, width=width,
                )

        def _draw_surface(self, history, values, xmin, xspan, yspan,
                          vmin, zspan):
            # GLSurfacePlotItem wants z/colors shaped (len(x), len(y)).
            n = len(history)
            xn = (np.asarray(history[0][0], dtype=np.float64) - xmin) / xspan
            yn = np.arange(n, dtype=np.float64) / yspan
            grid = np.vstack([np.asarray(zz, dtype=np.float64)
                              for zz in values])
            zn = (grid - vmin) / zspan
            # Flat (N,4) in x-major order to match the flattened (m,n,3)
            # vertex array MeshData indexes with flat face indices; a
            # (len(x),len(y),4) array would misalign.
            cols = np.ascontiguousarray(
                VIRIDIS_LUT[np.clip((zn * 255.0).astype(int), 0, 255)]
                .transpose(1, 0, 2).reshape(-1, 4)
            ).astype(np.float32)
            if self._surf_item is None:
                self._surf_item = gl.GLSurfacePlotItem(
                    x=xn.astype(np.float32),
                    y=yn.astype(np.float32),
                    z=zn.T.astype(np.float32),
                    colors=cols,
                    shader=None, smooth=False, computeNormals=False,
                    glOptions="opaque",
                )
                self.view.addItem(self._surf_item)
            else:
                self._surf_item.setData(
                    x=xn.astype(np.float32),
                    y=yn.astype(np.float32),
                    z=zn.T.astype(np.float32),
                    colors=cols,
                )

else:  # pragma: no cover - import probe

    class SpectrumGLView:  # type: ignore[no-redef]
        """Placeholder that fails loudly when the GPU stack is missing."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "GPU 3D view needs pyqtgraph + PyOpenGL "
                f"({_IMPORT_ERROR}); pip install pyqtgraph PyOpenGL "
                "or run with MSO5000_3D=mpl."
            )

if GL_AVAILABLE:  # pragma: no cover - needs a display/GL context to run

    class SharedHistoryStage(QDialog):
        """Single 3D history window for the whole app (GPU backend).

        Created once and never reparented or duplicated: its GL context,
        shader programs and GPU buffers therefore live exactly once.
        Per-dialog GL widgets rendered every second window blank
        (per-context resources vs process-wide shader caches), so tabs
        share this one instrument screen instead and keep only their data
        models (SurfaceHistory in qt_app/advanced.py). The control bar
        always mirrors the currently shown tab's model.
        """

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Spectrum history · 3D (GPU)")
            self.resize(900, 670)
            layout = QVBoxLayout(self)
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
            apply.clicked.connect(self._controls_changed)
            clear = QPushButton("CLEAR")
            clear.clicked.connect(self._clear_current)
            self.source = QLabel("")
            self.source.setObjectName("surfaceStageSource")
            for widget in (QLabel("Last N"), self.last_n, self.log_z,
                           QLabel("Mode"), self.mode, QLabel("Stride"),
                           self.stride, QLabel("Pts/line"), self.pts,
                           apply, clear):
                bar.addWidget(widget)
            bar.addStretch()
            bar.addWidget(self.source)
            # Controls apply live, like the former per-tab bar.
            self.last_n.valueChanged.connect(
                lambda _v=None: self._controls_changed())
            self.stride.valueChanged.connect(
                lambda _v=None: self._controls_changed())
            self.pts.valueChanged.connect(
                lambda _v=None: self._controls_changed())
            self.log_z.toggled.connect(
                lambda _on=None: self._controls_changed())
            self.mode.currentIndexChanged.connect(
                lambda _i=None: self._controls_changed())
            layout.addLayout(bar)
            self.gl_view = SpectrumGLView()
            layout.addWidget(self.gl_view)
            self.current = None
            self.current_name = ""

        # -- model hosting ------------------------------------------------

        def show_model(self, model, source_name=""):
            """Show this tab's data: load its controls, draw, raise."""
            self._load_model(model, source_name)
            self._redraw_current()
            self.show()
            self.raise_()

        def _load_model(self, model, source_name=""):
            for widget in (self.last_n, self.stride, self.pts,
                           self.log_z, self.mode):
                widget.blockSignals(True)
            try:
                self.last_n.setValue(int(model.max_lines))
                self.log_z.setChecked(bool(model.use_log))
                idx = self.mode.findText(model.render_mode)
                self.mode.setCurrentIndex(idx if idx >= 0 else 0)
                self.stride.setValue(int(model.stride_n))
                self.pts.setValue(int(model.pts_n))
            finally:
                for widget in (self.last_n, self.stride, self.pts,
                               self.log_z, self.mode):
                    widget.blockSignals(False)
            self.current = model
            self.current_name = (
                source_name or getattr(model, "source_name", ""))
            if self.current_name:
                self.setWindowTitle(
                    f"Spectrum history · 3D (GPU) — {self.current_name}")
            self.source.setText(self.current_name)

        def _controls_changed(self, *args):
            model = self.current
            if model is None:
                return
            model.max_lines = max(10, self.last_n.value())
            model.use_log = self.log_z.isChecked()
            model.render_mode = self.mode.currentText()
            model.stride_n = max(1, self.stride.value())
            model.pts_n = max(50, self.pts.value())
            model.history = model.history[-model.max_lines:]
            self._redraw_current()

        def _clear_current(self):
            if self.current is not None:
                self.current.history.clear()
                self.current._seen = 0
            self._redraw_current()

        def _redraw_current(self):
            model = self.current
            if model is None or not model.history:
                self.gl_view.clear(
                    "No spectra recorded yet — press MEASURE or enable Auto")
                return
            raw = [yy for _, yy in model.history]
            values, log_active, scale_note = prepare_values(
                raw, model.use_log)
            stacked = np.concatenate(values)
            vmin, vmax = float(np.min(stacked)), float(np.max(stacked))
            if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
                vmin, vmax = vmin - 0.5, vmax + 0.5
            level_label = "log₁₀(Level)" if log_active else "Level"
            try:
                self.gl_view.redraw(
                    model.history, values, render_mode=model.render_mode,
                    vmin=vmin, vmax=vmax, level_label=level_label,
                    range_hint=range_hint(vmin, vmax, log_active),
                    scale_note=scale_note, source=self.current_name,
                )
            except Exception as error:
                # One bad frame must never break the measurement pipeline.
                try:
                    self.gl_view.info.setText(f"3D error: {error}")
                except Exception:
                    pass

        def closeEvent(self, event):
            self.current = None
            event.accept()
