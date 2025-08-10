# gui/bh_curve.py — robust B–H curve acquisition & plotting (responsive)
# Drop-in replacement. Safe for lab use (no data writes except explicit CSV/PNG).
#
# Highlights
# - Responsive layout, compact toolbar, grouped controls
# - I/V/Auto cycle reference + optional T=1 extraction with cycle averaging
# - DC removal, detrend, Δt µs phase shift (voltage vs current)
# - Tight-fit axes (default) or symmetric ±max; equal-aspect optional
# - Auto-refresh with history fade; clean shutdown (after-cancel + Destroy bind)
# - Compact CSV always, optional detailed CSV of reconstructed samples, PNG export

import os
import csv
from datetime import datetime
import tkinter as tk
from tkinter import ttk
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import app.app_state as app_state
from scpi.interface import safe_query, scpi_lock
from utils.debug import log_debug

mu0 = 4 * np.pi * 1e-7  # H/m, permeability of free space

# ------------------------------- Utility helpers -------------------------------

def _cumulative_trapezoid(y: np.ndarray, dt: float) -> np.ndarray:
    """Cumulative trapezoidal integration without SciPy. Returns same length as y."""
    if len(y) == 0:
        return y
    y = np.asarray(y, dtype=float)
    z = np.empty_like(y)
    z[0] = 0.0
    if len(y) > 1:
        z[1:] = np.cumsum((y[1:] + y[:-1]) * 0.5) * dt
    return z


def _detect_zero_crossings_same_slope(waveform: np.ndarray) -> list:
    """Find indices where the sign flips and record the local slope sign."""
    y = np.asarray(waveform)
    if len(y) < 2:
        return []
    zc = []
    signs = np.signbit(y)
    idxs = np.where(np.diff(signs))[0]
    for k in idxs:
        dy = y[k + 1] - y[k]
        slope = np.sign(dy) if dy != 0 else 0.0
        zc.append((k, slope))
    return zc


def _find_cycles_by_wave(y: np.ndarray) -> list:
    """Successive zero-crossings with the same slope → cycle windows."""
    zc = _detect_zero_crossings_same_slope(y)
    if len(zc) < 2:
        return [(0, len(y))]
    cycles = []
    first_idx, first_slope = zc[0]
    for k in range(1, len(zc)):
        idx, slope = zc[k]
        if slope == first_slope and slope != 0:
            cycles.append((first_idx, idx))
            first_idx, first_slope = zc[k]
    if not cycles:
        cycles.append((zc[0][0], zc[1][0]))
    return cycles


def _estimate_fundamental_freq(y: np.ndarray, dt: float) -> float:
    n = len(y)
    if n < 8 or dt <= 0:
        return 0.0
    win = np.hanning(n)
    ywin = (y - np.mean(y)) * win
    Y = np.fft.rfft(ywin)
    mag = np.abs(Y)
    if len(mag) < 3:
        return 0.0
    k1 = 1 + np.argmax(mag[1:])
    fs = 1.0 / dt
    f = k1 * fs / n
    return float(f)


def _compute_thd(y: np.ndarray, dt: float, max_harmonics: int = 20) -> float:
    n = len(y)
    if n < 16 or dt <= 0:
        return 0.0
    y = y - np.mean(y)
    win = np.hanning(n)
    Y = np.fft.rfft(y * win)
    mag = np.abs(Y)
    if len(mag) < 3:
        return 0.0
    k1 = 1 + np.argmax(mag[1:])
    A1 = mag[k1]
    if A1 <= 0:
        return 0.0
    kmax = min(len(mag) - 1, k1 * max_harmonics)
    harm_idxs = [m * k1 for m in range(2, max(3, max_harmonics + 1)) if m * k1 <= kmax]
    if not harm_idxs:
        return 0.0
    harm_power = np.sum(mag[harm_idxs] ** 2)
    thd = np.sqrt(harm_power) / A1
    return float(thd * 100.0)


def _resample_segment(y: np.ndarray, n_points: int) -> np.ndarray:
    if len(y) <= 1 or n_points <= 1:
        return np.array(y, dtype=float)
    x_old = np.linspace(0.0, 1.0, num=len(y))
    x_new = np.linspace(0.0, 1.0, num=n_points)
    return np.interp(x_new, x_old, y)


