
"""
gui/noise/ar_spectrum.py
AR (Yule-Walker) spectrum with peak picking for line detection.
"""
from __future__ import annotations
import numpy as np
from scipy.linalg import solve_toeplitz
from scipy.signal import medfilt

def run_ar_spectrum(y, Fs, order=32, nfft=4096, stop_event=None):
    x = np.asarray(y, dtype=float)
    x = x - np.mean(x)
    r = np.correlate(x, x, mode="full")
    mid = len(r)//2
    rxx = r[mid:mid+order+1] / len(x)
    if rxx[0] <= 0:
        rxx[0] = 1e-12
    R = solve_toeplitz((rxx[:-1], rxx[:-1]), rxx[1:])
    a = np.r_[1.0, -R]
    e = rxx[0] - np.dot(R, rxx[1:])
    nfft = int(max(1024, nfft))
    w = np.fft.rfftfreq(nfft, d=1.0/Fs)
    jw = np.exp(-2j*np.pi*np.outer(w, np.arange(len(a)))/Fs)
    denom = np.abs(jw.dot(a))**2 + 1e-30
    P = e / denom
    L = 10*np.log10(np.abs(P) + 1e-30)
    base = medfilt(L, kernel_size=31 if len(L)>=31 else 3)
    resid = L - base
    thr = np.quantile(resid, 0.995) if np.isfinite(resid).all() else (np.max(resid) - 1.0)
    mask = resid > thr
    idx = np.flatnonzero(mask)
    detections = []
    if idx.size:
        splits = np.where(np.diff(idx) > 1)[0] + 1
        groups = np.split(idx, splits)
        for g in groups:
            gi = g[np.argmax(resid[g])]
            f0 = w[gi]
            bw = (w[g[-1]] - w[g[0]]) if len(g)>1 else (w[1]-w[0] if len(w)>1 else 0.0)
            detections.append({"type":"ar","f0_Hz":float(f0),"SNR_dB":float(resid[gi]),"BW_Hz":float(bw),"notes":""})
    df = float(w[1]-w[0]) if len(w)>1 else None
    return {"method":"AR Spectrum","plot_x":w,"plot_y":L,"detections":detections,"df_Hz":df,
            "params":{"order":int(order),"nfft":int(nfft)}}
