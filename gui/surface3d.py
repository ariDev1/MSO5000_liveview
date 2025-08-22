# gui/surface3d.py
# 3D surface/waterfall viewer used by Noise Inspector.
# Adds a 'Clear' button to wipe the in-memory history safely.
# Also includes pq3d-style HUD, full-bleed fit, projection toggle, and tunable perspective.
#
# Keys:
#   H — toggle overlay
#   F — toggle full-bleed square fit
#   Z — toggle projection (persp/ortho)
#   - / = — decrease / increase perspective strength (focal_length or dist)
#   L — toggle log-Z
#   M — cycle render mode: lines → wire → surface
#   [ / ] — decrease / increase Last N lines
#   , / . — decrease / increase time stride
#   p / P — decrease / increase target points per line (view-only decimation)
#   C — clear history (same as Clear button)
#
# Mouse:
#   Drag=rotate • Shift+drag=pan • Wheel=zoom
#
# Public API:
#   ensure_surface3d(root)           -> create/show window (idempotent)
#   push_surface_line(y, x=None, t=None) -> append one row (x optional); t in seconds

from collections import deque
import time
import numpy as np
import tkinter as tk
from tkinter import ttk
from cycler import cycler
from matplotlib import cm
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

# ------------------------------- state ---------------------------------------
_surface_state = {
    "window": None,
    "ax": None,
    "canvas": None,
    "history": None,  # deque[(x: np.ndarray, y: np.ndarray, t: float)]
    "t0": None,
    "max_lines": 60,
    "log_z": False,
    # render & perf
    "render_mode": "lines",       # "lines" | "wire" | "surface"
    "t_stride": 1,                 # draw every Nth time-slice (1 = all)
    "target_pts_per_line": 400,    # decimation target along X (view-only)
    "min_redraw_interval": 0.15,
    "last_draw": 0.0,
    # overlay/layout
    "overlay_visible": True,
    "_overlay_artist": None,
    "full_bleed": True,
    "edge_pad": 0.01,
    # projection
    "proj": "persp",             # "persp" | "ortho"
    "focal": 0.75,               # smaller => stronger perspective (if MPL supports it)
    "dist": 7.0,                 # fallback for older MPL (smaller => stronger perspective; default ~10)
    "_proj_supports_focal": None,
}

# ---- 3D look & feel (easy to tweak) ----
CUBE_STYLE = "transparent"   # "transparent" | "black" | "grey"
GRID_ALPHA = 0.18            # grid line opacity (0..1)

# Professional, muted line palette (Tableau/Vega style)
PRO_LINE_PALETTE = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ab",
]

