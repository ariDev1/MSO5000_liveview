# gui/scpi_console.py

import tkinter as tk
from tkinter import ttk
from scpi.interface import safe_query, scpi_lock
from scpi.data import scpi_data
from utils.debug import log_debug

def setup_scpi_tab(tab_frame, ip):
    tab_frame.columnconfigure(0, weight=3)
    tab_frame.columnconfigure(1, weight=1)
    tab_frame.rowconfigure(0, weight=1)

    # --- Left Side (input + output + send) ---
    left_frame = ttk.Frame(tab_frame)
    left_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

    scpi_input = ttk.Entry(left_frame, width=60)
    scpi_input.pack(pady=(0, 5), anchor="nw", fill="x")

    scpi_output = tk.Text(left_frame, height=14, font=("Courier", 10),
                          bg="#1a1a1a", fg="#ffffff", insertbackground="#ffffff",
                          selectbackground="#333333", wrap="none")
    scpi_output.pack(fill="both", expand=False)

    send_button = ttk.Button(left_frame, text="📡 Send")
    send_button.pack(pady=10, anchor="w")

    # --- Right Side (command list + insert button) ---
    right_frame = ttk.Frame(tab_frame)
    right_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

    ttk.Label(right_frame, text="Known Commands:").pack(anchor="w", pady=(0, 5))

    cmd_listbox = tk.Listbox(right_frame, bg="#1a1a1a", fg="#ffffff", selectbackground="#555555",
                             height=16, exportselection=False)
    cmd_listbox.pack(fill="both", expand=True)

    def insert_selected_command():
        sel = cmd_listbox.curselection()
        if sel:
            selected_cmd = cmd_listbox.get(sel[0])
            scpi_input.delete(0, tk.END)
            scpi_input.insert(0, selected_cmd)

    ttk.Button(right_frame, text="➡ Insert into Input", command=insert_selected_command).pack(pady=5)
    cmd_listbox.bind("<Double-Button-1>", lambda e: insert_selected_command())

    def load_known_commands():
        try:
            with open("scpi_command_list.txt", "r") as f:
                return [line.strip() for line in f if line.strip()]
        except Exception as e:
            log_debug(f"⚠️ Failed to load commands.txt: {e}", level="MINIMAL")
            return []

    for cmd in load_known_commands():
        cmd_listbox.insert(tk.END, cmd)

    def send_scpi_command():
        cmd = scpi_input.get().strip()
        if not cmd:
            return
        log_debug(f"📤 SCPI command sent by user: {cmd}", level="MINIMAL")

        scope = scpi_data.get("scope")
        if not scope:
            msg = "❌ Not connected to scope"
            scpi_output.insert(tk.END, f"{msg}\n")
            log_debug(msg, level="MINIMAL")
            return

        try:
            with scpi_lock:
                resp = safe_query(scope, cmd, default="(no response)")
        except Exception as e:
            resp = f"❌ Exception: {e}"
            log_debug(f"❌ Exception during SCPI command: {e}", level="MINIMAL")

        scpi_output.insert(tk.END, f"> {cmd}\n{resp}\n\n")
        scpi_output.see(tk.END)

    send_button.config(command=send_scpi_command)