def _single_cycle_by_fft(y: np.ndarray, dt: float) -> list:
    """Fallback single-cycle window using FFT-estimated period, centered in record."""
    n = len(y)
    if n < 8 or dt <= 0:
        return [(0, n)]
    f0 = _estimate_fundamental_freq(y, dt)
    if f0 <= 0:
        return [(0, n)]
    T = int(max(4, round((1.0 / f0) / dt)))
    if T >= n:
        return [(0, n)]
    mid = n // 2
    s = max(0, mid - T // 2)
    e = min(n, s + T)
    return [(s, e)]

# ------------------------------- SCPI fetch -------------------------------

def fetch_waveform_custom(scope, chan, samples, mode="NORM", stop_scope=True):
    import time

    valid_modes = ["NORM", "RAW"]
    mode = mode.upper()
    if mode not in valid_modes:
        mode = "NORM"
    if stop_scope:
        scope.write(":STOP")
        time.sleep(0.2)
    scope.write(":WAV:FORM BYTE")
    scope.write(f":WAV:MODE {mode}")
    scope.write(f":WAV:POIN:MODE {mode}")
    scope.write(f":WAV:POIN {samples}")
    scope.write(f":WAV:SOUR {chan}")
    scope.query(":WAV:PRE?")
    time.sleep(0.1)
    pre = scope.query(":WAV:PRE?").split(",")
    try:
        xinc = float(pre[4]); xorig = float(pre[5])
        yinc = float(pre[7]); yorig = float(pre[8]); yref = float(pre[9])
    except Exception:
        xinc, xorig, yinc, yorig, yref = 1.0, 0.0, 1.0, 0.0, 0.0

    if chan.startswith("MATH"):
        probe = 1.0
    else:
        try:
            probe = float(safe_query(scope, f":{chan}:PROB?", "1.0"))
        except Exception:
            probe = 1.0

    try:
        raw = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)
    except Exception as e:
        log_debug(f"❌ query_binary_values failed for {chan}: {e}")
        raw = np.array([], dtype=np.uint8)

    if stop_scope:
        try:
            scope.write(":RUN")
        except Exception:
            pass
    return raw, xinc, xorig, yinc, yorig, yref, probe

# ------------------------------- GUI setup -------------------------------

