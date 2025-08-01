# gui/scpi_console.py

import time
import tkinter as tk
from tkinter import ttk
from scpi.interface import safe_query, scpi_lock, connect_scope
from scpi.data import scpi_data
from utils.debug import log_debug
from scpi.waveform import get_channel_waveform_data, compute_power_from_scope

def setup_scpi_tab(tab_frame, ip):
    tab_frame.columnconfigure(0, weight=1)  # Left expands
    tab_frame.columnconfigure(1, weight=0)  # Right fixed
    tab_frame.rowconfigure(0, weight=1)

    # --- Left Side (input + output + send) ---
    left_frame = ttk.Frame(tab_frame)
    left_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

    scpi_input = ttk.Entry(left_frame, width=60)
    scpi_input.pack(pady=(0, 5), anchor="nw", fill="x")

    scpi_output = tk.Text(left_frame, height=14, font=("Courier", 10),
                          bg="#1a1a1a", fg="#ffffff", insertbackground="#ffffff",
                          selectbackground="#333333", wrap="none")
    scpi_data["scpi_output_widget"] = scpi_output
    scpi_output.pack(fill="both", expand=True)

    btn_row = tk.Frame(left_frame, bg="#1a1a1a")
    btn_row.pack(pady=10, anchor="w", fill="x")

    send_button = ttk.Button(btn_row, text="☢ Send", style="Action.TButton")
    send_button.pack(side="left", padx=(0, 10), ipadx=8, ipady=2)

    selftest_button = ttk.Button(btn_row, text="✞ Run Self-Test", style="Action.TButton",
                                 command=lambda: run_self_test(scpi_output))
    selftest_button.pack(side="left", ipadx=8, ipady=2)

    # --- Right Side (command list + insert button) ---
    right_frame = tk.Frame(tab_frame, width=420, bg="#1a1a1a", highlightthickness=0)
    right_frame.grid(row=0, column=1, sticky="ns", padx=5, pady=5)
    right_frame.grid_propagate(False)

    tk.Label(right_frame, text="Known Commands:",
             bg="#1a1a1a", fg="#ffffff").pack(anchor="w", pady=(0, 5))

    cmd_listbox = tk.Listbox(
        right_frame,
        bg="#1a1a1a", fg="#ffffff",
        selectbackground="#555555",
        height=16, exportselection=False,
        highlightthickness=0, relief="flat"
    )
    cmd_listbox.pack(fill="both", expand=True, padx=5, pady=(0, 5))

    def insert_selected_command():
        sel = cmd_listbox.curselection()
        if sel:
            selected_cmd = cmd_listbox.get(sel[0])
            scpi_input.delete(0, tk.END)
            scpi_input.insert(0, selected_cmd)

    insert_button = ttk.Button(right_frame, text="➡ Send to Input", style="Action.TButton",
                               command=insert_selected_command)
    insert_button.pack(pady=(0, 10), padx=5, ipadx=8, ipady=2, fill="x")

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

def run_self_test(output):
    def write(msg):
        from utils.debug import log_debug
        log_debug(msg)
        output.insert(tk.END, msg + "\n")
        output.see(tk.END)

    scope = connect_scope(scpi_data.get("ip", ""))

    if not scope:
        write("❌ Not connected to scope")
        return

    write("> 🧪 Self-Test Started")

    try:
        idn = safe_query(scope, "*IDN?", "N/A")
        write(f"✅ Scope ID: {idn}")
        scope.write(":STOP")
        time.sleep(0.5)

        for ch in [1]:
            scale = safe_query(scope, f":CHAN{ch}:SCALe?")
            unit  = safe_query(scope, f":CHAN{ch}:UNIT?")
            prob  = safe_query(scope, f":CHAN{ch}:PROB?")
            write(f"✅ CH{ch}: Scale={scale}, Unit={unit}, Probe={prob}x")
            time.sleep(0.5)

        try:
            vpp, vavg, vrms = get_channel_waveform_data(scope, 1)
            if vrms is not None:
                write(f"✅ Vrms = {vrms:.3f} V")
            else:
                write("❌ Vrms value was None")
        except Exception as e:
            write(f"❌ Exception during waveform fetch: {e}")


        result = compute_power_from_scope(scope, 1, 2)
        if result:
            p = result.get("Real Power (P)", None)
            if p is not None:
                write(f"✅ Power Estimate = {p:.2f} W")
                time.sleep(0.5)
        else:
            write("❌ Power analysis failed")

        if scpi_data.get("idn", None):
            write("✅ SCPI loop is active")
            time.sleep(0.5)
        else:
            write("⚠️ SCPI loop IDN not set")

        write("✅ Self-Test Passed ✅")

    except Exception as e:
        write(f"❌ Error: {e}")
