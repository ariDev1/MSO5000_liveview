#ui/power_analysis.py

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

# Performance optimizations
class PowerAnalysisOptimizer:
    """Class to handle optimizations for power analysis"""
    
    def __init__(self):
        self.cached_scale = None
        self.cached_probe_config = None
        self.last_plot_time = 0
        self.plot_throttle_ms = 100  # Minimum time between plot updates
        
    def get_cached_scale(self, probe_value, probe_type, correction_factor):
        """Cache probe scale calculations to avoid repeated computation"""
        config = (probe_value, probe_type, correction_factor)
        if self.cached_probe_config != config:
            try:
                val = float(probe_value)
                if probe_type == "shunt":
                    base_scale = 1.0 / val
                elif probe_type == "clamp":
                    base_scale = 1.0 / (val / 1000.0)
                else:
                    base_scale = 1.0
                
                corr = float(correction_factor) if correction_factor else 1.0
                self.cached_scale = base_scale * corr
                self.cached_probe_config = config
            except Exception:
                self.cached_scale = 1.0
                
        return self.cached_scale
    
    def should_update_plot(self):
        """Throttle plot updates to improve performance"""
        current_time = time.time() * 1000  # Convert to ms
        if current_time - self.last_plot_time > self.plot_throttle_ms:
            self.last_plot_time = current_time
            return True
        return False

