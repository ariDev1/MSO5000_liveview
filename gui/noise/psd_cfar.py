
"""
gui/noise/psd_cfar.py
---------------------
PSD + CFAR line detection for the "Noise Inspector" tab.

Method summary:
  1) Welch PSD (Hann, overlap) to reduce variance.
  2) Robust baseline in log domain via median filtering.
  3) Data-driven CFAR threshold using residual quantile for desired Pfa.
  4) Peak picking and parabolic refinement for f0.

Returns a dict compatible with the Noise Inspector view:
  {
    "method": "PSD+CFAR",
    "plot_x": f_Hz,
    "plot_y": L_dB,
    "detections": [ {type,f0_Hz,SNR_dB,BW_Hz,notes}, ... ],
    "df_Hz": resolution_Hz,
    "params": {...}
  }
"""

from __future__ import annotations

import numpy as np
from scipy.signal import welch, medfilt


def _robust_baseline_log(L_dB: np.ndarray, smooth_bins: int = 31) -> np.ndarray:
    """Median-filtered baseline in the log-PSD domain (odd kernel size)."""
    k = max(3, int(smooth_bins) | 1)  # ensure odd and >=3
    return medfilt(L_dB, kernel_size=k)


def _parabolic_peak_refine(f: np.ndarray, y: np.ndarray, i: int):
    """Parabolic interpolation around bin i; returns (f0, y0)."""
    if i <= 0 or i >= len(y) - 1:
        return float(f[i]), float(y[i])
    y1, y2, y3 = y[i-1], y[i], y[i+1]
    denom = (y1 - 2*y2 + y3)
    if abs(denom) < 1e-18:
        return float(f[i]), float(y[i])
    delta = 0.5 * (y1 - y3) / denom  # in bins
    delta = float(np.clip(delta, -1.0, 1.0))
    f0 = f[i] + delta * (f[1] - f[0])
    y0 = y2 - 0.25 * (y1 - y3) * delta
    return float(f0), float(y0)


def run_psd_cfar(
    y: np.ndarray,
    Fs: float,
    stop_event=None,
    nfft: int = 4096,
    seglen: int = 4096,
    overlap: float = 0.5,
    pfa: float = 1e-3,
    smooth_bins: int = 31,
) -> dict:
    """Compute PSD and detect narrowband lines using a CFAR-like rule."""
    if y is None or len(y) == 0:
        raise ValueError("Empty signal")

    x = np.asarray(y, dtype=np.float64)
    x = x - float(np.mean(x))

    # Welch PSD
    nperseg = int(max(128, min(int(seglen), len(x))))
    noverlap = int(max(0, min(nperseg - 1, int(overlap * nperseg))))
    nfft = int(max(nperseg, int(nfft)))

    f, Pxx = welch(
        x, fs=Fs, window="hann",
        nperseg=nperseg, noverlap=noverlap, nfft=nfft,
        detrend=False, return_onesided=True, scaling="density"
    )

    L_dB = 10.0 * np.log10(Pxx + 1e-30)
    df = float(f[1] - f[0]) if len(f) > 1 else None

    if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
        return {
            "method": "PSD+CFAR",
            "plot_x": f,
            "plot_y": L_dB,
            "detections": [],
            "df_Hz": df,
            "params": {
                "Fs": float(Fs),
                "nfft": int(nfft),
                "seglen": int(nperseg),
                "overlap": float(overlap),
                "pfa": float(pfa),
                "smooth_bins": int(smooth_bins),
            },
        }

    # Robust baseline and residuals
    base_dB = _robust_baseline_log(L_dB, smooth_bins=smooth_bins)
    resid = L_dB - base_dB

    # Data-driven CFAR offset
    pfa = float(np.clip(pfa, 1e-6, 0.2))
    try:
        offset = float(np.quantile(resid, 1.0 - pfa))
    except Exception:
        offset = 6.0  # dB fallback
    thr_dB = base_dB + offset

    # Detections
    mask = (L_dB > thr_dB)
    idx = np.flatnonzero(mask)
    detections = []
    if idx.size:
        splits = np.where(np.diff(idx) > 1)[0] + 1
        groups = np.split(idx, splits)
        for g in groups:
            if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
                break
            gi = g[np.argmax(resid[g])]
            f0, y0 = _parabolic_peak_refine(f, L_dB, gi)
            snr = float(y0 - base_dB[gi])
            bw = float(f[g[-1]] - f[g[0]]) if len(g) > 1 else (float(f[1] - f[0]) if len(f) > 1 else 0.0)
            detections.append({
                "type": "line",
                "f0_Hz": float(f0),
                "SNR_dB": snr,
                "BW_Hz": max(bw, 0.0),
                "notes": "",
            })

    return {
        "method": "PSD+CFAR",
        "plot_x": f,
        "plot_y": L_dB,
        "detections": detections,
        "df_Hz": df,
        "params": {
            "Fs": float(Fs),
            "nfft": int(nfft),
            "seglen": int(nperseg),
            "overlap": float(overlap),
            "pfa": float(pfa),
            "smooth_bins": int(smooth_bins),
        },
    }