# ------------------------------ public API -----------------------------------
def ensure_surface3d(root):
    st = _surface_state
    if st.get("window") is not None and st["window"].winfo_exists():
        st["window"].deiconify()
        st["window"].lift()
        return st["window"]

    win = tk.Toplevel(root)
    win.title("3D Surface (Waterfall)")
    win.geometry("900x600")
    win.configure(bg="#1a1a1a")

    # Top controls (restored) + Clear button
    bar = tk.Frame(win, bg="#1a1a1a")
    bar.pack(fill="x", padx=8, pady=6)

    ttk.Label(bar, text="Last N:").pack(side="left")
    n_var = tk.IntVar(value=int(st.get("max_lines", 60)))
    ttk.Spinbox(bar, from_=10, to=500, width=5, textvariable=n_var).pack(side="left", padx=(4,10))

    log_var = tk.IntVar(value=1 if st.get("log_z") else 0)
    ttk.Checkbutton(bar, text="Log Z", variable=log_var).pack(side="left", padx=(0,10))

    ttk.Label(bar, text="Mode:").pack(side="left")
    mode_var = tk.StringVar(value=st.get("render_mode", "lines"))
    ttk.Combobox(bar, state="readonly", width=9, textvariable=mode_var,
                 values=["lines", "wire", "surface"]).pack(side="left", padx=(4,10))

    ttk.Label(bar, text="Time stride:").pack(side="left")
    stride_var = tk.IntVar(value=int(st.get("t_stride", 1)))
    ttk.Spinbox(bar, from_=1, to=10, width=4, textvariable=stride_var).pack(side="left", padx=(4,10))

    ttk.Label(bar, text="Pts/line:").pack(side="left")
    tpp_var = tk.IntVar(value=int(st.get("target_pts_per_line", 400)))
    ttk.Spinbox(bar, from_=50, to=2000, width=6, textvariable=tpp_var).pack(side="left", padx=(4,10))

    def apply_opts():
        st["max_lines"] = max(10, int(n_var.get() or 60))
        st["log_z"] = bool(log_var.get())
        st["render_mode"] = mode_var.get()
        st["t_stride"] = max(1, int(stride_var.get() or 1))
        st["target_pts_per_line"] = max(50, int(tpp_var.get() or 400))
        # align deque if changed
        if st.get("history") is not None and st["history"].maxlen != st["max_lines"]:
            st["history"] = deque(list(st["history"]), maxlen=st["max_lines"])
        _redraw()
    ttk.Button(bar, text="Apply", command=apply_opts).pack(side="left", padx=8)

    ttk.Button(bar, text="Clear", command=_clear_history).pack(side="right", padx=8)

    # Figure / 3D axis
    fig = plt.Figure(figsize=(7,4), dpi=100, facecolor="#1a1a1a")
    ax = fig.add_subplot(111, projection='3d')
    _style_3d(ax)
    _apply_projection(ax)

    canvas = FigureCanvasTkAgg(fig, master=win)
    canvas.get_tk_widget().pack(fill="both", expand=True)

    st.update({
        "window": win,
        "ax": ax,
        "canvas": canvas,
        "history": deque(maxlen=st.get("max_lines", 60)),
        "t0": None,
    })

    # Layout/overlay setup
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    _fit_axes_to_window()
    _update_overlay()

    # Events
    fig.canvas.mpl_connect("resize_event", lambda evt: (_fit_axes_to_window(), _update_overlay()))
    fig.canvas.mpl_connect("key_press_event", _on_key)
    # Ensure keyboard focus so '-' '=' etc. work immediately after a click
    def _focus_event(_evt=None):
        try:
            canvas.get_tk_widget().focus_set()
        except Exception:
            pass
    fig.canvas.mpl_connect("button_press_event", _focus_event)
    fig.canvas.mpl_connect("figure_enter_event", _focus_event)

    def on_close():
        win.withdraw()
    win.protocol("WM_DELETE_WINDOW", on_close)

    return win


def push_surface_line(y, x=None, t=None):
    """Append a time-slice (x,y,t) and trigger redraw.
    - y: 1D array of amplitudes (required)
    - x: 1D array of positions; if None, uses arange(len(y))
    - t: seconds; if None, uses time.time()
    """
    st = _surface_state
    if st.get("history") is None:
        return False

    y = np.asarray(y, dtype=float)
    if y.size == 0:
        return False
    if x is None:
        x = np.arange(y.size, dtype=float)
    else:
        x = np.asarray(x, dtype=float)
        if x.size != y.size:
            # simple fallback: create an index axis
            x = np.arange(y.size, dtype=float)

    if t is None:
        t = time.time()
    else:
        t = float(t)

    if st["t0"] is None:
        st["t0"] = t

    st["history"].append((x, y, t))
    # deque length may be changed from UI
    if st["history"].maxlen != st["max_lines"]:
        st["history"] = deque(list(st["history"]), maxlen=st["max_lines"])
    _redraw_throttled()
    return True

