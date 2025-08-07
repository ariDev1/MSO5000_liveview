# gui/bh_curve.py

import tkinter as tk
from tkinter import ttk
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from scpi.interface import connect_scope, safe_query, scpi_lock
from utils.debug import log_debug
import app.app_state as app_state

def calculate_bh_curve(I_waveform, V_waveform, dt, N, Ae, le):
    H = (N * I_waveform) / le
    flux = np.cumsum(V_waveform) * dt
    B = flux / (N * Ae)
    return H, B

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
    xinc = float(pre[4])
    xorig = float(pre[5])
    yinc = float(pre[7])
    yorig = float(pre[8])
    yref = float(pre[9])
    probe = float(safe_query(scope, f":{chan}:PROB?", "1.0"))

    raw = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)
    if stop_scope:
        scope.write(":RUN")
    return raw, xinc, xorig, yinc, yorig, yref, probe

def setup_bh_curve_tab(tab_frame, ip, root):
    tab_frame.columnconfigure(0, weight=1)
    tab_frame.rowconfigure(2, weight=1)

    # -- Polished header strip like Power Analysis tab --
    header_frame = tk.Frame(tab_frame, bg="#226688", padx=8, pady=8)
    header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(12, 2))
    for col in range(12):
        header_frame.grid_columnconfigure(col, weight=1 if col != 0 else 0)

    # Inputs: white text for contrast
    tk.Label(header_frame, text="N (turns):", bg="#226688", fg="white").grid(row=0, column=0, sticky="e", padx=(0,2))
    entry_N = ttk.Entry(header_frame, width=6)
    entry_N.insert(0, "20")
    entry_N.grid(row=0, column=1, sticky="w", padx=(0,8))

    tk.Label(header_frame, text="Ae (mm²):", bg="#226688", fg="white").grid(row=0, column=2, sticky="e", padx=(0,2))
    entry_Ae = ttk.Entry(header_frame, width=8)
    entry_Ae.insert(0, "25")
    entry_Ae.grid(row=0, column=3, sticky="w", padx=(0,8))

    tk.Label(header_frame, text="le (mm):", bg="#226688", fg="white").grid(row=0, column=4, sticky="e", padx=(0,2))
    entry_le = ttk.Entry(header_frame, width=8)
    entry_le.insert(0, "50")
    entry_le.grid(row=0, column=5, sticky="w", padx=(0,8))

    tk.Label(header_frame, text="Current Ch:", bg="#226688", fg="white").grid(row=1, column=0, sticky="e", padx=(0,2))
    entry_ich = ttk.Entry(header_frame, width=6)
    entry_ich.insert(0, "1")
    entry_ich.grid(row=1, column=1, sticky="w", padx=(0,8))

    tk.Label(header_frame, text="Voltage Ch:", bg="#226688", fg="white").grid(row=1, column=2, sticky="e", padx=(0,2))
    entry_vch = ttk.Entry(header_frame, width=6)
    entry_vch.insert(0, "2")
    entry_vch.grid(row=1, column=3, sticky="w", padx=(0,8))

    tk.Label(header_frame, text="Probe Type:", bg="#226688", fg="white").grid(row=1, column=4, sticky="e", padx=(0,2))
    probe_type = tk.StringVar(value="shunt")
    rb_shunt = tk.Radiobutton(header_frame, text="Shunt", variable=probe_type, value="shunt",
        bg="#226688", fg="white", selectcolor="#3388aa", activebackground="#3388aa", indicatoron=False, width=7)
    rb_shunt.grid(row=1, column=5, sticky="w")
    rb_clamp = tk.Radiobutton(header_frame, text="Clamp", variable=probe_type, value="clamp",
        bg="#226688", fg="white", selectcolor="#3388aa", activebackground="#3388aa", indicatoron=False, width=7)
    rb_clamp.grid(row=1, column=6, sticky="w", padx=(2,8))

    tk.Label(header_frame, text="Value (Ω or A/V):", bg="#226688", fg="white").grid(row=1, column=7, sticky="e", padx=(0,2))
    entry_probe_value = ttk.Entry(header_frame, width=8)
    entry_probe_value.insert(0, "0.1")
    entry_probe_value.grid(row=1, column=8, sticky="w", padx=(0,8))

    # Sampling options row
    tk.Label(header_frame, text="Points:", bg="#226688", fg="white").grid(row=2, column=0, sticky="e", padx=(0,2))
    entry_samples = ttk.Entry(header_frame, width=8)
    entry_samples.insert(0, "1000")
    entry_samples.grid(row=2, column=1, sticky="w", padx=(0,8))

    tk.Label(header_frame, text="Mode:", bg="#226688", fg="white").grid(row=2, column=2, sticky="e", padx=(0,2))
    point_mode_var = tk.StringVar(value="NORM")
    point_mode_box = ttk.Combobox(header_frame, textvariable=point_mode_var, values=["NORM", "RAW"], width=6, state="readonly")
    point_mode_box.grid(row=2, column=3, sticky="w", padx=(0,8))

    stop_scope_var = tk.BooleanVar(value=True)
    stop_scope_check = ttk.Checkbutton(header_frame, text="Stop scope for fetch", variable=stop_scope_var)
    stop_scope_check.grid(row=2, column=4, columnspan=2, sticky="w", padx=(0,8))

    overlay_var = tk.BooleanVar(value=False)
    overlay_check = ttk.Checkbutton(header_frame, text="Overlay previous", variable=overlay_var)
    overlay_check.grid(row=2, column=6, columnspan=2, sticky="w", padx=(0,8))

    btn_acquire = ttk.Button(header_frame, text="Acquire & Plot")
    btn_acquire.grid(row=2, column=8, sticky="e", padx=(0,10))

    # --- Status bar, like Power Analysis ---
    status_var = tk.StringVar(value="")
    status_label = tk.Label(tab_frame, textvariable=status_var,
        fg="#bbbbbb", bg="#1a1a1a", font=("TkDefaultFont", 9))
    status_label.grid(row=1, column=0, sticky="ew", padx=10, pady=(3, 2))

    # --- Plot frame, dark bg and subtle border ---
    plot_frame = tk.Frame(tab_frame, bg="#202020", bd=1, relief="solid")
    plot_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(2,8))
    plot_frame.rowconfigure(0, weight=1)
    plot_frame.columnconfigure(0, weight=1)

    fig, ax = plt.subplots(figsize=(5, 4), dpi=100, facecolor="#1a1a1a")
    canvas = FigureCanvasTkAgg(fig, master=plot_frame)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
    ax.set_facecolor("#222222")
    ax.set_xlabel("H (A/m)")
    ax.set_ylabel("B (T)")
    last_HB = [None, None]

    def do_acquire_and_plot():
        try:
            N = int(entry_N.get())
            Ae = float(entry_Ae.get()) * 1e-6  # mm² to m²
            le = float(entry_le.get()) * 1e-3  # mm to m
            ich = entry_ich.get().strip()
            vch = entry_vch.get().strip()
            probe_val = float(entry_probe_value.get())
            overlay = overlay_var.get()
            probe_mode = probe_type.get()
            samples = int(entry_samples.get())
            point_mode = point_mode_var.get()
            stop_scope = stop_scope_var.get()
        except Exception as e:
            status_var.set(f"Invalid input: {e}")
            return

        from app.app_state import scope
        if not scope:
            status_var.set("Scope not connected.")
            return

        # --- Fetch current waveform ---
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
            if len(raw_i) < samples:
                status_var.set(f"⚠️ Only {len(raw_i)} of {samples} points received for {chan_i}. Try slower timebase or increase memory depth.")
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

        # --- Fetch voltage waveform ---
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
            if len(raw_v) < samples:
                status_var.set(f"⚠️ Only {len(raw_v)} of {samples} points received for {chan_v}. Try slower timebase or increase memory depth.")
            Vwave = ((raw_v - yref_v) * yinc_v + yorig_v) * probe_v
        except Exception as e:
            status_var.set(f"Failed to fetch voltage: {e}")
            return

        # --- Sanity check: sample intervals match ---
        dt = xinc
        if abs(xinc - xinc_v) > 1e-9:
            status_var.set("Sample intervals for current and voltage do not match! (adjust timebase?)")
            return

        # --- Compute B and H ---
        try:
            H, B = calculate_bh_curve(Iwave, Vwave, dt, N, Ae, le)
            if len(H) == 0 or len(B) == 0:
                status_var.set("Computed arrays are empty!")
                return
            # Reduce points for plotting (still calculating with full resolution)
            MAX_PLOT = 5000
            if len(H) > MAX_PLOT:
                step = len(H) // MAX_PLOT
                H_plot = H[::step]
                B_plot = B[::step]
            else:
                H_plot, B_plot = H, B

            # --- Plot (true dark mode) ---
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

            if overlay and last_HB[0] is not None and last_HB[1] is not None:
                ax.plot(last_HB[0], last_HB[1], color="red", alpha=0.5, label="Previous")
            ax.plot(H_plot, B_plot, color="magenta", lw=1, linestyle="--", marker="o", markersize=2, markerfacecolor="white", alpha=0.8, label="Current")

            leg = ax.legend(loc="upper left", facecolor="#1a1a1a", edgecolor="#444444", labelcolor="white", fontsize=9)
            if leg:
                for text in leg.get_texts():
                    text.set_color("white")
            canvas.draw()

            last_HB[0], last_HB[1] = (H, B)
        except Exception as e:
            status_var.set(f"Failed to compute B/H: {e}")
            return

        status_var.set(f"Points: {len(H)}  |  Peak H: {np.max(np.abs(H)):.2f} A/m, Peak B: {np.max(np.abs(B)):.4f} T")

    btn_acquire.config(command=do_acquire_and_plot)
