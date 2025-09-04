# gui/image_display.py

import os
import time
import threading
from PIL import Image, ImageTk
import tkinter as tk
from config import INTERVALL_BILD, SCOPE_IMAGE_ALLOW_UPSCALE
from utils.debug import log_debug

BILDPFAD = "/tmp/oszi_screenshot.png"
OSZI_IP = None
img_label = None
update_after_id = [None]

_capture_event = threading.Event()
_capture_event.set()  # start in 'running' state
_paused = False  # track state for clean logging

def pause_screenshots():
    """Pause VNC captures (called when image is hidden)."""
    global _paused
    _capture_event.clear()
    if not _paused:
        _paused = True
        log_debug("📷 Screenshots paused (Hide) — stopping VNC capture", level="MINIMAL")

def resume_screenshots():
    """Resume VNC captures (called when image is shown)."""
    global _paused
    if _paused:
        log_debug("📷 Screenshots resumed (Show) — restarting VNC capture", level="MINIMAL")
    _paused = False
    _capture_event.set()

def set_ip(ip):
    global OSZI_IP
    OSZI_IP = ip
    update_filename()

def update_filename():
    global BILDPFAD
    if OSZI_IP:
        BILDPFAD = f"/tmp/oszi_screenshot_{OSZI_IP.replace('.', '_')}.png"

def attach_image_label(label_widget):
    global img_label
    img_label = label_widget

def screenshot_loop():
    tmpfile = BILDPFAD + ".tmp.png"
    log_debug("📷 Screenshot thread started", level="MINIMAL")
    while True:
        try:
            # Block here when paused
            _capture_event.wait()

            # If an IP isn’t set yet, don’t hammer vncdo; just idle briefly
            if not OSZI_IP:
                time.sleep(0.5)
                continue

            os.system(f"vncdo -s {OSZI_IP} capture {tmpfile}")
            if os.path.exists(tmpfile):
                os.replace(tmpfile, BILDPFAD)
        except Exception as e:
            log_debug(f"Screenshot Error: {e}")
        time.sleep(INTERVALL_BILD)

def update_image(root):
    try:
        from app import app_state
        if getattr(app_state, "is_shutting_down", False):
            return
        if img_label is None or not isinstance(img_label, tk.Widget) or not img_label.winfo_exists():
            return

        #Skip work if not currently visible
        if not img_label.winfo_ismapped():
            # Still reschedule, but do nothing heavy
            pass
        else:
            if os.path.exists(BILDPFAD):
                with open(BILDPFAD, "rb") as f:
                    img = Image.open(f); img.load()
                window_width = root.winfo_width()
                window_height = root.winfo_height()
                available_height = max(300, window_height - 250)
                available_width = max(600, window_width - 50)

                img_ratio = img.width / img.height
                if available_width / available_height > img_ratio:
                    new_height = available_height
                    new_width = int(available_height * img_ratio)
                else:
                    new_width = available_width
                    new_height = int(available_width / img_ratio)

                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                img_tk = ImageTk.PhotoImage(img)
                img_label.config(image=img_tk)
                img_label.image = img_tk
    except Exception as e:
        log_debug(f"Image Load Error: {e}")

    # Re-schedule...
    try:
        from app import app_state
        if not getattr(app_state, "is_shutting_down", False) and img_label and img_label.winfo_exists():
            root.after(INTERVALL_BILD * 1000, lambda: update_image(root))
    except tk.TclError:
        return

def cancel_image_updates(root):
    try:
        if update_after_id[0] is not None:
            root.after_cancel(update_after_id[0])
            update_after_id[0] = None
    except Exception:
        pass

def start_screenshot_thread():
    thread = threading.Thread(target=screenshot_loop, daemon=True)
    thread.start()