# --------------------------- helpers / overlay --------------------------------
def _style_3d(ax):
    """Dark theme + professional palette + configurable cube panes."""
    # Background
    ax.set_facecolor("#0d0d0d")  # figure face stays dark; axes plane very dark
    # Axis labels
    ax.set_xlabel("X (bin / harmonic index)", color="#f0f0f0")
    ax.set_ylabel("Time (s)", color="#f0f0f0")
    ax.set_zlabel("Amplitude", color="#f0f0f0")
    # Ticks
    ax.tick_params(axis='x', colors='#e2e2e2')
    ax.tick_params(axis='y', colors='#e2e2e2')
    ax.tick_params(axis='z', colors='#e2e2e2')

    # Professional line color cycle (used by ax.plot)
    ax.set_prop_cycle(cycler(color=PRO_LINE_PALETTE))

    # Grid (mplot3d uses a private dict; wrap in try for version-compat)
    try:
        for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            axis._axinfo["grid"]["color"] = (1, 1, 1, GRID_ALPHA)
            axis._axinfo["grid"]["linestyle"] = "-"
            axis._axinfo["grid"]["linewidth"] = 0.8
    except Exception:
        ax.grid(True, color=(1, 1, 1, GRID_ALPHA))  # fallback

    # Panes (the three “walls” of the cube)
    # Options: transparent (no fill), black (subtle), grey (default-ish)
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        pane = axis.pane
        if CUBE_STYLE == "transparent":
            pane.fill = False                      # no fill
            pane.set_edgecolor((1, 1, 1, 0.15))    # faint edges
        elif CUBE_STYLE == "black":
            pane.fill = True
            pane.set_facecolor((0, 0, 0, 0.85))    # deep black, slight alpha
            pane.set_edgecolor((1, 1, 1, 0.15))
        else:  # "grey"
            pane.fill = True
            pane.set_facecolor((0.18, 0.18, 0.18, 1.0))
            pane.set_edgecolor((1, 1, 1, 0.15))

    # (Some mpl versions also expose spines; keep them subtle if present)
    for spine in getattr(ax, "spines", {}).values():
        try:
            spine.set_color((1, 1, 1, 0.15))
        except Exception:
            pass

def _apply_projection(ax):
    """Set projection type + strength, detecting focal_length support once."""
    st = _surface_state
    if st.get("_proj_supports_focal") is None:
        # Probe once: try focal_length; if TypeError, we’ll use ax.dist
        try:
            ax.set_proj_type(st.get("proj","persp"), focal_length=float(st.get("focal",0.75)))
            st["_proj_supports_focal"] = True
        except TypeError:
            st["_proj_supports_focal"] = False
    # Apply current settings
    if st["_proj_supports_focal"]:
        ax.set_proj_type(st.get("proj","persp"), focal_length=float(st.get("focal",0.75)))
    else:
        ax.set_proj_type(st.get("proj","persp"))
        try:
            ax.dist = float(st.get("dist", 7.0))
        except Exception:
            pass

def _fit_axes_to_window():
    st = _surface_state
    ax = st.get("ax")
    canvas = st.get("canvas")
    if ax is None or canvas is None:
        return
    fig = canvas.figure
    pad = float(st.get("edge_pad", 0.01))
    if not st.get("full_bleed", True):
        ax.set_position([pad, pad, 1 - 2*pad, 1 - 2*pad])
        return
    w_in, h_in = fig.get_size_inches()
    w, h = float(w_in), float(h_in)
    if w <= 0 or h <= 0:
        ax.set_position([pad, pad, 1 - 2*pad, 1 - 2*pad]); return
    if w > h:
        side = h / w
        x0 = (1.0 - side) * 0.5
        ax.set_position([x0 + pad, pad, side - 2*pad, 1 - 2*pad])
    else:
        side = w / h
        y0 = (1.0 - side) * 0.5
        ax.set_position([pad, y0 + pad, 1 - 2*pad, side - 2*pad])

