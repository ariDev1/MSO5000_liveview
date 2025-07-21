#!/usr/bin/env python3

import os
import sys
import glob
import pandas as pd
import matplotlib.pyplot as plt
import argparse
from scipy.interpolate import make_interp_spline
import numpy as np

def is_waveform_csv(path):
    try:
        df = pd.read_csv(path, comment="#", nrows=1)
        return "Time (s)" in df.columns and "Voltage (V)" in df.columns
    except Exception:
        return False

def is_session_log(path):
    try:
        df = pd.read_csv(path, nrows=1)
        return "Timestamp" in df.columns
    except Exception:
        return False

def is_power_log(path):
    try:
        df = pd.read_csv(path, nrows=1)
        return "P (W)" in df.columns and "S (VA)" in df.columns and "Q (VAR)" in df.columns
    except Exception:
        return False

def plot_waveform_csv(path, smooth=False, window=5, spline=False):
    try:
        df = pd.read_csv(path, comment="#")
        if "Time (s)" not in df.columns or "Voltage (V)" not in df.columns:
            print("❌ Invalid waveform CSV structure.")
            return
    except Exception as e:
        print(f"❌ Error reading waveform CSV: {e}")
        return

    plt.figure(figsize=(12, 6))
    plt.plot(df["Time (s)"], df["Voltage (V)"], label=os.path.basename(path), alpha=0.9)

    if smooth or spline:
        y = df["Voltage (V)"].rolling(window=window, center=True).mean() if smooth else df["Voltage (V)"]
        x = df["Time (s)"]

        if spline and y.notna().sum() > 3:
            x_vals = x[y.notna()]
            y_vals = y[y.notna()]
            x_smooth = np.linspace(x_vals.min(), x_vals.max(), 300)
            spline_fit = make_interp_spline(x_vals, y_vals, k=3)
            y_spline = spline_fit(x_smooth)
            plt.plot(x_smooth, y_spline, linestyle="dotted", label="Spline Curve")
        else:
            plt.plot(x, y, linestyle="dotted", label="Smoothed")

    plt.axhline(0, color='gray', linestyle='--', linewidth=1)
    plt.title("Waveform Preview")
    plt.xlabel("Time (s)")
    plt.ylabel("Voltage (V)")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()

def plot_session_log(path, smooth=False, window=5, spline=False):
    try:
        df = pd.read_csv(path, parse_dates=["Timestamp"])
        columns = [col for col in df.columns if col != "Timestamp"]
    except Exception as e:
        print(f"❌ Error reading session log: {e}")
        return

    if not columns:
        print("⚠️ No voltage columns found in session log.")
        return

    if smooth or spline:
        smoothed_df = df.copy()
        for col in columns:
            smoothed_df[col] = (
                df[col].rolling(window=window, center=True).mean() if smooth else df[col]
            )

    timestamp_num = df["Timestamp"].astype("int64") // 10**9

    plt.figure(figsize=(14, 6))
    for col in columns:
        plt.plot(df["Timestamp"], df[col], label=f"{col} (raw)", alpha=0.8)

        if smooth or spline:
            y = smoothed_df[col]
            x = timestamp_num
            mask = ~np.isnan(y)

            if spline and sum(mask) > 3:
                x_smooth = np.linspace(x[mask].min(), x[mask].max(), 300)
                spline_fit = make_interp_spline(x[mask], y[mask], k=3)
                y_smooth = spline_fit(x_smooth)
                time_smooth = pd.to_datetime(x_smooth, unit="s")
                plt.plot(time_smooth, y_smooth, linestyle="dotted", label=f"{col} (spline)")
            else:
                plt.plot(df["Timestamp"], y, linestyle="dotted", label=f"{col} (smooth)")

    plt.title("Session Log")
    plt.xlabel("Time")
    plt.ylabel("Voltage (V)")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()

def plot_power_log(path, smooth=False, window=5, spline=False):
    try:
        df = pd.read_csv(path, parse_dates=["Timestamp"])
        metrics = ["P (W)", "S (VA)", "Q (VAR)", "PF", "Vrms (V)", "Irms (A)"]
        df = df[["Timestamp"] + [m for m in metrics if m in df.columns]]
    except Exception as e:
        print(f"❌ Error reading power log: {e}")
        return

    timestamp_num = df["Timestamp"].astype("int64") // 10**9

    plt.figure(figsize=(14, 7))
    for col in df.columns[1:]:
        raw = df[col]
        label = f"{col} (raw)"
        plt.plot(df["Timestamp"], raw, label=label, alpha=0.85)

        if smooth or spline:
            y = raw.rolling(window=window, center=True).mean() if smooth else raw
            mask = ~np.isnan(y)

            if spline and sum(mask) > 3:
                x_smooth = np.linspace(timestamp_num[mask].min(), timestamp_num[mask].max(), 300)
                spline_fit = make_interp_spline(timestamp_num[mask], y[mask], k=3)
                y_smooth = spline_fit(x_smooth)
                time_smooth = pd.to_datetime(x_smooth, unit="s")
                plt.plot(time_smooth, y_smooth, linestyle="dotted", label=f"{col} (spline)")
            else:
                plt.plot(df["Timestamp"], y, linestyle="dotted", label=f"{col} (smooth)")

    plt.title("Power Analyzer Log")
    plt.xlabel("Time")
    plt.ylabel("Power / Voltage / Current")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()

def main():
    parser = argparse.ArgumentParser(
        description="""Plot waveform or session log CSV files.

Supported formats:
  - Waveform export (CHANx_*.csv) with 'Time (s)', 'Voltage (V)'
  - Session logs (session_log.csv) with 'Timestamp', Vpp/Vavg/Vrms

Examples:
  python3 plot_rigol_csv.py CHAN1.csv
  python3 plot_rigol_csv.py CHAN1.csv --smooth
  python3 plot_rigol_csv.py CHAN1.csv --spline
  python3 plot_rigol_csv.py CHAN1.csv --smooth --spline
  python3 plot_rigol_csv.py session_log.csv --smooth --window 7
""",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("file", help="Path to CSV file")
    parser.add_argument("--smooth", action="store_true", help="Apply rolling average to smooth signal")
    parser.add_argument("--spline", action="store_true", help="Interpolate a dotted spline curve")
    parser.add_argument("--window", type=int, default=5, help="Smoothing window size (default: 5)")
    args = parser.parse_args()

    path = args.file
    if not os.path.isfile(path):
        print(f"❌ File not found: {path}")
        sys.exit(1)

    if is_waveform_csv(path):
        plot_waveform_csv(path, smooth=args.smooth, window=args.window, spline=args.spline)
    elif is_session_log(path):
        plot_session_log(path, smooth=args.smooth, window=args.window, spline=args.spline)
    elif is_power_log(path):
        plot_power_log(path, smooth=args.smooth, window=args.window, spline=args.spline)
    else:
        print("❌ Unknown or unsupported CSV format.")

if __name__ == "__main__":
    main()
