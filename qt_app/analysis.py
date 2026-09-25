"""Qt-independent adapters around the project's existing numerical methods."""

import csv
import os
from datetime import datetime

import numpy as np

from gui.harmonic.harmonics import analyze_harmonics
from gui.magnetic.magnetics import compute_magnetics_full
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
        def windows_for(reference):
            crossing = np.flatnonzero((reference[:-1] < 0) & (reference[1:] >= 0))
            return list(zip(crossing[:-1], crossing[1:]))[-avg_cycles:]

        candidates = {"V": (v,), "I": (i,), "Auto": (i, v)}.get(cycle_ref, (i,))
        windows = []
        for reference in candidates:
            windows = windows_for(reference)
            if windows and not (len(windows) == 1
                                and windows[0][1] - windows[0][0] >= len(reference) - 1):
                break
        else:
            windows = []
        if not windows and cycle_ref == "Auto":
            # FFT single-cycle fallback on the stronger wave, as in the Tk tab.
            src = i if np.std(i) >= np.std(v) else v
            spectrum = np.abs(np.fft.rfft((src - np.mean(src)) * np.hanning(len(src))))
            f0 = (1 + int(np.argmax(spectrum[1:]))) / (len(src) * dt) if len(spectrum) > 1 else 0
            period = int(max(4, round(1.0 / f0 / dt))) if f0 > 0 else 0
            if 0 < period < len(src):
                mid = len(src) // 2
                start = max(0, mid - period // 2)
                windows = [(start, min(len(src), start + period))]
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


def magnetics(scope, voltage, current, n_turns, ae_m2, le_m, raw=False,
              deskew_us=0.0, i2_chan=None, n2=0, i3_chan=None, n3=0,
              r_winding=None):
    """Ferrite magnetics via the shared fetch path.

    Open-secondary mode when i2_chan/i3_chan are None (I_primary is the
    magnetising current). Loaded mode fetches the extra winding channels
    and refers them by N2/N1, N3/N1. Returns the full result dict of
    compute_magnetics_full (time arrays plus scalar readouts and the
    "decomp" cross-checks). Raises ValueError/RuntimeError on bad geometry
    or empty captures, mirroring bh_curve() conventions.
    """
    if n_turns <= 0 or ae_m2 <= 0 or le_m <= 0:
        raise ValueError("Turns, area and path length must be positive")
    ti, yi, _ = acquire(scope, current, raw)
    tv, v, _ = acquire(scope, voltage, raw)
    waves = [(ti, yi), (tv, v)]
    i2 = i3 = None
    if i2_chan:
        t2, y2, _ = acquire(scope, i2_chan, raw)
        waves.append((t2, y2))
    if i3_chan:
        t3, y3, _ = acquire(scope, i3_chan, raw)
        waves.append((t3, y3))
    t0 = max(w[0][0] for w in waves)
    t1 = min(w[0][-1] for w in waves)
    if t1 <= t0:
        raise ValueError("Waveforms have no common time range")
    n = min(len(w[1]) for w in waves)
    t = np.linspace(t0, t1, n)
    dt = (t1 - t0) / (n - 1)
    i = np.interp(t - deskew_us * 1e-6, ti, yi)
    vv = np.interp(t, tv, v)
    if i2_chan:
        i2 = np.interp(t - deskew_us * 1e-6, t2, y2)
    if i3_chan:
        i3 = np.interp(t - deskew_us * 1e-6, t3, y3)
    return compute_magnetics_full(vv, i, dt, int(n_turns), float(ae_m2),
                                  float(le_m), I2wave=i2, N2=int(n2 or 0),
                                  I3wave=i3, N3=int(n3 or 0),
                                  R_winding=r_winding)


def noise(y, fs, method, params, other=None, template_path=""):    # Qt-owned adapter: forwards operator params through the shared run_*
    # functions' existing keyword arguments only. Each default below equals
    # the shared default, so untouched Qt controls reproduce prior results.
    nfft = params.get("nfft", 4096)
    seglen = params.get("seglen", 4096)
    overlap = params.get("overlap", 0.5)
    smooth = params.get("smooth_bins", 31)
    if method == "PSD+CFAR":
        from gui.noise.psd_cfar import run_psd_cfar
        return run_psd_cfar(y, fs, nfft=nfft, seglen=seglen, overlap=overlap,
                            pfa=params.get("pfa", 1e-3), smooth_bins=smooth)
    if method == "Spectrogram":
        from gui.noise.spectrogram import run_spectro
        return run_spectro(y, fs, nfft=nfft, hop=params.get("hop", 2048),
                           pfa=params.get("pfa", 1e-3), smooth_bins=smooth,
                           topk=params.get("topk", 8))
    if method == "MSC":
        if other is None:
            raise ValueError("Select a second channel for coherence")
        from gui.noise.coherence import run_msc
        return run_msc(y, other, fs, nfft=nfft, seglen=seglen, overlap=overlap,
                       thr=params.get("msc_thr", 0.5))
    if method == "Multitaper":
        from gui.noise.multitaper import run_multitaper
        return run_multitaper(y, fs, K=params.get("k_tapers", 6), nfft=nfft,
                              seglen=seglen, overlap=overlap,
                              pfa=params.get("pfa", 1e-3), smooth_bins=smooth)
    if method == "Spectral Kurtosis":
        from gui.noise.kurtosis import run_spectral_kurtosis
        return run_spectral_kurtosis(y, fs, nfft=nfft, hop=params.get("hop", 2048),
                                     sk_thr=params.get("sk_thr", 2.5))
    if method == "Cepstrum":
        from gui.noise.cepstrum import run_cepstrum
        return run_cepstrum(y, fs, nfft=nfft, qmin_ms=params.get("qmin_ms", 0.02),
                            qmax_ms=params.get("qmax_ms", 5.0),
                            topk=params.get("cep_topk", 3))
    if method == "Matched Filter":
        from gui.noise.matched import run_matched_filter
        return run_matched_filter(y, fs, template_path=template_path)
    if method == "AR Spectrum":
        from gui.noise.ar_spectrum import run_ar_spectrum
        return run_ar_spectrum(y, fs, order=params.get("ar_order", 32), nfft=nfft)
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
