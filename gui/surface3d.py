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
from matplotlib.colors import LightSource

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
    # visual tuning (view-only)
    "z_gain": 1.0,            # exaggerate Z relief for visibility
    "clip_pct": 98.0,         # percentile clip for color/lighting stability (1..99.9)
    "shade": True,            # LightSource shading for surfaces
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
        f"Z×: {st.get('z_gain',1.0):.2f} (g/G)  Clip: {st.get('clip_pct',98.0):.1f}% (;/:)  Shade: {'on' if st.get('shade',True) else 'off'} (S)",
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
    # Z gain
    if k == 'g':  st["z_gain"] = max(0.1, float(st.get("z_gain",1.0)) * 0.8);  changed = True
    if k == 'G':  st["z_gain"] = min(10.0, float(st.get("z_gain",1.0)) * 1.25); changed = True
    # percentile clip
    if k == ';':  st["clip_pct"] = max(50.0, float(st.get("clip_pct",98.0)) - 2.0); changed = True
    if k == ':':  st["clip_pct"] = min(99.9, float(st.get("clip_pct",98.0)) + 2.0); changed = True
    # shading toggle
    if k.lower() == 's': st["shade"] = not st.get("shade", True); changed = True

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
    import time
    import numpy as np
    from matplotlib import cm, colors
    from matplotlib.colors import LightSource

    st = _surface_state
    ax = st.get("ax")
    canvas = st.get("canvas")
    hist = list(st.get("history") or [])
    if ax is None or canvas is None or not hist:
        return

    # ---- view-only knobs (safe defaults) ----
    z_gain       = float(st.get("z_gain", 1.0))             # Z exaggeration (view only)
    clip_pct     = float(st.get("clip_pct", 98.0))          # percentile for robust clim
    color_gamma  = float(st.get("color_gamma", 1.0))        # gamma for midtone detail
    cmap_name    = st.get("cmap", "viridis")                # 'viridis' | 'magma' | ...
    shade        = bool(st.get("shade", True))              # enable lighting at all
    dynamic_light= bool(st.get("dynamic_light", False))     # re-light with camera (slower)
    allow_interp = bool(st.get("allow_interpolate", False)) # interp non-uniform rows

    # Performance caps (tuned for interactivity)
    SURF_MIN_LINES      = 3
    MAX_SURF_POINTS     = 150_000      # auto switch to wire above this
    SURFACE_POLYS_CAP   = int(st.get("surface_polys_cap", 70_000))  # ~triangles
    CAM_EPS_DEG         = 8.0          # min angle change to recompute lighting
    SAMPLE_MAX_ELEMS    = 80_000       # percentile sample cap

    ax.clear()
    _style_3d(ax)
    _apply_projection(ax)

    # time decimation (view-only)
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
    uniform = all(len(x) == M0 and len(y) == M0 for x, y in zip(xs, ys))

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
    if (nlines < SURF_MIN_LINES) or (mode == "lines"):
        _plot_lines()
        ax.margins(x=0.02, y=0.02, z=0.02)
        _update_overlay()
        canvas.draw_idle()
        return

    # Need a common X grid; if non-uniform and not allowed to interp -> fallback to lines
    if (not uniform) and (not allow_interp):
        _plot_lines()
        ax.margins(x=0.02, y=0.02, z=0.02)
        _update_overlay()
        canvas.draw_idle()
        return

    # Reference grid from first row (decimated)
    X = xs[0][::decim]
    if X.size < 2:
        _plot_lines()
        ax.margins(x=0.02, y=0.02, z=0.02)
        _update_overlay()
        canvas.draw_idle()
        return

    # Build Z rows (view-only), with optional interpolation for non-uniform rows
    Z_rows = []
    if uniform:
        for y in ys:
            z = np.log10(np.maximum(y, 1e-12)) if st.get("log_z") else y
            Z_rows.append(z[::decim])
    else:
        for xrow, yrow in zip(xs, ys):
            yv = np.interp(X, xrow[::decim], yrow[::decim], left=yrow[0], right=yrow[-1])
            z = np.log10(np.maximum(yv, 1e-12)) if st.get("log_z") else yv
            Z_rows.append(z)

    Z = np.vstack(Z_rows)
    Y = np.tile(times[:, None], (1, X.shape[0]))
    Z_view = Z * z_gain  # view-only geometry exaggeration

    mesh_pts = X.size * Y.shape[0]

    # --- Wireframe path (unchanged visual, adaptive density) ---
    if (mode == "wire") or (mesh_pts > MAX_SURF_POINTS):
        max_wires_y = 120
        rstride = max(1, int(np.ceil(Y.shape[0] / max_wires_y)))
        max_wires_x = 220
        cstride = max(1, int(np.ceil(X.shape[0] / max_wires_x)))
        ax.plot_wireframe(
            X, Y, Z_view,
            rstride=rstride, cstride=cstride,
            linewidth=0.4, alpha=0.65, color="#7aa5ff"
        )
        ax.margins(x=0.02, y=0.02, z=0.02)
        _update_overlay(); canvas.draw_idle(); return

    # -------- Fast surface path --------
    # Cap triangles aggressively for interactivity
    tri_est = max(1, (Y.shape[0]-1) * (X.shape[0]-1) * 2)
    if tri_est > SURFACE_POLYS_CAP:
        factor = float(np.sqrt(tri_est / float(SURFACE_POLYS_CAP)))
        rstride_s = max(1, int(np.floor(factor)))
        cstride_s = max(1, int(np.ceil(factor)))
    else:
        rstride_s = 1
        cstride_s = 1

    # Decimate the geometry BEFORE shading/coloring (big win)
    Xp = X[::cstride_s]
    Zp = Z_view[::rstride_s, ::cstride_s]
    Yp = Y[::rstride_s, ::cstride_s]

    # Robust clim from a bounded sample (cheap on big grids)
    if Zp.size > SAMPLE_MAX_ELEMS:
        step = int(np.ceil(np.sqrt(Zp.size / SAMPLE_MAX_ELEMS)))
        Zs = Zp[::step, ::step]
    else:
        Zs = Zp
    p = np.clip(clip_pct, 50.0, 99.9)
    vmin = np.percentile(Zs, 100.0 - p)
    vmax = np.percentile(Zs, p)
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin >= vmax:
        vmin, vmax = float(np.min(Zs)), float(np.max(Zs))

    cmap_obj = getattr(cm, cmap_name, cm.viridis)
    norm = colors.PowerNorm(gamma=max(0.1, color_gamma), vmin=vmin, vmax=vmax)

    # Prepare (possibly cached) facecolors
    rgb = None
    cache = st.setdefault("_surf_cache", {})
    az = float(getattr(ax, "azim", 45.0))
    el = float(getattr(ax, "elev", 30.0))

    # Static or dynamic lighting choice (dynamic is slower)
    if shade:
        if dynamic_light:
            # Recompute only if camera moved enough or data changed
            sig = (Zp.shape, round(float(Zp.mean()), 6), round(float(Zp.std()), 6), round(times[-1], 6))
            last_sig = cache.get("sig_dyn")
            last_az  = cache.get("az_dyn")
            last_el  = cache.get("el_dyn")
            if cache.get("rgb_dyn") is not None and last_sig == sig and \
               abs(az - last_az) < CAM_EPS_DEG and abs(el - last_el) < CAM_EPS_DEG and \
               cache.get("cmap_dyn") == cmap_name and cache.get("gamma_dyn") == color_gamma and \
               cache.get("zgain_dyn") == z_gain:
                rgb = cache["rgb_dyn"]
            else:
                ls = LightSource(azdeg=(az - 35.0) % 360.0, altdeg=float(np.clip(el + 5.0, 10.0, 80.0)))
                rgb = ls.shade(Zp, cmap=cmap_obj, norm=norm, fraction=1.0)
                cache.update({
                    "rgb_dyn": rgb, "sig_dyn": sig, "az_dyn": az, "el_dyn": el,
                    "cmap_dyn": cmap_name, "gamma_dyn": color_gamma, "zgain_dyn": z_gain
                })
        else:
            # Fast static light; cache per data signature
            sig = (Zp.shape, round(float(Zp.mean()), 6), round(float(Zp.std()), 6), round(times[-1], 6))
            if cache.get("rgb_sta") is not None and cache.get("sig_sta") == sig and \
               cache.get("cmap_sta") == cmap_name and cache.get("gamma_sta") == color_gamma and \
               cache.get("zgain_sta") == z_gain:
                rgb = cache["rgb_sta"]
            else:
                ls = LightSource(azdeg=320, altdeg=35)
                rgb = ls.shade(Zp, cmap=cmap_obj, norm=norm, fraction=0.9)
                cache.update({
                    "rgb_sta": rgb, "sig_sta": sig,
                    "cmap_sta": cmap_name, "gamma_sta": color_gamma, "zgain_sta": z_gain
                })
    else:
        # No lighting: straight colormap (fastest)
        rgb = cmap_obj(norm(Zp))

    ax.plot_surface(
        Xp, Yp, Zp,
        rstride=1, cstride=1,
        facecolors=rgb,
        linewidth=0, antialiased=False, shade=False
    )

    ax.margins(x=0.02, y=0.02, z=0.02)
    _update_overlay()
    canvas.draw_idle()
