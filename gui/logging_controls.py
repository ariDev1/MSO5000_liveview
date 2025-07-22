# gui/logging_controls.py

import tkinter as tk
from tkinter import ttk
from logger.longtime import start_logging, pause_resume, stop_logging
from scpi.interface import connect_scope
from app.app_state import is_logging_active

def setup_logging_tab(tab_frame, ip, root):
    tab_frame.columnconfigure(0, weight=1)
    tab_frame.rowconfigure(0, weight=1)
    tab_frame.rowconfigure(1, weight=0)

    # === Outer Frame Layout ===
    content_frame = ttk.Frame(tab_frame)
    content_frame.grid(row=0, column=0, sticky="nsew")
    content_frame.columnconfigure(0, weight=0)
    content_frame.columnconfigure(1, weight=1)
    content_frame.rowconfigure(0, weight=1)

    # === Measurement Settings ===
    settings_frame = ttk.LabelFrame(content_frame, text="Measurement Settings", width=320)
    settings_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsw")
    settings_frame.grid_propagate(False)

    inner_left = ttk.Frame(settings_frame)
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

    tk.Checkbutton(inner_left, text="Include Vavg", variable=vavg_var,
        bg="#2d2d2d", fg="#ffffff", activebackground="#333333",
        selectcolor="#555555", indicatoron=False, relief="raised").pack(fill="x", pady=2)

    tk.Checkbutton(inner_left, text="Include Vrms", variable=vrms_var,
        bg="#2d2d2d", fg="#ffffff", activebackground="#333333",
        selectcolor="#555555", indicatoron=False, relief="raised").pack(fill="x", pady=2)

    # === Logging Status ===
    status_frame = ttk.LabelFrame(content_frame, text="Logging Status")
    status_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
    status_frame.grid_rowconfigure(0, weight=1)
    status_frame.grid_columnconfigure(0, weight=1)

    text_logstatus = tk.Text(status_frame, height=10, font=("Courier", 10), bg="#1a1a1a", fg="#ffffff",
                             insertbackground="#ffffff", selectbackground="#333333", wrap="none")
    text_logstatus.config(state=tk.DISABLED)

    scrollbar_log = ttk.Scrollbar(status_frame, orient="vertical", command=text_logstatus.yview)
    text_logstatus.configure(yscrollcommand=scrollbar_log.set)

    text_logstatus.grid(row=0, column=0, sticky="nsew", padx=(5, 0), pady=5)
    scrollbar_log.grid(row=0, column=1, sticky="ns", padx=(0, 5))

    # === Buttons (bottom right under status) ===
    btn_frame = ttk.Frame(content_frame)
    btn_frame.grid(row=1, column=1, sticky="e", padx=10, pady=(0, 5))
    btn_frame.grid_columnconfigure((0, 1, 2), weight=1)

    def update_log_buttons(state="idle", paused=False):
        if state == "idle":
            start_button.config(state="normal")
            pause_button.config(state="disabled")
            stop_button.config(state="disabled")
        elif state == "logging":
            start_button.config(state="disabled")
            pause_button.config(state="normal")
            stop_button.config(state="normal")
        elif state == "paused":
            start_button.config(state="disabled")
            pause_button.config(state="normal")
            stop_button.config(state="normal")

    def update_log_status(msg):
        text_logstatus.config(state=tk.NORMAL)
        text_logstatus.insert(tk.END, msg + "\n")
        text_logstatus.see(tk.END)
        text_logstatus.config(state=tk.DISABLED)

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
                      vavg_var.get(), vrms_var.get(), update_log_status)
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

    start_button = ttk.Button(btn_frame, text="▶ Start Logging", command=start_log_session)
    pause_button = ttk.Button(btn_frame, text="⏸ Pause", command=toggle_pause)
    stop_button = ttk.Button(btn_frame, text="⏹ Stop", command=stop_log_session)

    start_button.grid(row=0, column=0, padx=5)
    pause_button.grid(row=0, column=1, padx=5)
    stop_button.grid(row=0, column=2, padx=5)

    # === Performance Tips ===
    tip_frame = ttk.LabelFrame(tab_frame, text="⚠️ Performance Tips")
    tip_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

    tip_text = (
        "Logging more than 2 channels with <2s interval can cause delays. "
        "Use ≥2s for 3–4 channels. Use ≥1s for 1–2 channels. Disable Vavg/Vrms for faster logging."
    )

    ttk.Label(tip_frame, text=tip_text, justify="left",
              background="#1a1a1a", foreground="#cccccc", wraplength=700).pack(anchor="w", padx=10, pady=5)

    update_log_buttons(state="idle")