def _overlay_text():
    st = _surface_state
    # Show focal_length or dist depending on support
    if st.get("_proj_supports_focal", False):
        proj_extra = f"level {st.get('focal', 0.75):.2f} (-/=)"
    else:
        proj_extra = f"dist {st.get('dist', 7.0):.1f} (-/=)"
    lines = [
        f"Mode: {st.get('render_mode','lines')}   (M)",
        f"Z: {'log' if st.get('log_z') else 'linear'}   (L)",
        f"Last N: {st.get('max_lines',60)}   stride: {st.get('t_stride',1)}   ([ / ] , / .)",
        f"Pts/line: ~{st.get('target_pts_per_line',400)}   (p / P)",
        f"Layout: {'full-bleed' if st.get('full_bleed',True) else 'fit-all'}   (F)",
        f"Proj: {st.get('proj','persp')}   (Z)  —  {proj_extra}",
        "H: toggle help overlay",
        "Mouse: drag=rotate  •  Shift+drag=pan  •  Wheel=zoom",
    ]
    return "\n".join(lines)

def _update_overlay():
    st = _surface_state
    canvas = st.get("canvas")
    if canvas is None:
        return
    fig = canvas.figure
    if not st.get("overlay_visible", True):
        art = st.get("_overlay_artist")
        if art is not None:
            try: art.remove()
            except Exception: pass
        st["_overlay_artist"] = None
        fig.canvas.draw_idle()
        return
    txt = _overlay_text()
    art = st.get("_overlay_artist")
    if art is None:
        st["_overlay_artist"] = fig.text(
            0.015, 0.985, txt,
            va="top", ha="left",
            color="white",
            fontsize=9,
            family="monospace",
            linespacing=1.25,
            bbox=dict(
                facecolor=(0,0,0,0.55),
                edgecolor=(1,1,1,0.18),
                boxstyle="round,pad=0.35")
        )
    else:
        art.set_text(txt)
    fig.canvas.draw_idle()

def _clear_history():
    """Clear only the viewer's in-memory history and reset t0.
    Does NOT touch any measurement/CSV data; UI-only."""
    st = _surface_state
    if st.get("history") is not None:
        st["history"].clear()
    st["t0"] = None
    ax = st.get("ax")
    canvas = st.get("canvas")
    if ax is not None and canvas is not None:
        ax.clear()
        _style_3d(ax)
        _apply_projection(ax)
        _update_overlay()
        canvas.draw_idle()

def _on_key(event):
    if not event.key:
        return
    k = event.key
    st = _surface_state
    changed = False

    if k.lower() == 'h':
        st["overlay_visible"] = not st.get("overlay_visible", True)
        _update_overlay(); return
    if k.lower() == 'f':
        st["full_bleed"] = not st.get("full_bleed", True)
        _fit_axes_to_window(); _update_overlay(); return
    if k.lower() == 'z':
        st["proj"] = "ortho" if st.get("proj","persp") == "persp" else "persp"
        _apply_projection(st["ax"]); changed = True
    if k == '-' or k == '_':  # less focal length => stronger perspective
        if st.get("_proj_supports_focal", False):
            st["focal"] = float(max(0.3, st.get("focal",0.75) - 0.05))
        else:
            st["dist"] = float(max(2.0, st.get("dist",7.0) - 1.0))
        _apply_projection(st["ax"]); changed = True
    if k == '=' or k == '+':  # more focal length => flatter perspective
        if st.get("_proj_supports_focal", False):
            st["focal"] = float(min(3.0, st.get("focal",0.75) + 0.05))
        else:
            st["dist"] = float(min(20.0, st.get("dist",7.0) + 1.0))
        _apply_projection(st["ax"]); changed = True
    if k.lower() == 'l':
        st["log_z"] = not st.get("log_z", False); changed = True
    if k.lower() == 'm':
        modes = ["lines", "wire", "surface"]
        cur = st.get("render_mode","lines")
        st["render_mode"] = modes[(modes.index(cur)+1) % len(modes)]
        changed = True
    if k == '[':
        st["max_lines"] = max(10, int(st.get("max_lines",60)) - 5); changed = True
    if k == ']':
        st["max_lines"] = min(500, int(st.get("max_lines",60)) + 5); changed = True
    if k == ',':
        st["t_stride"] = max(1, int(st.get("t_stride",1)) - 1); changed = True
    if k == '.':
        st["t_stride"] = min(10, int(st.get("t_stride",1)) + 1); changed = True
    if k == 'p':
        st["target_pts_per_line"] = max(50, int(st.get("target_pts_per_line",400)) - 50); changed = True
    if k == 'P':
        st["target_pts_per_line"] = min(2000, int(st.get("target_pts_per_line",400)) + 50); changed = True
    if k.lower() == 'c':
        _clear_history(); return

    if st.get("history") is not None and st["history"].maxlen != st["max_lines"]:
        st["history"] = deque(list(st["history"]), maxlen=st["max_lines"])
        changed = True

    if changed:
        _update_overlay()
        _redraw_throttled()

