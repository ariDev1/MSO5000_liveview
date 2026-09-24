"""Qt-independent adapters around the project's existing numerical methods."""

import csv
import os
from datetime import datetime

import numpy as np

from gui.harmonic.harmonics import analyze_harmonics
from qt_app.backend import channel_name
from scpi.waveform import _fetch_wave


def acquire(scope, channel, raw=False):
    t, y, dt = _fetch_wave(scope, channel_name(channel), bool(raw))
    if t is None or y is None or dt is None or len(y) < 8 or dt <= 0:
        raise RuntimeError("Scope returned no usable waveform")
    return t, y, 1.0 / dt


def harmonics(scope, channel, raw=False, count=25, window="hann", include_dc=False):
    _, y, fs = acquire(scope, channel, raw)
    result = analyze_harmonics(y, fs, n_harmonics=count, window=window, include_dc=include_dc)
    n = len(y)
    w = np.hanning(n) if window == "hann" else np.ones(n)
    if window == "flattop":
        from scipy.signal.windows import flattop
        w = flattop(n)
    amplitude = (np.abs(np.fft.rfft((y - (0 if include_dc else np.mean(y))) * w))
                 * np.sqrt(2) / (n * np.mean(w)))
    frequencies = np.fft.rfftfreq(n, d=1 / fs)
    return result, frequencies, amplitude


def bh_curve(scope, voltage, current, turns, area_mm2, length_mm, probe_type,
             probe_value, raw=False, remove_dc=True, cycle=True, cycle_ref="I",
             avg_cycles=1, deskew_us=0.0, detrend=False):
    if turns <= 0 or area_mm2 <= 0 or length_mm <= 0 or probe_value <= 0:
        raise ValueError("Turns, area, length and probe value must be positive")
    ti, yi, fsi = acquire(scope, current, raw)
    tv, v, fsv = acquire(scope, voltage, raw)
    t0, t1 = max(ti[0], tv[0]), min(ti[-1], tv[-1])
    if t1 <= t0:
        raise ValueError("Voltage and current waveforms have no common time range")
    n = min(len(yi), len(v))
    t = np.linspace(t0, t1, n)
    dt = (t1 - t0) / (n - 1)
    i = np.interp(t - deskew_us * 1e-6, ti, yi)
    v = np.interp(t, tv, v)
    i = i / probe_value if probe_type == "shunt" else i * probe_value
    if remove_dc:
        i -= np.mean(i)
        v -= np.mean(v)
    if detrend:
        from scipy.signal import detrend as remove_trend
        i, v = remove_trend(i), remove_trend(v)
    if cycle:
        # Same-slope crossings from the reference waveform, as in the Tk tab.
        reference = v if cycle_ref == "V" else i
        crossing = np.flatnonzero((reference[:-1] < 0) & (reference[1:] >= 0))
        windows = list(zip(crossing[:-1], crossing[1:]))[-avg_cycles:]
        if windows:
            points = max(64, int(np.median([b - a for a, b in windows])))
            grid = np.linspace(0, 1, points)
            i = np.mean([np.interp(grid, np.linspace(0, 1, b - a), i[a:b])
                         for a, b in windows], axis=0)
            v = np.mean([np.interp(grid, np.linspace(0, 1, b - a), v[a:b])
                         for a, b in windows], axis=0)
            dt *= np.mean([b - a for a, b in windows]) / points
    h = turns * i / (length_mm * 1e-3)
    flux = np.r_[0.0, np.cumsum((v[1:] + v[:-1]) * 0.5) * dt]
    b = flux / (turns * area_mm2 * 1e-6)
    return h, b, dt


def noise(y, fs, method, params, other=None, template_path=""):
    nfft = params.get("nfft", 4096)
    seglen = params.get("seglen", 4096)
    overlap = params.get("overlap", 0.5)
    if method == "PSD+CFAR":
        from gui.noise.psd_cfar import run_psd_cfar
        return run_psd_cfar(y, fs, nfft=nfft, seglen=seglen, overlap=overlap,
                            pfa=params.get("pfa", 1e-3))
    if method == "Spectrogram":
        from gui.noise.spectrogram import run_spectro
        return run_spectro(y, fs, nfft=nfft, hop=params.get("hop", 2048),
                           pfa=params.get("pfa", 1e-3), topk=params.get("topk", 8))
    if method == "MSC":
        if other is None:
            raise ValueError("Select a second channel for coherence")
        from gui.noise.coherence import run_msc
        return run_msc(y, other, fs, nfft=nfft, seglen=seglen, overlap=overlap)
    if method == "Multitaper":
        from gui.noise.multitaper import run_multitaper
        return run_multitaper(y, fs, nfft=nfft, seglen=seglen, overlap=overlap)
    if method == "Spectral Kurtosis":
        from gui.noise.kurtosis import run_spectral_kurtosis
        return run_spectral_kurtosis(y, fs, nfft=nfft, hop=params.get("hop", 2048))
    if method == "Cepstrum":
        from gui.noise.cepstrum import run_cepstrum
        return run_cepstrum(y, fs, nfft=nfft)
    if method == "Matched Filter":
        from gui.noise.matched import run_matched_filter
        return run_matched_filter(y, fs, template_path=template_path)
    if method == "AR Spectrum":
        from gui.noise.ar_spectrum import run_ar_spectrum
        return run_ar_spectrum(y, fs, nfft=nfft)
    if method == "Cyclostationary":
        from gui.noise.cyclo import run_cyclo
        return run_cyclo(y, fs, nfft=nfft, hop=params.get("hop", 2048))
    if method == "Bicoherence":
        from gui.noise.cyclo_bispec import BicoherenceAccumulator
        nfft = min(nfft, 512)
        acc = BicoherenceAccumulator(nfft=nfft, noverlap=int(overlap * nfft))
        acc.update(y, fs)
        f, _, image = acc.results()
        return {"method": method, "image": image, "extent": (f[0], f[-1], f[0], f[-1]),
                "detections": [], "df_Hz": float(fs / nfft)}
    raise ValueError(f"Unknown noise method: {method}")


def read_wave_csv(path):
    import pandas as pd
    data = pd.read_csv(path, comment="#")
    if "t" in data and "y" in data:
        x, y = data["t"].to_numpy(float), data["y"].to_numpy(float)
    elif "Time (s)" in data and "Voltage (V)" in data:
        x = data["Time (s)"].to_numpy(float)
        y = data["Voltage (V)"].to_numpy(float)
    else:
        raise ValueError("Expected 't,y' or 'Time (s),Voltage (V)' waveform CSV")
    if len(x) < 8 or np.any(np.diff(x) <= 0):
        raise ValueError("Waveform CSV needs at least 8 increasing time samples")
    return y, 1 / float(np.median(np.diff(x)))


def save_xy_csv(folder, prefix, x, y, x_name, y_name):
    os.makedirs(folder, exist_ok=True)
    filename = os.path.join(folder, f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.csv")
    with open(filename, "w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow((x_name, y_name))
        writer.writerows(zip(x, y))
    return filename
