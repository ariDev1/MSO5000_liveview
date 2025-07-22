# gui/licenses.py

import tkinter as tk
from tkinter import ttk
from scpi.licenses import get_license_options

def setup_licenses_tab(tab_frame, ip, root):
    license_var = tk.StringVar()

    label = tk.Label(
        tab_frame, textvariable=license_var, font=("Courier", 10),
        justify="left", anchor="nw", bg="#1a1a1a", fg="#ffffff", wraplength=1100
    )
    label.pack(fill="both", expand=True, padx=10, pady=10)

    def update_licenses():
        options = get_license_options(ip)
        if not options:
            license_var.set("⚠️ No license data received.")
        else:
            lines = ["📋 LICENSED OPTIONS:", "=" * 60]
            for opt in options:
                status = opt['status']
                symbol = "✅" if status == "Forever" else "🕑" if "Trial" in status else "❌"
                lines.append(f"{symbol} {opt['code']:10s} | {status:12s} | {opt['desc']}")
            license_var.set("\n".join(lines))
        root.after(15000, update_licenses)

    update_licenses()
