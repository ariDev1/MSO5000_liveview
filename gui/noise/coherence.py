
"""
gui/noise/coherence.py
Two-channel magnitude-squared coherence (MSC) with thresholding.
"""
from __future__ import annotations
import numpy as np
from scipy.signal import coherence, get_window

def run_msc(yA, yB, Fs, stop_event=None, nfft=4096, seglen=4096, overlap=0.5, thr=0.5):
    x = np.asarray(yA, dtype=float); z = np.asarray(yB, dtype=float)
    nperseg = int(max(128, min(seglen, len(x), len(z))))
    nover = int(max(0, min(nperseg-1, int(overlap*nperseg))))
    nfft = max(nperseg, int(nfft))
    f, C = coherence(x, z, fs=Fs, window="hann", nperseg=nperseg, noverlap=nover, nfft=nfft)
    # Detections: peaks above threshold
    detections = []
    mask = C >= float(thr)
    idx = np.flatnonzero(mask)
    if idx.size:
        splits = np.where(np.diff(idx) > 1)[0] + 1
        groups = np.split(idx, splits)
        for g in groups:
            gi = g[np.argmax(C[g])]
            f0 = f[gi]
            bw = (f[g[-1]] - f[g[0]]) if len(g)>1 else (f[1]-f[0] if len(f)>1 else 0.0)
            detections.append({"type":"coh","f0_Hz":float(f0),"MSC":float(C[gi]),"BW_Hz":float(bw),"notes":""})
    return {"method":"MSC","plot_x":f,"plot_y":C,"detections":detections, "df_Hz": float(f[1]-f[0]) if len(f)>1 else None}
