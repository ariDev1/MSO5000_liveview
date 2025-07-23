# gui/marquee.py

import tkinter as tk
import urllib.request
import secrets
from utils.debug import log_debug
import random

def attach_marquee(parent, file_path="marquee.txt", url=None, speed=2, rotate_interval=60000):
    text_lines = []

    if url:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                text_data = response.read().decode("utf-8").strip()
                text_lines = [line.strip() for line in text_data.splitlines() if line.strip()]
                log_debug(f"🌐 Marquee fetched from URL — {len(text_lines)} lines")
        except Exception as e:
            log_debug(f"⚠️ Failed to fetch marquee.txt from server: {e}")

    if not text_lines:
        try:
            with open(file_path, "r") as f:
                text_lines = [line.strip() for line in f if line.strip()]
                log_debug(f"📁 Marquee loaded locally — {len(text_lines)} lines")
        except Exception as e:
            text_lines = ["⚠️ Could not load marquee.txt"]
            log_debug(f"❌ Failed to read local marquee.txt: {e}")

    if not text_lines:
        text_lines = ["(no content)"]

    # Pure, emoji-free Tesla thoughts
    tesla_thoughts = [
        "This frequency... it resonates.",
        "The Earth rings like a bell at 7.83 Hz.",
        "I can feel the power... but can you measure it?",
        "You call this noise? I call it music.",
        "Vibrations. Always vibrations.",
        "The energy is not lost. It's hiding behind sinewave.",
        "If you want to understand the universe, think in terms of energy and frequency.",
    ]

    canvas = tk.Canvas(parent, height=24, bg="#1a1a1a", highlightthickness=0)
    canvas.grid(row=0, column=0, sticky="ew")
    parent.columnconfigure(0, weight=1)

    current_text = secrets.choice(text_lines)
    text_id = canvas.create_text(0, 12, text=current_text, anchor="w",
                                 fill="#00ffcc", font=("Courier", 11, "bold"))

    def resize_handler(event):
        canvas.config(width=event.width)

    parent.bind("<Configure>", resize_handler)

    def scroll():
        try:
            x = canvas.coords(text_id)[0]
            bbox = canvas.bbox(text_id)
            text_width = bbox[2] - bbox[0] if bbox else 0
            new_x = x - speed
            if new_x < -text_width:
                new_x = canvas.winfo_width()
            canvas.coords(text_id, new_x, 12)
        except Exception as e:
            log_debug(f"⚠️ Scroll error: {e}")
        canvas.after(50, scroll)

    def rotate_text():
        nonlocal current_text

        is_tesla = False
        if random.random() < 0.2:
            new_text = secrets.choice(tesla_thoughts)
            is_tesla = True
        else:
            new_text = secrets.choice(text_lines)

        if new_text == current_text:
            new_text = secrets.choice(text_lines)
        current_text = new_text

        # Update font and color
        font = ("Times New Roman", 11, "italic") if is_tesla else ("Courier", 11, "bold")
        color = "#ffcc00" if is_tesla else "#00ffcc"

        canvas.itemconfig(text_id, text=current_text, font=font, fill=color)
        canvas.coords(text_id, canvas.winfo_width(), 12)
        canvas.after(rotate_interval, rotate_text)

    scroll()
    rotate_text()
    return canvas
