# gui/noise/cyclo.py
# -------------------
# Cyclostationary analysis (Spectral Correlation / Cyclic Spectrum) — fast, bin-aligned.
# Returns a heat-map over (frequency f, cyclic frequency alpha).
#
# Estimator (bin-aligned FAM-style):
#   X[k,f] = RFFT of windowed frames.
#   For α = 2*m*df, m=0..m_max:
#       C[f,α] = mean_k{ X[k,f+m] * conj(X[k,f-m]) }
#   Normalize by sqrt(Px[f+m] * Px[f-m]) to get a coherence-like |C| in [0,1].
#   Convert magnitude to dB for display.
#
# Display keys:
#   - image: SCD in dB
#   - extent: (f_min, f_max, a_min, a_max)
#   - xlabel/ylabel/title: axis labels (Noise Inspector reads these)
#   - vmin/vmax: autoscaled limits for imshow (for contrast; data unchanged)
#
# Notes:
#   - α=0 row is pushed to the display floor (it is ~0 dB by definition).
#   - 'auto_level' computes vmin/vmax from the data percentiles to avoid saturation.

from __future__ import annotations
import numpy as np

def _frame_signal(x: np.ndarray, nfft: int, hop: int, window: str = "hann"):
    N = int(len(x))
    if N < nfft:
        pad = np.zeros(nfft - N, dtype=x.dtype)
        x = np.concatenate([x, pad], axis=0)
        N = len(x)
    K = 1 + (N - nfft) // hop if N >= nfft else 1

    # Strided frames (no copy)
    shape = (K, nfft)
    strides = (x.strides[0] * hop, x.strides[0])
    frames = np.lib.stride_tricks.as_strided(x, shape=shape, strides=strides)

    # Window
    if window == "hann":
        w = np.hanning(nfft).astype(np.float64)
    else:
        w = np.hanning(nfft).astype(np.float64)
    frames = frames * w[None, :]
    return frames, K

def run_cyclo(
    y: np.ndarray,
    Fs: float,
    stop_event=None,
    nfft: int = 4096,
    seglen: int = 4096,    # kept for UI parity; we use nfft for frame length
    hop: int = 2048,
    alpha_max: float = 5000.0,  # Hz
    db_floor: float = -40.0,    # dB floor for display
    normalize: bool = True,
    # New: automatic display scaling (contrast), data stays unchanged
    auto_level: bool = True,
    vclip_db: float = 12.0,       # display window width around median if auto_level
    percentile_hi: float = 98.0,  # high percentile for vmax guard
) -> dict:
    if y is None or len(y) == 0:
        raise ValueError("Empty signal")
    x = np.asarray(y, dtype=np.float64)
    x = x - float(np.mean(x))

    nfft = int(max(256, nfft))
    hop = int(max(64, min(hop, nfft)))

    frames, K = _frame_signal(x, nfft=nfft, hop=hop, window="hann")
    if K <= 0:
        raise ValueError("Too-short signal for given nfft/hop")

    if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
        return {
            "method": "Cyclostationary",
            "image": None,
            "extent": None,
            "xlabel": "Frequency (Hz)",
            "ylabel": "Cyclic freq α (Hz)",
            "vmin": float(db_floor),
            "vmax": 0.0,
            "detections": [],
            "df_Hz": Fs / nfft,
            "title": "Cyclostationary",
            "params": {
                "Fs": float(Fs), "nfft": int(nfft), "hop": int(hop),
                "alpha_max": float(alpha_max), "normalize": bool(normalize),
                "db_floor": float(db_floor), "K": int(K)
            },
        }

    X = np.fft.rfft(frames, n=nfft, axis=1)   # (K, M)
    M = X.shape[1]
    df = Fs / nfft

    # Bin-aligned alpha grid: α = 2*m*df, m=0..m_max
    m_max = int(max(0, np.floor(alpha_max / (2.0 * df))))
    if m_max < 1:
        # Only α=0 possible at this df
        alphas = np.array([0.0], dtype=float)
        scd = np.zeros((1, M), dtype=float)
        extent = (0.0, (M - 1) * df, float(alphas.min()), float(alphas.max()))
        return {
            "method": "Cyclostationary",
            "image": 20.0 * np.log10(scd + 1e-12),  # will be db_floor via UI
            "extent": extent,
            "xlabel": "Frequency (Hz)",
            "ylabel": "Cyclic freq α (Hz)",
            "vmin": float(db_floor),
            "vmax": 0.0,
            "detections": [],
            "df_Hz": df,
            "title": "Cyclostationary",
            "params": {
                "Fs": float(Fs), "nfft": int(nfft), "hop": int(hop),
                "alpha_max": float(alpha_max), "normalize": bool(normalize),
                "db_floor": float(db_floor), "K": int(K)
            },
        }

    alphas = 2.0 * df * np.arange(0, m_max + 1, dtype=int)  # includes α=0

    # Power for normalization
    if normalize:
        Px = np.mean(np.abs(X) ** 2, axis=0) + 1e-30  # (M,)

    # Build SCD map
    rows = []
    for m, a in enumerate(alphas):
        if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
            break
        if 2 * m >= M:
            rows.append(np.zeros((M,), dtype=float))
            continue
        Xp = X[:, m:M - m]         # f + m
        Xm = X[:, 0:M - 2 * m]     # f - m
        C = np.mean(Xp * np.conj(Xm), axis=0)  # complex

        if normalize:
            denom = np.sqrt(Px[m:M - m] * Px[0:M - 2 * m]) + 1e-30
            C = C / denom

        row = np.zeros((M,), dtype=float)
        row[m:M - m] = np.abs(C)
        rows.append(row)

    S = np.vstack(rows)  # (n_alpha, M)

    # Magnitude -> dB for display
    Sdb = 20.0 * np.log10(S + 1e-12)
    Sdb = np.maximum(Sdb, float(db_floor))
    # α = 0 row is ~0 dB by definition; push it to the floor so it doesn't dominate
    if Sdb.shape[0] > 0:
        Sdb[0, :] = float(db_floor)

    # Image extent for imshow(origin="lower")
    extent = (0.0, (M - 1) * df, float(alphas.min()), float(alphas.max()))

    # --- Automatic display scaling (contrast) ---
    vmin = float(db_floor)
    vmax = 0.0
    if auto_level and Sdb.size > 0:
        body = Sdb[1:, :] if Sdb.shape[0] > 1 else Sdb
        median = float(np.median(body))
        p_hi = float(np.percentile(body, percentile_hi))
        # Center a small window around the "typical" level, but keep headroom for peaks
        vmin = median - (vclip_db / 2.0)
        vmax = max(p_hi, median + (vclip_db / 2.0))

    return {
        "method": "Cyclostationary",
        "image": Sdb,
        "extent": extent,
        "xlabel": "Frequency (Hz)",
        "ylabel": "Cyclic freq α (Hz)",
        "vmin": vmin,
        "vmax": vmax,
        "detections": [],
        "df_Hz": df,
        "title": "Cyclostationary",
        "params": {
            "Fs": float(Fs),
            "nfft": int(nfft),
            "hop": int(hop),
            "alpha_max": float(alpha_max),
            "db_floor": float(db_floor),
            "normalize": bool(normalize),
            "K": int(K),
            "auto_level": bool(auto_level),
            "vclip_db": float(vclip_db),
            "percentile_hi": float(percentile_hi),
        },
    }
