
"""
gui/noise/kurtosis.py
Spectral Kurtosis detector: highlights impulsive/bursty bands.
"""
from __future__ import annotations
import numpy as np
from scipy.signal import stft

def run_spectral_kurtosis(y, Fs, stop_event=None, nfft=4096, hop=2048, sk_thr=2.5):
    x = np.asarray(y, dtype=float)
    nperseg = int(max(128, min(nfft, len(x))))
    nover = int(max(0, nperseg - hop))
    f, t, Z = stft(x, fs=Fs, window="hann", nperseg=nperseg, noverlap=nover, nfft=nperseg, detrend=False, return_onesided=True)
    A = np.abs(Z) + 1e-30
    X = np.log(A)
    mu = np.mean(X, axis=1, keepdims=True)
    std = np.std(X, axis=1, keepdims=True) + 1e-12
    Zs = (X - mu) / std
    SK = np.mean(Zs**4, axis=1) - 3.0  # excess kurtosis per frequency
    detections = []
    mask = SK >= float(sk_thr)
    idx = np.flatnonzero(mask)
    if idx.size:
        splits = np.where(np.diff(idx) > 1)[0] + 1
        groups = np.split(idx, splits)
        for g in groups:
            gi = g[np.argmax(SK[g])]
            f0 = f[gi]
            bw = (f[g[-1]] - f[g[0]]) if len(g)>1 else (f[1]-f[0] if len(f)>1 else 0.0)
            detections.append({"type":"sk","f0_Hz":float(f0),"SK":float(SK[gi]),"BW_Hz":float(bw),"notes":""})
    image = (X - np.min(X)) / (np.max(X) - np.min(X) + 1e-12)
    extent = [float(t[0]) if len(t) else 0.0, float(t[-1]) if len(t) else 0.0, float(f[0]), float(f[-1] if len(f)>0 else 0.0)]
    return {"method":"Spectral Kurtosis","image":image,"extent":extent,"detections":detections,
            "df_Hz": float(f[1]-f[0]) if len(f)>1 else None}
