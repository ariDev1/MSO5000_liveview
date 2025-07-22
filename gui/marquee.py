import tkinter as tk
import urllib.request
from utils.debug import log_debug

def attach_marquee(parent, file_path="marquee.txt", url=None, speed=2):
    # Try downloading marquee text from URL
    text = None
    if url:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                text = response.read().decode("utf-8").strip()
                log_debug(f"🌐 Marquee text loaded from URL: {url}")
        except Exception as e:
            log_debug(f"⚠️ Marquee fetch failed from {url}: {e}")

    if not text:
        try:
            with open(file_path, "r") as f:
                text = f.read().strip()
        except:
            text = "⚠️ No marquee text available."

    # Sanitize characters that may render poorly
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')

    canvas = tk.Canvas(parent, height=24, bg="#1a1a1a", highlightthickness=0)
    canvas.grid(row=0, column=0, columnspan=99, sticky="ew")  # stretch fully

    text_id = canvas.create_text(0, 12, text=text, anchor="w", fill="#008066",
                                 font=("TkFixedFont", 11, "normal"))

    def update_width(event=None):
        canvas.config(width=parent.winfo_width())

    canvas.bind("<Configure>", update_width)
    parent.bind("<Configure>", update_width)
    canvas.after(100, update_width)

    def scroll():
        try:
            x = canvas.coords(text_id)[0]
            new_x = x - speed
            text_width = canvas.bbox(text_id)[2]
            if new_x < -text_width:
                new_x = canvas.winfo_width()
            canvas.coords(text_id, new_x, 12)
        except:
            pass
        canvas.after(50, scroll)

    scroll()
    return canvas
