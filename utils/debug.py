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
        # Determine shutdown state safely
        try:
            from app import app_state
            shutting_down = getattr(app_state, "is_shutting_down", False)
        except Exception:
            shutting_down = False

        # If we’re shutting down, proactively unhook yscrollcommand to avoid '...scroll'
        try:
            if shutting_down and debug_widget and debug_widget.winfo_exists():
                debug_widget.configure(yscrollcommand=None)
        except tk.TclError:
            return

        # Bail early if shutting down / no widget / paused
        if shutting_down or debug_widget is None or debug_paused:
            return

        try:
            if not debug_widget.winfo_exists():
                return

            debug_widget.config(state=tk.NORMAL)
            debug_widget.delete(1.0, tk.END)
            debug_widget.insert(tk.END, "\n".join(list(debug_log)[-500:]))
            debug_widget.config(state=tk.DISABLED)
            debug_widget.see(tk.END)
        except tk.TclError:
            # Widget hierarchy is going away
            return

        # Re-schedule only if still alive
        if not shutting_down and debug_widget.winfo_exists():
            root.after(250, update_gui)

    root.after(250, update_gui)
