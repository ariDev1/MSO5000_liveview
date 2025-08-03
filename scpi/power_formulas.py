# scpi/power_formulas.py
"""
Power calculation methods used by compute_power_from_scope().
All functions must return: (p_inst_vector, real_power_scalar)
"""

import numpy as np

def compute_power_standard(v, i, xinc):
    """
    Instantaneous real power using v(t)·i(t)
    """
    p_inst = v * i
    P = np.mean(p_inst)
    return p_inst, P

def compute_power_rms_cos_phi(v, i, xinc):
    """
    Vrms × Irms × cos(θ) method based on FFT phase angle
    """
    Vrms = np.sqrt(np.mean(v**2))
    Irms = np.sqrt(np.mean(i**2))

    fft_v = np.fft.fft(v)
    fft_i = np.fft.fft(i)
    phase_v = np.angle(fft_v[1])
    phase_i = np.angle(fft_i[1])
    theta = phase_v - phase_i

    P = Vrms * Irms * np.cos(theta)
    return v * i, P
