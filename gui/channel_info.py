# gui/channel_info.py

import tkinter as tk
from tkinter import ttk
from io import StringIO
from scpi.data import scpi_data
from scpi.interface import connect_scope
from scpi.waveform import export_channel_csv
from utils.debug import log_debug
from app.app_state import is_logging_active

def setup_channel_tab(tab_frame, ip, root):
    text_widget = tk.Text(tab_frame, font=("Courier", 10), bg="#1a1a1a", fg="#ffffff",
                          insertbackground="#ffffff", selectbackground="#333333", wrap="none")
    text_widget.pack(side="left", fill="both", expand=True, padx=5, pady=5)

    scrollbar = ttk.Scrollbar(tab_frame, orient="vertical", command=text_widget.yview)
    text_widget.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    text_widget.config(state=tk.DISABLED)

    def copy_channel_settings():
        full_text = text_widget.get("1.0", tk.END).strip()
        root.clipboard_clear()
        root.clipboard_append(full_text)
        root.update()
        log_debug("📋 Channel Settings copied to clipboard")

    def copy_channel_csv_to_clipboard():
        if is_logging_active:
            log_debug("❌ Logging in progress — copy disabled")
            return

        scope = connect_scope(ip)
        if not scope:
            log_debug("❌ Not connected — copy aborted")
            return

        output = StringIO()
        for ch in scpi_data.get("channel_info", {}).keys():
            try:
                if ch.startswith("CH"):
                    ch_num = int(ch[2:])
                    csv_path = export_channel_csv(scope, ch_num)
                elif ch.startswith("MATH"):
                    csv_path = export_channel_csv(scope, ch)
                else:
                    continue
                with open(csv_path, "r") as f:
                    output.write(f.read())
                    output.write("\n\n")
            except Exception as e:
                log_debug(f"⚠️ Export failed for {ch}: {e}")

        clipboard_data = output.getvalue()
        root.clipboard_clear()
        root.clipboard_append(clipboard_data)
        root.update()
        log_debug("📋 Channel CSV data copied to clipboard")

    def on_export():
        if is_logging_active:
            log_debug("❌ Logging in progress — export disabled")
            return

        scope = connect_scope(ip)
        if not scope:
            log_debug("❌ Not connected — export aborted")
            return

        for ch in scpi_data.get("channel_info", {}).keys():
            try:
                if ch.startswith("CH"):
                    ch_num = int(ch[2:])
                    export_channel_csv(scope, ch_num)
                elif ch.startswith("MATH"):
                    export_channel_csv(scope, ch)
            except Exception as e:
                log_debug(f"⚠️ Export failed for {ch}: {e}")

    btn_frame = ttk.Frame(tab_frame)
    btn_frame.pack(side="bottom", anchor="e", padx=10, pady=5)

    ttk.Button(btn_frame, text="📋 Copy Settings", command=copy_channel_settings).pack(fill="x", pady=2)
    ttk.Button(btn_frame, text="📋 Copy CSV Data", command=copy_channel_csv_to_clipboard).pack(fill="x", pady=2)
    tk.Button(btn_frame, text="📥 Export Channel CSV", command=on_export,
              bg="#2d2d2d", fg="#ffffff", activebackground="#333333").pack(fill="x", pady=4)

    last_text = [""]

    def update_channel_info():
        lines = []
        for ch, info in scpi_data["channel_info"].items():
            if ch.startswith("MATH"):
                lines.append(f"{ch:<6}: Scale={info['scale']:<8} Offset={info['offset']:<8} Type={info.get('type', 'N/A')}")
            else:
                lines.append(f"{ch:<6}: Scale={info['scale']:<8} Offset={info['offset']:<8} Coupling={info['coupling']:<6} Probe={info['probe']}x")

        full_text = "\n".join(lines) if lines else "⚠️ No active channels"

        if full_text != last_text[0]:
            scroll_position = text_widget.yview()
            sel_start = text_widget.index(tk.SEL_FIRST) if text_widget.tag_ranges(tk.SEL) else None
            sel_end   = text_widget.index(tk.SEL_LAST)  if text_widget.tag_ranges(tk.SEL) else None

            text_widget.config(state=tk.NORMAL)
            text_widget.delete("1.0", tk.END)
            text_widget.insert(tk.END, full_text)
            text_widget.config(state=tk.DISABLED)

            if sel_start and sel_end:
                text_widget.tag_add(tk.SEL, sel_start, sel_end)
            text_widget.yview_moveto(scroll_position[0])

            last_text[0] = full_text

        tab_frame.after(2000, update_channel_info)

    update_channel_info()
