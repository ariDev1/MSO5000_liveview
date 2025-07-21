import os
os.system("python3 build_version.py")
import argparse
import sys
import time
import math
from version import APP_NAME, VERSION, GIT_COMMIT, BUILD_DATE
import csv
from datetime import datetime
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

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use("Agg")  # Avoid any conflicts with non-GUI backends

import numpy as np
power_csv_path = None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--samples", type=int, help="Override number of waveform points (default: 1200)")
    args = parser.parse_args()

    if args.version:
        print(f"{APP_NAME} {VERSION}")
        print(f"Git Commit: {GIT_COMMIT}")
        print(f"Build Date: {BUILD_DATE}")
        sys.exit(0)

    # Optional override
    if args.samples:
        from config import WAV_POINTS
        import config
        config.WAV_POINTS = args.samples
        print(f"🔧 Overridden WAV_POINTS to {args.samples}")

    ip = input("Enter RIGOL MSO5000 IP address: ").strip()
    if not ip:
        print("❌ No IP provided. Exiting.")
        return
    set_ip(ip)

    from scpi.interface import connect_scope, safe_query
    scope = connect_scope(ip)
    if scope:
        try:
            freq_ref = safe_query(scope, ":POWer:QUALity:FREQreference?", "N/A")
            log_debug(f"📡 Frequency Reference: {freq_ref}")
            scpi_data["freq_ref"] = freq_ref
        except Exception as e:
            log_debug(f"⚠️ Could not get frequency reference: {e}")

    start_scpi_loop(ip)

    root = tk.Tk()

    # Create main vertical container
    main_frame = tk.Frame(root, bg="#1a1a1a")
    main_frame.pack(fill="both", expand=True)

    # Button row at top-right
    button_row = tk.Frame(main_frame, bg="#1a1a1a")
    button_row.pack(anchor="ne", padx=10, pady=(5, 0))

    toggle_btn = ttk.Button(button_row, text="🖼️ Hide", style="TButton")
    toggle_btn.pack(side="left", padx=(0, 5))

    shutdown_btn = ttk.Button(button_row, text="⏻ Shutdown", style="TButton", command=lambda: shutdown())
    shutdown_btn.pack(side="left")

    # Toggle screenshot visibility
    img_visible = [True]
    image_frame = tk.Frame(main_frame, bg="#1a1a1a")
    img_label = tk.Label(image_frame, bg="#1a1a1a")
    img_label.pack()

    tabs, notebook = create_main_gui(main_frame, ip)
    image_frame.pack(before=notebook, fill="x", pady=5)

    attach_image_label(img_label)
    update_image(root)
    start_screenshot_thread()

    def toggle_image():
        if img_visible[0]:
            image_frame.pack_forget()
            toggle_btn.config(text="🖼️ Show")
        else:
            image_frame.pack(before=notebook, fill="x", pady=5)
            toggle_btn.config(text="🖼️ Hide")
        img_visible[0] = not img_visible[0]

    toggle_btn.config(command=toggle_image)

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
                    ch_list.append(item)
                elif item.isdigit():
                    ch_list.append(int(item))

            dur = float(entry_duration.get())
            inter = float(entry_interval.get())

            assert dur > 0 and inter > 0 and ch_list
        except Exception as e:
            update_log_status(f"❌ Invalid input: {e}")
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
        freq_ref = scpi_data.get("freq_ref", None)
        if freq_ref:
            base_info += f"\n{'Freq. Reference' :<18}: {freq_ref}"

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

    # === SCPI Tab ===
    scpi_frame = tabs["SCPI"]
    scpi_frame.columnconfigure(0, weight=3)
    scpi_frame.columnconfigure(1, weight=1)
    scpi_frame.rowconfigure(0, weight=1)

    # --- Left Side (input + output + send) ---
    left_frame = ttk.Frame(scpi_frame)
    left_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

    scpi_input = ttk.Entry(left_frame, width=60)
    scpi_input.pack(pady=(0, 5), anchor="nw", fill="x")

    scpi_output = tk.Text(left_frame, height=14, font=("Courier", 10),
                          bg="#1a1a1a", fg="#ffffff", insertbackground="#ffffff",
                          selectbackground="#333333", wrap="none")
    scpi_output.pack(fill="both", expand=False)

    send_button = ttk.Button(left_frame, text="📡 Send")
    send_button.pack(pady=10, anchor="w")

    # --- Right Side (command list + insert button) ---
    right_frame = ttk.Frame(scpi_frame)
    right_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

    ttk.Label(right_frame, text="Known Commands:").pack(anchor="w", pady=(0, 5))

    cmd_listbox = tk.Listbox(right_frame, bg="#1a1a1a", fg="#ffffff", selectbackground="#555555",
                             height=16, exportselection=False)
    cmd_listbox.pack(fill="both", expand=True)

    def insert_selected_command():
        sel = cmd_listbox.curselection()
        if sel:
            selected_cmd = cmd_listbox.get(sel[0])
            scpi_input.delete(0, tk.END)
            scpi_input.insert(0, selected_cmd)

    ttk.Button(right_frame, text="➡ Insert into Input", command=insert_selected_command).pack(pady=5)
    cmd_listbox.bind("<Double-Button-1>", lambda e: insert_selected_command())

    # --- Load command list ---
    def load_known_commands():
        try:
            with open("scpi_command_list.txt", "r") as f:
                return [line.strip() for line in f if line.strip()]
        except Exception as e:
            log_debug(f"⚠️ Failed to load commands.txt: {e}")
            return []

    for cmd in load_known_commands():
        cmd_listbox.insert(tk.END, cmd)

    # --- SCPI send logic ---
    def send_scpi_command():
        cmd = scpi_input.get().strip()
        if not cmd:
            return
        log_debug(f"📤 SCPI command sent by user: {cmd}")

        scope = scpi_data.get("scope")
        if not scope:
            msg = "❌ Not connected to scope"
            scpi_output.insert(tk.END, f"{msg}\n")
            log_debug(msg)
            return

        from scpi.interface import scpi_lock
        try:
            with scpi_lock:
                from scpi.interface import safe_query
                resp = safe_query(scope, cmd, default="(no response)")
        except Exception as e:
            resp = f"❌ Exception: {e}"
            log_debug(f"❌ Exception during SCPI command: {e}")

        scpi_output.insert(tk.END, f"> {cmd}\n{resp}\n\n")
        scpi_output.see(tk.END)

    send_button.config(command=send_scpi_command)

    # === Power Analysis Tab ===
    power_frame = tabs["Power Analysis"]
    power_frame.columnconfigure(0, weight=1)
    power_frame.columnconfigure(1, weight=3)

    # --- Channel Selection (Compact Layout) ---
    ch_input_frame = ttk.Frame(power_frame)
    ch_input_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

    # Get reference string
    initial_ref = scpi_data.get("freq_ref", "N/A")
    ref_text = tk.StringVar(value=f"Reference: {initial_ref}")

    # Voltage Channel
    ttk.Label(ch_input_frame, text="Voltage Ch:").grid(row=0, column=0, sticky="e", padx=(2, 2))
    entry_vch = ttk.Entry(ch_input_frame, width=8)
    entry_vch.grid(row=0, column=1, sticky="w", padx=(0, 6))

    # Current Channel
    ttk.Label(ch_input_frame, text="Current Ch:").grid(row=0, column=2, sticky="e", padx=(2, 2))
    entry_ich = ttk.Entry(ch_input_frame, width=8)
    entry_ich.grid(row=0, column=3, sticky="w", padx=(0, 6))

    # Reference Info (faded gray)
    ttk.Label(ch_input_frame, textvariable=ref_text, foreground="#bbbbbb").grid(
        row=0, column=4, sticky="w", padx=(10, 0)
    )

    # Stretch last column to consume extra space
    ch_input_frame.grid_columnconfigure(5, weight=1)

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
    ttk.Label(probe_frame, text="Tip: Use 0.01 for 10 mΩ shunt, or 1.0 if scope shows Amps directly",
          foreground="#bbbbbb", background="#1a1a1a", wraplength=500).grid(
          row=1, column=0, columnspan=6, sticky="w", padx=5, pady=(2, 8))

    entry_probe_value = ttk.Entry(probe_frame, width=10)
    entry_probe_value.insert(0, "1.0")
    entry_probe_value.grid(row=0, column=3, sticky="w", padx=5)

    ttk.Label(probe_frame, text="→ Scaling (A/V):").grid(row=0, column=4, sticky="e", padx=15)
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

    tk.Checkbutton(control_row, text="Remove DC Offset", variable=remove_dc_var,
                   bg="#2d2d2d", fg="#ffffff", activebackground="#333333",
                   selectcolor="#555555", indicatoron=False, relief="raised").grid(row=0, column=0, padx=3)

    ttk.Button(control_row, text="⚡ Analyze Power", command=lambda: analyze_power()).grid(row=0, column=1, padx=3)

    #ttk.Button(control_row, text="🛑 Stop", command=lambda: stop_power_analysis()).grid(row=0, column=2, padx=3)

    tk.Checkbutton(control_row, text="Auto Refresh", variable=refresh_var,
                   bg="#2d2d2d", fg="#ffffff", activebackground="#333333",
                   selectcolor="#555555", indicatoron=False, relief="raised").grid(row=0, column=3, padx=3)

    ttk.Label(control_row, text="Interval (s):").grid(row=0, column=4, padx=(20, 3), sticky="e")
    ttk.Spinbox(control_row, from_=2, to=60, width=5, textvariable=refresh_interval).grid(row=0, column=5, padx=(0, 5), sticky="w")

    # --- Result Display ---
    text_result = tk.Text(power_frame, height=14, font=("Courier", 10),
                          bg="#1a1a1a", fg="#ffffff", insertbackground="#ffffff",
                          selectbackground="#333333", wrap="none")
    text_result.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
    text_result.config(state=tk.DISABLED)

    fig, ax = plt.subplots(figsize=(4, 3), dpi=100, facecolor="#1a1a1a")
    canvas = FigureCanvasTkAgg(fig, master=power_frame)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=5, pady=(0, 4))
    power_frame.rowconfigure(3, weight=1)  # text_result
    power_frame.rowconfigure(4, weight=2)  # PQ plot
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
        text_result.config(state=tk.NORMAL)
        text_result.delete(1.0, tk.END)

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
        global power_csv_path
        if power_csv_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs("oszi_csv", exist_ok=True)  # 🔧 ensure folder exists
            power_csv_path = os.path.join("oszi_csv", f"power_log_{timestamp}.csv")
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

        # Add extra section (only once)
        text_result.insert(tk.END, "\n")
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

        # Adaptive zoom range with tighter fallback
        p_range = max(abs(p) * 1.5, 1.0)   # 🔧 fallback = ±1 W
        q_range = max(abs(q) * 1.5, 1.0)   # 🔧 fallback = ±1 VAR

        ax.set_xlim(-p_range, p_range)
        ax.set_ylim(-q_range, q_range)

        # Trail history: fading gray
        if len(pq_trail) > 1:
            trail_x = [pt[0] for pt in pq_trail]
            trail_y = [pt[1] for pt in pq_trail]
            ax.plot(trail_x, trail_y, color="#888888", linestyle="-", linewidth=1, alpha=0.4)

        #ax.plot(p, q, "ro", markersize=8)
        for i, (xp, yq) in enumerate(pq_trail):
            fade = (i + 1) / len(pq_trail)
            alpha = max(0.0, min(1.0, 0.2 + 0.8 * fade))
            ax.plot(xp, yq, "o", color="red", markersize=4, alpha=alpha)


        # Quadrant labels
        ax.text(0.9, 0.9, "I", transform=ax.transAxes, fontsize=10, color="#bbbbbb")
        ax.text(0.1, 0.9, "II", transform=ax.transAxes, fontsize=10, color="#bbbbbb")
        ax.text(0.1, 0.1, "III", transform=ax.transAxes, fontsize=10, color="#bbbbbb")
        ax.text(0.9, 0.1, "IV", transform=ax.transAxes, fontsize=10, color="#bbbbbb")

        ax.grid(True, linestyle="--", color="#444444", alpha=0.5)
        # Power factor angle line from origin
        ax.plot([0, p], [0, q], color="orange", linestyle="--", linewidth=1, label="PF Angle θ")
        ax.legend(loc="lower right", fontsize=8, facecolor="#1a1a1a", edgecolor="#444444", labelcolor="white")

        canvas.draw()

    def analyze_power():
        from scpi.interface import connect_scope, safe_query
        from scpi.waveform import compute_power_from_scope
        from utils.debug import log_debug

        vch = entry_vch.get().strip()
        ich = entry_ich.get().strip()

        log_debug(f"📡 Analyzing power for V={vch}, I={ich}")

        if not vch or not ich:
            show_power_results({"Error": "Missing channel input"})
            log_debug("⚠️ Missing voltage or current channel input")
            return

        scope = connect_scope(ip)
        if not scope:
            show_power_results({"Error": "Scope not connected"})
            log_debug("❌ Scope not connected")
            return

        try:
            # 🧠 Auto-detect if current channel is already in Amps
            try:
                chnum = ich.replace("CH", "").strip()
                unit = safe_query(scope, f":CHAN{chnum}:UNIT?", default="VOLT").strip().upper()
                if unit == "AMP":
                    scaling = 1.0
                    log_debug(f"⚙️ CH{chnum} unit is AMP — no scaling applied")
                else:
                    scaling = float(entry_current_scale.get())
                    log_debug(f"⚙️ CH{chnum} unit is VOLT — using scaling: {scaling:.4f} A/V")
            except Exception as e:
                log_debug(f"⚠️ Could not detect channel unit: {e}")
                scaling = float(entry_current_scale.get())

            result = compute_power_from_scope(
                scope, vch, ich,
                remove_dc=remove_dc_var.get(),
                current_scale=scaling
            )

            # ✅ Log results if available
            if result:
                p = result.get("Real Power (P)", 0)
                q = result.get("Reactive Power (Q)", 0)
                pf = result.get("Power Factor", 0)

                if all(map(math.isfinite, [p, q, pf])):
                    log_debug(f"📈 Result — P={p:.3f} W, Q={q:.3f} VAR, PF={pf:.3f}")
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
            pq_trail.clear()  # 🔥 clear old trail on auto-refresh reset

        if refresh_var.get():
            try:
                analyze_power()
            except Exception as e:
                from utils.debug import log_debug
                log_debug(f"⚠️ Auto-refresh error: {e}")
        
        power_frame.after(refresh_interval.get() * 1000, refresh_power_loop)
    
    refresh_power_loop()

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

    def shutdown():
        log_debug("🛑 Shutdown requested")
        refresh_var.set(False)  # stop auto refresh
        global power_csv_path
        power_csv_path = None
        stop_logging()          # stop long-time logging if running
        root.destroy()          # close the GUI

    root.mainloop()

if __name__ == "__main__":
    main()
