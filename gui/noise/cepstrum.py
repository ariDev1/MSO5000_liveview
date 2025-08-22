
"""
gui/noise/cepstrum.py
Power cepstrum to detect comb spacing / fundamental periodicity.
"""
from __future__ import annotations
import numpy as np

def run_cepstrum(y, Fs, stop_event=None, nfft=4096, qmin_ms=0.02, qmax_ms=5.0, topk=3):
    x = np.asarray(y, dtype=float)
    N = len(x)
    nfft = int(max(1024, min(int(nfft), 1<<18)))
    win = np.hanning(min(N, nfft))
    xw = x[-len(win):] * win
    X = np.fft.rfft(xw, n=nfft)
    mag = np.abs(X) + 1e-30
    log_mag = np.log(mag)
    cep = np.fft.irfft(log_mag)
    q = np.arange(len(cep)) / float(Fs)  # seconds
    qmin = max(1.0/Fs, float(qmin_ms)*1e-3)
    qmax = min(q[-1], float(qmax_ms)*1e-3)
    mask = (q >= qmin) & (q <= qmax)
    if not np.any(mask):
        return {"method":"Cepstrum","plot_x":1.0/(q+1e-30),"plot_y":cep, "detections":[], "df_Hz": None}
    qi = np.where(mask)[0]
    seg = cep[qi]
    idx = np.argsort(seg)[-int(max(1, min(int(topk), seg.size))):][::-1]
    detections = []
    for i in idx:
        q0 = q[qi[i]]
        f0 = 1.0 / q0 if q0 > 0 else 0.0
        detections.append({"type":"comb","f0_Hz":float(f0),"SNR_dB":float(seg[i]),"BW_Hz":0.0,"notes":"fundamental spacing"})
    fq = 1.0/(q[mask] + 1e-30)
    yq = seg
    df = float(fq[1]-fq[0]) if len(fq)>1 else None
    return {"method":"Cepstrum","plot_x":fq,"plot_y":yq,"detections":detections,"df_Hz":df}
