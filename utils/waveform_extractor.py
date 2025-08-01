# waveform_extractor.py
#
# Waveform Extraction Tool for Rigol MSO5000 Series
#
# This script connects to a Rigol MSO5000 oscilloscope over LAN and retrieves
# waveform data from any visible channel (CH1–4 or MATH1–3). It supports selecting
# SCPI waveform point modes (NORM, MAX, RAW) and fetches either screen-resolution
# or full memory-depth samples depending on mode.
#
# Features:
# - Select channel, sample count, and point mode (NORM, MAX, RAW)
# - Stop acquisition for stable memory access (optional)
# - Plot waveform with matplotlib
# - Save waveform plot as PNG (--save)
# - Print acquisition settings (sample rate, memory depth)
# - Auto-detect scope over-delivery and inform the user
#
# Example:
#   python3 plot_1000_samples.py 192.168.1.54 --channel 1 --samples 1200 --mode RAW --stop --save
#
# Note: In RAW/MAX modes, the scope may ignore the requested sample count and return
# the full memory buffer (e.g., 25M points). This script detects and reports such behavior.

import sys
import os
import argparse
import time
import numpy as np
import matplotlib.pyplot as plt

# Allow import of project modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scpi.interface import connect_scope, scpi_lock, safe_query
from config import BLACKLISTED_COMMANDS, WAV_POINTS
import config

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ip", help="Scope IP address")
    parser.add_argument("--channel", type=str, default="1", help="Channel (1-4, MATH1, etc.)")
    parser.add_argument("--samples", type=int, default=1000, help="Number of samples to fetch")
    parser.add_argument("--mode", type=str, choices=["NORM", "MAX", "RAW"], default="NORM",
                        help="Waveform point mode: NORM (screen), MAX (up to max), RAW (full memory)")
    parser.add_argument("--stop", action="store_true", help="Stop acquisition before fetch (safer for RAW)")
    parser.add_argument("--save", action="store_true", help="Save plot as PNG")
    args = parser.parse_args()

    config.WAV_POINTS = args.samples

    scope = connect_scope(args.ip)
    if not scope:
        print("❌ Could not connect to scope.")
        return

    chan = args.channel if args.channel.upper().startswith("MATH") else f"CHAN{args.channel}"
    print(f"📡 Connected. Fetching {args.samples} samples from {chan}...")

    try:
        with scpi_lock:
            # Optional: stop scope before fetch (RAW stability)
            if args.stop:
                scope.write(":STOP")
                print("🛑 Acquisition stopped for waveform readout")

            mode = args.mode.upper()
            valid_modes = ["NORM", "MAX", "RAW"]
            if mode not in valid_modes:
                print(f"⚠️ Invalid mode '{mode}' — defaulting to NORM.")
                mode = "NORM"

            if safe_query(scope, f":{chan}:DISP?") != "1":
                print(f"⚠️ Channel {chan} is not visible — skipping.")
                return

            scope.write(":WAV:FORM BYTE")
            scope.write(f":WAV:MODE {mode}")
            print(f"🔧 Using point mode: {mode}")
            scope.write(f":WAV:POIN:MODE {mode}")
            scope.write(f":WAV:POIN {args.samples}")
            scope.write(f":WAV:SOUR {chan}")

            scope.query(":WAV:PRE?")
            time.sleep(0.1)
            pre = scope.query(":WAV:PRE?").split(",")
            xinc = float(pre[4])
            xorig = float(pre[5])
            yinc = float(pre[7])
            yorig = float(pre[8])
            yref = float(pre[9])
            probe = float(safe_query(scope, f":{chan}:PROB?", "1.0"))

            # Print acquisition config
            srate = safe_query(scope, ":ACQ:SRAT?")
            mdepth = safe_query(scope, ":ACQ:MDEP?")
            print(f"📊 Sample Rate: {srate} Sa/s — Memory Depth: {mdepth} pts")

            print("⏳ Downloading waveform data...")
            raw = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)

            # Feedback on returned length
            if len(raw) < args.samples:
                print(f"⚠️ Only received {len(raw)} samples (requested {args.samples}).")

                if ":WAV:POIN:MODE?" in BLACKLISTED_COMMANDS:
                    confirmed_mode = "N/A (blacklisted)"
                else:
                    confirmed_mode = safe_query(scope, ":WAV:POIN:MODE?").strip().upper()

                print(f"📟 Scope confirmed mode: {confirmed_mode}")

                if confirmed_mode not in valid_modes:
                    print(f"⚠️ Could not confirm point mode. Scope may not support ':WAV:POIN:MODE?'.")
                elif confirmed_mode != mode:
                    print(f"⚠️ Requested mode '{mode}' but scope is using '{confirmed_mode}' instead.")
                    print("ℹ️ Scope may have rejected the mode due to memory or acquisition settings.")
                else:
                    print(f"ℹ️ Scope accepted mode '{mode}', but still returned fewer samples.")
                    print("ℹ️ Try increasing timebase or memory depth (e.g., :ACQ:MDEP 56000).")
            else:
                print(f"✅ Received full {len(raw)} samples from scope.")


            if len(raw) == 0:
                print("⚠️ No waveform data returned.")
                return

            # Decode to voltage
            t = xorig + np.arange(len(raw)) * xinc
            v = ((raw - yref) * yinc + yorig) * probe

            # Plot
            plt.figure(figsize=(10, 4))
            plt.plot(t, v, linewidth=1.0)
            plt.title(f"{len(raw)} Samples from {chan} (mode: {mode})")
            plt.xlabel("Time (s)")
            plt.ylabel("Voltage (V)")
            plt.grid(True)
            plt.tight_layout()

            if args.save:
                fname = f"{chan}_{len(raw)}pts_{mode}_{time.strftime('%Y%m%d_%H%M%S')}.png"
                plt.savefig(fname, dpi=150)
                print(f"🖼️  Saved plot as {fname}")

            plt.show()

            if args.stop:
                scope.write(":RUN")
                print("▶️ Acquisition resumed.")

    except Exception as e:
        print(f"❌ Error during waveform fetch: {e}")

if __name__ == "__main__":
    main()
