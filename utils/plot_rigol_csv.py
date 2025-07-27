#!/usr/bin/env python3

import os
import sys
import glob
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import argparse
from scipy.interpolate import make_interp_spline
import numpy as np
from datetime import datetime

def load_operator_info(path="utils/operator-info.txt"):
    info = {}
    try:
        with open(path, "r") as f:
            for line in f:
                if ":" in line:
                    key, val = line.strip().split(":", 1)
                    info[key.strip()] = val.strip()
    except Exception as e:
        info["Metadata Error"] = f"Could not read {path}: {e}"
    return info

def get_scope_info(path="utils/idn.txt"):
    """
    Try to load the scope info from a saved IDN string.
    Fallback: fake data.
    """
    if os.path.isfile(path):
        try:
            with open(path, "r") as f:
                line = f.read().strip()
                parts = line.split(",")
                if len(parts) >= 4:
                    return {
                        "Model": parts[1],
                        "Serial": parts[2],
                        "FW": parts[3]
                    }
        except:
            pass
    return {"Model": "Unknown", "Serial": "Unknown", "FW": "Unknown"}

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

    #print(f"Time delta between first 2 samples: {df['Time (s)'].iloc[1] - df['Time (s)'].iloc[0]}")
    #print(f"Total duration: {df['Time (s)'].iloc[-1] - df['Time (s)'].iloc[0]}")

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


def plot_power_log(path, smooth=False, window=5, spline=False, scale=1.0):
    try:
        df = pd.read_csv(path, parse_dates=["Timestamp"])
        metrics = [
            "P (W)", "S (VA)", "Q (VAR)", "PF", "Vrms (V)", "Irms (A)",
            "Real Energy (Wh)", "Apparent Energy (VAh)", "Reactive Energy (VARh)"
        ]

        # Compute energy from power over time
        df["Elapsed (s)"] = (df["Timestamp"] - df["Timestamp"].iloc[0]).dt.total_seconds()
        df["Elapsed (h)"] = df["Elapsed (s)"] / 3600.0

        df["Real Energy (Wh)"] = df["P (W)"] * df["Elapsed (h)"]
        df["Apparent Energy (VAh)"] = df["S (VA)"] * df["Elapsed (h)"]
        df["Reactive Energy (VARh)"] = df["Q (VAR)"] * df["Elapsed (h)"]

        df = df[["Timestamp"] + [m for m in metrics if m in df.columns]]
    except Exception as e:
        print(f"❌ Error reading power log: {e}")
        return

    # Copy and scale data (except PF)
    scaled_df = df.copy()
    for col in scaled_df.columns:
        if col == "PF" or col == "Timestamp":
            continue
        if scaled_df[col].dtype.kind in "fi":  # numeric
            scaled_df[col] *= scale

    timestamp_num = scaled_df["Timestamp"].astype("int64") // 10**9

    plt.figure(figsize=(14, 7))
    for col in scaled_df.columns[1:]:
        if col in ["Real Energy (Wh)", "Apparent Energy (VAh)", "Reactive Energy (VARh)"]:
            continue  # we do NOT plot these as curves
        raw = scaled_df[col]
        label = f"{col} (raw × {scale})" if scale != 1.0 else f"{col} (raw)"
        plt.plot(scaled_df["Timestamp"], raw, label=label, alpha=0.85)

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
                plt.plot(scaled_df["Timestamp"], y, linestyle="dotted", label=f"{col} (smooth)")

    plt.title(f"Power Analyzer Log (scale ×{scale})")
    plt.xlabel("Time")
    plt.ylabel("Power / Voltage / Current")
    plt.grid(True)

    # --- Energy totals (legend injection)
    last = scaled_df.iloc[-1]
    energy_labels = [
        f"Real Energy: {last['Real Energy (Wh)']:.2f} Wh",
        f"Apparent Energy: {last['Apparent Energy (VAh)']:.2f} VAh",
        f"Reactive Energy: {last['Reactive Energy (VARh)']:.2f} VARh"
    ]
    energy_handles = [Line2D([0], [0], color='none') for _ in energy_labels]

    handles, labels = plt.gca().get_legend_handles_labels()
    handles += energy_handles
    labels += energy_labels
    plt.legend(handles, labels, loc="upper left", framealpha=1.0)

    # --- Footer metadata
    metadata = load_operator_info()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata["Timestamp"] = timestamp
    footer_line_1 = " | ".join([f"{k}: {v}" for k, v in metadata.items()])

    scope = get_scope_info()
    footer_line_2 = f"{scope['Model']} | SN: {scope['Serial']} | FW: {scope['FW']} | Timestamp: {timestamp}"

    fig = plt.gcf()
    fig.text(0.01, 0.018, footer_line_1, ha="left", va="bottom", fontsize=7, color="#444444")
    fig.text(0.01, 0.005, footer_line_2, ha="left", va="bottom", fontsize=7, color="#555555")

    plt.tight_layout()

    # --- Save PNG with same name as CSV ---
    png_path = os.path.splitext(path)[0] + ".png"
    plt.savefig(png_path, bbox_inches="tight", dpi=150)
    print(f"✅ Saved plot to: {png_path}")

    plt.show()

def main():
    parser = argparse.ArgumentParser(
        description="""Plot waveform, session log, or power analysis CSV files.

    Run from project root like:
      python3 utils/plot_rigol_csv.py <your_csv_file>

    Supported formats:
      - Waveform export (CHANx_*.csv) with 'Time (s)', 'Voltage (V)'
      - Session logs (session_log.csv) with 'Timestamp', Vpp/Vavg/Vrms
      - Power Analyzer logs (power_log_*.csv) with P, Q, S, PF, Vrms, Irms, Energy

    Examples:
      python3 utils/plot_rigol_csv.py CHAN1.csv
      python3 utils/plot_rigol_csv.py session_log.csv --smooth
      python3 utils/plot_rigol_csv.py oszi_csv/power_log_20250721_152301.csv --spline
      python3 utils/plot_rigol_csv.py oszi_csv/power_log.csv --smooth --scale 100
    """,

        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("file", help="Path to CSV file")
    parser.add_argument("--smooth", action="store_true", help="Apply rolling average to smooth signal")
    parser.add_argument("--spline", action="store_true", help="Interpolate a dotted spline curve")
    parser.add_argument("--window", type=int, default=5, help="Smoothing window size (default: 5)")
    parser.add_argument("--scale", type=float, default=1.0, help="Multiply all numeric values by this factor (default: 1.0). Use e.g. 100 for 10mΩ shunt.")
    args = parser.parse_args()

    path = args.file
    if not os.path.isfile(path):
        print(f"❌ File not found: {path}")
        sys.exit(1)

    if is_waveform_csv(path):
        plot_waveform_csv(path, smooth=args.smooth, window=args.window, spline=args.spline)

    elif is_power_log(path):
        plot_power_log(path, smooth=args.smooth, window=args.window, spline=args.spline, scale=args.scale)

    elif is_session_log(path):
        plot_session_log(path, smooth=args.smooth, window=args.window, spline=args.spline)
    
    else:
        print("❌ Unknown or unsupported CSV format.")

if __name__ == "__main__":
    main()
