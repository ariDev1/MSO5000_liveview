#!/usr/bin/env python3

import os
import glob
import sys
import pandas as pd
import matplotlib.pyplot as plt

def get_latest_csv(folder="oszi_csv"):
    try:
        csv_files = glob.glob(os.path.join(folder, "*.csv"))
        if not csv_files:
            print("⚠️ No CSV files found.")
            return None
        latest = max(csv_files, key=os.path.getmtime)
        return latest
    except Exception as e:
        print(f"❌ Error finding latest CSV: {e}")
        return None

def preview_csv_plot(csv_path):
    try:
        data = pd.read_csv(csv_path, comment="#")
        if "Time (s)" not in data.columns or "Voltage (V)" not in data.columns:
            print("⚠️ Invalid CSV format: expected 'Time (s)' and 'Voltage (V)'")
            return False
    except Exception as e:
        print(f"❌ Failed to load CSV: {e}")
        return False

    plt.figure(figsize=(12, 6))
    plt.plot(data["Time (s)"], data["Voltage (V)"], label=os.path.basename(csv_path))
    plt.axhline(0, color='gray', linestyle='--', linewidth=1)
    plt.title("CSV Waveform Preview")
    plt.xlabel("Time (s)")
    plt.ylabel("Voltage (V)")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()
    return True

def cli_main():
    if len(sys.argv) > 2:
        print("Usage:\n  python3 csv_preview.py           # Preview latest\n  python3 csv_preview.py file.csv  # Preview given file")
        sys.exit(1)

    if len(sys.argv) == 2:
        path = sys.argv[1]
        if not os.path.exists(path):
            print(f"❌ File not found: {path}")
            sys.exit(1)
    else:
        path = get_latest_csv()
        if not path:
            sys.exit(1)

    print(f"📊 Previewing: {path}")
    preview_csv_plot(path)

if __name__ == "__main__":
    cli_main()
