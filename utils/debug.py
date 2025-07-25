# utils/debug.py

import time
from collections import deque
import tkinter as tk

debug_log = deque(maxlen=10000)
debug_paused = False
debug_widget = None

# Global debug level: "FULL" or "MINIMAL"
DEBUG_LEVEL = "FULL"

def set_debug_level(level):
    global DEBUG_LEVEL
    DEBUG_LEVEL = level

def log_debug(message, level="FULL"):
    if DEBUG_LEVEL == "MINIMAL" and level != "MINIMAL":
        return
    timestamp = time.strftime("%H:%M:%S")
    full_msg = f"[{timestamp}] {message}"
    debug_log.append(full_msg)
    print(full_msg)

def attach_debug_widget(widget):
    global debug_widget
    debug_widget = widget

def start_debug_updater(root):
    def update_gui():
        if debug_widget and not debug_paused:
            try:
                debug_widget.config(state=tk.NORMAL)
                debug_widget.delete(1.0, tk.END)
                debug_widget.insert(tk.END, "\n".join(list(debug_log)[-500:]))
                debug_widget.config(state=tk.DISABLED)
                debug_widget.see(tk.END)
            except Exception as e:
                print(f"[log_debug GUI error] {e}")
        root.after(250, update_gui)  # update every 250ms

    root.after(250, update_gui)
