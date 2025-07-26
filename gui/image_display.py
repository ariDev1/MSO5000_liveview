# gui/image_display.py

import os
import time
import threading
from PIL import Image, ImageTk
import tkinter as tk
from config import INTERVALL_BILD
from utils.debug import log_debug

BILDPFAD = "/tmp/oszi_screenshot.png"
OSZI_IP = None
img_label = None

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
    while True:
        try:
            os.system(f"vncdo -s {OSZI_IP} capture {tmpfile}")
            if os.path.exists(tmpfile):
                os.replace(tmpfile, BILDPFAD)
        except Exception as e:
            log_debug(f"Screenshot Error: {e}")
        time.sleep(INTERVALL_BILD)

def update_image(root):
    try:
        if os.path.exists(BILDPFAD):
            with open(BILDPFAD, "rb") as f:
                img = Image.open(f)
                img.load()
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
    root.after(INTERVALL_BILD * 1000, lambda: update_image(root))

def start_screenshot_thread():
    thread = threading.Thread(target=screenshot_loop, daemon=True)
    thread.start()
