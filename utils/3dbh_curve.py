#!/usr/bin/env python3
import numpy as np
import matplotlib.pyplot as plt
import sys
import os
from collections import Counter

def load_bh_csv(path, cycle=None):
    """
    Load H, B from a log file with: run_index, time_iso, H, B
    Optionally only for a specific run_index (cycle).
    """
    runidx = []
    H = []
    B = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            try:
                idx = int(parts[0])
                h = float(parts[2])
                b = float(parts[3])
            except Exception:
                continue
            if (cycle is None) or (idx == cycle):
                runidx.append(idx)
                H.append(h)
                B.append(b)
    return np.array(H), np.array(B), np.array(runidx)

def robust_clip(H, B, factor=5):
    """
    Remove points where H or B are >factor*median absolute value (outlier filter)
    """
    abs_H = np.abs(H)
    abs_B = np.abs(B)
    h_med = np.median(abs_H)
    b_med = np.median(abs_B)
    mask = (abs_H < factor*h_med) & (abs_B < factor*b_med)
    return H[mask], B[mask]

def plot_bh_2d(H, B, ax=None, label="BH-curve"):
    if ax is None:
        fig, ax = plt.subplots()
    ax.plot(H, B, color='magenta', lw=1.5, label=label)
    ax.set_xlabel("H (A/m)")
    ax.set_ylabel("B (T)")
    ax.grid(True, alpha=0.3)
    ax.set_title("Classic 2D BH-Curve")
    ax.legend()
    return ax

def plot_bh_3d_vortex(H, B, ax=None, color="magenta"):
    centerH = np.mean(H)
    centerB = np.mean(B)
    theta = np.unwrap(np.arctan2(B - centerB, H - centerH))
    if ax is None:
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')
    ax.plot(H, B, theta, color=color, linewidth=2)
    ax.set_xlabel('H (A/m)')
    ax.set_ylabel('B (T)')
    ax.set_zlabel('Vortex phase (θ)')
    ax.set_title('3D Vortex BH-Curve')
    try:
        ax.set_box_aspect([np.ptp(H), np.ptp(B), np.ptp(theta)])
    except Exception:
        pass
    return ax

def main():
    cycle = None  # default: use most common cycle in file

    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        csv_path = sys.argv[1]
        print(f"Loading BH-curve data from: {csv_path}")
        H_full, B_full, runidx = load_bh_csv(csv_path)
        # Use the most common run_index by default, to avoid mixing cycles
        if len(runidx) and (np.ptp(runidx) > 0):
            cycle_counter = Counter(runidx)
            most_common_cycle, _ = cycle_counter.most_common(1)[0]
            cycle = most_common_cycle
            print(f"Multiple cycles found, auto-selecting run_index = {cycle}")
            H, B, _ = load_bh_csv(csv_path, cycle=cycle)
        else:
            H, B = H_full, B_full
        print(f"Loaded {len(H)} points.")
    else:
        print("No CSV provided, using synthetic demo data.")
        t = np.linspace(0, 2 * np.pi, 600)
        H = 1.0 * np.sin(t)
        B = 0.9 * np.sin(t + 0.7) + 0.1 * np.sin(5 * t)

    if len(H) < 2:
        print("Not enough data for plotting.")
        return

    # Print data stats
    print(f"H: min={np.min(H):.2g}, max={np.max(H):.2g}, median={np.median(H):.2g}")
    print(f"B: min={np.min(B):.2g}, max={np.max(B):.2g}, median={np.median(B):.2g}")

    # Outlier clipping
    H_clip, B_clip = robust_clip(H, B, factor=5)
    print(f"After outlier removal: {len(H_clip)} points remain ({100.0 * len(H_clip)/len(H):.1f}% of original)")

    # Final plot (use clipped values if possible)
    if len(H_clip) > 10:
        H_plot, B_plot = H_clip, B_clip
    else:
        H_plot, B_plot = H, B

    fig = plt.figure(figsize=(12,5))
    ax1 = fig.add_subplot(1,2,1)
    plot_bh_2d(H_plot, B_plot, ax=ax1)

    ax2 = fig.add_subplot(1,2,2, projection='3d')
    plot_bh_3d_vortex(H_plot, B_plot, ax=ax2)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()
