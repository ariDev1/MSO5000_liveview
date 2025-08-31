# gui/power/formulas.py
import numpy as np
import math

SIGN_CONVENTION = "IEEE 1459: Q>0 inductive (I lags), Q<0 capacitive (I leads)"

def _estimate_f0(v, fs, mains_hint=None, span_hz=None, fmin=1.0, fmax=None):
    n = len(v)
    if fs is None or n < 8:
        return mains_hint if mains_hint else 0.0
    x = (v - np.mean(v)) * np.hanning(n)
    V = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, d=1.0/fs)

    if mains_hint is None:
        lo = max(fmin, 0.1)
        hi = fmax if (fmax and fmax < fs/2) else (0.98*fs/2)
    else:
        lo = mains_hint - (span_hz or 6.0)
        hi = mains_hint + (span_hz or 6.0)

    mask = (freqs >= lo) & (freqs <= hi)
    if not np.any(mask):
        return mains_hint or 0.0
    k = np.argmax(np.abs(V[mask]))
    return float(freqs[mask][k])

def _fundamental_phasor(x, fs, f0):
    """
    Projektion auf cos/sin bei f0 → komplexer RMS-Phasor X1 (Betrag = RMS der Grundschwingung).
    """
    n = len(x)
    if n == 0 or fs is None or f0 <= 0:
        return 0.0 + 0.0j
    t = np.arange(n) / fs
    # DC herausnehmen für saubere Grundschwingung
    x = x - np.mean(x)
    c = np.cos(2*np.pi*f0*t)
    s = np.sin(2*np.pi*f0*t)
    av = (2.0/n) * np.sum(x * c)
    bv = (2.0/n) * np.sum(x * s)
    # RMS-Phasor: (av - j*bv)/sqrt(2)
    return (av - 1j*bv) / np.sqrt(2.0)

def _p_s_from_time(v, i):
    """Zeitbereich: P, Vrms, Irms, S"""
    P = float(np.mean(v * i))
    Vrms = float(np.sqrt(np.mean(v**2)))
    Irms = float(np.sqrt(np.mean(i**2)))
    S = float(Vrms * Irms)
    return P, Vrms, Irms, S

def _q1_from_fundamental(v, i, fs, mains_hint=50.0):
    """Fundamentale Blindleistung mit korrektem Vorzeichen (IEEE 1459)."""
    if fs is None:
        return np.nan, np.nan, np.nan, None  # Q1, P1, phi1_deg, f0
    f0 = _estimate_f0(v, fs, mains_hint=mains_hint)
    U1 = _fundamental_phasor(v, fs, f0)
    I1 = _fundamental_phasor(i, fs, f0)
    S1 = U1 * np.conjugate(I1)
    P1 = float(np.real(S1))
    Q1 = float(np.imag(S1))  # +induktiv, –kapazitiv
    phi1 = float(np.degrees(np.arctan2(Q1, P1))) if (P1 != 0 or Q1 != 0) else np.nan
    return Q1, P1, phi1, f0

def _pack_result(P, S, Q, Vrms, Irms, PF_extra=None, notes=None, phi1_deg=None, f0=None):
    PF = float(P / S) if S > 0 else 0.0
    out = {
        "Real Power (P)": float(P),
        "Apparent Power (S)": float(S),
        "Reactive Power (Q)": float(Q),     # Hier: Q == Q1 (signiert)
        "Power Factor": float(PF),
        "Vrms": float(Vrms),
        "Irms": float(Irms),
        "phi1_deg": None if phi1_deg is None else float(phi1_deg),
        "f0": None if f0 is None else float(f0),
        "convention": SIGN_CONVENTION,
        "notes": notes or []
    }
    if PF_extra is not None:
        out["Power Factor (fundamental)"] = float(PF_extra)
    return out

