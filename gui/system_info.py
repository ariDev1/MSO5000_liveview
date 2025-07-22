# gui/system_info.py

import tkinter as tk
from tkinter import ttk
from version import APP_NAME, VERSION, GIT_COMMIT, BUILD_DATE, AUTHOR, PROJECT_URL
from scpi.data import scpi_data
from utils.debug import log_debug

def setup_system_info_tab(tab_frame, root):
    text_widget = tk.Text(tab_frame, font=("Courier", 10), bg="#1a1a1a", fg="#ffffff",
                          insertbackground="#ffffff", selectbackground="#333333", wrap="none")
    text_widget.pack(side="left", fill="both", expand=True, padx=5, pady=5)

    scrollbar = ttk.Scrollbar(tab_frame, orient="vertical", command=text_widget.yview)
    text_widget.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")

    text_widget.config(state=tk.DISABLED)

    def copy_system_info_to_clipboard():
        meta_info = (
            f"\n\n{'-'*60}\n"
            f"{APP_NAME} {VERSION}\n"
            f"Build Date : {BUILD_DATE}\n"
            f"Git Commit : {GIT_COMMIT}\n"
            f"Maintainer : {AUTHOR}\n"
            f"Project    : {PROJECT_URL}\n"
        )

        base_info = scpi_data.get("system_info", "")
        full_text = base_info + meta_info

        root.clipboard_clear()
        root.clipboard_append(full_text)
        root.update()
        log_debug("📋 System Info copied to clipboard")

    ttk.Button(tab_frame, text="📋 Copy System Info", command=copy_system_info_to_clipboard).pack(
        side="bottom", anchor="e", padx=10, pady=5
    )

    # Smart refresh with scroll preservation
    last_system_text = [""]

    def update_system_info():
        meta_info = (
            f"\n\n{'-'*60}\n"
            f"{APP_NAME} {VERSION}\n"
            f"Build Date : {BUILD_DATE}\n"
            f"Git Commit : {GIT_COMMIT}\n"
            f"Maintainer : {AUTHOR}\n"
            f"Project    : {PROJECT_URL}\n"
        )

        base_info = scpi_data.get("system_info", "")
        freq_ref = scpi_data.get("freq_ref", None)
        if freq_ref:
            base_info += f"\n{'Freq. Reference' :<18}: {freq_ref}"

        full_text = base_info + meta_info

        if full_text != last_system_text[0]:
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

            last_system_text[0] = full_text

        root.after(2000, update_system_info)

    update_system_info()
