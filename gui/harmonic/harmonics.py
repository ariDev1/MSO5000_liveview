
"""
harmonics.py — Core harmonic analysis (fundamental, harmonics table, THD/THD+N, SINAD, SNR).
Designed for MSO5000 Liveview. Pure numpy; no VISA/GUI dependencies.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Literal, Tuple
import numpy as np
import math

Window = Literal["rect", "hann", "flattop"]

@dataclass
class HarmonicRow:
    k: int
    f_hz: float
    mag_rms: float
    percent: float
    phase_deg: float

@dataclass
class HarmonicResult:
    f1_hz: float
    v1_rms: float
    thd: float
    thdn: Optional[float]
    sinad_db: Optional[float]
    snr_db: Optional[float]
    crest: float
    form_factor: float
    rows: List[HarmonicRow]
    coherence_cycles: float
    warnings: List[str]
    fs: float
    window: Window
    include_dc: bool

# ----- Window helpers -----

def _window_and_cg(N: int, window: Window) -> tuple[np.ndarray, float, float]:
    """
    Return window vector (length N), coherent gain (CG), and ENBW (bins).
    CG is used to correct amplitude in FFT domain.
    ENBW is used for noise bandwidth notes (not essential for metrics, but can be logged).
    """
    if window == "rect":
        w = np.ones(N, dtype=float)
        cg = 1.0
        enbw = 1.0
    elif window == "hann":
        w = np.hanning(N)
        # Coherent gain = mean of window
        cg = float(np.sum(w) / N)
        # ENBW in bins for Hann ≈ 1.5
        enbw = 1.5
    elif window == "flattop":
        # 5-term flat-top (Harris) coefficients (approximate), amplitude-accurate
        # a0..a4 as commonly used in measurement FFTs
        a0 = 1.0
        a1 = 1.933
        a2 = 1.286
        a3 = 0.388
        a4 = 0.032
        n = np.arange(N)
        w = (
            a0
            - a1*np.cos(2*np.pi*n/(N-1))
            + a2*np.cos(4*np.pi*n/(N-1))
            - a3*np.cos(6*np.pi*n/(N-1))
            + a4*np.cos(8*np.pi*n/(N-1))
        )
        # Normalize to typical flat-top level (we'll compute CG explicitly anyway)
        cg = float(np.sum(w) / N)
        # ENBW for this flat-top ≈ 3.77 bins (varies by definition)
        enbw = 3.77
    else:
        raise ValueError(f"Unknown window: {window}")
    return w.astype(float), float(cg), float(enbw)

# ----- Peak helpers -----

def _parabolic_interpolation(y_minus: float, y0: float, y_plus: float) -> float:
    """
    Quadratic interpolation of peak location relative to the center bin.
    Returns delta in [-0.5, 0.5].
    """
    denom = (y_minus - 2*y0 + y_plus)
    if denom == 0:
        return 0.0
    delta = 0.5 * (y_minus - y_plus) / denom
    # Clamp to avoid silly values if spectrum is weird
    return float(max(min(delta, 0.5), -0.5))

def _estimate_fundamental(xw: np.ndarray, fs: float) -> tuple[float, float, int, float]:
    """
    Estimate fundamental frequency f1 using FFT peak and parabolic interpolation.
    Returns (f1_hz, V1_rms, k0, delta), where k0 is integer bin and delta sub-bin shift.
    V1_rms is corrected for window coherent gain (assumes window already applied).
    """
    N = len(xw)
    # Real FFT
    X = np.fft.rfft(xw)
    mag = np.abs(X)
    # Exclude DC for peak search
    mag[0] = 0.0
    k0 = int(np.argmax(mag))
    if k0 <= 0 or k0 >= len(mag)-1:
        f1 = k0 * fs / N
        V1_rms = (mag[k0] / N) / np.sqrt(2)
        return f1, V1_rms, k0, 0.0
    # Parabolic interpolation on magnitude
    delta = _parabolic_interpolation(mag[k0-1], mag[k0], mag[k0+1])
    k_hat = k0 + delta
    f1 = k_hat * fs / N
    # Interpolated magnitude (approx): correct center magnitude with neighbors
    mag_hat = mag[k0] - 0.25*(mag[k0-1] - mag[k0+1]) * delta
    V1_rms = (mag_hat / N) / np.sqrt(2)
    return float(f1), float(V1_rms), int(k0), float(delta)

def _interpolate_bin(X: np.ndarray, k: int) -> complex:
    """
    Return complex bin value at integer index k (no sub-bin phase interp here).
    """
    if k < 0 or k >= len(X):
        return 0.0 + 0.0j
    return X[k]

def _harmonic_at(X: np.ndarray, fs: float, N: int, f_target: float) -> tuple[float, float]:
    """
    Extract magnitude RMS and phase at f_target by examining nearest FFT bin and doing
    parabolic interpolation on magnitude only. Returns (mag_rms, phase_deg).
    """
    k_float = f_target * N / fs
    k = int(round(k_float))
    if k <= 0 or k >= len(X):
        return 0.0, 0.0
    mag = np.abs(X)
    if 1 <= k < len(mag)-1:
        delta = _parabolic_interpolation(mag[k-1], mag[k], mag[k+1])
        mag_hat = mag[k] - 0.25*(mag[k-1] - mag[k+1]) * delta
        phase = np.angle(X[k])  # simple phase estimate at center bin
        return float((mag_hat / N) / np.sqrt(2)), float(np.degrees(phase))
    else:
        return float((mag[k] / N) / np.sqrt(2)), float(np.degrees(np.angle(X[k])))

def analyze_harmonics(x: np.ndarray, fs: float, n_harmonics: int = 25,
                      window: Window = "hann", include_dc: bool = False,
                      compute_thdn: bool = True, band_hz: Optional[Tuple[float,float]] = None
                     ) -> HarmonicResult:
    """
    x: signal in SI units (V or A) as already-scaled time-domain array.
    fs: sample rate (Hz).
    Returns HarmonicResult with table and metrics.
    """
    assert x.ndim == 1, "x must be a 1-D array"
    N = len(x)
    warnings: list[str] = []

    # 1) DC removal (optional)
    if not include_dc:
        x = x - float(np.mean(x))

    # 2) Window & coherent gain
    w, cg, enbw_bins = _window_and_cg(N, window)
    xw = x * w

    # 3) FFT once
    X = np.fft.rfft(xw)
    mag = np.abs(X)

    # 4) Fundamental estimate
    f1, V1_rms_unscaled, k0, delta0 = _estimate_fundamental(xw, fs)
    # Correct by coherent gain
    V1_rms = float(V1_rms_unscaled / cg)

    # 5) Coherence indicator
    duration = N / fs
    coherence_cycles = float(duration * f1 if f1 > 0 else 0.0)
    if f1 <= 0.0:
        warnings.append("No fundamental detected (f1≤0)")
    if coherence_cycles < 3.0:
        warnings.append("Low cycle count in buffer (<3 cycles)")
    # 6) Harmonics table
    rows: list[HarmonicRow] = []
    nyquist = fs / 2.0

    for k in range(2, n_harmonics+1):
        f_k = k * f1
        if f_k >= nyquist:
            break
        mag_k_unscaled, phase_deg = _harmonic_at(X, fs, N, f_k)
        mag_k = float(mag_k_unscaled / cg)  # correct CG
        percent = float(0.0 if V1_rms == 0 else 100.0 * mag_k / V1_rms)
        rows.append(HarmonicRow(k=k, f_hz=float(f_k), mag_rms=mag_k, percent=percent, phase_deg=phase_deg))

    # 7) THD
    sum_h2 = float(np.sum([r.mag_rms**2 for r in rows]))
    thd = float(0.0 if V1_rms == 0 else math.sqrt(sum_h2) / V1_rms)

    # Total RMS in-band (time-domain)
    total_rms = float(np.sqrt(np.mean(x**2)))
    # 8) THD+N
    thdn = None
    sinad_db = None
    snr_db = None
    if compute_thdn:
        if V1_rms > 0:
            thdn = float(max(0.0, math.sqrt(max(0.0, total_rms**2 - V1_rms**2)) / V1_rms))
            denom = math.sqrt(max(1e-30, total_rms**2 - V1_rms**2))
            sinad_db = float(20.0 * math.log10(V1_rms / max(1e-30, math.sqrt(sum_h2 + (denom**2 - sum_h2)))))
            # crude SNR estimate by removing (approx) harmonics: zero bins near harmonics and inverse-FFT
            # For speed and determinism, we derive SNR from spectrum power excluding ±1 bin around harmonics.
            Y = X.copy()
            # Zero DC if excluded
            if not include_dc and len(Y) > 0:
                Y[0] = 0.0
            # Fundamental ±1
            if 1 <= k0 < len(Y)-1:
                Y[k0-1:k0+2] = 0.0
            # Harmonics ±1 (up to n_harmonics)
            for r in rows:
                k_idx = int(round(r.f_hz * N / fs))
                k_lo = max(0, k_idx-1); k_hi = min(len(Y), k_idx+2)
                Y[k_lo:k_hi] = 0.0
            noise_rms_spec = float(np.sqrt(np.sum(np.abs(Y)**2)) / (N*np.sqrt(2)))  # spectrum-based approx
            snr_db = float(20.0 * math.log10(max(V1_rms,1e-30) / max(noise_rms_spec,1e-30)))
        else:
            thdn = None
            sinad_db = None
            snr_db = None

    # Crest & form factor from time-domain
    crest = float(np.max(np.abs(x)) / max(total_rms, 1e-30))
    vavg_rect = float(np.mean(np.abs(x)))
    form_factor = float(total_rms / max(vavg_rect, 1e-30))

    return HarmonicResult(
        f1_hz=float(f1),
        v1_rms=float(V1_rms),
        thd=float(thd),
        thdn=thdn,
        sinad_db=sinad_db,
        snr_db=snr_db,
        crest=crest,
        form_factor=form_factor,
        rows=rows,
        coherence_cycles=coherence_cycles,
        warnings=warnings,
        fs=float(fs),
        window=window,
        include_dc=include_dc,
    )