# ------------------------------- drawing --------------------------------------
def _redraw_throttled():
    st = _surface_state
    now = time.time()
    if now - float(st.get("last_draw", 0.0)) < float(st.get("min_redraw_interval", 0.15)):
        return
    st["last_draw"] = now
    _redraw()

def _redraw():
    st = _surface_state
    ax = st.get("ax")
    canvas = st.get("canvas")
    hist = list(st.get("history") or [])
    if ax is None or canvas is None or not hist:
        return

    SURF_MIN_LINES = 3
    MAX_SURF_POINTS = 150_000  # cap grid size for plot_surface

    ax.clear()
    _style_3d(ax)
    _apply_projection(ax)

    # apply stride (time decimation)
    t_stride = max(1, int(st.get("t_stride", 1)))
    if t_stride > 1:
        hist = hist[::t_stride]

    xs = [row[0] for row in hist]
    ys = [row[1] for row in hist]
    ts = [row[2] for row in hist]
    nlines = len(xs)
    if nlines == 0:
        _update_overlay(); canvas.draw_idle(); return

    M0 = len(xs[0])
    uniform = all(len(x)==M0 and len(y)==M0 for x,y in zip(xs,ys))

    t0 = st.get("t0") or ts[0]
    times = np.array(ts, dtype=float) - float(t0)

    # X decimation (view-only)
    target = max(50, int(st.get("target_pts_per_line", 400)))
    decim = max(1, int(np.ceil(M0 / float(max(1, target)))))

    def _plot_lines():
        for (x, y, t) in hist:
            xv = x[::decim]
            zv = np.log10(np.maximum(y, 1e-12)) if st.get("log_z") else y
            zv = zv[::decim]
            ax.plot(xv, np.full_like(xv, t - t0), zv, linewidth=0.9, alpha=0.95)

    mode = st.get("render_mode", "lines")
    if (nlines < SURF_MIN_LINES) or not uniform or mode == "lines":
        _plot_lines()
        ax.margins(x=0.02, y=0.02, z=0.02)
        _update_overlay()
        canvas.draw_idle()
        return

    # Surface/wire need a common X grid (use first row as reference)
    X = xs[0][::decim]
    if X.size < 2:
        _plot_lines()
        ax.margins(x=0.02, y=0.02, z=0.02)
        _update_overlay()
        canvas.draw_idle()
        return

    # Build Z (nlines x len(X)) and tile Y (same shape)
    Z_rows = []
    for y in ys:
        z = np.log10(np.maximum(y, 1e-12)) if st.get("log_z") else y
        Z_rows.append(z[::decim])
    Z = np.vstack(Z_rows)
    Y = np.tile(times[:, None], (1, X.shape[0]))

    mesh_pts = X.size * Y.shape[0]
    if mode == "wire" or mesh_pts > MAX_SURF_POINTS:
        ax.plot_wireframe(X, Y, Z, rstride=1, cstride=max(1, int(X.shape[0] // 200)))
    else:
        ax.plot_surface(X, Y, Z, rstride=1, cstride=1, linewidth=0, antialiased=False, cmap=cm.viridis)

    ax.margins(x=0.02, y=0.02, z=0.02)
    _update_overlay()
    canvas.draw_idle()