def setup_power_analysis_tab(tab_frame, ip, root):
    if app_state.is_logging_active:
        log_debug("⚠️ Cannot start power analysis during long-time logging.")
        return
    
    app_state.is_power_analysis_active = False
    global_power_csv_path = [None]
    optimizer = PowerAnalysisOptimizer()  # Initialize optimizer
    
    # Pre-compile format strings for better performance
    SI_FORMATS = {
        'M': (1e6, "{:.3f} M{}"),
        'k': (1e3, "{:.3f} k{}"),
        '': (1, "{:.3f} {}"),
        'm': (1e-3, "{:.3f} m{}"),
        'µ': (1e-6, "{:.3f} µ{}"),
        'e': (1, "{:.3e} {}")
    }
    
    def format_si_optimized(value, unit):
        """Optimized SI formatting with pre-compiled formats"""
        abs_val = abs(value)
        if abs_val >= 1e6:
            return SI_FORMATS['M'][1].format(value / SI_FORMATS['M'][0], unit)
        elif abs_val >= 1e3:
            return SI_FORMATS['k'][1].format(value / SI_FORMATS['k'][0], unit)
        elif abs_val >= 1:
            return SI_FORMATS[''][1].format(value, unit)
        elif abs_val >= 1e-3:
            return SI_FORMATS['m'][1].format(value / SI_FORMATS['m'][0], unit)
        elif abs_val >= 1e-6:
            return SI_FORMATS['µ'][1].format(value / SI_FORMATS['µ'][0], unit)
        else:
            return SI_FORMATS['e'][1].format(value, unit)

    correction_factor = tk.StringVar(value="1.0")
    def validate_correction_input(*args):
        val = correction_factor.get().strip()
        if val == "":
            correction_factor.set("1.0")

    correction_factor.trace_add("write", validate_correction_input)

    power_duration = tk.IntVar(value=0)  # 0 = unlimited
    use_25m_v_var = tk.BooleanVar(value=False)
    use_25m_i_var = tk.BooleanVar(value=False)

    # === UI Setup (keeping original structure but with optimizations) ===
    power_frame = tab_frame
    power_frame.columnconfigure(0, weight=1)
    power_frame.columnconfigure(1, weight=3)

    # Channel Selection Frame
    ch_input_frame = tk.Frame(power_frame, bg="#226688")
    ch_input_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

    # UI Elements (keeping original layout)
    tk.Label(ch_input_frame, text="Voltage Ch:", bg="#226688", fg="white").grid(row=0, column=0, sticky="e", padx=(2, 2), pady=4)
    entry_vch = ttk.Entry(ch_input_frame, width=3)
    entry_vch.grid(row=0, column=1, sticky="w", padx=(0, 6), pady=4)

    tk.Label(ch_input_frame, text="Current Ch:", bg="#226688", fg="white").grid(row=0, column=2, sticky="e", padx=(2, 2), pady=4)
    entry_ich = ttk.Entry(ch_input_frame, width=3)
    entry_ich.grid(row=0, column=3, sticky="w", padx=(0, 6), pady=4)

    tk.Label(ch_input_frame, text="Corr:", bg="#226688", fg="white").grid(row=0, column=4, sticky="e", padx=(2, 2), pady=4)
    entry_corr = ttk.Entry(ch_input_frame, width=6, textvariable=correction_factor)
    entry_corr.grid(row=0, column=5, sticky="w", padx=(0, 6), pady=4)

    expected_power = tk.StringVar(value="")
    tk.Label(ch_input_frame, text="Expected P (W):", bg="#226688", fg="white").grid(row=0, column=6, sticky="e", padx=(2, 2), pady=4)
    entry_expected = ttk.Entry(ch_input_frame, width=6, textvariable=expected_power)
    entry_expected.grid(row=0, column=7, sticky="w", padx=(0, 6), pady=4)

    initial_ref = scpi_data.get("freq_ref", "N/A")
    ref_text = tk.StringVar(value=f"Ref: {initial_ref}")
    tk.Label(ch_input_frame, textvariable=ref_text, bg="#226688", fg="white").grid(row=0, column=8, sticky="w", padx=(10, 0), pady=4)

    ch_input_frame.grid_columnconfigure(11, weight=1)

    # Probe Scaling Controls
    probe_frame = ttk.Frame(power_frame)
    probe_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

    ttk.Label(probe_frame, text="Current Probe Type:").grid(row=0, column=0, sticky="e", padx=5)

    probe_type = tk.StringVar(value="shunt")

    def set_probe_type(mode):
        probe_type.set(mode)
        update_current_scale()

    probe_mode_frame = ttk.Frame(probe_frame)
    probe_mode_frame.grid(row=0, column=1, sticky="w", padx=5)

    # Radio buttons for probe type
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
        text="Tip: Use 0.01 for 10mΩ shunt, or 1.0 if scope shows Amps directly. For better power accuracy, enable 20MHz BW limit on Channels it filters noise, stabilizes FFT phase and PF. Avoid >20MHz unless needed.",
        foreground="#bbbbbb", background="#1a1a1a",
        wraplength=720, font=("TkDefaultFont", 8)
    ).grid(row=1, column=0, columnspan=6, sticky="w", padx=5, pady=(2, 8))

    entry_probe_value = ttk.Entry(probe_frame, width=6)
    entry_probe_value.insert(0, "1.0")
    entry_probe_value.grid(row=0, column=3, sticky="w", padx=5)

    ttk.Label(probe_frame, text="→ Base Scale (A/V):").grid(row=0, column=4, sticky="e", padx=15)
    entry_current_scale = ttk.Entry(probe_frame, width=6, state="readonly")
    entry_current_scale.grid(row=0, column=5, sticky="w", padx=5)

    # Optimized scale calculation with caching
    def update_current_scale(*args):
        try:
            scale = optimizer.get_cached_scale(
                entry_probe_value.get(),
                probe_type.get(),
                correction_factor.get()
            )
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

    # Control Variables
    remove_dc_var = tk.BooleanVar(value=False)
    refresh_var = tk.BooleanVar(value=False)
    refresh_interval = tk.IntVar(value=5)

    # Control Row
    control_row = ttk.Frame(power_frame)
    control_row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=(0, 10))
    control_row.columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

    ttk.Checkbutton(control_row, text="DC Offset", variable=remove_dc_var).grid(row=0, column=0, padx=3)
    
    def toggle_auto_refresh():
        if not refresh_var.get():
            stop_auto_refresh()

    def auto_calibrate():
        log_debug("🧪 Auto-calibrate triggered")
        raw_exp_p = expected_power.get().strip()
        if not raw_exp_p:
            log_debug("⚠️ No expected power entered")
            return
        try:
            exp_p = float(raw_exp_p)
            if exp_p == 0:
                raise ValueError("Expected power must not be 0")
        except ValueError:
            log_debug(f"⚠️ Invalid expected power: '{raw_exp_p}'")
            return

        from app.app_state import scope
        if not scope:
            log_debug("❌ Scope not connected")
            return

        try:
            # Use cached scale calculation
            raw_scale = optimizer.get_cached_scale(
                entry_probe_value.get(),
                probe_type.get(),
                1.0  # No correction for calibration
            )
            
            vch = entry_vch.get().strip()
            ich = entry_ich.get().strip()
            result = compute_power_from_scope(
                scope, vch, ich,
                remove_dc=remove_dc_var.get(),
                current_scale=raw_scale
            )
            measured_p = result.get("Real Power (P)", None)
            if measured_p is None or measured_p <= 0:
                log_debug("⚠️ Invalid measured power")
                return

            new_corr = exp_p / measured_p
            correction_factor.set(f"{new_corr:.4f}")
            log_debug(f"✅ Auto-calibrated: ×{new_corr:.4f}")
            analyze_power()

        except Exception as e:
            log_debug(f"❌ Auto-calibration failed: {e}")

    ttk.Button(ch_input_frame, text="⚙ Cal", command=auto_calibrate).grid(
        row=0, column=9, sticky="w", padx=(10, 5), pady=4
    )

    refresh_chk = ttk.Checkbutton(control_row, text="Power Analysis", variable=refresh_var, command=toggle_auto_refresh)
    refresh_chk.grid(row=0, column=3, padx=3)

    def plot_last_power_log():
        import glob, subprocess
        files = glob.glob("oszi_csv/power_log_*.csv")
        if not files:
            log_debug("⚠️ No power log files found")
            return

        latest_file = max(files, key=os.path.getmtime)
        try:
            scale = float(entry_current_scale.get())
        except Exception:
            scale = 1.0
        
        log_debug(f"📊 Launching plot for {latest_file}")
        subprocess.Popen(["python3", "utils/plot_rigol_csv.py", latest_file, "--scale", str(scale)])

    ttk.Button(control_row, text="📈 Plot Last", command=plot_last_power_log).grid(row=0, column=2, padx=3)
    #ttk.Button(control_row, text="⚙ Auto-Calibrate", command=auto_calibrate).grid(row=0, column=6, padx=3)

    ttk.Label(control_row, text="Int(s):").grid(row=0, column=4, padx=(20, 3), sticky="e")
    ttk.Spinbox(control_row, from_=2, to=60, width=3, textvariable=refresh_interval).grid(row=0, column=5, padx=(0, 5), sticky="w")

    ttk.Label(control_row, text="Dur(s):").grid(row=0, column=6, padx=(10, 3), sticky="e")
    ttk.Entry(control_row, width=4, textvariable=power_duration).grid(row=0, column=7, padx=(0, 5), sticky="w")

    #ttk.Checkbutton(control_row, text="25M Points", variable=use_25m_var).grid(row=0, column=8, padx=3)
    ttk.Checkbutton(control_row, text="25M[v]", variable=use_25m_v_var).grid(row=0, column=8, padx=3)
    ttk.Checkbutton(control_row, text="25M[i]", variable=use_25m_i_var).grid(row=0, column=9, padx=3)

    # Result Display Setup
    result_header = tk.Frame(power_frame, bg="#1a1a1a")
    result_header.grid(row=3, column=0, columnspan=2, sticky="ew", padx=5, pady=(5, 0))
    result_header.grid_columnconfigure(0, weight=0)
    result_header.grid_columnconfigure(1, weight=1)

    tk.Label(result_header, text="📊 Analysis Output", font=("TkDefaultFont", 10, "bold"),
             bg="#1a1a1a", fg="white").grid(row=0, column=0, sticky="w")

    dc_status_var = tk.StringVar(value="DC Offset Removal is OFF — full waveform is analyzed.")
    offset_status_var = tk.StringVar(value="")
    tk.Label(result_header, textvariable=dc_status_var, bg="#1a1a1a", fg="#cccccc",
             font=("TkDefaultFont", 9)).grid(row=0, column=1, sticky="e", padx=(10, 5))
    offset_status_label = tk.Label(result_header, textvariable=offset_status_var,
        bg="#1a1a1a", fg="#ff9999", font=("TkDefaultFont", 9))
    offset_status_label.grid(row=1, column=1, sticky="e", padx=(10, 5))

    # Output Text Box
    result_frame = tk.Frame(power_frame, bg="#202020", bd=1, relief="solid")
    result_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=5, pady=(0, 0))
    power_frame.rowconfigure(4, weight=1)

    text_container = tk.Frame(result_frame, bg="#202020", padx=6, pady=4)
    text_container.pack(fill="both", expand=True)

    text_result = tk.Text(text_container, height=14, font=("Courier", 10),
                      bg="#000000", fg="#ffffff", insertbackground="#ffffff",
                      selectbackground="#333333", wrap="none",
                      borderwidth=0, relief="flat")
    text_result.pack(fill="both", expand=True)
    text_result.config(state=tk.DISABLED)

    # Plot Setup
    fig, ax = plt.subplots(figsize=(4, 3), dpi=100, facecolor="#1a1a1a")
    pq_row = tk.Frame(power_frame, bg="#1a1a1a")
    pq_row.grid(row=5, column=0, columnspan=2, sticky="nsew", padx=(0, 0), pady=(0, 0))
    pq_row.columnconfigure(0, weight=1)

    canvas = FigureCanvasTkAgg(fig, master=pq_row)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(side="left", fill="both", expand=True)

    power_frame.rowconfigure(5, weight=2)
    power_frame.rowconfigure(4, weight=1)
    power_frame.columnconfigure(0, weight=1)
    power_frame.columnconfigure(1, weight=1)

    # Stats and Data Management
    power_stats = {
        "count": 0,
        "P_sum": 0.0, "S_sum": 0.0, "Q_sum": 0.0,
        "PF_sum": 0.0, "Vrms_sum": 0.0, "Irms_sum": 0.0,
        "start_time": None
    }
    pq_trail = []
    MAX_TRAIL = 30
    dc_offset_logged = {"status": None}
    
    # Pre-compute common values to avoid repeated calculations
    key_mapping = {
        "Real Power (P)": ("P_sum", "W"),
        "Apparent Power (S)": ("S_sum", "VA"),
        "Reactive Power (Q)": ("Q_sum", "VAR"),
        "Power Factor": ("PF_sum", ""),
        "Vrms": ("Vrms_sum", "V"),
        "Irms": ("Irms_sum", "A")
    }

    def show_power_results(result, metadata):
        """Optimized result display with reduced string operations"""
        power_csv_path = global_power_csv_path[0]

        text_result.config(state=tk.NORMAL)
        text_result.delete(1.0, tk.END)

        # Update DC status
        dc_status_var.set("DC Offset Removal is ON — results may exclude DC component." 
                         if remove_dc_var.get() else 
                         "DC Offset Removal is OFF — full waveform is analyzed.")
        
        # Build output more efficiently using list and join
        output_lines = []
        output_lines.append(f"{'Correction Factor':<22}: ×{correction_factor.get().strip():<12}\n\n")
        
        power_stats["count"] += 1
        if power_stats["start_time"] is None:
            power_stats["start_time"] = time.time()

        elapsed_sec = int(time.time() - power_stats["start_time"])
        elapsed_hms = time.strftime("%H:%M:%S", time.gmtime(elapsed_sec))

        # Calculate averages more efficiently
        count = power_stats["count"]
        averages = {}
        for key, (stat_key, unit) in key_mapping.items():
            val = result.get(key, None)
            if isinstance(val, float):
                power_stats[stat_key] += val
                averages[key] = power_stats[stat_key] / count

        header = f"{'Metric':<22} {'Instant':>12}    {'Average':>12}\n"
        output_lines.append(header)
        output_lines.append("-" * len(header) + "\n")

        # Use optimized formatting
        for key, (stat_key, unit) in key_mapping.items():
            val = result.get(key, None)
            if isinstance(val, float) and key in averages:
                avg = averages[key]
                
                if key == "Power Factor":
                    val_str = f"{val:.4f}"
                    avg_str = f"{avg:.6f}"
                else:
                    val_str = format_si_optimized(val, unit)
                    avg_str = format_si_optimized(avg, unit)

                output_lines.append(f"{key:<22}: {val_str:<12} | {avg_str:<12}\n")

        # Additional calculations
        output_lines.append("\n")

        Vrms = result.get("Vrms", 0.0)
        Irms = result.get("Irms", 0.0)

        if isinstance(Vrms, float) and isinstance(Irms, float) and Irms > 1e-6:
            Z = Vrms / Irms
            metadata["Z"] = Z
            metadata["Vrms"] = Vrms
            metadata["Irms"] = Irms

            output_lines.append(f"{'Impedance (Z)':<22}: {format_si_optimized(Z, 'Ω'):<12}\n")

        # Frequency reference
        freq_val = scpi_data.get("freq_ref", None)
        if freq_val:
            output_lines.append(f"{'Frequency (ref)':<22}: {freq_val.strip():<12}  (used for θ, PF)\n")

        # Power factor angle and energy calculations
        avg_pf = averages.get("Power Factor", 0)
        try:
            if math.isfinite(avg_pf):
                clamped_pf = max(min(avg_pf, 1.0), -1.0)
                pf_angle = math.degrees(math.acos(clamped_pf))
            else:
                pf_angle = None
        except Exception:
            pf_angle = None

        if pf_angle is not None:
            output_lines.append(f"{'PF Angle (θ)':<22}: {pf_angle:>10.2f} °\n")

        # Energy calculations
        elapsed_hr = elapsed_sec / 3600.0
        avg_p = averages.get("Real Power (P)", 0)
        avg_s = averages.get("Apparent Power (S)", 0)
        avg_q = averages.get("Reactive Power (Q)", 0)
        
        energy_wh = avg_p * elapsed_hr
        energy_vah = avg_s * elapsed_hr
        energy_varh = avg_q * elapsed_hr

        output_lines.extend([
            f"{'Real Energy':<22}: {format_si_optimized(energy_wh, 'Wh'):<12}\n",
            f"{'Apparent Energy':<22}: {format_si_optimized(energy_vah, 'VAh'):<12}\n",
            f"{'Reactive Energy':<22}: {format_si_optimized(energy_varh, 'VARh'):<12}\n",
            f"\nIterations: {power_stats['count']}    Elapsed: {elapsed_hms}\n"
        ])

        # Write all at once for better performance
        text_result.insert(tk.END, ''.join(output_lines))
        text_result.config(state=tk.DISABLED)

        # CSV logging (batch write for better I/O performance)
        if power_csv_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs("oszi_csv", exist_ok=True)
            power_csv_path = os.path.join("oszi_csv", f"power_log_{timestamp}.csv")
            global_power_csv_path[0] = power_csv_path

            with open(power_csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Timestamp", "P (W)", "S (VA)", "Q (VAR)", "PF", "PF Angle (°)",
                    "Vrms (V)", "Irms (A)", "Real Energy (Wh)", "Apparent Energy (VAh)", "Reactive Energy (VARh)"
                ])

        # Log data
        now_iso = datetime.now().isoformat()
        with open(power_csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                now_iso, avg_p, avg_s, avg_q, avg_pf, pf_angle if pf_angle is not None else "",
                result.get("Vrms", ""), result.get("Irms", ""),
                energy_wh, energy_vah, energy_varh
            ])

        # Update PQ plot with throttling
        pq_trail.append((avg_p, avg_q))
        if len(pq_trail) > MAX_TRAIL:
            pq_trail.pop(0)

        if optimizer.should_update_plot():
            draw_pq_plot(avg_p, avg_q, metadata)

    def draw_pq_plot(p, q, metadata=None):
        import math
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch

        ax.clear()
        fig = ax.get_figure()

        # Set dark theme
        ax.set_facecolor("#1a1a1a")
        fig.patch.set_facecolor("#1a1a1a")

        for spine in ax.spines.values():
            spine.set_color('#cccccc')
        ax.tick_params(axis='both', colors='white')
        ax.xaxis.label.set_color('white')
        ax.yaxis.label.set_color('white')
        ax.title.set_color('white')

        ax.axhline(0, color="#777777", linewidth=1)
        ax.axvline(0, color="#777777", linewidth=1)

        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.text(0.5, 0.02, "Real Power P (W)", transform=ax.transAxes,
                ha="center", va="bottom", fontsize=8, color="white")
        ax.text(0.01, 0.97, "Reactive Power Q (VAR)", transform=ax.transAxes,
                ha="left", va="top", fontsize=8, color="white", rotation="vertical")

        ax.set_title("PQ Operating Point", fontsize=9)

        # Determine ranges
        p_range = max(abs(p) * 1.5, 1.0)
        q_range = max(abs(q) * 1.5, 1.0)
        ax.set_xlim(-p_range, p_range)
        ax.set_ylim(-q_range, q_range)

        # Determine quadrant
        def determine_quadrant(p, q):
            if p >= 0 and q >= 0:
                return 1
            elif p < 0 and q >= 0:
                return 2
            elif p < 0 and q < 0:
                return 3
            else:
                return 4

        quadrant = determine_quadrant(p, q)

        # Draw trail
        if len(pq_trail) > 1:
            trail_x, trail_y = zip(*pq_trail)
            ax.plot(trail_x, trail_y, color="#888888", linestyle="-", linewidth=1, alpha=0.4)
            for i, (xp, yq) in enumerate(pq_trail):
                fade = (i + 1) / len(pq_trail)
                alpha = max(0.2, min(1.0, 0.2 + 0.8 * fade))
                ax.plot(xp, yq, "o", color="red", markersize=4, alpha=alpha)

        # Quadrant labels
        quad_labels = [("I", 0.9, 0.9), ("II", 0.1, 0.9), ("III", 0.1, 0.1), ("IV", 0.9, 0.1)]
        for label, x, y in quad_labels:
            ax.text(x, y, label, transform=ax.transAxes, fontsize=9, color="#bbbbbb")

        # Power triangle
        S = math.hypot(p, q)
        theta_rad = math.atan2(q, p)
        theta_deg = math.degrees(theta_rad)
        pf = p / S if S > 0 else 0.0
        cos_theta = p / S if S > 0 else 0.0
        sin_theta = q / S if S > 0 else 0.0

        # Triangle edges
        ax.plot([0, p], [0, q], color="orange", linestyle="--", linewidth=1, label="PF Angle θ")
        ax.plot([p, p], [0, q], color="lime", linestyle="-", linewidth=1)
        ax.plot([0, p], [0, 0], color="cyan", linestyle="-", linewidth=1)

        # Adaptive label positions
        if quadrant == 1:
            ax.annotate(f"P = {p:.2f} W", xy=(p / 2, -0.05 * q_range), color="white", fontsize=8, ha="center")
            ax.annotate(f"Q = {q:.2f} VAR", xy=(p + 0.05 * p_range, q / 2), color="white", fontsize=8, ha="left")
        elif quadrant == 2:
            ax.annotate(f"P = {p:.2f} W", xy=(p / 2, -0.05 * q_range), color="white", fontsize=8, ha="center")
            ax.annotate(f"Q = {q:.2f} VAR", xy=(p - 0.10 * p_range, q / 2), color="white", fontsize=8, ha="right")
        elif quadrant == 3:
            ax.annotate(f"P = {p:.2f} W", xy=(p / 2, +0.05 * q_range), color="white", fontsize=8, ha="center")
            ax.annotate(f"Q = {q:.2f} VAR", xy=(p - 0.10 * p_range, q / 2), color="white", fontsize=8, ha="right")
        elif quadrant == 4:
            ax.annotate(f"P = {p:.2f} W", xy=(p / 2, +0.05 * q_range), color="white", fontsize=8, ha="center")
            ax.annotate(f"Q = {q:.2f} VAR", xy=(p + 0.05 * p_range, q / 2), color="white", fontsize=8, ha="left")

        ax.annotate(f"S = {S:.2f} VA", xy=(p / 2, q / 2), color="white", fontsize=8, ha="center")
        ax.text(p / 2, q / 2 - 0.1 * q_range, f"θ = {theta_deg:.1f}°", color="orange", fontsize=8, ha="center")

        # Impedance info
        try:
            z = metadata.get("Z", 0.0)
            z_angle = theta_deg
        except Exception:
            z = 0.0
            z_angle = 0.0

        pf_color = "lime" if pf >= 0 else "red"

        summary_text = (
            f"PF = {pf:.3f}\n"
            f"θ = {theta_deg:.1f}°\n"
            f"S = {S:.2f} VA\n"
            f"───\n"
            f"S → ({p:.2f} + j{q:.2f}) VA\n"
            f"|S| = {S:.2f} VA\n"
            f"cos(θ) = {cos_theta:.3f}\n"
            f"sin(θ) = {sin_theta:.3f}\n"
            f"───\n"
            f"Z = {z:.3f} Ω ∠ {z_angle:.1f}°"
        )

        # Choose corner position based on quadrant
        if quadrant == 1:
            box_x, box_y = 0.05, 0.10
            ha, va = "left", "bottom"
        elif quadrant == 2:
            box_x, box_y = 0.95, 0.10
            ha, va = "right", "bottom"
        elif quadrant == 3:
            box_x, box_y = 0.98, 0.90
            ha, va = "right", "top"
        elif quadrant == 4:
            box_x, box_y = 0.05, 0.90
            ha, va = "left", "top"

        ax.text(box_x, box_y, summary_text,
                transform=ax.transAxes, ha=ha, va=va,
                fontsize=7.5, color="white", linespacing=1.2,
                bbox=dict(facecolor="#1a1a1a", edgecolor="#444444", boxstyle="round,pad=0.3"))


        ax.grid(True, linestyle="--", color="#444444", alpha=0.5)
        ax.legend(loc="lower left", fontsize=7, facecolor="#1a1a1a", edgecolor="#444444", labelcolor="white")
        fig.subplots_adjust(left=0.08, right=0.92, top=0.94, bottom=0.08)
        canvas.draw()


    def analyze_power():
        """Optimized power analysis with reduced overhead"""

        if app_state.is_logging_active:
            log_debug("⚠️ Cannot start power analysis during logging")
            return

        app_state.is_power_analysis_active = True

        start = time.time()  # ⏱ start timing

        try:
            vch = entry_vch.get().strip()
            ich = entry_ich.get().strip()

            if not vch or not ich:
                show_power_results({"Error": "Missing channel input"})
                return

            from app.app_state import scope
            if not scope:
                show_power_results({"Error": "Scope not connected"})
                return

            chan_v = vch if vch.startswith("MATH") else f"CHAN{vch}"
            chan_i = ich if ich.startswith("MATH") else f"CHAN{ich}"
            try:
                v_offset = float(safe_query(scope, f":{chan_v}:OFFS?", "0"))
                i_offset = float(safe_query(scope, f":{chan_i}:OFFS?", "0"))
            except Exception as e:
                log_debug(f"⚠️ Failed to read channel offset: {e}")
                v_offset, i_offset = 0.0, 0.0

            if abs(v_offset) > 0.01 or abs(i_offset) > 0.01:
                log_debug(f"⚠️ Offset active! Voltage Ch={chan_v} = {v_offset:.3f} V, Current Ch={chan_i} = {i_offset:.3f} V — results may be distorted!", level="MINIMAL")
                offset_status_var.set(f"⚠ Offset active: V={v_offset:.2f} V, I={i_offset:.2f} V — waveform is shifted!")
                offset_status_label.config(fg="#ff9999")
            else:
                offset_status_var.set("✓ No active offset — raw signal used.")
                offset_status_label.config(fg="#00dd88")

            # Use cached scaling calculation
            scaling = optimizer.get_cached_scale(
                entry_probe_value.get(),
                probe_type.get(),
                correction_factor.get()
            )

            result = compute_power_from_scope(
                scope, vch, ich,
                remove_dc=remove_dc_var.get(),
                current_scale=scaling,
                use_25m_v=use_25m_v_var.get(),
                use_25m_i=use_25m_i_var.get()
            )

            if result:
                p = result.get("Real Power (P)", 0)
                q = result.get("Reactive Power (Q)", 0)
                pf = result.get("Power Factor", 0)

                if all(map(math.isfinite, [p, q, pf])):
                    log_debug(f"📈 Result: P={p:.3f} W, Q={q:.3f} VAR, PF={pf:.3f}", level="MINIMAL")

            metadata = {
                "Vrms": result.get("Vrms", 0),
                "Irms": result.get("Irms", 0)
            }

            show_power_results(result, metadata)

        except Exception as e:
            log_debug(f"⚠️ Power analysis error: {e}")
            #show_power_results({"Error": str(e)})
            show_power_results({"Error": str(e)}, {})


        finally:
            elapsed = time.time() - start  # ⏱ end timing
            interval_s = refresh_interval.get()
            log_debug(f"⏱ analyze_power() took {elapsed:.2f}s", level="MINIMAL")

            if elapsed > interval_s:
                lag = elapsed - interval_s
                log_debug(f"⚠️ Behind schedule by {lag:.2f}s", level="MINIMAL")

            if use_25m_v_var.get() or use_25m_i_var.get():
                log_debug(f"🧪 Full 25M waveform mode — V: {use_25m_v_var.get()} | I: {use_25m_i_var.get()}", level="MINIMAL")
            
            app_state.is_power_analysis_active = False

    # Button for manual analysis
    ttk.Button(control_row, text="⚡ Measure", command=analyze_power).grid(row=0, column=1, padx=3)

    # Auto-refresh functionality with optimized loop
    def refresh_power_loop():
        nonlocal power_stats

        power_frame.after(refresh_interval.get() * 1000, refresh_power_loop)

        if not refresh_var.get():
            # Reset stats when auto-refresh is turned off
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
                if not app_state.is_logging_active:

                    # Stop auto-refresh after user-defined duration
                    duration_limit = power_duration.get()
                    if duration_limit > 0 and power_stats["start_time"]:
                        elapsed = time.time() - power_stats["start_time"]
                        if elapsed >= duration_limit:
                            log_debug("🛑 Auto-measure duration reached, stopping")
                            stop_auto_refresh()
                            return

                    analyze_power()
                else:
                    log_debug("⚠️ Auto-refresh paused — logging in progress")
            except Exception as e:
                log_debug(f"⚠️ Auto-refresh error: {e}")

    # Start the refresh loop
    refresh_power_loop()

    def stop_auto_refresh():
        """Optimized shutdown with final plot save"""
        log_debug("🛑 Stopping auto-refresh")
        refresh_var.set(False)
        app_state.is_power_analysis_active = False

        # Save final PQ plot if we have data
        if global_power_csv_path[0] and len(pq_trail) > 1:
            try:
                img_path = global_power_csv_path[0].replace(".csv", "_summary.png")
                draw_pq_plot(*pq_trail[-1])
                canvas.draw()
                fig.savefig(img_path, dpi=150, facecolor=fig.get_facecolor())
                log_debug(f"🖼️ Saved final PQ plot to {img_path}")
            except Exception as e:
                log_debug(f"⚠️ Failed to save final PQ plot: {e}")

    def update_refresh_checkbox_state():
        """Manage refresh checkbox state based on logging status"""
        if app_state.is_logging_active:
            refresh_chk.config(state="disabled")
            refresh_var.set(False)
        else:
            refresh_chk.config(state="normal")
        power_frame.after(1000, update_refresh_checkbox_state)

    # Initialize
    update_refresh_checkbox_state()
    draw_pq_plot(0.0, 0.0)

    dc_status_var.set("DC Offset Removal is ON — results may exclude DC component." 
        if remove_dc_var.get() else 
        "DC Offset Removal is OFF — full waveform is analyzed.")

    tab_frame._shutdown = stop_auto_refresh

