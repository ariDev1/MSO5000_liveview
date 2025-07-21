#!/usr/bin/env python3

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

def load_csv_waveform(path):
    df = pd.read_csv(path, comment="#")
    return df["Time (s)"].values, df["Voltage (V)"].values

def compute_power_metrics(t, v, i, remove_dc=True):
    if remove_dc:
        v = v - np.mean(v)
        i = i - np.mean(i)

    p_inst = v * i
    dt = t[1] - t[0]  # assume uniform
    P = np.mean(p_inst)
    Vrms = np.sqrt(np.mean(v**2))
    Irms = np.sqrt(np.mean(i**2))
    S = Vrms * Irms
    Q = np.sqrt(max(S**2 - P**2, 0))
    PF = P / S if S != 0 else 0

    return {
        "Real Power (P)": P,
        "Apparent Power (S)": S,
        "Reactive Power (Q)": Q,
        "Power Factor": PF,
        "Vrms": Vrms,
        "Irms": Irms,
        "Instantaneous Power": p_inst
    }

def main():
    v_path = "oszi_csv/CHAN1_2025-07-19T20-40-12.csv"
    i_path = "oszi_csv/CHAN2_2025-07-19T20-40-13.csv"
    
    t1, v = load_csv_waveform(v_path)
    t2, i = load_csv_waveform(i_path)

    # Interpolation if necessary
    if not np.array_equal(t1, t2):
        i = np.interp(t1, t2, i)
        t = t1
    else:
        t = t1

    result = compute_power_metrics(t, v, i)
    for key, val in result.items():
        if isinstance(val, np.ndarray): continue
        print(f"{key:<22}: {val:.6f}")

    # Optional: plot instantaneous power
    plt.figure(figsize=(12, 6))
    plt.plot(t, v, label="Voltage", alpha=0.8)
    plt.plot(t, i, label="Current", alpha=0.8)
    plt.plot(t, result["Instantaneous Power"], label="Power (v*i)", alpha=0.8)
    plt.title("Waveform + Instantaneous Power")
    plt.xlabel("Time (s)")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()