def setup_bh_curve_tab(tab_frame, ip, root):
    # Grid + weights for full responsiveness
    tab_frame.columnconfigure(0, weight=1)
    tab_frame.rowconfigure(5, weight=1)  # plot area grows

    # --------------------------- Toolbar ---------------------------
    toolbar = tk.Frame(tab_frame, bg="#1a1a1a")
    toolbar.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
    for c in range(14):
        toolbar.grid_columnconfigure(c, weight=1 if c == 9 else 0)  # spacer at col 9 grows

    after_id = [None]  # holds the scheduled after() id for auto-refresh

    btn_acquire = ttk.Button(toolbar, text="▶ Acquire & Plot", style="Action.TButton")
    btn_clear   = ttk.Button(toolbar, text="⭮ Clear")
    btn_png     = ttk.Button(toolbar, text="💾 Save PNG")

    auto_var = tk.BooleanVar(value=False)
    auto_check = ttk.Checkbutton(toolbar, text="Auto", variable=auto_var)
    interval_var = tk.IntVar(value=5)
    interval_spin = ttk.Spinbox(toolbar, from_=1, to=60, width=3, textvariable=interval_var)
    tk.Label(toolbar, text="s", bg="#1a1a1a", fg="#ffffff").grid(row=0, column=3, padx=(4, 0))

    auto_cycle_var = tk.BooleanVar(value=False)
    auto_cycle_check = ttk.Checkbutton(toolbar, text="T=1", variable=auto_cycle_var)
    tk.Label(toolbar, text="Avg cycles:", bg="#1a1a1a", fg="#ffffff").grid(row=0, column=5, padx=(10, 2))
    avg_cycles_var = tk.IntVar(value=1)
    avg_spin = ttk.Spinbox(toolbar, from_=1, to=10, width=3, textvariable=avg_cycles_var)

    # Cycle reference selector (I, V, Auto)
    tk.Label(toolbar, text="Ref:", bg="#1a1a1a", fg="#ffffff").grid(row=0, column=7, padx=(8, 2))
    cycle_ref_var = tk.StringVar(value="I")
    cycle_ref_box = ttk.Combobox(toolbar, textvariable=cycle_ref_var, values=["I", "V", "Auto"], width=5, state="readonly")
    cycle_ref_box.grid(row=0, column=8, padx=(0, 8))

    # Layout toggles
    compact_var = tk.BooleanVar(value=False)  # Plot focus mode
    compact_check = ttk.Checkbutton(toolbar, text="Plot focus", variable=compact_var)
    data_var = tk.BooleanVar(value=True)      # Data panel visibility
    data_check = ttk.Checkbutton(toolbar, text="Data", variable=data_var)

    # Place toolbar items
    btn_acquire.grid(row=0, column=0, padx=(0, 8))
    auto_check.grid(row=0, column=1, padx=(4, 4))
    interval_spin.grid(row=0, column=2, padx=(0, 0))
    auto_cycle_check.grid(row=0, column=4, padx=(8, 8))
    avg_spin.grid(row=0, column=6, padx=(0, 8))
    tk.Frame(toolbar, bg="#1a1a1a").grid(row=0, column=9, sticky="ew")  # expanding spacer
    btn_png.grid(row=0, column=10, padx=(8, 6))
    btn_clear.grid(row=0, column=11, padx=(6, 0))
    compact_check.grid(row=0, column=12, padx=(8, 4))
    data_check.grid(row=0, column=13, padx=(0, 0))

    # --------------------------- Grouped controls ---------------------------
    controls_host = tk.Frame(tab_frame, bg="#1a1a1a")
    controls_host.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
    controls_host.grid_columnconfigure(0, weight=1)

    def mk_group(title: str):
        lf = ttk.LabelFrame(controls_host, text=title)
        lf.grid_propagate(False)
        for c in range(4):
            lf.grid_columnconfigure(c, weight=1)
        return lf

    grp_geometry = mk_group("Core Geometry")
    grp_channels = mk_group("Channels & Probe")
    grp_sampling = mk_group("Sampling")
    grp_processing = mk_group("Processing")
    grp_display = mk_group("Display")

    # --- Core Geometry ---
    tk.Label(grp_geometry, text="N:", background="#1a1a1a", foreground="#ffffff").grid(row=0, column=0, sticky="e", padx=(6, 2), pady=3)
    entry_N = ttk.Entry(grp_geometry, width=6); entry_N.insert(0, "20"); entry_N.grid(row=0, column=1, sticky="w", padx=(0, 6), pady=3)
    tk.Label(grp_geometry, text="Ae (mm²):", background="#1a1a1a", foreground="#ffffff").grid(row=0, column=2, sticky="e", padx=(6, 2), pady=3)
    entry_Ae = ttk.Entry(grp_geometry, width=8); entry_Ae.insert(0, "25"); entry_Ae.grid(row=0, column=3, sticky="w", padx=(0, 6), pady=3)
    tk.Label(grp_geometry, text="le (mm):", background="#1a1a1a", foreground="#ffffff").grid(row=1, column=0, sticky="e", padx=(6, 2), pady=3)
    entry_le = ttk.Entry(grp_geometry, width=8); entry_le.insert(0, "50"); entry_le.grid(row=1, column=1, sticky="w", padx=(0, 6), pady=3)
    tk.Label(grp_geometry, text="Δt (µs):", background="#1a1a1a", foreground="#ffffff").grid(row=1, column=2, sticky="e", padx=(6, 2), pady=3)
    entry_dt_shift = ttk.Entry(grp_geometry, width=8); entry_dt_shift.insert(0, "0.0"); entry_dt_shift.grid(row=1, column=3, sticky="w", padx=(0, 6), pady=3)

    # --- Channels & Probe ---
    tk.Label(grp_channels, text="[i]Ch:", background="#1a1a1a", foreground="#ffffff").grid(row=0, column=0, sticky="e", padx=(6, 2), pady=3)
    entry_ich = ttk.Entry(grp_channels, width=6); entry_ich.insert(0, "3"); entry_ich.grid(row=0, column=1, sticky="w", padx=(0, 6), pady=3)
    tk.Label(grp_channels, text="[v]Ch:", background="#1a1a1a", foreground="#ffffff").grid(row=0, column=2, sticky="e", padx=(6, 2), pady=3)
    entry_vch = ttk.Entry(grp_channels, width=6); entry_vch.insert(0, "1"); entry_vch.grid(row=0, column=3, sticky="w", padx=(0, 6), pady=3)

    tk.Label(grp_channels, text="Probe:", background="#1a1a1a", foreground="#ffffff").grid(row=1, column=0, sticky="e", padx=(6, 2), pady=3)
    probe_type = tk.StringVar(value="shunt")
    rb_shunt = tk.Radiobutton(grp_channels, text="Shunt", variable=probe_type, value="shunt",
                              bg="#1a1a1a", fg="#ffffff", selectcolor="#2d2d2d", activebackground="#2d2d2d", indicatoron=False, width=7)
    rb_clamp = tk.Radiobutton(grp_channels, text="Clamp", variable=probe_type, value="clamp",
                              bg="#1a1a1a", fg="#ffffff", selectcolor="#2d2d2d", activebackground="#2d2d2d", indicatoron=False, width=7)
    rb_shunt.grid(row=1, column=1, sticky="w", padx=(0, 2), pady=3)
    rb_clamp.grid(row=1, column=2, sticky="w", padx=(0, 2), pady=3)

    tk.Label(grp_channels, text="Value (Ω or A/V):", background="#1a1a1a", foreground="#ffffff").grid(row=1, column=3, sticky="e", padx=(6, 2), pady=3)
    entry_probe_value = ttk.Entry(grp_channels, width=8); entry_probe_value.insert(0, "0.1"); entry_probe_value.grid(row=1, column=3, sticky="w", padx=(120, 6), pady=3)

    # --- Sampling ---
    tk.Label(grp_sampling, text="Mode:", background="#1a1a1a", foreground="#ffffff").grid(row=0, column=0, sticky="e", padx=(6, 2), pady=3)
    point_mode_var = tk.StringVar(value="NORM")
    point_mode_box = ttk.Combobox(grp_sampling, textvariable=point_mode_var, values=["NORM", "RAW"], width=6, state="readonly")
    point_mode_box.grid(row=0, column=1, sticky="w", padx=(0, 6), pady=3)

    tk.Label(grp_sampling, text="Pts:", background="#1a1a1a", foreground="#ffffff").grid(row=0, column=2, sticky="e", padx=(6, 2), pady=3)
    entry_samples = ttk.Entry(grp_sampling, width=8); entry_samples.insert(0, "1000"); entry_samples.grid(row=0, column=3, sticky="w", padx=(0, 6), pady=3)

    stop_scope_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(grp_sampling, text="Stop/Fetch", variable=stop_scope_var).grid(row=1, column=0, columnspan=2, sticky="w", padx=(6, 0), pady=3)

    # --- Processing ---
    remove_dc_var = tk.BooleanVar(value=True)
    detrend_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(grp_processing, text="Remove DC", variable=remove_dc_var).grid(row=0, column=0, sticky="w", padx=(6, 0), pady=3)
    ttk.Checkbutton(grp_processing, text="Detrend", variable=detrend_var).grid(row=0, column=1, sticky="w", padx=(6, 0), pady=3)

    # --- Display ---
    overlay_var = tk.BooleanVar(value=False)
    equal_aspect_var = tk.BooleanVar(value=False)
    tight_fit_var = tk.BooleanVar(value=True)
    detailed_csv_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(grp_display, text="Overlay prev.", variable=overlay_var).grid(row=0, column=0, sticky="w", padx=(6, 0), pady=3)
    ttk.Checkbutton(grp_display, text="Equal aspect", variable=equal_aspect_var).grid(row=0, column=1, sticky="w", padx=(6, 0), pady=3)
    ttk.Checkbutton(grp_display, text="Detailed CSV", variable=detailed_csv_var).grid(row=0, column=2, sticky="w", padx=(6, 0), pady=3)
    ttk.Checkbutton(grp_display, text="Tight fit", variable=tight_fit_var).grid(row=1, column=0, sticky="w", padx=(6, 0), pady=3)

    # Reflow groups responsively
    groups = [grp_geometry, grp_channels, grp_sampling, grp_processing, grp_display]

    def place_groups(ncols: int):
        for g in groups:
            g.grid_forget()
        for i, g in enumerate(groups):
            r, c = divmod(i, ncols)
            g.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")
        for c in range(ncols):
            controls_host.grid_columnconfigure(c, weight=1)
        for c in range(ncols, 6):
            controls_host.grid_columnconfigure(c, weight=0)

    def on_resize(event=None):
        try:
            w = controls_host.winfo_width() or tab_frame.winfo_width()
        except Exception:
            w = 1200
        if w >= 1200:
            cols = 3
        elif w >= 900:
            cols = 2
        else:
            cols = 1
        place_groups(cols)

    controls_host.bind("<Configure>", on_resize)
    tab_frame.after(50, on_resize)

    # --------------------------- Status + Data Panel ---------------------------
    status_var = tk.StringVar(value="")
    status_label = tk.Label(tab_frame, textvariable=status_var, fg="#bbbbbb", bg="#1a1a1a", font=("TkDefaultFont", 9))
    status_label.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 2))

    data_text = tk.Text(tab_frame, height=8, font=("Courier", 9), bg="#181818", fg="#eeeeee", wrap="none")
    data_text.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 6))
    data_text.config(state=tk.DISABLED)

    # --------------------------- Plot ---------------------------
    plot_frame = tk.Frame(tab_frame, bg="#202020", bd=1, relief="solid")
    plot_frame.grid(row=5, column=0, sticky="nsew", padx=10, pady=(2, 10))
    plot_frame.rowconfigure(0, weight=1)
    plot_frame.columnconfigure(0, weight=1)

    fig, ax = plt.subplots(figsize=(5, 4), dpi=100, facecolor="#1a1a1a")
    canvas = FigureCanvasTkAgg(fig, master=plot_frame)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.grid(row=0, column=0, sticky="nsew")
    ax.set_facecolor("#222222")
    ax.set_xlabel("H (A/m)")
    ax.set_ylabel("B (T)")

    last_HB = [None, None]
    history = []  # for auto heatmap

    # ----- Compact / visibility toggles -----
    def apply_compact_ui():
        try:
            if compact_var.get():
                controls_host.grid_remove()
            else:
                controls_host.grid()
        except Exception:
            pass

    def toggle_data_panel():
        try:
            if data_var.get():
                data_text.grid()
            else:
                data_text.grid_remove()
        except Exception:
            pass

    compact_check.config(command=apply_compact_ui)
    data_check.config(command=toggle_data_panel)

    # --- Reset helper ---
    def reset_history():
        history.clear()
        last_HB[0], last_HB[1] = None, None
        if hasattr(do_acquire_and_plot, "csv_path"):
            delattr(do_acquire_and_plot, "csv_path")
        if hasattr(do_acquire_and_plot, "run_index"):
            delattr(do_acquire_and_plot, "run_index")
        ax.clear()
        fig = ax.get_figure()
        ax.set_facecolor("#1a1a1a")
        fig.patch.set_facecolor("#1a1a1a")
        ax.set_xlabel("H (A/m)")
        ax.set_ylabel("B (T)")
        ax.set_title("B-H (Hysteresis) Curve")
        canvas.draw()
        status_var.set("Plot and history cleared.")

    btn_clear.config(command=reset_history)

    # --- Main acquisition/plot function ---
    def do_acquire_and_plot():
        from app.app_state import scope

        # Parse UI inputs
        try:
            N = int(entry_N.get())
            Ae = float(entry_Ae.get()) * 1e-6
            le = float(entry_le.get()) * 1e-3
            ich = entry_ich.get().strip()
            vch = entry_vch.get().strip()
            probe_val = float(entry_probe_value.get())
            overlay = overlay_var.get()
            probe_mode = probe_type.get()
            samples = int(entry_samples.get())
            point_mode = point_mode_var.get()
            stop_scope = stop_scope_var.get()
            avg_cycles = max(1, int(avg_cycles_var.get()))
            dt_shift_us = float(entry_dt_shift.get())
        except Exception as e:
            status_var.set(f"Invalid input: {e}")
            return

        if not auto_var.get() and not overlay:
            reset_history()

        if not scope:
            status_var.set("Scope not connected.")
            return

        # Fetch CURRENT waveform
        try:
            chan_i = ich if ich.startswith("MATH") else f"CHAN{ich}"
            disp_status_i = safe_query(scope, f":{chan_i}:DISP?")
            if disp_status_i != "1":
                status_var.set(f"{chan_i} not enabled on scope!")
                return
            with scpi_lock:
                raw_i, xinc, xorig, yinc_i, yorig_i, yref_i, probe_i = fetch_waveform_custom(
                    scope, chan_i, samples, point_mode, stop_scope)
            if raw_i is None or len(raw_i) == 0:
                status_var.set(f"No data for {chan_i} (check timebase & trigger settings!)")
                return
            Iwave = ((raw_i - yref_i) * yinc_i + yorig_i)
            if probe_mode == "shunt":
                if probe_val == 0:
                    status_var.set("Shunt value must not be zero!")
                    return
                Iwave = Iwave / probe_val
            else:
                Iwave = Iwave * probe_val  # A/V
        except Exception as e:
            status_var.set(f"Failed to fetch current: {e}")
            return

        # Fetch VOLTAGE waveform
        try:
            chan_v = vch if vch.startswith("MATH") else f"CHAN{vch}"
            disp_status_v = safe_query(scope, f":{chan_v}:DISP?")
            if disp_status_v != "1":
                status_var.set(f"{chan_v} not enabled on scope!")
                return
            with scpi_lock:
                raw_v, xinc_v, xorig_v, yinc_v, yorig_v, yref_v, probe_v = fetch_waveform_custom(
                    scope, chan_v, samples, point_mode, stop_scope)
            if raw_v is None or len(raw_v) == 0:
                status_var.set(f"No data for {chan_v} (check timebase & trigger settings!)")
                return
            Vwave = ((raw_v - yref_v) * yinc_v + yorig_v) * probe_v
        except Exception as e:
            status_var.set(f"Failed to fetch voltage: {e}")
            return

        # Validate sampling interval and lengths
        dt = xinc
        if not (np.isfinite(dt) and dt > 0):
            status_var.set("Invalid sample interval from scope.")
            return
        if abs(xinc - xinc_v) > 1e-9:
            status_var.set("Sample intervals for current and voltage do not match! (adjust timebase?)")
            return
        n = min(len(Iwave), len(Vwave))
        Iwave = Iwave[:n]
        Vwave = Vwave[:n]

        # Optional pre-processing
        if remove_dc_var.get():
            Iwave = Iwave - np.mean(Iwave)
            Vwave = Vwave - np.mean(Vwave)
        if detrend_var.get() and len(Iwave) > 1:
            x = np.arange(len(Iwave))
            A = np.vstack([x, np.ones_like(x)]).T
            coef, *_ = np.linalg.lstsq(A, Iwave, rcond=None)
            Iwave = Iwave - (coef[0] * x + coef[1])
            coef, *_ = np.linalg.lstsq(A, Vwave, rcond=None)
            Vwave = Vwave - (coef[0] * x + coef[1])

        # Optional relative time shift (µs) applied to VOLTAGE to compensate probe lag
        if dt_shift_us != 0.0:
            t = xorig + np.arange(len(Vwave)) * dt
            t_shift = dt_shift_us * 1e-6
            Vwave = np.interp(t, t + t_shift, Vwave, left=Vwave[0], right=Vwave[-1])

        # Choose cycle reference according to UI (I / V / Auto)
        ref = cycle_ref_var.get().upper()
        if ref == "I":
            cycles = _find_cycles_by_wave(Iwave)
        elif ref == "V":
            cycles = _find_cycles_by_wave(Vwave)
        else:  # Auto
            cycles = _find_cycles_by_wave(Iwave)
            if not cycles or (len(cycles) == 1 and (cycles[0][1] - cycles[0][0]) == len(Iwave)):
                alt = _find_cycles_by_wave(Vwave)
                if alt and not (len(alt) == 1 and (alt[0][1] - alt[0][0]) == len(Vwave)):
                    cycles = alt
                else:
                    cycles = _single_cycle_by_fft(Iwave if np.std(Iwave) > np.std(Vwave) else Vwave, dt)

        msg = ""
        if auto_cycle_var.get():
            if len(cycles) >= 1:
                use_cycles = cycles[-max(1, int(avg_cycles_var.get())):]
                lengths = [end - start for (start, end) in use_cycles]
                target_pts = max(64, int(np.median(lengths)))
                I_acc = []
                V_acc = []
                for (s, e) in use_cycles:
                    if e - s > 4:
                        I_acc.append(_resample_segment(Iwave[s:e], target_pts))
                        V_acc.append(_resample_segment(Vwave[s:e], target_pts))
                if I_acc and V_acc:
                    Iwave_cyc = np.mean(np.vstack(I_acc), axis=0)
                    Vwave_cyc = np.mean(np.vstack(V_acc), axis=0)
                    dt_eff = (float(np.mean(lengths)) * dt) / float(target_pts)
                    msg = f"Averaged {len(I_acc)} cycle(s)"
                else:
                    Iwave_cyc, Vwave_cyc = Iwave, Vwave
                    dt_eff = dt
                    msg = "⚠️ Could not average — insufficient cycle data"
            else:
                Iwave_cyc, Vwave_cyc = Iwave, Vwave
                dt_eff = dt
                msg = "⚠️ Could not detect full cycle — showing all data"
        else:
            Iwave_cyc, Vwave_cyc = Iwave, Vwave
            dt_eff = dt

        # Compute B and H
        try:
            H = (N * Iwave_cyc) / le
            flux = _cumulative_trapezoid(Vwave_cyc, dt_eff)
            B = flux / (N * Ae)
        except Exception as e:
            status_var.set(f"Failed to compute B/H: {e}")
            return

        if len(H) == 0 or len(B) == 0:
            status_var.set("Computed arrays are empty!")
            return

        # Diagnostics
        try:
            f0 = _estimate_fundamental_freq(Iwave, dt)
            fs = 1.0 / dt
            ratio = fs / max(1e-12, f0)
            thd_i = _compute_thd(Iwave, dt)
            thd_v = _compute_thd(Vwave, dt)
        except Exception:
            f0, fs, ratio, thd_i, thd_v = 0.0, 0.0, 0.0, 0.0, 0.0

        # Figures of merit
        try:
            def interpolate_crossing(x, y):
                idxs = np.where(np.diff(np.signbit(y)))[0]
                if not len(idxs):
                    return np.nan
                i = idxs[0]
                x0, x1 = x[i], x[i + 1]
                y0, y1 = y[i], y[i + 1]
                if y1 == y0:
                    return x0
                return x0 + (0 - y0) * (x1 - x0) / (y1 - y0)
            Hc = interpolate_crossing(H, B)
            Br = interpolate_crossing(B, H)
            loop_area = np.abs(np.trapz(B, H))
            with np.errstate(divide='ignore', invalid='ignore'):
                mu_r_arr = np.abs(B / (H + 1e-12)) / mu0
                mu_r_max = np.nanmax(mu_r_arr[np.isfinite(mu_r_arr) & (np.abs(H) > 1e-4)])
        except Exception:
            Hc = Br = loop_area = mu_r_max = np.nan

        if np.max(np.abs(H)) < 1.0 or np.max(np.abs(B)) < 1e-4:
            msg = (msg + " | " if msg else "") + "⚠️ Low signal — results may be noisy"
        if f0 > 0 and ratio < 20:
            msg = (msg + " | " if msg else "") + f"⚠️ fs/f0={ratio:.1f} < 20 — increase sample rate"

        log_debug(f"[BH] Peak H={np.max(H):.3g} A/m  Peak B={np.max(B):.3g} T  Hc={Hc:.3g} A/m  Br={Br:.3g} T  Area={loop_area:.3g} J/m³  μr_max={mu_r_max:.3g}")
        log_debug(f"[BH] fs={fs:.3f} Hz  f0≈{f0:.3f} Hz  THD(I)={thd_i:.1f}%  THD(V)={thd_v:.1f}%")

        # Data panel
        try:
            data_text.config(state=tk.NORMAL)
            data_text.delete(1.0, tk.END)
            data_text.insert(tk.END, f"N={N}  Ae={Ae:.2e} m²  le={le:.2e} m  Probe:{probe_mode} {probe_val}  Samples:{samples}  dt={dt:.2e} s\n")
            data_text.insert(tk.END, f"fs={fs:.2f} Hz  f0≈{f0:.3f} Hz  fs/f0={ratio:.1f}  THD(I)={thd_i:.1f}%  THD(V)={thd_v:.1f}%\n")
            data_text.insert(tk.END, f"Peak |H|={np.max(np.abs(H)):.3g} A/m  Peak |B|={np.max(np.abs(B)):.3g} T  Area={loop_area:.3g} J/m³\n")
            data_text.insert(tk.END, f"Coercivity Hc={Hc:.3g} A/m  Remanence Br={Br:.3g} T  Max μr={mu_r_max:.3g}\n")
            data_text.insert(tk.END, "H (A/m): " + np.array2string(H[:8], precision=3, separator=", "))
            if len(H) > 16:
                data_text.insert(tk.END, " ... ")
                data_text.insert(tk.END, np.array2string(H[-8:], precision=3, separator=", "))
            data_text.insert(tk.END, "\nB (T):   " + np.array2string(B[:8], precision=5, separator=", "))
            if len(B) > 16:
                data_text.insert(tk.END, " ... ")
                data_text.insert(tk.END, np.array2string(B[-8:], precision=5, separator=", "))
            data_text.config(state=tk.DISABLED)
        except Exception:
            pass

        # CSV logging (compact)
        if not hasattr(do_acquire_and_plot, "csv_path"):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            bh_folder = os.path.join("oszi_csv", "bh-curve")
            os.makedirs(bh_folder, exist_ok=True)
            do_acquire_and_plot.csv_path = os.path.join(bh_folder, f"bhcurve_log_{timestamp}.csv")
            do_acquire_and_plot.run_index = 0
        csv_path = do_acquire_and_plot.csv_path
        do_acquire_and_plot.run_index += 1
        write_header = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
        try:
            with open(csv_path, "a", newline="") as f:
                writer = csv.writer(f)
                if write_header:
                    idn = safe_query(app_state.scope, "*IDN?", "Unknown") if getattr(app_state, "scope", None) else "Unknown"
                    writer.writerow(["# BH-curve data log"])
                    writer.writerow(["# Device", idn, "N", N, "Ae (m^2)", Ae, "le (m)", le, "Probe", probe_mode, "Probe Value", probe_val, "Samples", samples, "dt (s)", dt])
                    writer.writerow(["# Columns: run_index, time_iso, H (A/m), B (T)"])
                for hval, bval in zip(H, B):
                    writer.writerow([do_acquire_and_plot.run_index, datetime.now().isoformat(), hval, bval])
                writer.writerow([])
        except Exception as e:
            log_debug(f"[BH] CSV write error: {e}")

        # Optional detailed CSV
        if detailed_csv_var.get():
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                bh_folder = os.path.join("oszi_csv", "bh-curve")
                os.makedirs(bh_folder, exist_ok=True)
                detailed_path = os.path.join(bh_folder, f"bhcurve_samples_{timestamp}_run{do_acquire_and_plot.run_index}.csv")
                t_proc = np.arange(len(H)) * (dt_eff if 'dt_eff' in locals() else dt)
                with open(detailed_path, "w", newline="") as f:
                    writer = csv.writer(f)
                    idn = safe_query(app_state.scope, "*IDN?", "Unknown") if getattr(app_state, "scope", None) else "Unknown"
                    writer.writerow(["# Device", idn])
                    writer.writerow(["# Columns: t(s), V(V), I(A), H(A/m), B(T)"])
                    for k in range(len(H)):
                        writer.writerow([t_proc[k], float(Vwave_cyc[k]), float(Iwave_cyc[k]), float(H[k]), float(B[k])])
            except Exception as e:
                log_debug(f"[BH] Detailed CSV write error: {e}")

        # Plot
        ax.clear()
        fig = ax.get_figure()
        ax.set_facecolor("#1a1a1a")
        fig.patch.set_facecolor("#1a1a1a")
        for spine in ax.spines.values():
            spine.set_color('#cccccc')
        ax.tick_params(axis='both', colors='white')
        ax.grid(True, color="#444444", alpha=0.5)
        ax.set_title("B-H (Hysteresis) Curve")
        ax.set_xlabel("Magnetic Field H = N·I / le   (A/m)")
        ax.set_ylabel("Flux Density B = ∫V dt / (N·Ae)   (T)")
        ax.xaxis.label.set_color('white')
        ax.yaxis.label.set_color('white')
        ax.title.set_color('white')

        MAX_PLOT = 5000
        if len(H) > MAX_PLOT:
            step = len(H) // MAX_PLOT
            H_plot = H[::step]
            B_plot = B[::step]
        else:
            H_plot, B_plot = H, B

        # History
        if auto_var.get():
            if len(history) > 30:
                history.pop(0)
            history.append((np.copy(H_plot), np.copy(B_plot)))

        # Heatmap/fade
        if auto_var.get() and len(history) > 1:
            cmap = cm.get_cmap('plasma')
            for i, (h_hist, b_hist) in enumerate(history[:-1]):
                tcol = i / (len(history) - 2 + 1e-6)
                color = cmap(tcol)
                ax.plot(h_hist, b_hist, color=color, linewidth=1.3, alpha=0.7)
            ax.plot(H_plot, B_plot, color='yellow', marker='o', linestyle='None', markersize=3, label="Current")
        else:
            ax.plot(H_plot, B_plot, color='#00eaff', lw=1.8, label="Current")

        # Overlay previous
        if overlay and last_HB[0] is not None and last_HB[1] is not None:
            ax.plot(last_HB[0], last_HB[1], color="red", alpha=0.55, label="Previous")

        # Axis limits — tight (min/max) or symmetric ±max
        try:
            if tight_fit_var.get():
                hmin, hmax = float(np.min(H_plot)), float(np.max(H_plot))
                bmin, bmax = float(np.min(B_plot)), float(np.max(B_plot))
                if hmax == hmin:
                    hmin -= 1.0; hmax += 1.0
                if bmax == bmin:
                    bmin -= 1e-3; bmax += 1e-3
                hm = 0.08 * (hmax - hmin)
                bm = 0.08 * (bmax - bmin)
                ax.set_xlim(hmin - hm, hmax + hm)
                ax.set_ylim(bmin - bm, bmax + bm)
            else:
                hx = float(np.max(np.abs(H_plot)))
                bx = float(np.max(np.abs(B_plot)))
                if hx > 0 and bx > 0:
                    ax.set_xlim(-1.1 * hx, 1.1 * hx)
                    ax.set_ylim(-1.1 * bx, 1.1 * bx)
        except Exception:
            pass

        # Equal aspect option
        try:
            ax.set_aspect('equal' if equal_aspect_var.get() else 'auto', adjustable='datalim')
        except Exception:
            pass

        # Make scientific offset text visible on dark theme
        try:
            ax.xaxis.get_offset_text().set_color('white')
            ax.yaxis.get_offset_text().set_color('white')
        except Exception:
            pass

        leg = ax.legend(loc="upper left", facecolor="#1a1a1a", edgecolor="#444444", labelcolor="white", fontsize=9)
        if leg:
            for text in leg.get_texts():
                text.set_color("white")
        canvas.draw()

        last_HB[0], last_HB[1] = (H, B)
        status_var.set((msg + " | " if msg else "") + f"Peak H: {np.max(np.abs(H)):.2f} A/m, Peak B: {np.max(np.abs(B)):.4f} T")

    # Wire buttons
    btn_acquire.config(command=do_acquire_and_plot)

    # Auto-refresh loop — guarded + cancellable
    def auto_refresh_loop():
        try:
            if getattr(app_state, "is_shutting_down", False) or not tab_frame.winfo_exists():
                return
            if auto_var.get():
                do_acquire_and_plot()
        except Exception as e:
            log_debug(f"[BH] auto refresh error: {e}")
        finally:
            try:
                if not getattr(app_state, "is_shutting_down", False) and tab_frame.winfo_exists():
                    after_id[0] = tab_frame.after(int(max(1, interval_var.get())) * 1000, auto_refresh_loop)
            except Exception:
                pass

    after_id[0] = tab_frame.after(500, auto_refresh_loop)

    # PNG save handler
    def save_png():
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            outdir = os.path.join("oszi_csv", "bh-curve")
            os.makedirs(outdir, exist_ok=True)
            path = os.path.join(outdir, f"bhcurve_{timestamp}.png")
            idn = safe_query(app_state.scope, "*IDN?", "Unknown") if getattr(app_state, "scope", None) else "Unknown"
            meta = f"IDN: {idn}  |  N={entry_N.get()}  Ae={float(entry_Ae.get())*1e-6:.2e} m²  le={float(entry_le.get())*1e-3:.2e} m  ts={timestamp}"
            fig_ = ax.get_figure()
            txt = fig_.text(0.01, 0.01, meta, color='white', fontsize=7)
            fig_.savefig(path, facecolor=fig_.get_facecolor(), dpi=150, bbox_inches='tight')
            txt.remove()
            status_var.set(f"✅ Saved {path}")
            log_debug(f"[BH] Saved PNG: {path}")
        except Exception as e:
            status_var.set(f"❌ PNG save error: {e}")
            log_debug(f"[BH] PNG save error: {e}")

    btn_png.config(command=save_png)

    # --- Shutdown hook to cancel timers and avoid '...scroll' errors ---
    shutdown_done = [False]

    def _shutdown(*_):
        if shutdown_done[0]:
            return
        shutdown_done[0] = True
        try:
            if after_id[0] is not None:
                tab_frame.after_cancel(after_id[0])
                after_id[0] = None
        except Exception:
            pass
        try:
            data_text.configure(yscrollcommand=None)
        except Exception:
            pass
        log_debug("🛑 Stopping auto-refresh", level="MINIMAL")

    tab_frame._shutdown = _shutdown
    tab_frame.bind("<Destroy>", _shutdown)