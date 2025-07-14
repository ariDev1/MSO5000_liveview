import tkinter as tk
from tkinter import ttk
from gui.layout import create_main_gui
from gui.image_display import attach_image_label, update_image, set_ip, start_screenshot_thread
from utils.debug import attach_debug_widget, log_debug
from scpi.waveform import export_channel_csv
from scpi.licenses import get_license_options
from scpi.loop import start_scpi_loop
from scpi.data import scpi_data
from scpi.interface import connect_scope
from logger.longtime import start_logging, pause_resume, stop_logging
from app.app_state import is_logging_active

def main():
    ip = input("Enter RIGOL MSO5000 IP address: ").strip()
    if not ip:
        print("❌ No IP provided. Exiting.")
        return
    set_ip(ip)

    start_scpi_loop(ip)

    root = tk.Tk()

    # Screenshot tab image
    img_label = tk.Label(root, bg="#1a1a1a")
    img_label.pack(pady=5)
    attach_image_label(img_label)
    update_image(root)
    start_screenshot_thread()

    tabs = create_main_gui(root)

    # === Long-Time Measurement Tab ===
    logmeas_frame = tabs["Long-Time Measurement"]
    logmeas_frame.columnconfigure(0, weight=1)
    logmeas_frame.columnconfigure(1, weight=1)
    # ⚠️ Performance Tip Label
    tip_text = (
        "⚠️ Performance Tip:\n"
        "• Logging more than 2 channels with <2s interval can cause delays.\n"
        "• Use ≥2s for 3–4 channels. Use ≥1s for 1–2 channels.\n"
        "• Disable Vavg/Vrms for faster logging.\n"
        "• Ideal for long-term measurements (e.g. 1–24h)."
    )
    ttk.Label(
        logmeas_frame, text=tip_text, justify="left",
        background="#1a1a1a", foreground="#cccccc", wraplength=600
    ).grid(row=99, column=0, columnspan=2, padx=10, pady=10, sticky="w")

    ttk.Label(logmeas_frame, text="Channels (e.g., 1,2):", background="#1a1a1a", foreground="#ffffff").grid(row=0, column=0, sticky="e", padx=10, pady=5)
    entry_channels = ttk.Entry(logmeas_frame, width=20)
    entry_channels.grid(row=0, column=1, sticky="w", padx=10, pady=5)

    ttk.Label(logmeas_frame, text="Duration (hours):", background="#1a1a1a", foreground="#ffffff").grid(row=1, column=0, sticky="e", padx=10, pady=5)
    entry_duration = ttk.Entry(logmeas_frame, width=20)
    entry_duration.grid(row=1, column=1, sticky="w", padx=10, pady=5)

    ttk.Label(logmeas_frame, text="Interval (seconds):", background="#1a1a1a", foreground="#ffffff").grid(row=2, column=0, sticky="e", padx=10, pady=5)
    entry_interval = ttk.Entry(logmeas_frame, width=20)
    entry_interval.grid(row=2, column=1, sticky="w", padx=10, pady=5)

    vavg_var = tk.BooleanVar(value=False)
    vrms_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(logmeas_frame, text="Include Vavg", variable=vavg_var).grid(row=3, column=0, sticky="e", padx=10, pady=5)
    ttk.Checkbutton(logmeas_frame, text="Include Vrms", variable=vrms_var).grid(row=3, column=1, sticky="w", padx=10, pady=5)

    log_status = tk.StringVar(value="Idle")
    ttk.Label(logmeas_frame, textvariable=log_status, background="#1a1a1a", foreground="#ffffff").grid(row=4, column=0, columnspan=2, sticky="w", padx=10, pady=5)

    def start_log_session():
        try:
            ch_list = [int(c.strip()) for c in entry_channels.get().split(',') if c.strip().isdigit()]
            dur = float(entry_duration.get())
            inter = float(entry_interval.get())
            assert dur > 0 and inter > 0 and ch_list
        except Exception as e:
            log_status.set(f"❌ Invalid input: {e}")
            return

        scope = connect_scope(ip)
        if not scope:
            log_status.set("❌ No scope connection")
            return

        start_logging(None, ip, ch_list, dur, inter,
                      vavg_var.get(), vrms_var.get(), log_status.set)
        log_status.set("🔴 Logging started")

    def toggle_pause():
        paused = pause_resume()
        log_status.set("⏸ Paused" if paused else "▶ Resumed")

    def stop_log_session():
        stop_logging()
        log_status.set("🛑 Stop requested")

    ttk.Button(logmeas_frame, text="▶ Start Logging", command=start_log_session).grid(row=5, column=0, sticky="e", padx=10, pady=10)
    ttk.Button(logmeas_frame, text="Pause", command=toggle_pause).grid(row=5, column=1, sticky="w", padx=10, pady=10)
    ttk.Button(logmeas_frame, text="⏹ Stop", command=stop_log_session).grid(row=6, column=0, columnspan=2, pady=10)

    # === Licenses Tab ===
    license_frame = tabs["Licenses"]
    license_var = tk.StringVar()
    tk.Label(license_frame, textvariable=license_var, font=("Courier", 10), justify="left", anchor="nw",
             bg="#1a1a1a", fg="#ffffff", wraplength=1100).pack(fill="both", expand=True, padx=10, pady=10)

    def update_licenses():
        options = get_license_options(ip)
        if not options:
            license_var.set("⚠️ No license data received.")
        else:
            lines = ["📋 LICENSED OPTIONS:", "="*60]
            for opt in options:
                status = opt['status']
                symbol = "✅" if status == "Forever" else "🕑" if "Trial" in status else "❌"
                lines.append(f"{symbol} {opt['code']:10s} | {status:12s} | {opt['desc']}")
            license_var.set("\n".join(lines))
        root.after(15000, update_licenses)
    update_licenses()

    # === System Info Tab ===
    system_frame = tabs["System Info"]
    system_var = tk.StringVar()
    tk.Label(system_frame, textvariable=system_var, font=("Courier", 10), justify="left", anchor="nw",
             bg="#1a1a1a", fg="#ffffff", wraplength=1100).pack(fill="both", expand=True, padx=10, pady=10)

    def update_system_info():
        system_var.set(scpi_data["system_info"])
        root.after(2000, update_system_info)
    update_system_info()

    # === Channel Data Tab ===
    channel_frame = tabs["Channel Data"]
    channel_var = tk.StringVar()
    tk.Label(channel_frame, textvariable=channel_var, font=("Courier", 10), justify="left", anchor="nw",
             bg="#1a1a1a", fg="#ffffff", wraplength=1100).pack(fill="both", expand=True, padx=10, pady=10)

    def update_channel_info():
        lines = []
        for ch, info in scpi_data["channel_info"].items():
            lines.append(f"{ch}: {info['scale']} V/div | Offset: {info['offset']} V | Coupling: {info['coupling']} | Probe: {info['probe']}x")
        channel_var.set("\n".join(lines) if lines else "⚠️ No active channels")
        root.after(2000, update_channel_info)
    update_channel_info()

    def on_export():
        if is_logging_active:
            log_debug("❌ Logging in progress — export disabled")
            return

        scope = connect_scope(ip)
        if not scope:
            log_debug("❌ Not connected — export aborted")
            return

        for ch in range(1, 5):
            export_channel_csv(scope, ch)

    tk.Button(channel_frame, text="📥 Export Channel CSV", command=on_export,
              bg="#2d2d2d", fg="#ffffff", activebackground="#333333").pack(pady=10)

    # === Debug Tab ===
    debug_frame = tabs["Debug Log"]
    text_widget = tk.Text(debug_frame, font=("Courier", 9), height=100,
                          bg="#1a1a1a", fg="#ffffff", insertbackground="#ffffff",
                          selectbackground="#333333", state=tk.DISABLED)
    text_widget.pack(side="left", fill="both", expand=True, padx=5, pady=5)
    scrollbar = ttk.Scrollbar(debug_frame, orient="vertical", command=text_widget.yview)
    text_widget.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    attach_debug_widget(text_widget)
    log_debug("🔧 Debug log ready.")

    root.mainloop()

if __name__ == "__main__":
    main()
