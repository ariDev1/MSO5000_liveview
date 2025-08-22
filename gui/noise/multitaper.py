
"""
gui/noise/multitaper.py
Multitaper PSD (DPSS) with CFAR detection, safer for faint/close tones.
"""
from __future__ import annotations
import numpy as np
from scipy.signal.windows import dpss
from scipy.signal import medfilt

def _robust_baseline_log(L_dB: np.ndarray, smooth_bins: int = 31) -> np.ndarray:
    k = max(3, int(smooth_bins) | 1)
    return medfilt(L_dB, kernel_size=k)

def _parabolic_peak_refine(f: np.ndarray, y: np.ndarray, i: int):
    if i <= 0 or i >= len(y) - 1:
        return float(f[i]), float(y[i])
    y1, y2, y3 = y[i-1], y[i], y[i+1]
    denom = (y1 - 2*y2 + y3)
    if abs(denom) < 1e-18:
        return float(f[i]), float(y[i])
    delta = 0.5 * (y1 - y3) / denom
    delta = float(np.clip(delta, -1.0, 1.0))
    f0 = f[i] + delta * (f[1] - f[0])
    y0 = y2 - 0.25 * (y1 - y3) * delta
    return float(f0), float(y0)

def run_multitaper(y, Fs, stop_event=None, K=6, nfft=4096, seglen=4096, overlap=0.5, pfa=1e-3, smooth_bins=31):
    x = np.asarray(y, dtype=float) - float(np.mean(y))
    N = len(x)
    nperseg = min(int(seglen), N)
    nover = int(max(0, min(nperseg-1, int(overlap*nperseg))))
    if nperseg <= 0: raise ValueError("seglen too small")
    # Build K DPSS tapers with NW=K/2 (heuristic)
    NW = max(2.5, K/2.0)
    tapers = dpss(nperseg, NW=NW, Kmax=int(K), sym=False)
    step = nperseg - nover
    # Segment the signal and average tapered periodograms
    nfft = max(int(nfft), nperseg)
    Pxx = None
    count = 0
    for start in range(0, N - nperseg + 1, step):
        if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
            break
        seg = x[start:start+nperseg]
        Sk = 0.0
        for k in range(tapers.shape[0]):
            s = seg * tapers[k]
            X = np.fft.rfft(s, n=nfft)
            Sk += (np.abs(X)**2)
        Sk /= float(tapers.shape[0])
        if Pxx is None:
            Pxx = Sk
        else:
            Pxx += Sk
        count += 1
    if count == 0:
        # Single-segment fallback
        seg = x[-nperseg:]
        Sk = 0.0
        for k in range(tapers.shape[0]):
            s = seg * tapers[k]
            X = np.fft.rfft(s, n=nfft)
            Sk += (np.abs(X)**2)
        P = Sk / float(tapers.shape[0])
        f = np.fft.rfftfreq(nfft, d=1.0/Fs)
    else:
        P = Pxx / float(count)
        f = np.fft.rfftfreq(nfft, d=1.0/Fs)

    # Approximate density scaling
    P = P / (Fs)

    L_dB = 10*np.log10(P + 1e-30)
    base_dB = _robust_baseline_log(L_dB, smooth_bins=smooth_bins)
    resid = L_dB - base_dB
    pfa = float(np.clip(pfa, 1e-6, 0.2))
    try:
        offset = float(np.quantile(resid, 1.0 - pfa))
    except Exception:
        offset = 6.0
    thr_dB = base_dB + offset
    mask = (L_dB > thr_dB)
    idx = np.flatnonzero(mask)
    detections = []
    if idx.size:
        splits = np.where(np.diff(idx) > 1)[0] + 1
        groups = np.split(idx, splits)
        for g in groups:
            gi = g[np.argmax(resid[g])]
            f0, y0 = _parabolic_peak_refine(f, L_dB, gi)
            snr = float(y0 - base_dB[gi])
            bw = float(f[g[-1]] - f[g[0]]) if len(g) > 1 else (float(f[1]-f[0]) if len(f)>1 else 0.0)
            detections.append({"type":"line","f0_Hz":float(f0),"SNR_dB":snr,"BW_Hz":max(bw,0.0),"notes":""})
    df = float(f[1]-f[0]) if len(f)>1 else None
    return {"method":"Multitaper","plot_x":f,"plot_y":L_dB,"detections":detections,"df_Hz":df,
            "params":{"K":int(K),"nfft":int(nfft),"seglen":int(nperseg),"overlap":float(overlap),"pfa":float(pfa),"smooth_bins":int(smooth_bins)}}
