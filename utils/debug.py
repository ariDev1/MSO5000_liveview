import time
from collections import deque
import tkinter as tk

debug_log = deque(maxlen=10000)
debug_paused = False
debug_widget = None

def log_debug(message):
    timestamp = time.strftime("%H:%M:%S")
    full_msg = f"[{timestamp}] {message}"
    debug_log.append(full_msg)

    # Print to console
    print(full_msg)

    # Show in GUI
    if debug_widget and not debug_paused:
        debug_widget.config(state=tk.NORMAL)
        debug_widget.delete(1.0, tk.END)
        debug_widget.insert(tk.END, "\n".join(list(debug_log)[-500:]))
        debug_widget.config(state=tk.DISABLED)
        debug_widget.see(tk.END)

def attach_debug_widget(widget):
    global debug_widget
    debug_widget = widget