# Additional Performance Tips for the broader codebase:

class PerformanceOptimizations:
    """
    Additional optimization strategies that can be applied:
    
    1. SCPI Communication Optimization:
       - Batch SCPI commands when possible
       - Use binary data transfer for waveforms
       - Implement connection pooling
       - Cache scope settings that don't change
    
    2. Waveform Processing Optimization:
       - Use NumPy vectorized operations instead of loops
       - Pre-allocate arrays with known sizes
       - Use in-place operations where possible
       - Consider using numba for JIT compilation of hot loops
    
    3. UI Optimization:
       - Update UI elements only when values actually change
       - Use virtual scrolling for large data sets
       - Batch UI updates using after_idle()
       - Minimize text widget operations
    
    4. Memory Management:
       - Implement circular buffers for continuous data
       - Clear large arrays when not needed
       - Use generators for large data processing
       - Monitor memory usage and implement cleanup
    
    5. File I/O Optimization:
       - Use buffered I/O for CSV writing
       - Implement async file operations for large files
       - Consider using binary formats for large datasets
       - Batch file operations when possible
    """
    
    @staticmethod
    def optimize_scpi_communication():
        """
        Example of optimized SCPI communication:
        
        # Instead of multiple individual queries:
        # freq = scope.query(":MEAS:FREQ? CH1")
        # amp = scope.query(":MEAS:VAMP? CH1") 
        # phase = scope.query(":MEAS:PHAS? CH1")
        
        # Use batch query:
        batch_cmd = ":MEAS:FREQ? CH1;:MEAS:VAMP? CH1;:MEAS:PHAS? CH1"
        results = scope.query(batch_cmd).split(';')
        freq, amp, phase = map(float, results)
        """
        pass
    
    @staticmethod
    def optimize_numpy_operations():
        """
        Example of optimized NumPy operations:
        
        # Instead of:
        # power_samples = []
        # for i in range(len(voltage)):
        #     power_samples.append(voltage[i] * current[i])
        
        # Use vectorized operation:
        power_samples = voltage * current
        
        # For FFT operations, use optimized sizes (powers of 2)
        optimal_size = 2**int(np.log2(len(data)))
        fft_result = np.fft.fft(data[:optimal_size])
        """
        pass
    
    @staticmethod
    def optimize_ui_updates():
        """
        Example of optimized UI updates:
        
        # Instead of updating on every data point:
        def update_ui_throttled(self):
            current_time = time.time()
            if current_time - self.last_ui_update > 0.1:  # 10 FPS max
                self.update_display()
                self.last_ui_update = current_time
        
        # Batch text updates:
        def batch_text_update(self, lines):
            self.text_widget.config(state=tk.NORMAL)
            self.text_widget.delete(1.0, tk.END)
            self.text_widget.insert(1.0, '\n'.join(lines))
            self.text_widget.config(state=tk.DISABLED)
        """
        pass