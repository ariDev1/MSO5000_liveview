# gui/bh_curve.py
import os
import csv
from datetime import datetime

import tkinter as tk
from tkinter import ttk
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from scpi.interface import connect_scope, safe_query, scpi_lock
from utils.debug import log_debug
import app.app_state as app_state

mu0 = 4 * np.pi * 1e-7  # H/m, permeability of free space


def extract_one_cycle(waveform):
    """
    Extract indices for one full period in the waveform, based on zero-crossings
    with the same slope (best for periodic signals like current).
    Returns (start_idx, end_idx) inclusive of start, exclusive of end.
    """
    waveform = np.asarray(waveform)
    crossings = np.where(np.diff(np.signbit(waveform)))[0]
    if len(crossings) < 2:
        return 0, len(waveform)
    # Try to find two zero-crossings with the same direction (rising/rising or falling/falling)
    for i in range(1, len(crossings)):
        s0 = np.sign(waveform[crossings[0]+1] - waveform[crossings[0]])
        si = np.sign(waveform[crossings[i]+1] - waveform[crossings[i]])
        if si == s0:
            return crossings[0], crossings[i]
    # Fallback: just use first two crossings
    return crossings[0], crossings[1]

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
    import numpy as np
    import tkinter as tk
    from tkinter import ttk

    tab_frame.columnconfigure(0, weight=1)
    tab_frame.rowconfigure(3, weight=1)  # plot area grows

    # -- Header strip --
    header_frame = tk.Frame(tab_frame, bg="#226688", padx=8, pady=8)
    header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(12, 2))
    for col in range(16):
        header_frame.grid_columnconfigure(col, weight=1 if col != 0 else 0)

    # Inputs
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
    entry_ich.insert(0, "3")
    entry_ich.grid(row=1, column=1, sticky="w", padx=(0,8))
    tk.Label(header_frame, text="Voltage Ch:", bg="#226688", fg="white").grid(row=1, column=2, sticky="e", padx=(0,2))
    entry_vch = ttk.Entry(header_frame, width=6)
    entry_vch.insert(0, "1")
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
    auto_cycle_var = tk.BooleanVar(value=False)
    auto_cycle_check = ttk.Checkbutton(header_frame, text="Auto one cycle", variable=auto_cycle_var)
    auto_cycle_check.grid(row=2, column=9, columnspan=2, sticky="w", padx=(4,0))

    # ---- Auto refresh controls ----
    auto_var = tk.BooleanVar(value=False)
    auto_check = ttk.Checkbutton(header_frame, text="Auto", variable=auto_var)
    auto_check.grid(row=2, column=11, sticky="w", padx=(4,0))
    interval_var = tk.IntVar(value=5)
    interval_spin = ttk.Spinbox(header_frame, from_=1, to=60, width=3, textvariable=interval_var)
    interval_spin.grid(row=2, column=12, sticky="w")
    tk.Label(header_frame, text="s", bg="#226688", fg="white").grid(row=2, column=13, sticky="w")

    # --- Status bar
    status_var = tk.StringVar(value="")
    status_label = tk.Label(tab_frame, textvariable=status_var,
        fg="#bbbbbb", bg="#1a1a1a", font=("TkDefaultFont", 9))
    status_label.grid(row=1, column=0, sticky="ew", padx=10, pady=(3, 2))

    # --- Data output panel
    data_text = tk.Text(tab_frame, height=7, font=("Courier", 9), bg="#181818", fg="#eeeeee", wrap="none")
    data_text.grid(row=2, column=0, sticky="ew", padx=10, pady=(0,2))
    data_text.config(state=tk.DISABLED)

    # --- Plot frame
    plot_frame = tk.Frame(tab_frame, bg="#202020", bd=1, relief="solid")
    plot_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(2,8))
    plot_frame.rowconfigure(0, weight=1)
    plot_frame.columnconfigure(0, weight=1)

    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    fig, ax = plt.subplots(figsize=(5, 4), dpi=100, facecolor="#1a1a1a")
    canvas = FigureCanvasTkAgg(fig, master=plot_frame)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
    ax.set_facecolor("#222222")
    ax.set_xlabel("H (A/m)")
    ax.set_ylabel("B (T)")
    last_HB = [None, None]

    # --- Heatmap history buffer ---
    history = []

    # --- Main acquisition/plot function ---
    def do_acquire_and_plot():
        import numpy as np
        from scpi.interface import safe_query, scpi_lock
        from app.app_state import scope
        from time import sleep

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
        except Exception as e:
            status_var.set(f"Invalid input: {e}")
            return

        if not scope:
            status_var.set("Scope not connected.")
            return

        # Fetch current waveform
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

        # Fetch voltage waveform
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
            Vwave = Vwave - np.mean(Vwave)
        except Exception as e:
            status_var.set(f"Failed to fetch voltage: {e}")
            return

        # Check sample interval
        dt = xinc
        if abs(xinc - xinc_v) > 1e-9:
            status_var.set("Sample intervals for current and voltage do not match! (adjust timebase?)")
            return

        # Auto-extract one cycle if enabled
        def extract_one_cycle(waveform):
            waveform = np.asarray(waveform)
            crossings = np.where(np.diff(np.signbit(waveform)))[0]
            if len(crossings) < 2:
                return 0, len(waveform)
            for i in range(1, len(crossings)):
                s0 = np.sign(waveform[crossings[0]+1] - waveform[crossings[0]])
                si = np.sign(waveform[crossings[i]+1] - waveform[crossings[i]])
                if si == s0:
                    return crossings[0], crossings[i]
            return crossings[0], crossings[1]

        if auto_cycle_var.get():
            idx0, idx1 = extract_one_cycle(Iwave)
            idx0 = max(0, idx0)
            idx1 = min(len(Iwave)-1, idx1)
            if idx1 - idx0 > 20:
                Iwave_cyc = Iwave[idx0:idx1]
                Vwave_cyc = Vwave[idx0:idx1]
                samples_cyc = idx1 - idx0
                msg = f"Auto one cycle: {samples_cyc} points"
            else:
                Iwave_cyc = Iwave
                Vwave_cyc = Vwave
                msg = "⚠️ Could not detect full cycle—showing all data"
        else:
            Iwave_cyc = Iwave
            Vwave_cyc = Vwave

        # Compute B and H
        def calculate_bh_curve(I_waveform, V_waveform, dt, N, Ae, le):
            H = (N * I_waveform) / le
            flux = np.cumsum(V_waveform) * dt
            B = flux / (N * Ae)
            return H, B

        try:
            H, B = calculate_bh_curve(Iwave_cyc, Vwave_cyc, dt, N, Ae, le)
            if len(H) == 0 or len(B) == 0:
                status_var.set("Computed arrays are empty!")
                return

            # --- Data panel update ---
            data_text.config(state=tk.NORMAL)
            data_text.delete(1.0, tk.END)
            data_text.insert(tk.END, f"N={N}  Ae={Ae:.2e} m²  le={le:.2e} m  Probe:{probe_mode} {probe_val}  Samples:{samples}  dt={dt:.2e} s\n")
            data_text.insert(tk.END, f"Peak H={np.max(H):.3g} A/m  Peak B={np.max(B):.3g} T  Min H={np.min(H):.3g} A/m  Min B={np.min(B):.3g} T\n")

            mu0 = 4 * np.pi * 1e-7
            def interpolate_crossing(x, y):
                idxs = np.where(np.diff(np.signbit(y)))[0]
                if not len(idxs):
                    return np.nan
                i = idxs[0]
                x0, x1 = x[i], x[i+1]
                y0, y1 = y[i], y[i+1]
                if y1 == y0:
                    return x0
                return x0 + (0 - y0) * (x1 - x0) / (y1 - y0)
            Hc = interpolate_crossing(H, B)
            Br = interpolate_crossing(B, H)
            loop_area = np.abs(np.trapz(B, H))
            with np.errstate(divide='ignore', invalid='ignore'):
                mu_r_arr = np.abs(B / (H + 1e-12)) / mu0
                mu_r_max = np.nanmax(mu_r_arr[np.isfinite(mu_r_arr) & (np.abs(H) > 1e-4)])
            data_text.insert(tk.END, f"Coercivity Hc={Hc:.3g} A/m  Remanence Br={Br:.3g} T  Loop Area={loop_area:.3g} J/m³\n")
            data_text.insert(tk.END, f"Max Rel. Permeability μr={mu_r_max:.3g}\n")
            data_text.insert(tk.END, "H (A/m): " + np.array2string(H[:8], precision=3, separator=", "))
            if len(H) > 16:
                data_text.insert(tk.END, " ... ")
                data_text.insert(tk.END, np.array2string(H[-8:], precision=3, separator=", "))
            data_text.insert(tk.END, "\nB (T):   " + np.array2string(B[:8], precision=5, separator=", "))
            if len(B) > 16:
                data_text.insert(tk.END, " ... ")
                data_text.insert(tk.END, np.array2string(B[-8:], precision=5, separator=", "))
            data_text.config(state=tk.DISABLED)

            # --- CSV logging for bh-curve data ---
            if not hasattr(do_acquire_and_plot, "csv_path"):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                bh_folder = os.path.join("oszi_csv", "bh-curve")
                os.makedirs(bh_folder, exist_ok=True)
                do_acquire_and_plot.csv_path = os.path.join(bh_folder, f"bhcurve_log_{timestamp}.csv")
                do_acquire_and_plot.run_index = 0

            csv_path = do_acquire_and_plot.csv_path
            do_acquire_and_plot.run_index += 1

            write_header = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0

            with open(csv_path, "a", newline="") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(["# BH-curve data log"])
                    #writer.writerow(["# N", N, "Ae (m²)", Ae, "le (m)", le, "Probe", probe_mode, probe_val, "Samples", samples, "dt (s)", dt])
                    writer.writerow([
                        "# N", N, 
                        "Ae (m²)", Ae, 
                        "le (m)", le, 
                        "Probe", probe_mode, 
                        "Probe Value", probe_val, 
                        "Samples", samples, 
                        "dt (s)", dt
                    ])

                    writer.writerow(["# Columns: run_index, time_iso, H (A/m), B (T)"])
                for idx, (hval, bval) in enumerate(zip(H, B)):
                    writer.writerow([
                        do_acquire_and_plot.run_index,
                        datetime.now().isoformat(),
                        hval, bval
                    ])
                writer.writerow([])  # blank line between runs            

            # --- Heatmap/plotting ---
            MAX_PLOT = 5000
            if len(H) > MAX_PLOT:
                step = len(H) // MAX_PLOT
                H_plot = H[::step]
                B_plot = B[::step]
            else:
                H_plot, B_plot = H, B

            # Update history for heatmap if auto is on
            if auto_var.get():
                if len(history) > 30:   # Keep last 30 traces
                    history.pop(0)
                history.append((np.copy(H_plot), np.copy(B_plot)))

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

            # --- Heatmap: faded history traces ---
            if auto_var.get() and len(history) > 1:
                cmap = cm.get_cmap('plasma')
                for i, (h_hist, b_hist) in enumerate(history[:-1]):
                    t = i / (len(history) - 2 + 1e-6)
                    color = cmap(t)
                    ax.plot(h_hist, b_hist, color=color, linewidth=1.3, alpha=0.7)

            if auto_var.get() and len(history) > 1:
                # In auto mode with history: show current as yellow dots
                ax.plot(H_plot, B_plot, color='yellow', marker='o', linestyle='None', markersize=3, label="Current")

            else:
                # In manual/one-shot mode: show current as electric blue line
                ax.plot(H_plot, B_plot, color='#00eaff', lw=1.8, label="Current")


            # Overlay previous (optional)
            if overlay and last_HB[0] is not None and last_HB[1] is not None:
                ax.plot(last_HB[0], last_HB[1], color="red", alpha=0.5, label="Previous")

            leg = ax.legend(loc="upper left", facecolor="#1a1a1a", edgecolor="#444444", labelcolor="white", fontsize=9)
            if leg:
                for text in leg.get_texts():
                    text.set_color("white")
            canvas.draw()


            last_HB[0], last_HB[1] = (H, B)
        except Exception as e:
            status_var.set(f"Failed to compute B/H: {e}")
            return

        status_var.set(
            (msg if auto_cycle_var.get() else "") +
            f" | Peak H: {np.max(np.abs(H)):.2f} A/m, Peak B: {np.max(np.abs(B)):.4f} T"
        )

    # --- Auto-refresh loop ---
    def auto_refresh_loop():
        if auto_var.get():
            do_acquire_and_plot()
        tab_frame.after(interval_var.get() * 1000, auto_refresh_loop)
    auto_refresh_loop()

    btn_acquire.config(command=do_acquire_and_plot)
