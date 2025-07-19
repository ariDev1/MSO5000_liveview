import os
os.system("python3 build_version.py")

import sys
from version import APP_NAME, VERSION, GIT_COMMIT, BUILD_DATE

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
    if "--version" in sys.argv:
        print(f"{APP_NAME} {VERSION}")
        print(f"Git Commit: {GIT_COMMIT}")
        print(f"Build Date: {BUILD_DATE}")
        sys.exit(0)

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

    tabs = create_main_gui(root, ip)
    def update_status(message):
        update_log_status(message)
        if "finished" in message.lower() or "error" in message.lower():
           update_log_buttons(state="idle")


    def start_log_session():
        try:
            raw = entry_channels.get()
            ch_list = []
            for item in raw.split(","):
                item = item.strip().upper()
                if item.startswith("MATH") and item[4:].isdigit():
                    ch_list.append(item)  # MATH1, MATH2, etc.
                elif item.isdigit():
                    ch_list.append(int(item))  # CH1, CH2, etc.

            dur = float(entry_duration.get())
            inter = float(entry_interval.get())
            assert dur > 0 and inter > 0 and ch_list
        except Exception as e:
            update_log_status(f"❌ Invalid input: {e}")
            return

        scope = connect_scope(ip)
        if not scope:
            update_log_status("❌ No scope connection")
            return

        update_log_buttons(state="logging", paused=False)
        pause_button.config(text="⏸ Pause")

        start_logging(None, ip, ch_list, dur, inter,
                      vavg_var.get(), vrms_var.get(), update_status)
        update_log_status("🔴 Logging started")

    def toggle_pause():
        paused = pause_resume()
        if paused:
            update_log_status("⏸ Paused")
            pause_button.config(text="▶ Resume")
            update_log_buttons(state="paused", paused=True)
        else:
            update_log_status("▶ Resumed")
            pause_button.config(text="⏸ Pause")
            update_log_buttons(state="logging", paused=False)

    def stop_log_session():
        stop_logging()
        update_log_status("🛑 Stop requested")
        update_log_buttons(state="idle")

    # === Long-Time Measurement Tab ===
    logmeas_frame = tabs["Long-Time Measurement"]
    logmeas_frame.columnconfigure(0, weight=1)
    logmeas_frame.columnconfigure(1, weight=1)

    # --- Measurement Settings Group ---
    meas_frame = ttk.LabelFrame(logmeas_frame, text="Measurement Settings", width=320)
    meas_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ns")
    meas_frame.grid_propagate(False)

    inner_left = ttk.Frame(meas_frame)
    inner_left.pack(fill="both", expand=True, padx=5, pady=5)

    ttk.Label(inner_left, text="Channels (e.g., 1,2,MATH1):", background="#1a1a1a", foreground="#ffffff").pack(anchor="w", pady=2)
    entry_channels = ttk.Entry(inner_left, width=20)
    entry_channels.pack(fill="x", pady=2)

    ttk.Label(inner_left, text="Duration (hours):", background="#1a1a1a", foreground="#ffffff").pack(anchor="w", pady=2)
    entry_duration = ttk.Entry(inner_left, width=20)
    entry_duration.pack(fill="x", pady=2)

    ttk.Label(inner_left, text="Interval (seconds):", background="#1a1a1a", foreground="#ffffff").pack(anchor="w", pady=2)
    entry_interval = ttk.Entry(inner_left, width=20)
    entry_interval.pack(fill="x", pady=2)

    vavg_var = tk.BooleanVar(value=False)
    vrms_var = tk.BooleanVar(value=False)
    #ttk.Checkbutton(inner_left, text="Include Vavg", variable=vavg_var).pack(anchor="w", pady=2)
    #ttk.Checkbutton(inner_left, text="Include Vrms", variable=vrms_var).pack(anchor="w", pady=2)
    tk.Checkbutton(inner_left, text="Include Vavg", variable=vavg_var,
               bg="#2d2d2d", fg="#ffffff", activebackground="#333333",
               selectcolor="#555555", indicatoron=False, relief="raised").pack(fill="x", pady=2)

    tk.Checkbutton(inner_left, text="Include Vrms", variable=vrms_var,
                   bg="#2d2d2d", fg="#ffffff", activebackground="#333333",
                   selectcolor="#555555", indicatoron=False, relief="raised").pack(fill="x", pady=2)

    # --- Logging Status Output (scrollable like other tabs)
    status_frame = ttk.LabelFrame(logmeas_frame, text="Logging Status")
    status_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

    text_logstatus = tk.Text(status_frame, height=10, font=("Courier", 10), bg="#1a1a1a", fg="#ffffff",
                             insertbackground="#ffffff", selectbackground="#333333", wrap="none")
    text_logstatus.pack(side="left", fill="both", expand=True, padx=5, pady=5)

    scrollbar_log = ttk.Scrollbar(status_frame, orient="vertical", command=text_logstatus.yview)
    text_logstatus.configure(yscrollcommand=scrollbar_log.set)
    scrollbar_log.pack(side="right", fill="y")

    text_logstatus.config(state=tk.DISABLED)

    def update_log_status(msg):
        text_logstatus.config(state=tk.NORMAL)
        text_logstatus.insert(tk.END, msg + "\n")
        text_logstatus.see(tk.END)
        text_logstatus.config(state=tk.DISABLED)

    # --- Button Controls (stacked right-aligned)
    btn_frame = ttk.Frame(logmeas_frame)
    btn_frame.grid(row=1, column=1, sticky="ne", padx=10, pady=10)

    btn_frame.grid_columnconfigure((0, 1, 2), weight=1)

    start_button = ttk.Button(btn_frame, text="▶ Start Logging", command=start_log_session)
    start_button.grid(row=0, column=0, padx=5)

    pause_button = ttk.Button(btn_frame, text="⏸ Pause", command=toggle_pause)
    pause_button.grid(row=0, column=1, padx=5)

    stop_button = ttk.Button(btn_frame, text="⏹ Stop", command=stop_log_session)
    stop_button.grid(row=0, column=2, padx=5)


    def update_log_buttons(state="idle", paused=False):
        if state == "idle":
            start_button.config(state="normal")
            pause_button.config(state="disabled")
            stop_button.config(state="disabled")
        elif state == "logging":
            start_button.config(state="disabled")
            pause_button.config(state="normal" if not paused else "normal")
            stop_button.config(state="normal")
        elif state == "paused":
            start_button.config(state="disabled")
            pause_button.config(state="normal")
            stop_button.config(state="normal")

    # --- Performance Tips
    tip_frame = ttk.LabelFrame(logmeas_frame, text="⚠️ Performance Tips")
    tip_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

    tip_text = (
        "Logging more than 2 channels with <2s interval can cause delays. Use ≥2s for 3–4 channels. Use ≥1s for 1–2 channels. Disable Vavg/Vrms for faster logging. Ideal for long-term measurements (e.g. 1–24h)."
    )

    ttk.Label(tip_frame, text=tip_text, justify="left",
              background="#1a1a1a", foreground="#cccccc", wraplength=700).pack(anchor="w", padx=10, pady=5)
    
    update_log_buttons(state="idle")

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

    text_system = tk.Text(system_frame, font=("Courier", 10), bg="#1a1a1a", fg="#ffffff",
                          insertbackground="#ffffff", selectbackground="#333333", wrap="none")
    
    text_system.pack(side="left", fill="both", expand=True, padx=5, pady=5)

    scrollbar_sys = ttk.Scrollbar(system_frame, orient="vertical", command=text_system.yview)
    text_system.configure(yscrollcommand=scrollbar_sys.set)
    scrollbar_sys.pack(side="right", fill="y")

    text_system.config(state=tk.DISABLED)

    def copy_system_info_to_clipboard():
        from version import APP_NAME, VERSION, GIT_COMMIT, BUILD_DATE, AUTHOR, PROJECT_URL

        meta_info = (
            f"\n\n{'-'*60}\n"
            f"{APP_NAME} {VERSION}\n"
            f"Build Date : {BUILD_DATE}\n"
            f"Git Commit : {GIT_COMMIT}\n"
            f"Maintainer : {AUTHOR}\n"
            f"Project    : {PROJECT_URL}\n"
        )

        base_info = scpi_data.get("system_info", "")
        full_text = base_info + meta_info

        root.clipboard_clear()
        root.clipboard_append(full_text)
        root.update()
        log_debug("📋 System Info copied to clipboard")

    ttk.Button(system_frame, text="📋 Copy System Info", command=copy_system_info_to_clipboard).pack(
        side="bottom", anchor="e", padx=10, pady=5
    )

    # Smart refresh with scroll preservation
    last_system_text = [""]

    def update_system_info():
        from version import APP_NAME, VERSION, GIT_COMMIT, BUILD_DATE, AUTHOR, PROJECT_URL

        meta_info = (
            f"\n\n{'-'*60}\n"
            f"{APP_NAME} {VERSION}\n"
            f"Build Date : {BUILD_DATE}\n"
            f"Git Commit : {GIT_COMMIT}\n"
            f"Maintainer : {AUTHOR}\n"
            f"Project    : {PROJECT_URL}\n"
        )

        base_info = scpi_data.get("system_info", "")
        full_text = base_info + meta_info

        if full_text != last_system_text[0]:
            scroll_position = text_system.yview()
            sel_start = text_system.index(tk.SEL_FIRST) if text_system.tag_ranges(tk.SEL) else None
            sel_end   = text_system.index(tk.SEL_LAST)  if text_system.tag_ranges(tk.SEL) else None

            text_system.config(state=tk.NORMAL)
            text_system.delete("1.0", tk.END)
            text_system.insert(tk.END, full_text)
            text_system.config(state=tk.DISABLED)

            if sel_start and sel_end:
                text_system.tag_add(tk.SEL, sel_start, sel_end)
            text_system.yview_moveto(scroll_position[0])

            last_system_text[0] = full_text

        root.after(2000, update_system_info)

    update_system_info()

    # === Channel Data Tab ===
    channel_frame = tabs["Channel Data"]

    text_channel = tk.Text(channel_frame, font=("Courier", 10), bg="#1a1a1a", fg="#ffffff",
                           insertbackground="#ffffff", selectbackground="#333333", wrap="none")
    text_channel.pack(side="left", fill="both", expand=True, padx=5, pady=5)

    scrollbar_ch = ttk.Scrollbar(channel_frame, orient="vertical", command=text_channel.yview)
    text_channel.configure(yscrollcommand=scrollbar_ch.set)
    scrollbar_ch.pack(side="right", fill="y")

    text_channel.config(state=tk.DISABLED)

    # CSV Export function — was missing!
    def on_export():
        if is_logging_active:
            log_debug("❌ Logging in progress — export disabled")
            return

        scope = connect_scope(ip)
        if not scope:
            log_debug("❌ Not connected — export aborted")
            return

        for ch in scpi_data.get("channel_info", {}).keys():
            try:
                if ch.startswith("CH"):
                    ch_num = int(ch[2:])
                    export_channel_csv(scope, ch_num)
                elif ch.startswith("MATH"):
                    export_channel_csv(scope, ch)  # pass "MATH1", "MATH2", etc.
            except Exception as e:
                log_debug(f"⚠️ Export failed for {ch}: {e}")

    # Copy to Clipboard button
    def copy_channel_settings():
        full_text = text_channel.get("1.0", tk.END).strip()
        root.clipboard_clear()
        root.clipboard_append(full_text)
        root.update()
        log_debug("📋 Channel Settings copied to clipboard")

    def copy_channel_csv_to_clipboard():
        if is_logging_active:
            log_debug("❌ Logging in progress — copy disabled")
            return

        scope = connect_scope(ip)
        if not scope:
            log_debug("❌ Not connected — copy aborted")
            return

        from io import StringIO
        output = StringIO()

        for ch in scpi_data.get("channel_info", {}).keys():
            try:
                if ch.startswith("CH"):
                    ch_num = int(ch[2:])
                    csv_path = export_channel_csv(scope, ch_num)
                elif ch.startswith("MATH"):
                    csv_path = export_channel_csv(scope, ch)
                with open(csv_path, "r") as f:
                    output.write(f.read())
                    output.write("\n\n")
            except Exception as e:
                log_debug(f"⚠️ Export failed for {ch}: {e}")

        clipboard_data = output.getvalue()
        root.clipboard_clear()
        root.clipboard_append(clipboard_data)
        root.update()
        log_debug("📋 Channel CSV data copied to clipboard")

    # Buttons (stacked vertically on bottom right)
    btn_frame = ttk.Frame(channel_frame)
    btn_frame.pack(side="bottom", anchor="e", padx=10, pady=5)

    ttk.Button(btn_frame, text="📋 Copy Settings", command=copy_channel_settings).pack(fill="x", pady=2)
    ttk.Button(btn_frame, text="📋 Copy CSV Data", command=copy_channel_csv_to_clipboard).pack(fill="x", pady=2)
    tk.Button(btn_frame, text="📥 Export Channel CSV", command=on_export,
              bg="#2d2d2d", fg="#ffffff", activebackground="#333333").pack(fill="x", pady=4)

    # Scroll-preserving update logic
    last_channel_text = [""]

    def update_channel_info():
        lines = []
        for ch, info in scpi_data["channel_info"].items():
            if ch.startswith("MATH"):
                lines.append(f"{ch:<6}: Scale={info['scale']:<8} Offset={info['offset']:<8} Type={info.get('type', 'N/A')}")
            else:
                lines.append(f"{ch:<6}: Scale={info['scale']:<8} Offset={info['offset']:<8} Coupling={info['coupling']:<6} Probe={info['probe']}x")

        full_text = "\n".join(lines) if lines else "⚠️ No active channels"

        if full_text != last_channel_text[0]:
            scroll_position = text_channel.yview()
            sel_start = text_channel.index(tk.SEL_FIRST) if text_channel.tag_ranges(tk.SEL) else None
            sel_end   = text_channel.index(tk.SEL_LAST)  if text_channel.tag_ranges(tk.SEL) else None

            text_channel.config(state=tk.NORMAL)
            text_channel.delete("1.0", tk.END)
            text_channel.insert(tk.END, full_text)
            text_channel.config(state=tk.DISABLED)

            if sel_start and sel_end:
                text_channel.tag_add(tk.SEL, sel_start, sel_end)
            text_channel.yview_moveto(scroll_position[0])

            last_channel_text[0] = full_text

        root.after(2000, update_channel_info)

    update_channel_info()

    
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