def compute_vi_mean(voltage, current, fs=None, mains_hint=50.0, allow_dc=True):
    """
    Instantaneous Power (Zeitbereich) + Q1 aus Grundschwingung (falls fs verfügbar).
    """
    v = np.asarray(voltage, dtype=float)
    i = np.asarray(current, dtype=float)
    n = min(len(v), len(i))
    v, i = v[:n], i[:n]

    if not allow_dc:
        v = v - np.mean(v)
        i = i - np.mean(i)

    P, Vrms, Irms, S = _p_s_from_time(v, i)
    Q1, P1, phi1_deg, f0 = _q1_from_fundamental(v, i, fs, mains_hint=mains_hint)

    notes = []
    if np.isnan(Q1):
        notes.append("Q is fundamental-only and requires fs; returned NaN.")
    if S > 0 and (abs(P) > 1.05 * S):
        notes.append("WARN: |P| > S (check scaling/phase).")

    PF1 = float(P1 / math.hypot(P1, Q1)) if not (np.isnan(Q1) or (P1 == 0 and Q1 == 0)) else None
    return _pack_result(P, S, Q1, Vrms, Irms, PF_extra=PF1, notes=notes, phi1_deg=phi1_deg, f0=f0)

def compute_rms_cos_phi(voltage, current, fs=None, mains_hint=50.0):
    """
    Historisch: P = Vrms*Irms*cos(phi). In der Praxis ist cos(phi)=PF (=P/S).
    Q wird korrekt als Q1 (Grundschwingung) berechnet, falls fs vorhanden.
    """
    v = np.asarray(voltage, dtype=float)
    i = np.asarray(current, dtype=float)
    P, Vrms, Irms, S = _p_s_from_time(v, i)
    # cos_phi aus P/S (robust und äquivalent)
    cos_phi = float(P / S) if S > 0 else 0.0
    # Q1 über Grundschwingung
    Q1, P1, phi1_deg, f0 = _q1_from_fundamental(v, i, fs, mains_hint=mains_hint)
    PF1 = float(P1 / math.hypot(P1, Q1)) if not (np.isnan(Q1) or (P1 == 0 and Q1 == 0)) else None
    return _pack_result(P, S, Q1, Vrms, Irms, PF_extra=PF1, notes=[], phi1_deg=phi1_deg, f0=f0)

def compute_rms_only(voltage, current):
    Vrms = float(np.sqrt(np.mean(np.asarray(voltage, dtype=float)**2)))
    Irms = float(np.sqrt(np.mean(np.asarray(current, dtype=float)**2)))
    S = float(Vrms * Irms)
    return _pack_result(0.0, S, 0.0, Vrms, Irms, notes=["S only"], phi1_deg=None, f0=None)

def compute_fft_phase_power(voltage, current, fs=None, mains_hint=50.0):
    """
    NEU: Fundamentale Phasor-Methode (statt „Summen-FFT-Winkel“).
    Liefert P aus Zeitbereich; Q als Q1 (signiert); zusätzlich PF1, phi1, f0.
    """
    v = np.asarray(voltage, dtype=float)
    i = np.asarray(current, dtype=float)
    P, Vrms, Irms, S = _p_s_from_time(v, i)
    Q1, P1, phi1_deg, f0 = _q1_from_fundamental(v, i, fs, mains_hint=mains_hint)
    PF1 = float(P1 / math.hypot(P1, Q1)) if not (np.isnan(Q1) or (P1 == 0 and Q1 == 0)) else None
    notes = []
    if np.isnan(Q1):
        notes.append("Q requires fs; returned NaN.")
    return _pack_result(P, S, Q1, Vrms, Irms, PF_extra=PF1, notes=notes, phi1_deg=phi1_deg, f0=f0)

def compute_power(voltage, current, method="standard", **kwargs):
    """
    kwargs: fs=None, mains_hint=50.0, allow_dc=True
    """
    if method == "standard":
        return compute_vi_mean(voltage, current, **kwargs)
    elif method == "rms_cos_phi":
        return compute_rms_cos_phi(voltage, current, **kwargs)
    elif method == "rms_only":
        return compute_rms_only(voltage, current)
    elif method == "fft_phase":
        return compute_fft_phase_power(voltage, current, **kwargs)
    else:
        raise ValueError(f"Unknown method: {method}")

method_options = {
    "Instantaneous (v·i mean)": "standard",
    "Vrms × Irms × cos(φ)": "rms_cos_phi",
    "Apparent Power only (Vrms × Irms)": "rms_only",
    "FFT-based Phase (fundamental phasor)": "fft_phase"
}
