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
from gui.licenses import setup_licenses_tab
from gui.system_info import setup_system_info_tab
from gui.channel_info import setup_channel_tab
from gui.image_display import attach_image_label, update_image, set_ip, start_screenshot_thread
from gui.scpi_console import setup_scpi_tab
from gui.logging_controls import setup_logging_tab
from gui.marquee import attach_marquee
from gui.power_analysis import setup_power_analysis_tab
from utils.debug import attach_debug_widget, start_debug_updater, log_debug, set_debug_level
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
    scpi_data["ip"] = ip

    scope = connect_scope(ip)
    if scope:
        try:
            freq_ref = safe_query(scope, ":POWer:QUALity:FREQreference?", "N/A")
            log_debug(f"📡 Frequency Reference: {freq_ref}")
            scpi_data["freq_ref"] = freq_ref
        except Exception as e:
            log_debug(f"⚠️ Could not get frequency reference: {e}")

    import app.app_state as app_state
    app_state.scope = scope
    app_state.scope_ip = ip

    start_scpi_loop(ip)

    #Entry Point
    root = tk.Tk()
    main_frame = tk.Frame(root, bg="#1a1a1a")
    main_frame.pack(fill="both", expand=True)

    #Top Row
    button_row = tk.Frame(main_frame, bg="#1a1a1a")
    button_row.pack(fill="x", padx=10, pady=(5, 0))

    # Two-column layout inside button_row
    button_row.columnconfigure(0, weight=1)  # marquee expands
    button_row.columnconfigure(1, weight=0)  # buttons stay fixed

    # Frame for marquee (left side)
    marquee_frame = tk.Frame(button_row, bg="#1a1a1a")
    marquee_frame.grid(row=0, column=0, sticky="ew")

    # Frame for buttons (right side)
    button_frame = tk.Frame(button_row, bg="#1a1a1a")
    button_frame.grid(row=0, column=1, sticky="e")

    # Attach marquee to left subframe
    marquee = attach_marquee(marquee_frame, file_path="marquee.txt", url="https://aether-research.institute/MSO5000/marquee.txt")

    # Buttons to right subframe
    toggle_btn = ttk.Button(button_frame, text="🗗 Hide", style="TButton")
    toggle_btn.pack(side="left", padx=(10, 5))

    shutdown_btn = ttk.Button(button_frame, text="⏻ Exit", style="TButton", command=lambda: shutdown())
    shutdown_btn.pack(side="left", padx=(0, 5))

    # Toggle screenshot visibility
    img_visible = [True]
    image_frame = tk.Frame(main_frame, bg="#1a1a1a")

    #Screenshot Area
    img_label = tk.Label(image_frame, bg="#1a1a1a")
    img_label.pack()

    #Build All Tab Contaoners
    tabs, notebook = create_main_gui(main_frame, ip)

    image_frame.pack(before=notebook, fill="x", pady=5)

    attach_image_label(img_label)
    update_image(root)
    start_screenshot_thread()

    def toggle_image():
        if img_visible[0]:
            image_frame.pack_forget()
            toggle_btn.config(text="🗖 Show")
        else:
            image_frame.pack(before=notebook, fill="x", pady=5)
            toggle_btn.config(text="🗗 Hide")
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

    setup_licenses_tab(tabs["Licenses"], ip, root)

    setup_system_info_tab(tabs["System Info"], root)

    setup_channel_tab(tabs["Channel Data"], ip, root)

    setup_logging_tab(tabs["Long-Time Measurement"], ip, root)

    setup_scpi_tab(tabs["SCPI"], ip)

    setup_power_analysis_tab(tabs["Power Analysis"], ip, root)
    power_tab = tabs["Power Analysis"]
    power_shutdown = getattr(power_tab, "_shutdown", lambda: None)

    # === Debug Tab ===
    debug_frame = tabs["Debug Log"]

    debug_level_frame = tk.Frame(debug_frame, bg="#2d2d2d")
    debug_level_frame.pack(fill="x", padx=5, pady=(5, 0))

    # Left-aligned label
    tk.Label(debug_level_frame, text="Debug Output Level:",
             bg="#2d2d2d", fg="#bbbbbb", font=("TkDefaultFont", 9)).pack(side="left", padx=(10, 10))

    # Spacer expands to push buttons right
    tk.Frame(debug_level_frame, bg="#2d2d2d").pack(side="left", expand=True, fill="x")

    # Right-aligned radio buttons
    debug_var = tk.StringVar(value="FULL")

    def on_debug_level_change():
        from utils.debug import set_debug_level
        set_debug_level(debug_var.get())

    for level, label in [("FULL", "🛠 Full"), ("MINIMAL", "⚠️ Minimal")]:
        tk.Radiobutton(debug_level_frame, text=label, variable=debug_var, value=level,
            command=on_debug_level_change,
            bg="#2d2d2d", fg="#ffffff", selectcolor="#555555",
            activebackground="#333333", indicatoron=False,
            relief="raised", width=10).pack(side="left", padx=5)

    text_widget = tk.Text(debug_frame, font=("Courier", 9), height=100,
                          bg="#1a1a1a", fg="#ffffff", insertbackground="#ffffff",
                          selectbackground="#333333", state=tk.DISABLED)
    text_widget.pack(side="left", fill="both", expand=True, padx=5, pady=5)
    scrollbar = ttk.Scrollbar(debug_frame, orient="vertical", command=text_widget.yview)
    text_widget.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    attach_debug_widget(text_widget)
    start_debug_updater(root)
    log_debug("🔧 Debug log ready.")

    def shutdown():
        log_debug("🛑 Shutdown requested")
        power_shutdown()          # safely stop auto-refresh in Power Analysis tab
        stop_logging()            # stop long-time logging if running
        root.destroy()            # close the GUI

    root.mainloop()

if __name__ == "__main__":
    main()