
"""
gui/noise/matched.py
Matched filter / normalized correlation against a template from file.
Template file: CSV with one column (y) or two columns (t,y).
"""
from __future__ import annotations
import numpy as np
import os

def _load_template(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    try:
        import pandas as pd
        df = pd.read_csv(path)
        if "y" in df.columns:
            y = df["y"].to_numpy(dtype=float)
        else:
            y = df.iloc[:, -1].to_numpy(dtype=float)
        return y
    except Exception:
        arr = np.loadtxt(path, delimiter=",")
        if arr.ndim == 1: return arr.astype(float)
        return arr[:, -1].astype(float)

def run_matched_filter(y, Fs, template_path: str, stop_event=None):
    if not template_path or not isinstance(template_path, str):
        raise RuntimeError("Template Path is empty. Set it in the CSV/Template field.")
    h = _load_template(template_path)
    x = np.asarray(y, dtype=float)
    h = h - np.mean(h); x0 = x - np.mean(x)
    nh = np.linalg.norm(h) + 1e-12
    nx = np.linalg.norm(x0) + 1e-12
    h = h / nh
    x0 = x0 / nx
    r = np.correlate(x0, h, mode="valid")
    k = int(np.argmax(r))
    rmax = float(r[k])
    t = np.arange(len(r)) / float(Fs)
    detections = [{"type":"corr","f0_Hz":0.0,"SNR_dB":rmax,"BW_Hz":0.0,"notes":f"peak idx {k}"}]
    return {"method":"Matched Filter","plot_x":t,"plot_y":r,"detections":detections,"df_Hz":None}
