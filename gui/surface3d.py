# gui/surface3d.py
import time
from collections import deque
import numpy as np
import tkinter as tk
from tkinter import ttk

import matplotlib
from matplotlib import cm
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

# Singleton handles stored here so any tab can push data
_surface_state = {
    "window": None,
    "ax": None,
    "canvas": None,
    "history": None,   # deque of (x, y_row, t)
    "t0": None,        # first timestamp to make relative time axis
    "max_lines": 60,   # tune as you like
    "log_z": False,    # optional log magnitude
}

def ensure_surface3d(root):
    """Create (or focus) the 3D surface window."""
    st = _surface_state
    if st["window"] and st["window"].winfo_exists():
        st["window"].deiconify()
        st["window"].lift()
        return st["window"]

    win = tk.Toplevel(root)
    win.title("3D Surface (Waterfall)")
    win.geometry("900x600")
    win.configure(bg="#1a1a1a")

    # Top bar
    bar = tk.Frame(win, bg="#1a1a1a")
    bar.pack(fill="x", padx=8, pady=6)
    ttk.Label(bar, text="Last N lines:").pack(side="left")
    n_var = tk.IntVar(value=st["max_lines"])
    n_spin = ttk.Spinbox(bar, from_=10, to=500, width=5, textvariable=n_var)
    n_spin.pack(side="left", padx=(4,10))

    log_var = tk.BooleanVar(value=st["log_z"])
    ttk.Checkbutton(bar, text="Log Z", variable=log_var).pack(side="left")

    def apply_opts():
        st["max_lines"] = max(10, int(n_var.get() or 60))
        st["log_z"] = bool(log_var.get())
        _redraw()
    ttk.Button(bar, text="Apply", command=apply_opts).pack(side="left", padx=8)

    # Figure / 3D axis
    fig = plt.Figure(figsize=(7,4), dpi=100, facecolor="#1a1a1a")
    ax = fig.add_subplot(111, projection='3d')
    _style_3d(ax)

    canvas = FigureCanvasTkAgg(fig, master=win)
    canvas.get_tk_widget().pack(fill="both", expand=True)

    st.update({
        "window": win,
        "ax": ax,
        "canvas": canvas,
        "history": deque(maxlen=st["max_lines"]),
        "t0": None,
    })

    # On close, just hide (keeps history unless app exits)
    def on_close():
        win.withdraw()
    win.protocol("WM_DELETE_WINDOW", on_close)

    return win

def push_surface_line(y, x=None, t=None):
    """
    y: 1-D numpy-like array (amplitudes for bins/harmonics)
    x: 1-D array of same length as y (bin centers or harmonic indices). If None, uses 0..len(y)-1
    t: timestamp (seconds). If None, uses time.time()
    """
    st = _surface_state
    if st["window"] is None or not st["window"].winfo_exists():
        # Nothing to draw into yet; ignore silently
        return

    y = np.asarray(y).astype(float)
    x = np.arange(len(y)) if x is None else np.asarray(x).astype(float)
    if y.shape != x.shape:
        # Keep data pristine, do not resample silently
        raise ValueError("push_surface_line: x and y must have the same length")

    if t is None:
        t = time.time()

    if st["t0"] is None:
        st["t0"] = t

    # Store one row
    st["history"].append((x, y, float(t)))

    # If user changed N, align deque maxlen
    if st["history"].maxlen != st["max_lines"]:
        st["history"] = deque(list(st["history"]), maxlen=st["max_lines"])

    _redraw()

def _style_3d(ax):
    ax.set_facecolor("#1a1a1a")
    for spine in ax.spines.values():
        spine.set_color('#cccccc')
    ax.set_xlabel("X (bin / harmonic index)", color="white")
    ax.set_ylabel("Time (s)", color="white")
    ax.set_zlabel("Amplitude", color="white")
    ax.tick_params(axis='both', colors='white')
    ax.tick_params(axis='z', colors='white')
    ax.grid(True, color="#444444", alpha=0.4)

def _redraw():
    st = _surface_state
    ax = st["ax"]
    canvas = st["canvas"]
    hist = list(st["history"])
    if not hist:
        return

    # Tunables (view-only; no effect on saved/analysis data)
    SURF_MIN_LINES = 3          # need at least 3 time-slices to show a real surface
    TARGET_PTS_PER_LINE = 600   # decimate X for view if longer than this
    MAX_SURF_POINTS = 200_000   # total X*Y threshold to fall back to lines

    ax.clear()
    _style_3d(ax)

    xs = [row[0] for row in hist]
    ys = [row[1] for row in hist]
    ts = [row[2] for row in hist]

    nlines = len(xs)
    # All rows same length?
    M0 = len(xs[0])
    uniform = all(len(x) == M0 and len(y) == M0 for x, y in zip(xs, ys))

    t0 = st["t0"] or ts[0]
    times = np.array(ts) - t0

    # Decide decimation for view (no data modification!)
    decim = 1
    if M0 > TARGET_PTS_PER_LINE:
        decim = max(1, int(np.ceil(M0 / TARGET_PTS_PER_LINE)))

    def _plot_lines():
        for (x, y, t) in hist:
            x_v = x[::decim]
            y_v = np.log10(np.maximum(y, 1e-12)) if st["log_z"] else y
            y_v = y_v[::decim]
            ax.plot(x_v, np.full_like(x_v, t - t0), y_v, linewidth=1)

    # Too few lines for a surface, or non-uniform rows -> draw “fences”
    if (nlines < SURF_MIN_LINES) or not uniform:
        _plot_lines()
        canvas.draw_idle()
        return

    # Build decimated surface
    X = np.vstack([x[::decim] for x in xs])
    Z = np.vstack([(np.log10(np.maximum(y, 1e-12)) if st["log_z"] else y)[::decim] for y in ys])
    Y = np.tile(times[:, None], (1, X.shape[1]))

    # If it would be too heavy, fall back to lines
    if X.size > MAX_SURF_POINTS:
        _plot_lines()
    else:
        ax.plot_surface(X, Y, Z, rstride=1, cstride=1, linewidth=0, antialiased=False, cmap=cm.viridis)

    ax.margins(x=0.02, y=0.02, z=0.02)
    canvas.draw_idle()
