# utils/debug.py
"""
MSO5000 Liveview — Debug Logging Utilities
------------------------------------------
This module provides a tiny, low‑overhead debug log and a safe Tkinter updater
for showing recent messages in the GUI's "Debug Log" tab.

Design goals
------------
• Zero-risk for measurement paths: logging never raises upstream.
• Thread-safe enough for this app: writers append to a bounded deque; the GUI
  reader runs on Tk's main thread via `after()`.
• Graceful teardown: the updater stops itself cleanly when the window closes
  or the app enters shutdown.

Public API
----------
set_debug_level(level: str)
    Set global filter: "FULL" (default) or "MINIMAL". Messages logged with
    level="MINIMAL" always pass; any other level is suppressed when in MINIMAL.

log_debug(message: str, level: str = "FULL")
    Timestamp + append the message to the ring buffer and also print to stdout.

attach_debug_widget(widget: tk.Text)
    Provide the Text widget where logs should appear. (The module does not
    create widgets; it only updates the one you attach.)

start_debug_updater(root: tk.Tk)
    Starts a recurring GUI update (~4 Hz). It:
      - stops automatically during teardown,
      - shows only the most recent ~500 lines to keep UI responsive,
      - unhooks yscrollcommand on destroy to avoid "...scroll" Tcl errors.

Notes
-----
• The ring buffer is limited to 10,000 lines to cap memory use.
• This module never touches acquisition or SCPI loops directly—only text UI.
• Do not import Tkinter here in tight inner loops—only at module scope as done.
"""

import time
from collections import deque
import tkinter as tk

# -------- Internal state (kept minimal and explicit) -------------------------

# Bounded ring buffer of recent log lines. Large enough for long sessions,
# small enough to keep memory bounded even with chatty logs.
debug_log = deque(maxlen=10000)

# Pause flag (currently unused by UI, kept for future needs).
debug_paused = False

# Tk Text widget attached by the GUI to display logs.
debug_widget = None

# Global debug level filter: "FULL" (all messages) or "MINIMAL" (only level="MINIMAL")
DEBUG_LEVEL = "FULL"

# Stores the current `after()` callback id so we can cancel it during shutdown.
_debug_after_id = [None]


# -------- Configuration -------------------------------------------------------

def set_debug_level(level):
    """
    Set global log filtering. Accepts "FULL" or "MINIMAL".
    In MINIMAL mode, only messages logged with level="MINIMAL" are shown.
    """
    global DEBUG_LEVEL
    DEBUG_LEVEL = level


# -------- Logging entry point -------------------------------------------------

def log_debug(message, level="FULL"):
    """
    Append a timestamped message to the ring buffer and print to stdout.

    Filtering:
      - If DEBUG_LEVEL == "MINIMAL", drop messages where level != "MINIMAL".
      - Otherwise, accept all messages.
    """
    if DEBUG_LEVEL == "MINIMAL" and level != "MINIMAL":
        return
    timestamp = time.strftime("%H:%M:%S")
    full_msg = f"[{timestamp}] {message}"
    debug_log.append(full_msg)
    # Keep stdout printing for CLI runs / log captures.
    print(full_msg)


# -------- GUI wiring ----------------------------------------------------------

def attach_debug_widget(widget):
    """
    Provide the Text widget used to display logs.
    The updater will check `.winfo_exists()` before touching it.
    """
    global debug_widget
    debug_widget = widget


def start_debug_updater(root):
    """
    Start a recurring Tk `after()` loop that mirrors the ring buffer into the
    attached Text widget. Safe against teardown and window destruction.

    Life-cycle guarantees:
      - Stops when the app sets `app_state.is_shutting_down = True`.
      - Stops if the widget is destroyed.
      - Cancels its own pending after() on <Destroy> to avoid dangling callbacks.
      - Unhooks yscrollcommand at shutdown to prevent Tcl "...scroll" errors.
    """
    def update_gui():
        # Detect shutdown without importing heavy modules at import-time.
        try:
            from app import app_state
            shutting_down = getattr(app_state, "is_shutting_down", False)
        except Exception:
            shutting_down = False

        # If shutting down or paused or not yet attached, do nothing.
        if shutting_down or debug_widget is None or debug_paused:
            return

        try:
            # Widget might have been destroyed while we were scheduled.
            if not debug_widget.winfo_exists():
                return

            # Only show a tail to keep UI snappy (≈ last 500 lines).
            tail = "\n".join(list(debug_log)[-500:])

            debug_widget.config(state=tk.NORMAL)
            debug_widget.delete(1.0, tk.END)
            debug_widget.insert(tk.END, tail)
            debug_widget.config(state=tk.DISABLED)
            debug_widget.see(tk.END)

        except tk.TclError:
            # Happens during teardown; silently stop.
            return

        # Re-schedule next tick if still alive.
        try:
            if not shutting_down and debug_widget.winfo_exists():
                _debug_after_id[0] = root.after(250, update_gui)  # ~4 Hz
        except tk.TclError:
            # Root/window is going away—stop rescheduling.
            return

    # Schedule first tick.
    _debug_after_id[0] = root.after(250, update_gui)

    # Ensure we cancel our after() and unhook scroll bindings on destroy.
    def _shutdown(*_):
        try:
            if _debug_after_id[0] is not None:
                root.after_cancel(_debug_after_id[0])
                _debug_after_id[0] = None
        except Exception:
            pass
        # Unhook yscrollcommand to avoid late callbacks into a dead scrollbar.
        try:
            if debug_widget and debug_widget.winfo_exists():
                debug_widget.configure(yscrollcommand=None)
        except Exception:
            pass

    # Bind once on the top-level root; Tk will call this during teardown.
    root.bind("<Destroy>", _shutdown)
