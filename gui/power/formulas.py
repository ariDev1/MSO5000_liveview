# gui/power/formulas.py

import numpy as np
import math


def compute_vi_mean(voltage, current):
    """Instantaneous Power via mean(v·i)"""
    vi = voltage * current
    P = np.mean(vi)
    Vrms = np.sqrt(np.mean(voltage**2))
    Irms = np.sqrt(np.mean(current**2))
    S = Vrms * Irms
    Q = math.sqrt(max(S**2 - P**2, 0))
    PF = P / S if S > 0 else 0.0
    return {
        "Real Power (P)": P,
        "Apparent Power (S)": S,
        "Reactive Power (Q)": Q,
        "Power Factor": PF,
        "Vrms": Vrms,
        "Irms": Irms
    }


def compute_rms_cos_phi(voltage, current):
    """P = Vrms × Irms × cos(phi) with phi from cross-correlation"""
    Vrms = np.sqrt(np.mean(voltage**2))
    Irms = np.sqrt(np.mean(current**2))

    # Normalize for angle calc
    v = voltage - np.mean(voltage)
    i = current - np.mean(current)

    try:
        dot = np.dot(v, i)
        cos_phi = dot / (np.linalg.norm(v) * np.linalg.norm(i))
        cos_phi = max(min(cos_phi, 1.0), -1.0)
    except:
        cos_phi = 1.0

    P = Vrms * Irms * cos_phi
    S = Vrms * Irms
    Q = math.sqrt(max(S**2 - P**2, 0))
    return {
        "Real Power (P)": P,
        "Apparent Power (S)": S,
        "Reactive Power (Q)": Q,
        "Power Factor": cos_phi,
        "Vrms": Vrms,
        "Irms": Irms
    }


def compute_rms_only(voltage, current):
    """Only calculates Apparent Power = Vrms × Irms"""
    Vrms = np.sqrt(np.mean(voltage**2))
    Irms = np.sqrt(np.mean(current**2))
    S = Vrms * Irms
    return {
        "Real Power (P)": 0.0,
        "Apparent Power (S)": S,
        "Reactive Power (Q)": 0.0,
        "Power Factor": 0.0,
        "Vrms": Vrms,
        "Irms": Irms
    }


def compute_fft_phase_power(voltage, current):
    """Uses FFT cross-phase to calculate angle φ and derive power quantities"""
    Vrms = np.sqrt(np.mean(voltage**2))
    Irms = np.sqrt(np.mean(current**2))

    v = voltage - np.mean(voltage)
    i = current - np.mean(current)

    fft_v = np.fft.fft(v)
    fft_i = np.fft.fft(i)

    try:
        dot = np.vdot(fft_v, fft_i)
        phi = np.angle(dot)
        cos_phi = np.cos(phi)
        sin_phi = np.sin(phi)
    except:
        cos_phi = 1.0
        sin_phi = 0.0

    P = Vrms * Irms * cos_phi
    Q = Vrms * Irms * sin_phi
    S = Vrms * Irms

    return {
        "Real Power (P)": P,
        "Apparent Power (S)": S,
        "Reactive Power (Q)": Q,
        "Power Factor": cos_phi,
        "Vrms": Vrms,
        "Irms": Irms
    }


def compute_power(voltage, current, method="standard"):
    if method == "standard":
        return compute_vi_mean(voltage, current)
    elif method == "rms_cos_phi":
        return compute_rms_cos_phi(voltage, current)
    elif method == "rms_only":
        return compute_rms_only(voltage, current)
    elif method == "fft_phase":
        return compute_fft_phase_power(voltage, current)
    else:
        raise ValueError(f"Unknown method: {method}")


method_options = {
    "Instantaneous (v·i mean)": "standard",
    "Vrms × Irms × cos(φ)": "rms_cos_phi",
    "Apparent Power only (Vrms × Irms)": "rms_only",
    "FFT-based Phase (Vrms × Irms × cos(fft(φ)))": "fft_phase"
}
