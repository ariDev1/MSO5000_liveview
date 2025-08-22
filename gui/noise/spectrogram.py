
"""
gui/noise/spectrogram.py
Spectrogram with persistence-based line detection.
"""
from __future__ import annotations
import numpy as np
from scipy.signal import stft

def run_spectro(y, Fs, stop_event=None, nfft=4096, hop=2048, pfa=1e-3, smooth_bins=31, topk=8):
    if y is None or len(y) == 0:
        raise ValueError("Empty signal")
    x = np.asarray(y, dtype=float)
    nperseg = int(max(128, min(nfft, len(x))))
    nover = int(max(0, min(nperseg-1, nperseg - hop)))
    f, t, Z = stft(x, fs=Fs, window="hann", nperseg=nperseg, noverlap=nover, nfft=nperseg, detrend=False, return_onesided=True)
    P = np.abs(Z)**2 + 1e-30
    L = 10*np.log10(P)
    # Robust baseline per frequency: median across time
    base = np.median(L, axis=1, keepdims=True)
    resid = L - base
    # CFAR offset per frequency using quantile
    pfa = float(np.clip(pfa, 1e-6, 0.2))
    offs = np.quantile(resid, 1.0 - pfa, axis=1, keepdims=True)
    mask = resid > offs
    # Occupancy per frequency
    occ = mask.mean(axis=1)
    # Pick top-k frequencies by occupancy
    K = int(max(1, min(topk, len(f))))
    idx = np.argsort(occ)[::-1][:K]
    detections = []
    for i in idx:
        if occ[i] <= 0: break
        # Estimate local bandwidth as contiguous mask run around max frame
        bw = f[1]-f[0] if len(f)>1 else 0.0
        detections.append({"type":"line","f0_Hz":float(f[i]),"Occup_%":float(100*occ[i]),"BW_Hz":float(bw),"notes":""})
    # Return image for display
    image = L  # log-PSD image
    extent = [float(t[0]) if len(t) else 0.0, float(t[-1]) if len(t) else 0.0, float(f[0]), float(f[-1] if len(f)>0 else 0.0)]
    return {"method":"Spectrogram","image":image,"extent":extent,"detections":detections, "df_Hz": float(f[1]-f[0]) if len(f)>1 else None}
