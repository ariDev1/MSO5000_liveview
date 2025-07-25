# gui/power_analysis.py

import os, csv, math, time
from datetime import datetime
import tkinter as tk
from tkinter import ttk
import numpy as np
import matplotlib.pyplot as plt
import app.app_state as app_state
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from scpi.interface import connect_scope, safe_query
from scpi.waveform import compute_power_from_scope
from scpi.data import scpi_data
from utils.debug import log_debug, set_debug_level

def setup_power_analysis_tab(tab_frame, ip, root):
    if app_state.is_logging_active:
        log_debug("⚠️ Cannot start power analysis during long-time logging.")
        return
    app_state.is_power_analysis_active = False
    #power_csv_path = None
    global_power_csv_path = [None]  # use list for mutability
    shutdown_hook = lambda: None  # placeholder

    correction_factor = tk.StringVar(value="1.0")
    def validate_correction_input(*args):
        val = correction_factor.get().strip()
        if val == "":
            correction_factor.set("1.0")

    correction_factor.trace_add("write", validate_correction_input)

    # === Power Analysis Tab ===
    power_frame = tab_frame
    power_frame.columnconfigure(0, weight=1)
    power_frame.columnconfigure(1, weight=3)

    # --- Channel Selection (Colored Background Row) ---
    ch_input_frame = tk.Frame(power_frame, bg="#226688")
    ch_input_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

    # Voltage Channel
    tk.Label(ch_input_frame, text="Voltage Ch:", bg="#226688", fg="white").grid(row=0, column=0, sticky="e", padx=(2, 2), pady=4)
    entry_vch = ttk.Entry(ch_input_frame, width=8)
    entry_vch.grid(row=0, column=1, sticky="w", padx=(0, 6), pady=4)

    # Current Channel
    tk.Label(ch_input_frame, text="Current Ch:", bg="#226688", fg="white").grid(row=0, column=2, sticky="e", padx=(2, 2), pady=4)
    entry_ich = ttk.Entry(ch_input_frame, width=8)
    entry_ich.grid(row=0, column=3, sticky="w", padx=(0, 6), pady=4)

    # Correction Factor Field
    tk.Label(ch_input_frame, text="Correction:", bg="#226688", fg="white").grid(row=0, column=4, sticky="e", padx=(2, 2), pady=4)
    entry_corr = ttk.Entry(ch_input_frame, width=8, textvariable=correction_factor)
    entry_corr.grid(row=0, column=5, sticky="w", padx=(0, 6), pady=4)

    expected_power = tk.StringVar(value="")
    tk.Label(ch_input_frame, text="Expected P (W):", bg="#226688", fg="white").grid(row=0, column=6, sticky="e", padx=(2, 2), pady=4)
    entry_expected = ttk.Entry(ch_input_frame, width=8, textvariable=expected_power)
    entry_expected.grid(row=0, column=7, sticky="w", padx=(0, 6), pady=4)

    # Reference Info (shifted right)
    initial_ref = scpi_data.get("freq_ref", "N/A")
    ref_text = tk.StringVar(value=f"Reference: {initial_ref}")
    tk.Label(ch_input_frame, textvariable=ref_text, bg="#226688", fg="white").grid(row=0, column=8, sticky="w", padx=(10, 0), pady=4)

    # Stretch last column
    ch_input_frame.grid_columnconfigure(11, weight=1)


    # --- Probe Scaling Controls ---
    probe_frame = ttk.Frame(power_frame)
    probe_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

    ttk.Label(probe_frame, text="Current Probe Type:").grid(row=0, column=0, sticky="e", padx=5)

    probe_type = tk.StringVar(value="shunt")

    def set_probe_type(mode):
        probe_type.set(mode)
        update_current_scale()

    probe_mode_frame = ttk.Frame(probe_frame)
    probe_mode_frame.grid(row=0, column=1, sticky="w", padx=5)

    btn_shunt = tk.Radiobutton(probe_mode_frame, text="Shunt", variable=probe_type, value="shunt",
        command=lambda: set_probe_type("shunt"),
        bg="#2d2d2d", fg="#ffffff", selectcolor="#555555",
        activebackground="#333333", indicatoron=False, width=6, relief="raised")
    btn_shunt.pack(side="left", padx=1)

    btn_clamp = tk.Radiobutton(probe_mode_frame, text="Clamp", variable=probe_type, value="clamp",
        command=lambda: set_probe_type("clamp"),
        bg="#2d2d2d", fg="#ffffff", selectcolor="#555555",
        activebackground="#333333", indicatoron=False, width=6, relief="raised")
    btn_clamp.pack(side="left", padx=1)

    ttk.Label(probe_frame, text="Probe Value (Ω or A/V):").grid(row=0, column=2, sticky="e", padx=15)
    
    ttk.Label(
        probe_frame,
        text=(
            "Tip: Use 0.01 for 10mΩ shunt, or 1.0 if scope shows Amps directly. For better power accuracy, enable 20MHz BW limit on Channels it filters noise, stabilizes FFT phase and PF. Avoid >20MHz unless needed."
        ),
        foreground="#bbbbbb", background="#1a1a1a",
        wraplength=720, font=("TkDefaultFont", 8)
    ).grid(
        row=1, column=0, columnspan=6, sticky="w", padx=5, pady=(2, 8)
    )

    entry_probe_value = ttk.Entry(probe_frame, width=10)
    entry_probe_value.insert(0, "1.0")
    entry_probe_value.grid(row=0, column=3, sticky="w", padx=5)

    ttk.Label(probe_frame, text="→ Base Scale (A/V):").grid(row=0, column=4, sticky="e", padx=15)
    entry_current_scale = ttk.Entry(probe_frame, width=10, state="readonly")
    entry_current_scale.grid(row=0, column=5, sticky="w", padx=5)

    # Initialize calculated scale
    def update_current_scale(*args):
        try:
            val = float(entry_probe_value.get())
            mode = probe_type.get()
            if mode == "shunt":
                scale = 1.0 / val
            elif mode == "clamp":
                scale = 1.0 / (val / 1000.0)
            else:
                scale = 1.0
            entry_current_scale.configure(state="normal")
            entry_current_scale.delete(0, tk.END)
            entry_current_scale.insert(0, f"{scale:.4f}")
            entry_current_scale.configure(state="readonly")
        except Exception:
            entry_current_scale.configure(state="normal")
            entry_current_scale.delete(0, tk.END)
            entry_current_scale.insert(0, "ERR")
            entry_current_scale.configure(state="readonly")

    probe_type.trace_add("write", update_current_scale)
    entry_probe_value.bind("<KeyRelease>", update_current_scale)

    update_current_scale()

    # --- Control Variables ---
    remove_dc_var = tk.BooleanVar(value=True)
    refresh_var = tk.BooleanVar(value=False)
    refresh_interval = tk.IntVar(value=5)

    # --- Control Row ---
    control_row = ttk.Frame(power_frame)
    control_row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=(0, 10))
    control_row.columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

    ttk.Checkbutton(control_row, text="Remove DC Offset", variable=remove_dc_var,
                    style="DC.TCheckbutton").grid(row=0, column=0, padx=3)
    
    def toggle_auto_refresh():
        if not refresh_var.get():  # Means the checkbox is being turned OFF
            stop_auto_refresh()

    def auto_calibrate():
        log_debug("🧪 Auto-calibrate triggered")
        log_debug(f"🧪 GUI correction factor entry now = {entry_corr.get()}")

        # Try to read manually entered expected power
        try:
            exp_p = float(expected_power.get().strip())
            if exp_p == 0:
                raise ValueError("Expected power must not be 0")
            log_debug(f"⚙️ Using manually entered expected P = {exp_p:.3f} W")
        except Exception as e:
            log_debug(f"⚠️ Invalid expected power: {e}")
            return

        # Connect to scope
        from app.app_state import scope
        if not scope:
            log_debug("❌ Scope not connected")
            return

        # Recalculate base probe scale (without any correction)
        try:
            val = float(entry_probe_value.get())
            mode = probe_type.get()
            if mode == "shunt":
                raw_scale = 1.0 / val
            elif mode == "clamp":
                raw_scale = 1.0 / (val / 1000.0)
            else:
                raw_scale = 1.0
            log_debug(f"🔎 Raw scale used for calibration: {raw_scale:.4f} A/V")
        except Exception as e:
            raw_scale = 1.0
            log_debug(f"⚠️ Could not calculate raw probe scale — defaulting to 1.0 ({e})")

        # Run actual power analysis using raw scale
        try:
            vch = entry_vch.get().strip()
            ich = entry_ich.get().strip()
            result = compute_power_from_scope(
                scope, vch, ich,
                remove_dc=remove_dc_var.get(),
                current_scale=raw_scale  # no correction applied!
            )
            measured_p = result.get("Real Power (P)", None)
            if measured_p is None or measured_p <= 0:
                log_debug("⚠️ Invalid measured power — auto-calibration aborted")
                return

            log_debug(f"📐 Measured Power = {measured_p:.3f} W  |  Target = {exp_p:.3f} W")
            new_corr = exp_p / measured_p
            correction_factor.set(f"{new_corr:.4f}")
            log_debug(f"✅ Auto-calibrated correction factor: ×{new_corr:.4f}")
            analyze_power()

        except Exception as e:
            log_debug(f"❌ Auto-calibration failed: {e}")


    refresh_chk = ttk.Checkbutton(control_row, text="Auto Measure", variable=refresh_var,
        style="Refresh.TCheckbutton", command=toggle_auto_refresh)
    refresh_chk.grid(row=0, column=3, padx=3)

    def plot_last_power_log():
        import glob
        import subprocess

        files = glob.glob("oszi_csv/power_log_*.csv")
        if not files:
            log_debug("⚠️ No power log files found in oszi_csv/")
            return

        latest_file = max(files, key=os.path.getmtime)

        try:
            scale = float(entry_current_scale.get())
            log_debug(f"⚙️ Plot scale factor: {scale:.4f} A/V (used for all power values)")
        except Exception:
            scale = 1.0
            log_debug("⚠️ Invalid scale factor — defaulting to 1.0")

        log_debug(f"📊 Launching plot for {latest_file} with scale={scale}")
        subprocess.Popen(["python3", "utils/plot_rigol_csv.py", latest_file, "--scale", str(scale)])

    ttk.Button(control_row, text="📈 Plot Last Power Log",
           command=plot_last_power_log, style="Action.TButton").grid(row=0, column=2, padx=3)
    
    ttk.Button(control_row, text="🧪 Auto-Calibrate", command=auto_calibrate, style="Action.TButton").grid(row=0, column=6, padx=3)
    log_debug("🧪 Auto-calibrate button created and wired correctly")

    ttk.Label(control_row, text="Interval (s):").grid(row=0, column=4, padx=(20, 3), sticky="e")
    ttk.Spinbox(control_row, from_=2, to=60, width=5, textvariable=refresh_interval).grid(row=0, column=5, padx=(0, 5), sticky="w")

    # --- Custom Header with Inline DC Offset Status ---
    result_header = tk.Frame(power_frame, bg="#1a1a1a")
    result_header.grid(row=3, column=0, columnspan=2, sticky="ew", padx=5, pady=(5, 0))
    result_header.grid_columnconfigure(0, weight=0)
    result_header.grid_columnconfigure(1, weight=1)

    tk.Label(result_header, text="📊 Analysis Output", font=("TkDefaultFont", 10, "bold"),
             bg="#1a1a1a", fg="white").grid(row=0, column=0, sticky="w")

    dc_status_var = tk.StringVar(value="DC Offset Removal is OFF — full waveform is analyzed.")
    tk.Label(result_header, textvariable=dc_status_var, bg="#1a1a1a", fg="#cccccc",
             font=("TkDefaultFont", 9)).grid(row=0, column=1, sticky="e", padx=(10, 5))

    # --- Output Box below it ---
    result_frame = tk.Frame(power_frame, bg="#202020", bd=1, relief="solid")
    result_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=5, pady=(0, 5))
    power_frame.rowconfigure(4, weight=1)


    # Create a wrapper frame inside the LabelFrame
    text_container = tk.Frame(result_frame, bg="#202020", padx=6, pady=4)
    text_container.pack(fill="both", expand=True)

    text_result = tk.Text(text_container, height=14, font=("Courier", 10),
                      bg="#000000", fg="#ffffff", insertbackground="#ffffff",
                      selectbackground="#333333", wrap="none",
                      borderwidth=0, relief="flat")

    text_result.pack(fill="both", expand=True)
    text_result.config(state=tk.DISABLED)

    fig, ax = plt.subplots(figsize=(4, 3), dpi=100, facecolor="#1a1a1a")

    # Create row to hold plot and selector side-by-side
    pq_row = tk.Frame(power_frame, bg="#1a1a1a")
    pq_row.grid(row=5, column=0, columnspan=2, sticky="nsew", padx=5, pady=(0, 4))
    pq_row.columnconfigure(0, weight=1)

    # ✅ Now safe to attach canvas to pq_row
    canvas = FigureCanvasTkAgg(fig, master=pq_row)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(side="left", fill="both", expand=True)

    # Row weights (important!)
    power_frame.rowconfigure(5, weight=2)


    power_frame.rowconfigure(4, weight=1)  # text_result
    power_frame.rowconfigure(5, weight=2)  # PQ plot

    power_frame.columnconfigure(0, weight=1)
    power_frame.columnconfigure(1, weight=1)

    # --- Stats Tracker ---
    power_stats = {
        "count": 0,
        "P_sum": 0.0, "S_sum": 0.0, "Q_sum": 0.0,
        "PF_sum": 0.0, "Vrms_sum": 0.0, "Irms_sum": 0.0,
        "start_time": None
    }
    pq_trail = []  # stores (P, Q)
    MAX_TRAIL = 30  # number of points to show
    
    # Track last-logged DC offset setting
    dc_offset_logged = {"status": None}
    
    def format_si(value, unit):
        abs_val = abs(value)
        if abs_val >= 1e6:
            return f"{value / 1e6:.3f} M{unit}"
        elif abs_val >= 1e3:
            return f"{value / 1e3:.3f} k{unit}"
        elif abs_val >= 1:
            return f"{value:.3f} {unit}"
        elif abs_val >= 1e-3:
            return f"{value * 1e3:.3f} m{unit}"
        elif abs_val >= 1e-6:
            return f"{value * 1e6:.3f} µ{unit}"
        else:
            return f"{value:.3e} {unit}"

    def show_power_results(result):
        power_csv_path = global_power_csv_path[0]

        text_result.config(state=tk.NORMAL)
        text_result.delete(1.0, tk.END)

        # Show DC offset setting at top of result
        if remove_dc_var.get():
            dc_status_var.set("DC Offset Removal is ON — results may exclude DC component.")
        else:
            dc_status_var.set("DC Offset Removal is OFF — full waveform is analyzed.")
        
        text_result.insert(tk.END, f"{'Correction Factor':<22}: ×{correction_factor.get().strip():<12}\n")

        text_result.insert(tk.END, "\n")

        keys = ["Real Power (P)", "Apparent Power (S)", "Reactive Power (Q)",
                "Power Factor", "Vrms", "Irms"]

        key_map = {
            "Real Power (P)": "P_sum",
            "Apparent Power (S)": "S_sum",
            "Reactive Power (Q)": "Q_sum",
            "Power Factor": "PF_sum",
            "Vrms": "Vrms_sum",
            "Irms": "Irms_sum"
        }

        power_stats["count"] += 1

        if power_stats["start_time"] is None:
            power_stats["start_time"] = time.time()

        elapsed_sec = int(time.time() - power_stats["start_time"])
        elapsed_hms = time.strftime("%H:%M:%S", time.gmtime(elapsed_sec))

        # Calculate averages
        avg_p = power_stats["P_sum"] / power_stats["count"] if power_stats["count"] else 0
        avg_s = power_stats["S_sum"] / power_stats["count"] if power_stats["count"] else 0
        avg_q = power_stats["Q_sum"] / power_stats["count"] if power_stats["count"] else 0
        avg_pf = power_stats["PF_sum"] / power_stats["count"] if power_stats["count"] else 0

        # Power factor angle θ
        try:
            if math.isfinite(avg_pf):
                clamped_pf = max(min(avg_pf, 1.0), -1.0)  # ensure in [-1, 1]
                pf_angle = math.degrees(math.acos(clamped_pf))
            else:
                pf_angle = None
        except Exception as e:
            pf_angle = None
            log_debug(f"⚠️ PF Angle calc error: {e}")

        # Create CSV log file once
        if power_csv_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs("oszi_csv", exist_ok=True)  # 🔧 ensure folder exists
            power_csv_path = os.path.join("oszi_csv", f"power_log_{timestamp}.csv")
            global_power_csv_path[0] = power_csv_path

            with open(power_csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Timestamp", "P (W)", "S (VA)", "Q (VAR)", "PF", "PF Angle (°)",
                    "Vrms (V)", "Irms (A)", "Real Energy (Wh)", "Apparent Energy (VAh)", "Reactive Energy (VARh)"
                ])
            log_debug(f"📝 Created power log file: {power_csv_path}")

        # Energy estimates over time
        elapsed_hr = elapsed_sec / 3600.0
        energy_wh = avg_p * elapsed_hr
        energy_vah = avg_s * elapsed_hr
        energy_varh = avg_q * elapsed_hr

        header = f"{'Metric':<22} {'Instant':>12}    {'Average':>12}\n"
        text_result.insert(tk.END, header)
        text_result.insert(tk.END, "-" * len(header) + "\n")

        for key in keys:
            val = result.get(key, None)
            if isinstance(val, float):
                stat_key = key_map.get(key)
                if stat_key:
                    power_stats[stat_key] += val
                    avg = power_stats[stat_key] / power_stats["count"]

                    # Define unit
                    unit = ""
                    if "Real Power" in key or "Apparent Power" in key:
                        unit = "W" if "Real" in key else "VA"
                    elif "Reactive Power" in key:
                        unit = "VAR"
                    elif "Vrms" in key:
                        unit = "V"
                    elif "Irms" in key:
                        unit = "A"

                    if key == "Power Factor":
                        val_str = f"{val:.4f}"
                        avg_str = f"{avg:.6f}"
                    else:
                        val_str = format_si(val, unit)
                        avg_str = format_si(avg, unit)

                    line = f"{key:<22}: {val_str:<12} | {avg_str:<12}\n"
                    text_result.insert(tk.END, line)

        text_result.insert(tk.END, "\n")
        Vrms = result.get("Vrms")
        Irms = result.get("Irms")

        # Impedance
        if isinstance(Vrms, float) and isinstance(Irms, float) and Irms != 0:
            Z = Vrms / Irms
            text_result.insert(tk.END, f"{'Impedance (Z)':<22}: {format_si(Z, 'Ω'):<12}\n")

        # FFT-based frequency estimates (experimental, not published)
        #f_v = result.get("Freq_V")
        #f_i = result.get("Freq_I")
        #if isinstance(f_v, float):
        #    text_result.insert(tk.END, f"{'Voltage Freq (FFT)':<22}: {f_v:.2f} Hz\n")
        #if isinstance(f_i, float):
        #    text_result.insert(tk.END, f"{'Current Freq (FFT)':<22}: {f_i:.2f} Hz\n")

        # Scope frequency reference
        freq_val = scpi_data.get("freq_ref", None)
        if freq_val:
            text_result.insert(tk.END, f"{'Frequency (ref)':<22}: {freq_val.strip():<12}  (used for θ, PF)\n")

        # Add extra section (only once)
        #text_result.insert(tk.END, "\n")
        if pf_angle is not None:
            text_result.insert(tk.END, f"{'PF Angle (θ)':<22}: {pf_angle:>10.2f} °\n")
        text_result.insert(tk.END, f"{'Real Energy':<22}: {format_si(energy_wh, 'Wh'):<12}\n")
        text_result.insert(tk.END, f"{'Apparent Energy':<22}: {format_si(energy_vah, 'VAh'):<12}\n")
        text_result.insert(tk.END, f"{'Reactive Energy':<22}: {format_si(energy_varh, 'VARh'):<12}\n")
  
        # Log row
        now_iso = datetime.now().isoformat()
        with open(power_csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                now_iso, avg_p, avg_s, avg_q, avg_pf, pf_angle if pf_angle is not None else "",
                result.get("Vrms", ""), result.get("Irms", ""),
                energy_wh, energy_vah, energy_varh
            ])

        # Update PQ plot
        avg_p = power_stats["P_sum"] / power_stats["count"] if power_stats["count"] else 0
        avg_q = power_stats["Q_sum"] / power_stats["count"] if power_stats["count"] else 0

        pq_trail.append((avg_p, avg_q))

        if len(pq_trail) > MAX_TRAIL:
            pq_trail.pop(0)

        draw_pq_plot(avg_p, avg_q)

        text_result.insert(tk.END, "\n")
        text_result.insert(tk.END, f"Iterations: {power_stats['count']}    Elapsed: {elapsed_hms}\n")
        text_result.config(state=tk.DISABLED)
        tab_frame._shutdown = stop_auto_refresh

    def draw_pq_plot(p, q):
        ax.clear()

        # Set dark background
        ax.set_facecolor("#1a1a1a")
        fig.patch.set_facecolor("#1a1a1a")

        # Axis styling
        ax.spines['bottom'].set_color('#cccccc')
        ax.spines['top'].set_color('#cccccc')
        ax.spines['left'].set_color('#cccccc')
        ax.spines['right'].set_color('#cccccc')
        ax.tick_params(axis='x', colors='white')
        ax.tick_params(axis='y', colors='white')
        ax.xaxis.label.set_color('white')
        ax.yaxis.label.set_color('white')
        ax.title.set_color('white')

        ax.axhline(0, color="#777777", linewidth=1)
        ax.axvline(0, color="#777777", linewidth=1)

        ax.set_xlabel("Real Power P (W)")
        ax.set_ylabel("Reactive Power Q (VAR)")
        ax.set_title("PQ Operating Point", fontsize=10)

        p_range = max(abs(p) * 1.5, 1.0)
        q_range = max(abs(q) * 1.5, 1.0)
        ax.set_xlim(-p_range, p_range)
        ax.set_ylim(-q_range, q_range)

        # Trail history (fading dots)
        if len(pq_trail) > 1:
            trail_x = [pt[0] for pt in pq_trail]
            trail_y = [pt[1] for pt in pq_trail]
            ax.plot(trail_x, trail_y, color="#888888", linestyle="-", linewidth=1, alpha=0.4)

        for i, (xp, yq) in enumerate(pq_trail):
            fade = (i + 1) / len(pq_trail)
            alpha = max(0.0, min(1.0, 0.2 + 0.8 * fade))
            ax.plot(xp, yq, "o", color="red", markersize=4, alpha=alpha)

        # Quadrant labels
        ax.text(0.9, 0.9, "I", transform=ax.transAxes, fontsize=10, color="#bbbbbb")
        ax.text(0.1, 0.9, "II", transform=ax.transAxes, fontsize=10, color="#bbbbbb")
        ax.text(0.1, 0.1, "III", transform=ax.transAxes, fontsize=10, color="#bbbbbb")
        ax.text(0.9, 0.1, "IV", transform=ax.transAxes, fontsize=10, color="#bbbbbb")

        # Power triangle
        S = math.hypot(p, q)
        theta_deg = math.degrees(math.atan2(q, p))

        # Hypotenuse (already drawn)
        ax.plot([0, p], [0, q], color="orange", linestyle="--", linewidth=1, label="PF Angle θ")
        # Vertical leg (Q)
        ax.plot([p, p], [0, q], color="lime", linestyle="-", linewidth=1)
        # Horizontal leg (P)
        ax.plot([0, p], [0, 0], color="cyan", linestyle="-", linewidth=1)

        # Annotate P, Q, S
        ax.annotate(f"P = {p:.2f} W", xy=(p/2, -0.07*q), color="white", fontsize=9, ha="center")
        ax.annotate(f"Q = {q:.2f} VAR", xy=(p + 0.05*p, q/2), color="white", fontsize=9)
        ax.annotate(f"S = {S:.2f} VA", xy=(p/2, q/2), color="white", fontsize=9, ha="center")

        # Midpoint of hypotenuse
        s_x = p / 2
        s_y = q / 2

        # Apparent Power label (already drawn)
        ax.annotate(f"S = {S:.2f} VA", xy=(s_x, s_y), color="white", fontsize=9, ha="center")

        # PF Angle label — now shifted further below
        ax.text(s_x, s_y - 0.1 * q_range, f"θ = {theta_deg:.1f}°", color="orange", fontsize=9, ha="center")


        # Grid and legend
        ax.grid(True, linestyle="--", color="#444444", alpha=0.5)
        ax.legend(loc="lower right", fontsize=8, facecolor="#1a1a1a", edgecolor="#444444", labelcolor="white")

        canvas.draw()

    def analyze_power():
        if app_state.is_logging_active:
            log_debug("⚠️ Cannot start power analysis during long-time logging")
            return

        app_state.is_power_analysis_active = True  # 🔒 set flag before starting

        current_dc_setting = remove_dc_var.get()
        if dc_offset_logged["status"] != current_dc_setting:
            dc_offset_logged["status"] = current_dc_setting
            log_debug(f"⚙️ Remove DC Offset: {'ON' if current_dc_setting else 'OFF'}")
            if current_dc_setting:
                log_debug("⚠️ Analyzer will subtract mean(V) and mean(I)")
            else:
                log_debug("ℹ️ Full waveform (including DC) is used")

        try:
            from scpi.interface import connect_scope, safe_query
            from scpi.waveform import compute_power_from_scope

            vch = entry_vch.get().strip()
            ich = entry_ich.get().strip()

            log_debug(f"📡 Analyzing power for V={vch}, I={ich}", level="MINIMAL")

            if not vch or not ich:
                show_power_results({"Error": "Missing channel input"})
                log_debug("⚠️ Missing voltage or current channel input")
                return

            from app.app_state import scope
            if not scope:
                show_power_results({"Error": "Scope not connected"})
                log_debug("❌ Scope not connected")
                return

            try:
                chnum = ich.replace("CH", "").strip()
                unit = safe_query(scope, f":CHAN{chnum}:UNIT?", default="VOLT").strip().upper()
                if unit == "AMP":
                    scaling = 1.0
                    log_debug(f"⚙️ CH{chnum} unit is AMP — no probe scaling applied")
                else:
                    try:
                        val = float(entry_probe_value.get())
                        mode = probe_type.get()
                        if mode == "shunt":
                            base_scale = 1.0 / val
                        elif mode == "clamp":
                            base_scale = 1.0 / (val / 1000.0)
                        else:
                            base_scale = 1.0
                    except Exception as e:
                        base_scale = 1.0
                        log_debug(f"⚠️ Failed to get base probe scale — defaulting to 1.0 ({e})")

                    try:
                        corr = float(correction_factor.get().strip())
                    except Exception as e:
                        corr = 1.0
                        log_debug(f"⚠️ Invalid correction factor — defaulting to 1.0 ({e})")

                    scaling = base_scale * corr
                    log_debug(f"⚙️ Final scaling = base {base_scale:.4f} × corr {corr:.4f} = {scaling:.4f}")

                    log_debug(f"⚙️ CH{chnum} unit is VOLT — using scaling: {scaling:.4f} A/V")

                # ✅ Apply correction factor in both cases
                try:
                    user_corr = float(correction_factor.get().strip())
                    scaling *= user_corr
                    log_debug(f"🧪 Correction factor applied: ×{user_corr:.4f}")
                    log_debug(f"⚙️ Final scaling factor (A/V): {scaling:.4f}")
                except Exception as e:
                    user_corr = 1.0
                    log_debug(f"⚠️ Invalid correction factor — defaulting to 1.0 ({e})")

            except Exception as e:
                log_debug(f"⚠️ Could not detect channel unit: {e}")
                try:
                    val = float(entry_probe_value.get())
                    mode = probe_type.get()
                    if mode == "shunt":
                        base_scale = 1.0 / val
                    elif mode == "clamp":
                        base_scale = 1.0 / (val / 1000.0)
                    else:
                        base_scale = 1.0
                except Exception as e:
                    base_scale = 1.0
                    log_debug(f"⚠️ Failed to get base probe scale — defaulting to 1.0 ({e})")

                try:
                    corr_raw = correction_factor.get().strip()
                    corr = float(corr_raw) if corr_raw else 1.0
                except Exception as e:
                    corr = 1.0
                    log_debug(f"⚠️ Invalid correction factor — defaulting to 1.0 ({e})")

                scaling = base_scale * corr
                log_debug(f"⚙️ Final scaling = base {base_scale:.4f} × corr {corr:.4f} = {scaling:.4f}")


            result = compute_power_from_scope(
                scope, vch, ich,
                remove_dc=remove_dc_var.get(),
                current_scale=scaling
            )

            if result:
                p = result.get("Real Power (P)", 0)
                q = result.get("Reactive Power (Q)", 0)
                pf = result.get("Power Factor", 0)

                if all(map(math.isfinite, [p, q, pf])):
                    pq_trail.append((p, q))

                    log_debug(f"📈 Result: P={p:.3f} W, Q={q:.3f} VAR, PF={pf:.3f}", level="MINIMAL")
                    log_debug(f"📍 PQ now {len(pq_trail)} points")

                    if p > 0 and q > 0: quad = "I"
                    elif p < 0 and q > 0: quad = "II"
                    elif p < 0 and q < 0: quad = "III"
                    elif p > 0 and q < 0: quad = "IV"
                    else: quad = "origin"
                    log_debug(f"🧭 Operating Point in Quadrant {quad}")
                else:
                    log_debug("⚠️ Non-finite P/Q/PF — skipping log")

            show_power_results(result)

        except Exception as e:
            log_debug(f"⚠️ Power analysis error: {e}")
            show_power_results({"Error": str(e)})

        finally:
            app_state.is_power_analysis_active = False  # ✅ release lock no matter what
    
    ttk.Button(control_row, text="⚡ Measure Power", command=analyze_power, style="Action.TButton").grid(row=0, column=1, padx=3)

    def update_current_scale(*args):
        try:
            val = float(entry_probe_value.get())
            mode = probe_type.get()
            if mode == "shunt":
                scale = 1.0 / val
            elif mode == "clamp":
                scale = 1.0 / (val / 1000.0)
            else:
                scale = 1.0
            entry_current_scale.configure(state="normal")
            entry_current_scale.delete(0, tk.END)
            entry_current_scale.insert(0, f"{scale:.4f}")
            entry_current_scale.configure(state="readonly")
        except Exception:
            entry_current_scale.configure(state="normal")
            entry_current_scale.delete(0, tk.END)
            entry_current_scale.insert(0, "ERR")
            entry_current_scale.configure(state="readonly")

    probe_type.trace_add("write", update_current_scale)
    entry_probe_value.bind("<KeyRelease>", update_current_scale)

    def refresh_power_loop():
        nonlocal power_stats

        if not refresh_var.get():
            power_stats.clear()
            power_stats.update({
                "count": 0,
                "P_sum": 0.0, "S_sum": 0.0, "Q_sum": 0.0,
                "PF_sum": 0.0, "Vrms_sum": 0.0, "Irms_sum": 0.0,
                "start_time": None
            })
            pq_trail.clear()

        if refresh_var.get():
            try:
                if app_state.is_logging_active:
                    log_debug("⚠️ Auto-refresh paused — logging in progress")
                else:
                    analyze_power()
            except Exception as e:
                log_debug(f"⚠️ Auto-refresh error: {e}")

        power_frame.after(refresh_interval.get() * 1000, refresh_power_loop)

    refresh_power_loop()

    def stop_auto_refresh():
        log_debug("🧪 stop_auto_refresh() called")
        log_debug(f"🧪 csv = {global_power_csv_path[0]}")
        log_debug(f"🧪 pq_trail = {len(pq_trail)} points")

        refresh_var.set(False)
        app_state.is_power_analysis_active = False
        log_debug("🛑 Refresh stopped by shutdown")

        # Save final PQ plot if possible
        if global_power_csv_path[0] and len(pq_trail) > 1:
            try:
                img_path = global_power_csv_path[0].replace(".csv", "_summary.png")

                # Force redraw before saving
                draw_pq_plot(*pq_trail[-1])
                canvas.draw()
                fig.savefig(img_path, dpi=150, facecolor=fig.get_facecolor())

                log_debug(f"🖼️ Saved final PQ plot to {img_path}")
            except Exception as e:
                log_debug(f"⚠️ Failed to save final PQ plot: {e}")

    def update_refresh_checkbox_state():
        if app_state.is_logging_active:
            refresh_chk.config(state="disabled")
            refresh_var.set(False)
        else:
            refresh_chk.config(state="normal")
        power_frame.after(1000, update_refresh_checkbox_state)

    update_refresh_checkbox_state()
    draw_pq_plot(0.0, 0.0)
    tab_frame._shutdown = stop_auto_refresh
