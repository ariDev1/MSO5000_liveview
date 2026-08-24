# scpi/power_formulas.py
"""
Power calculation methods used by compute_power_from_scope().
All functions must return: (p_inst_vector, real_power_scalar)
"""

import numpy as np


def _validate_waveform_pair(voltage, current):
    voltage = np.asarray(voltage, dtype=float)
    current = np.asarray(current, dtype=float)

    if voltage.size == 0 or current.size == 0:
        raise ValueError("Waveform inputs must not be empty.")
    if voltage.shape != current.shape:
        raise ValueError("Waveform inputs must have the same length.")
    if not np.all(np.isfinite(voltage)) or not np.all(np.isfinite(current)):
        raise ValueError("Waveform inputs must contain only finite values.")

    return voltage, current


def compute_power_standard(v, i, xinc):
    """
    Instantaneous real power using v(t)·i(t)
    """
    v, i = _validate_waveform_pair(v, i)
    p_inst = v * i
    P = np.mean(p_inst)
    return p_inst, P

def compute_power_rms_cos_phi(v, i, xinc):
    """
    Vrms × Irms × cos(θ) method based on FFT phase angle
    """
    v, i = _validate_waveform_pair(v, i)
    Vrms = np.sqrt(np.mean(v**2))
    Irms = np.sqrt(np.mean(i**2))

    fft_v = np.fft.fft(v)
    fft_i = np.fft.fft(i)
    phase_v = np.angle(fft_v[1])
    phase_i = np.angle(fft_i[1])
    theta = phase_v - phase_i

    P = Vrms * Irms * np.cos(theta)
    return v * i, P
