"""Magnetics core: B/H/L/mu_r computation, geometry, materials.

Extracted verbatim from the advancedmagnetics Tk tab
(gui/magnetics_tab.py) — calculation code only, no Tk imports.
Source ranges: mu0/USER_MATERIALS_FILE/CH_SOURCES, lines 48-175
(materials + toroid geometry), lines 240-1043 (magnetics maths).
SCPI fetch, plots and widgets intentionally stay behind.
"""

import json
import math
import os

import numpy as np

from utils.debug import log_debug


mu0 = 4.0 * np.pi * 1e-7

USER_MATERIALS_FILE = os.path.join(
    os.path.expanduser("~"), ".mso5000_liveview", "user_materials.json")

CH_SOURCES = ["CH1","CH2","CH3","CH4","MATH1","MATH2","MATH3","MATH4"]

# ─────────────────────────────────────────────────────────────────────────────
# Material database
# Each entry: (display_name, mu_i, Bsat_mT, description)
# mu_i = initial relative permeability (low-signal, low-freq reference)
# Bsat_mT = saturation flux density in mT
# ─────────────────────────────────────────────────────────────────────────────
MATERIALS = {
    "Fair-Rite #31":  (1500, 320, "MnZn, 1–300 MHz EMI suppression"),
    "Fair-Rite #43":  (800,  290, "MnZn, 10–500 MHz general purpose"),
    "Fair-Rite #61":  (125,  230, "NiZn, 200 MHz–2 GHz, low loss"),
    "Fair-Rite #67":  (40,   350, "NiZn, 50 MHz–1 GHz, power"),
    "Fair-Rite #77":  (2000, 320, "MnZn, 10 kHz–1 MHz power"),
    "Fair-Rite #78":  (2300, 330, "MnZn, 1–500 kHz SMPS"),
    "Fair-Rite #52":  (250,  320, "NiZn, 1–100 MHz"),
    "Micrometals T-26":(75,  1400,"Iron powder, 1–50 MHz, high Bsat"),
    "Micrometals T-52":(75,  1400,"Iron powder (same core family)"),
    "Custom":         (None, None, "Enter μᵢ and Bsat manually"),
}


# Built-in material names — these can't be overwritten by user presets
BUILTIN_MATERIAL_NAMES = {
    "Fair-Rite #31", "Fair-Rite #43", "Fair-Rite #61", "Fair-Rite #67",
    "Fair-Rite #77", "Fair-Rite #78", "Fair-Rite #52",
    "Micrometals T-26", "Micrometals T-52", "Custom"}


def _material_to_dict(entry):
    """Normalise a MATERIALS entry to a dict regardless of source schema.
    Built-in entries are 3-tuples (mu_i, Bsat_mT, desc).
    User presets are dicts with at least mu_i, bsat_mT, desc, and optional
    geometry: Ae_cm2, le_cm, N, dim_mode, OD_mm, ID_mm, HT_mm."""
    if isinstance(entry, dict):
        return dict(entry)   # already a dict, return a copy
    if isinstance(entry, (list, tuple)) and len(entry) == 3:
        mu_i, bsat, desc = entry
        return {"mu_i": mu_i, "bsat_mT": bsat, "desc": desc}
    return {"mu_i": None, "bsat_mT": None, "desc": ""}


def _get_material(name):
    """Look up a material by name and return a normalised dict, or None."""
    e = MATERIALS.get(name)
    if e is None: return None
    return _material_to_dict(e)


def _load_user_materials():
    """Load user-saved custom materials from the persistent JSON file.
    Merges them into MATERIALS in-place. Silent no-op if the file doesn't
    exist or is malformed (won't crash the tab on first run).

    Two storage formats are accepted for backward compatibility:
      Old (v23 and earlier): [mu_i, bsat_mT, desc]  → 3-list
      New (v25+):            {mu_i, bsat_mT, desc, optional geometry...}  → dict

    User presets are always stored as dicts going forward."""
    try:
        if not os.path.exists(USER_MATERIALS_FILE):
            return
        with open(USER_MATERIALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for name, vals in data.items():
            if not name or name in BUILTIN_MATERIAL_NAMES:
                continue
            # Handle both old (list) and new (dict) formats
            if isinstance(vals, dict):
                # Validate required keys
                if "mu_i" in vals and "bsat_mT" in vals:
                    MATERIALS[name] = dict(vals)
            elif isinstance(vals, (list, tuple)) and len(vals) == 3:
                mu_i, bsat, desc = vals
                MATERIALS[name] = {
                    "mu_i": mu_i, "bsat_mT": bsat, "desc": str(desc)}
    except Exception as e:
        log_debug(f"user materials load: {e}")


def _save_user_materials():
    """Write all non-built-in materials to the persistent JSON file.
    Safe to call after every preset addition. Creates the directory if
    needed. Skips the built-in entries (those don't need persisting).
    Always writes the new dict format."""
    user_only = {}
    for n, v in MATERIALS.items():
        if n in BUILTIN_MATERIAL_NAMES: continue
        d = _material_to_dict(v)
        # Strip None/NaN-like values to keep JSON clean
        user_only[n] = {k: vv for k, vv in d.items() if vv is not None and vv != ""}
    try:
        os.makedirs(os.path.dirname(USER_MATERIALS_FILE), exist_ok=True)
        with open(USER_MATERIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(user_only, f, indent=2)
        return True
    except Exception as e:
        log_debug(f"user materials save: {e}")
        return False


# Load any persisted user materials at import time so they show up in the
# combobox immediately when the tab is built.
_load_user_materials()
MATERIAL_NAMES = list(MATERIALS.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Toroid geometry formulas
# ─────────────────────────────────────────────────────────────────────────────

def toroid_Ae(OD_mm, ID_mm, HT_mm):
    """Effective cross-section area (m²) for a round toroid."""
    return ((OD_mm - ID_mm) / 2.0 * 1e-3) * (HT_mm * 1e-3)

def toroid_le(OD_mm, ID_mm):
    """Effective magnetic path length (m) for a round toroid."""
    r_mean = ((OD_mm + ID_mm) / 4.0) * 1e-3   # mean radius in m
    return 2.0 * math.pi * r_mean

def AL_from_geometry(mu_i, Ae_m2, le_m):
    """AL value (nH/N²) from geometry and initial permeability."""
    if mu_i is None or Ae_m2 <= 0 or le_m <= 0:
        return None
    return (mu0 * mu_i * Ae_m2 / le_m) * 1e9   # nH/N²

def L_from_AL(AL_nH, N):
    """Inductance (µH) from AL (nH/N²) and turns."""
    return AL_nH * N * N / 1000.0   # µH

# ─────────────────────────────────────────────────────────────────────────────
# Magnetics maths
# ─────────────────────────────────────────────────────────────────────────────

def _cumtrap(y, dt):
    z = np.empty_like(y, dtype=float); z[0] = 0.0
    z[1:] = np.cumsum((y[1:] + y[:-1]) * 0.5) * dt
    return z


def _find_period_samples(V, dt):
    """
    Estimate the fundamental period in samples.

    Strategy: zero-crossing spacing on the AC-coupled signal is exact
    (no bin discretisation error), provided the signal isn't dominated
    by noise. FFT spectral peak is more robust to noise but limited to
    integer-bin resolution → wrong period when the window doesn't contain
    a whole number of cycles.

    So: use ZC when we have 3+ clean rising crossings. Use FFT as a
    fallback when ZC is degenerate. Use FFT as a sanity check: if ZC and
    FFT disagree by more than 50%, the data is suspect → trust FFT.

    Returns period in samples (rounded to nearest integer), or None if
    no clean fundamental can be identified.
    """
    n = len(V)
    if n < 8 or dt <= 0:
        return None

    # ── Method A: FFT spectral peak (for sanity check / fallback) ─────────
    T_fft = None
    try:
        v = V - np.mean(V)
        win = np.hanning(n)
        S   = np.abs(np.fft.rfft(v * win))
        if len(S) >= 2:
            k_peak = int(np.argmax(S[1:])) + 1
            if k_peak >= 1 and S[k_peak] > 0:
                T_fft = n / k_peak
    except Exception:
        pass

    # ── Method B: Zero-crossing spacing (primary, exact) ──────────────────
    T_zc = None
    n_zc = 0
    try:
        v_ac = V - np.mean(V)
        signs = np.sign(v_ac)
        signs[signs == 0] = 1
        zc_rise_raw = np.where(np.diff(signs) > 0)[0]
        if len(zc_rise_raw) >= 2:
            # Aggressive chatter rejection: enforce minimum spacing between
            # consecutive crossings. A real signal at frequency f has rising
            # crossings exactly T apart; noise can create false crossings
            # within milliseconds of a real one.
            # Minimum gap = 0.5 × FFT-estimated period (or 0.5 × naive median)
            if T_fft is not None:
                min_gap = 0.5 * T_fft
            else:
                # Use median of raw spacings as starting estimate
                min_gap = 0.5 * float(np.median(np.diff(zc_rise_raw)))
            # Greedy filter: keep first crossing, only accept later ones at
            # least min_gap samples after the last accepted one
            zc_clean = [int(zc_rise_raw[0])]
            for z in zc_rise_raw[1:]:
                if z - zc_clean[-1] >= min_gap:
                    zc_clean.append(int(z))
            if len(zc_clean) >= 2:
                zc_spacings = np.diff(zc_clean)
                T_zc = float(np.median(zc_spacings))
                n_zc = len(zc_spacings)
    except Exception:
        pass

    # ── Combine ────────────────────────────────────────────────────────────
    if T_zc is not None and n_zc >= 3:
        # ZC has at least 3 spacings → statistically reliable, exact resolution
        # Sanity check against FFT: must agree within 50%, else trust FFT
        if T_fft is not None and abs(T_zc - T_fft) / max(T_zc, T_fft) > 0.5:
            T_samp = int(round(T_fft))
        else:
            T_samp = int(round(T_zc))
    elif T_zc is not None and T_fft is not None:
        # Few ZCs available; use whichever agrees with FFT-disambiguated nearby
        if abs(T_zc - T_fft) / max(T_zc, T_fft) < 0.1:
            T_samp = int(round(T_zc))   # they agree, trust ZC
        else:
            T_samp = int(round(T_fft))  # disagree, FFT is more robust
    elif T_zc is not None:
        T_samp = int(round(T_zc))
    elif T_fft is not None:
        T_samp = int(round(T_fft))
    else:
        return None

    if T_samp < 4:
        return None
    return T_samp


def compute_magnetics(Vwave, Iwave, dt, N, Ae, le):
    n = min(len(Vwave), len(Iwave))
    V = Vwave[:n].copy(); I = Iwave[:n].copy()

    # ── Step 1: estimate switching period and trim to whole cycles ────────
    # Period detector returns samples-per-cycle from FFT spectral peak.
    # We then align the trim window to the FIRST rising zero-crossing of V,
    # so the integer-cycle FFT below sees a coherent (no edge discontinuity)
    # window. Without this alignment, even a correct T_samp can yield an
    # inconsistent BH loop because the trim starts mid-cycle.
    T_samp = _find_period_samples(V, dt)
    if T_samp and T_samp > 4:
        # Find first rising zero-crossing of V (after detrending), with
        # chatter rejection — only accept the first ZC, then enforce a gap
        # of ≥ T_samp/2 before the next valid one. This matches the trim
        # window to a real cycle boundary, not a noise spike.
        v_centered = V - np.mean(V)
        signs = np.sign(v_centered)
        signs[signs == 0] = 1
        zc_rise_raw = np.where(np.diff(signs) > 0)[0]
        # Pick the first ZC. If it's followed by another within T_samp/2,
        # that's chatter — but the first one is still a valid cycle start.
        # However if the first crossing is anomalously close to t=0 (within
        # a few samples), it might be a noise spike at the capture edge —
        # skip it and use the next one.
        if len(zc_rise_raw) >= 1:
            min_gap = T_samp // 2
            # Walk forward past any chatter clusters at the start
            start = int(zc_rise_raw[0])
            # If the next ZC is too close (chatter), look for the real next one
            for z in zc_rise_raw[1:]:
                if z - start < min_gap:
                    # This is chatter following start — keep moving
                    continue
                else:
                    break
            n_remaining = n - start
            n_cycles = n_remaining // T_samp
            if n_cycles >= 1:
                n_use = n_cycles * T_samp
                V = V[start:start + n_use]
                I = I[start:start + n_use]
                n = n_use
            else:
                # Not enough room; fall back to length-trim from origin
                n_cycles = n // T_samp
                if n_cycles >= 1:
                    n_use = n_cycles * T_samp
                    V = V[:n_use]; I = I[:n_use]; n = n_use
        else:
            # No zero-crossing found; length-trim from origin
            n_cycles = n // T_samp
            if n_cycles >= 1:
                n_use = n_cycles * T_samp
                V = V[:n_use]; I = I[:n_use]; n = n_use
    else:
        T_samp = None   # fallback: unknown period

    # ── Step 2: remove DC from V before integration ───────────────────────
    # For a symmetric square wave mean ≈ 0 already, but remove it precisely.
    # If T_samp is known, use per-cycle mean (more robust than global mean).
    if T_samp and T_samp > 4 and n >= T_samp:
        # Reshape into cycles and subtract per-cycle mean from each cycle
        cycles = V.reshape(-1, T_samp)
        v_ac   = (cycles - cycles.mean(axis=1, keepdims=True)).ravel()
    else:
        v_ac = V - np.mean(V)

    # ── Step 3: integrate with drift correction ───────────────────────────
    # Two paths:
    #   (a) Fundamental-locked path: extract V's fundamental phasor and
    #       integrate analytically in the frequency domain. B = ∫V/(N·Ae) dt
    #       in the time domain becomes B_k = V_k / (jω_k · N·Ae) for each
    #       harmonic. This is COMPLETELY DRIFT-FREE because the ω=0 (DC)
    #       bin is excluded from the integration. Best for low-frequency
    #       drives where time-domain integration drift dominates.
    #   (b) Time-domain cumulative trapezoidal integration, with per-cycle
    #       end-point drift fit. The original method, kept as a fallback
    #       and as the primary path when no clean fundamental is found.
    #
    # We use (a) when we have at least 2 whole cycles AND a clean fundamental
    # bin (one bin clearly dominant). Otherwise fall back to (b).
    flux = None
    if T_samp and T_samp > 4 and n >= 2 * T_samp:
        try:
            n_cycles_int = n // T_samp
            n_ic = n_cycles_int * T_samp
            v_ic = v_ac[:n_ic]
            V_spec = np.fft.rfft(v_ic)
            freqs  = np.fft.rfftfreq(n_ic, d=dt)
            # Frequency-domain integration: divide each bin by jω
            # Skip DC bin to avoid divide-by-zero (and that's exactly what
            # makes this integration drift-free)
            integ_spec = np.zeros_like(V_spec)
            with np.errstate(divide="ignore", invalid="ignore"):
                omega_arr = 2.0 * np.pi * freqs
                # Only integrate bins with non-zero frequency
                nz = omega_arr > 0
                integ_spec[nz] = V_spec[nz] / (1j * omega_arr[nz])
            flux_ic = np.fft.irfft(integ_spec, n=n_ic).real
            # Pad back out to n if needed (just hold last value — won't be used)
            if n_ic < n:
                flux = np.zeros(n)
                flux[:n_ic] = flux_ic
                flux[n_ic:] = flux_ic[-1]
                # Also trim n down so the rest of compute uses the clean window
                V = V[:n_ic]; I = I[:n_ic]; flux = flux[:n_ic]; n = n_ic
            else:
                flux = flux_ic
        except Exception:
            flux = None

    if flux is None:
        # Fallback: time-domain cumulative integration with drift correction
        flux = _cumtrap(v_ac, dt)
        if T_samp and T_samp > 4 and n >= T_samp:
            n_cycles = n // T_samp
            endpoints = flux[T_samp-1::T_samp][:n_cycles]
            if len(endpoints) >= 2:
                ep_x    = np.arange(len(endpoints)) * T_samp + (T_samp - 1)
                ep_coef = np.polyfit(ep_x, endpoints, 1)
                drift   = np.polyval(ep_coef, np.arange(n))
                flux   -= drift
            else:
                flux -= np.linspace(flux[0], flux[-1], n)
        else:
            flux -= np.linspace(flux[0], flux[-1], n)

    # Centre flux around zero — removes any remaining DC offset so B swings ±symmetrically
    flux -= np.mean(flux)

    B = flux / (N * Ae)
    H = (N * I) / le

    t = np.arange(n) * dt

    # Peak-region mask: relative thresholds so zero-crossing spikes are excluded.
    # L and mu_r are only meaningful away from zero crossings of I and H.
    # Values outside the mask are NaN so plots autoscale cleanly without spikes.
    I_pk = np.nanmax(np.abs(I)); B_pk = np.nanmax(np.abs(B))
    H_pk = np.nanmax(np.abs(H))

    mask = (np.abs(I) > 0.20 * I_pk) & (np.abs(B) > 0.10 * B_pk)

    # Use relative denominators — never divide near zero
    H_safe = np.where(mask & (np.abs(H) > 0.05 * H_pk), H, np.nan)
    I_safe = np.where(mask & (np.abs(I) > 0.20 * I_pk), I, np.nan)

    with np.errstate(divide="ignore", invalid="ignore"):
        mu_r = np.where(np.isfinite(H_safe), B / (mu0 * H_safe), np.nan)
        L_H  = np.where(np.isfinite(I_safe), N * Ae * B / I_safe, np.nan)

    L_pr  = L_H[mask];  mu_pr = mu_r[mask]
    L_at_peak  = float(np.nanmedian(L_pr))  if np.any(np.isfinite(L_pr))  else np.nan
    mu_at_peak = float(np.nanmedian(mu_pr)) if np.any(np.isfinite(mu_pr)) else np.nan
    reluc = (N**2 / L_at_peak) if (np.isfinite(L_at_peak) and L_at_peak > 0) else np.nan
    f0    = _est_freq(V, dt)

    # L from dI/dt — independent cross-check not dependent on B
    # Valid during flat-V half-cycles where V = L * dI/dt
    # For square wave: L = Vpk / (2*Ipk / (T/2)) = Vpk*T/(4*Ipk)
    L_didt_uH = np.nan
    try:
        di_arr = np.gradient(I, dt)
        v_flat = np.abs(V) > 0.7 * np.nanmax(np.abs(V))
        valid  = v_flat & (np.abs(di_arr) > 0.01 * np.nanmax(np.abs(di_arr)))
        if np.any(valid):
            L_samples = V[valid] / di_arr[valid]
            L_didt_uH = float(np.nanmedian(L_samples[np.isfinite(L_samples)])) * 1e6
    except Exception:
        pass

    # Differential permeability μ_diff = dB/dH / μ₀  — local slope of B-H curve
    # Smooth H and B before differentiating to remove noise-driven spikes.
    mu_diff = np.full(n, np.nan)
    rising  = np.ones(n, dtype=bool)
    falling = np.zeros(n, dtype=bool)
    try:
        from scipy.signal import savgol_filter
        # Window ~5% of period, odd, minimum 5
        win = max(5, int(n * 0.05) | 1)   # ensure odd
        H_sm = savgol_filter(H, window_length=win, polyorder=3)
        B_sm = savgol_filter(B, window_length=win, polyorder=3)
    except Exception:
        H_sm = H; B_sm = B

    try:
        dH = np.gradient(H_sm, dt)
        dB = np.gradient(B_sm, dt)
        rising  = dH > 0
        falling = dH < 0
        with np.errstate(divide="ignore", invalid="ignore"):
            dBdH = np.where(np.abs(dH) > 0.05 * np.nanmax(np.abs(dH)),
                            dB / dH, np.nan)
        mu_diff = dBdH / mu0
        mu_limit = 5.0 * max(float(np.nanmax(np.abs(mu_diff[mask]))) if np.any(mask & np.isfinite(mu_diff)) else 1e4, 1.0)
        mu_diff  = np.where(np.abs(mu_diff) < mu_limit, mu_diff, np.nan)
    except Exception:
        pass

    # ── Br and Hc from B-H zero crossings ────────────────────────────────
    Br_mT = np.nan; Hc_Am = np.nan
    try:
        H_sign = np.sign(H); H_zc = np.where(np.diff(H_sign) != 0)[0]
        if len(H_zc) >= 2:
            Br_vals = []
            for k in H_zc:
                frac = H[k]/(H[k]-H[k+1]) if (H[k]-H[k+1]) != 0 else 0.5
                Br_vals.append(B[k] + frac*(B[k+1]-B[k]))
            Br_mT = float(np.nanmedian(np.abs(Br_vals))) * 1e3
    except Exception: pass
    try:
        B_sign = np.sign(B); B_zc = np.where(np.diff(B_sign) != 0)[0]
        if len(B_zc) >= 2:
            Hc_vals = []
            for k in B_zc:
                frac = B[k]/(B[k]-B[k+1]) if (B[k]-B[k+1]) != 0 else 0.5
                Hc_vals.append(H[k] + frac*(H[k+1]-H[k]))
            Hc_Am = float(np.nanmedian(np.abs(Hc_vals)))
    except Exception: pass

    return {
        "t": t, "V": V, "I": I, "B": B, "H": H,
        "mu_r": mu_r, "L_H": L_H, "mu_diff": mu_diff,
        "rising": rising if 'rising' in dir() else np.ones(n, dtype=bool),
        "falling": falling if 'falling' in dir() else np.zeros(n, dtype=bool),
        "p_inst": V * I, "mask": mask,
        "B_peak_mT":    float(B_pk) * 1e3,
        "H_peak":       float(np.nanmax(np.abs(H))),
        "Br_mT":        Br_mT,
        "Hc_Am":        Hc_Am,
        "mu_at_peak":   mu_at_peak,
        "L_at_peak_uH": L_at_peak * 1e6 if np.isfinite(L_at_peak) else np.nan,
        "L_didt_uH":    L_didt_uH,
        "reluc_MA":     reluc / 1e6 if np.isfinite(reluc) else np.nan,
        "P_avg_W":      float(np.mean(V * I)),
        "f_fund_kHz":   f0 / 1e3,
    }


def compute_magnetics_full(Vwave, Iwave, dt, N1, Ae, le,
                           I2wave=None, N2=None,
                           I3wave=None, N3=None,
                           R_winding=None,
                           sm_k=None, sm_a=None, sm_b=None,
                           bh_smooth_factor=None):
    """
    Extended magnetics computation with winding current decomposition.

    Open-secondary mode (I2wave=None AND I3wave=None):
        With no secondary load, I_primary IS the magnetising current.
        I_mag = I1 directly. L_primary computed unambiguously.

    Loaded mode (I2wave and/or I3wave provided):
        I_total  = I_magnetising + I_ref2 + I_ref3
        I_ref2 = I2 * (N2 / N1)
        I_ref3 = I3 * (N3 / N1)
        I_mag  = I_total − I_ref2 − I_ref3
        H_true = N1 * I_mag / le

    L-computation strategy (fixes the -L bug from earlier builds):
        1. Integer-cycle FFT phasor (no window → no leakage)
           L_phasor = |V_ph| / (ω · |I_mag_ph|)   [magnitude-only, always >0]
        2. Energy-based L cross-check over integer cycles
           L_energy = 2·W_peak / I_mag_pk²
           where W_peak is the peak stored energy ∫V·I_mag dt
        3. Slope-based L from flat-V half-cycles (square-wave drive)
           L_slope = V_flat · Δt / ΔI_mag
        Primary reading = L_phasor. Others shown as cross-checks.

    Returns base dict (same keys as compute_magnetics) plus "decomp" dict.
    """
    base = compute_magnetics(Vwave, Iwave, dt, N1, Ae, le)
    n    = len(base["t"])

    # ── Detect open-secondary mode ────────────────────────────────────────
    open_sec = (I2wave is None) and (I3wave is None)

    # Align lengths
    def _trim(w):
        if w is None: return np.zeros(n)
        return w[:n] if len(w) >= n else np.pad(w, (0, n - len(w)), constant_values=0.0)

    I2 = _trim(I2wave) if I2wave is not None else np.zeros(n)
    I3 = _trim(I3wave) if I3wave is not None else np.zeros(n)
    n2 = N2 if N2 else 0
    n3 = N3 if N3 else 0

    if open_sec:
        # No secondary → primary current IS magnetising current
        I_ref2 = np.zeros(n)
        I_ref3 = np.zeros(n)
        I_mag  = base["I"].copy()
    else:
        I_ref2 = I2 * (n2 / N1) if n2 else np.zeros(n)
        I_ref3 = I3 * (n3 / N1) if n3 else np.zeros(n)
        I_mag  = base["I"] - I_ref2 - I_ref3

    # True H from magnetising current only
    H_true = (N1 * I_mag) / le

    # ── Integer-cycle windowing for clean phasor extraction ───────────────
    # Find fundamental bin directly from V's spectrum. This is more reliable
    # than re-running the period detector (which can mis-detect on already-
    # trimmed/noisy data); the dominant non-DC FFT bin IS the fundamental
    # by definition. Then trim to n_cycles*T_samp where n_cycles = k_peak.
    try:
        v_full = base["V"] - np.mean(base["V"])
        S_v = np.abs(np.fft.rfft(v_full * np.hanning(n)))
        if len(S_v) >= 2:
            k_peak = int(np.argmax(S_v[1:])) + 1
            if k_peak >= 1 and S_v[k_peak] > 0:
                # T_samp from FFT bin: round to nearest integer cycle width
                T_samp = max(4, int(round(n / k_peak)))
                n_cycles = max(1, n // T_samp)
                n_ic = n_cycles * T_samp
            else:
                T_samp = None
                n_ic = n
                n_cycles = 1
        else:
            T_samp = None
            n_ic = n
            n_cycles = 1
    except Exception:
        T_samp = None
        n_ic = n
        n_cycles = 1

    def _phasor_ic(sig):
        """Fundamental phasor over integer cycles, no window needed.
        Returns complex amplitude (peak, not RMS)."""
        if n_ic < 8: return complex(0)
        s = sig[:n_ic] - np.mean(sig[:n_ic])
        S = np.fft.rfft(s)
        # Fundamental bin = n_cycles (since we have n_cycles full periods)
        k = n_cycles if n_cycles < len(S) else int(np.argmax(np.abs(S[1:]))) + 1
        return S[k] * 2.0 / n_ic   # peak amplitude

    V_ph     = _phasor_ic(base["V"])
    I1_ph    = _phasor_ic(base["I"])
    B_ph     = _phasor_ic(base["B"])
    Hm_ph    = _phasor_ic(H_true)
    Imag_ph  = _phasor_ic(I_mag)
    I2_ph    = _phasor_ic(I2)
    I3_ph    = _phasor_ic(I3)

    # Fundamental angular frequency
    f0 = _est_freq(base["V"], dt)
    omega = 2.0 * np.pi * f0 if f0 > 0 else 0.0

    # ── BH-loop smoothing (visualization only, NOT used for L math) ───────
    # When the bench has parasitic LC ringing on the current waveform, the
    # BH loop renders as a "zigzag" because B (=∫V dt) is naturally smooth
    # but I carries the ringing. A frequency-domain low-pass filter with
    # cutoff = bh_smooth_factor × f_fund cleans up the loop without
    # affecting the inductance math (which still uses the raw arrays).
    #
    # Reasonable factor values: 5–20. Default off (None). At factor=10,
    # harmonics 1–10 are kept and anything above is zeroed — so a 5 kHz
    # drive keeps content up to 50 kHz, plenty for a real magnetising
    # current but cleans up parasitic ringing typically at 100+ kHz.
    I_smoothed     = None
    I_mag_smoothed = None
    H_true_smoothed = None
    if bh_smooth_factor is not None and bh_smooth_factor > 0 and f0 > 0:
        try:
            f_cut = bh_smooth_factor * f0
            # Apply over the integer-cycle window so the spectrum is clean.
            # Pad / replicate beyond n_ic to keep array lengths consistent.
            def _lpf(sig):
                s = sig[:n_ic] - np.mean(sig[:n_ic])
                S = np.fft.rfft(s)
                freqs = np.fft.rfftfreq(n_ic, d=dt)
                S[freqs > f_cut] = 0.0   # ideal LPF (zero-phase, brick-wall)
                filt = np.fft.irfft(S, n=n_ic).real + np.mean(sig[:n_ic])
                # Pad back to full length if signal was longer
                if len(sig) > n_ic:
                    out = np.empty_like(sig)
                    out[:n_ic] = filt
                    out[n_ic:] = filt[-1]   # hold last value (won't be used)
                    return out
                return filt
            I_smoothed      = _lpf(base["I"])
            I_mag_smoothed  = _lpf(I_mag)
            H_true_smoothed = (N1 * I_mag_smoothed) / le
        except Exception:
            I_smoothed = I_mag_smoothed = H_true_smoothed = None

    # ── L from phasor (magnitude-only, always ≥ 0) ────────────────────────
    # Uses V and I_mag directly: L = |V|/(ω·|I_mag|)
    # This is the textbook open-circuit / no-load inductance measurement.
    L_phasor = np.nan
    if omega > 0 and abs(Imag_ph) > 1e-10:
        L_phasor = float(abs(V_ph) / (omega * abs(Imag_ph)))

    # ── L from complex permeability (includes core phase info) ────────────
    mu_prime = mu_dbl_prime = tan_delta = L_mu = np.nan
    if abs(Hm_ph) > 1e-10:
        mu_c         = B_ph / (mu0 * Hm_ph)
        mu_prime     = float(mu_c.real)
        mu_dbl_prime = float(abs(mu_c.imag))
        if abs(mu_prime) > 1e-10:
            tan_delta = mu_dbl_prime / abs(mu_prime)
        # L from real part of μ (energy-storage component only)
        L_mu = N1**2 * Ae * abs(mu_prime) * mu0 / le

    # ── Energy-based L cross-check ────────────────────────────────────────
    # For a pure inductor at one frequency: V = L·dI/dt, so
    #   V·I = d/dt[½·L·I²]  →  ∫(V·I − P_avg) dt = ½·L·I² + const
    # where P_avg = mean(V·I) is the real power (zero for lossless L, nonzero
    # with core loss). We must remove that DC before integrating — otherwise
    # any real-power component creates a linear ramp in W(t) that dominates
    # W_pp and corrupts the result.
    #
    # For non-sinusoidal drive (square → triangular I), we first bandpass-
    # filter to the fundamental so V and I are both sinusoidal at ω. This
    # makes the V·I = d/dt[½·L·I²] identity exact.
    L_energy = np.nan
    try:
        if n_ic > 8 and n_cycles >= 1:
            v_seg  = base["V"][:n_ic] - np.mean(base["V"][:n_ic])
            im_seg = I_mag[:n_ic]    - np.mean(I_mag[:n_ic])
            # Keep only fundamental bin — eliminates harmonics so identity holds
            V_spec  = np.fft.rfft(v_seg)
            Im_spec = np.fft.rfft(im_seg)
            k_f = n_cycles if n_cycles < len(V_spec) else int(np.argmax(np.abs(V_spec[1:]))) + 1
            V_fund_spec  = np.zeros_like(V_spec)
            Im_fund_spec = np.zeros_like(Im_spec)
            V_fund_spec[k_f]  = V_spec[k_f]
            Im_fund_spec[k_f] = Im_spec[k_f]
            v_fund  = np.fft.irfft(V_fund_spec,  n=n_ic)
            im_fund = np.fft.irfft(Im_fund_spec, n=n_ic)
            # Subtract the DC of v·i (which = P_avg, the real/loss component)
            # before integrating. Leaves only the reactive energy oscillation.
            vi_prod = v_fund * im_fund
            vi_prod -= np.mean(vi_prod)
            W_t  = _cumtrap(vi_prod, dt)
            W_pp = float(np.nanmax(W_t) - np.nanmin(W_t))
            Im_fund_pk = float(np.nanmax(np.abs(im_fund)))
            if Im_fund_pk > 1e-6:
                # ∫(V·I − P_avg) dt swings between 0 and ½·L·I_pk²
                # → pk-pk = ½·L·I_pk²  → L = 2·W_pp / I_pk²
                L_energy = 2.0 * W_pp / (Im_fund_pk ** 2)
    except Exception:
        pass

    # ── L from V/(dI/dt) during flat-V regions (slope method) ─────────────
    # For square-wave drive: during flat-V half-cycle, V = L·dI/dt
    # Most accurate for square-wave-driven inductors; insensitive to phase.
    L_slope = np.nan
    try:
        V_seg = base["V"]
        di_dt = np.gradient(I_mag, dt)
        v_flat_thr = 0.7 * np.nanmax(np.abs(V_seg))
        di_thr     = 0.02 * np.nanmax(np.abs(di_dt))
        valid = (np.abs(V_seg) > v_flat_thr) & (np.abs(di_dt) > di_thr)
        if np.any(valid):
            L_samples = V_seg[valid] / di_dt[valid]
            # Take absolute value then median — handles both polarities
            L_slope = float(np.nanmedian(np.abs(L_samples)))
    except Exception:
        pass

    # ── L from harmonic-fit (weighted least-squares over harmonics) ───────
    # For an ideal inductor at any frequency: V_n = jωₙ·L·I_n
    # so each harmonic n with significant SNR gives an L estimate:
    #   L_n = Im(V_n / I_n) / ωₙ
    # The fundamental-only methods above ignore information that's actually
    # there in the higher harmonics. A weighted average using |V_n|² as
    # weights (so dominant harmonics matter most) gives a more accurate L
    # for non-sinusoidal drives.
    #
    # Side benefit: per-harmonic L values reveal frequency-dependent μ.
    # If L_n drifts with n, μ' is varying over the drive's harmonic span —
    # a real physical effect for ferrites near rolloff.
    L_harmfit = np.nan
    L_per_harmonic = []      # list of (n, freq_Hz, L_n_uH, |V_n|_V) for diagnostics
    try:
        if n_ic >= 8 and n_cycles >= 1:
            v_seg  = base["V"][:n_ic] - np.mean(base["V"][:n_ic])
            im_seg = I_mag[:n_ic]    - np.mean(I_mag[:n_ic])
            V_spec  = np.fft.rfft(v_seg)
            Im_spec = np.fft.rfft(im_seg)
            f_bin = 1.0 / (n_ic * dt)   # Hz per bin
            # Reference fundamental magnitude for SNR threshold
            V_fund_mag = abs(V_spec[n_cycles]) if n_cycles < len(V_spec) else 0.0
            if V_fund_mag > 0:
                # Walk through harmonics 1, 2, 3, ..., up to ~15 or Nyquist/2,
                # keep those with |V_n| above 5% of fundamental (well above
                # noise) and reasonable |I_n| (avoid divide-by-tiny).
                L_vals = []; weights = []
                for harm in range(1, 16):
                    k = harm * n_cycles
                    if k >= len(V_spec): break
                    Vk_mag = abs(V_spec[k]); Ik_mag = abs(Im_spec[k])
                    # SNR gate
                    if Vk_mag < 0.05 * V_fund_mag: continue
                    if Ik_mag < 1e-12: continue
                    omega_k = 2.0 * np.pi * harm * n_cycles * f_bin
                    if omega_k <= 0: continue
                    Z_k = V_spec[k] / Im_spec[k]
                    L_k = Z_k.imag / omega_k
                    # Reject obviously bad estimates (negative or huge spread
                    # vs fundamental L). Negative L_k means this harmonic is
                    # dominated by capacitive parasitic — exclude it.
                    if L_k <= 0: continue
                    L_vals.append(L_k)
                    weights.append(Vk_mag ** 2)
                    L_per_harmonic.append(
                        (harm, harm * n_cycles * f_bin, L_k * 1e6, Vk_mag * 2.0 / n_ic))
                if L_vals:
                    L_vals_arr = np.array(L_vals)
                    w_arr      = np.array(weights)
                    L_harmfit  = float(np.sum(w_arr * L_vals_arr) / np.sum(w_arr))
    except Exception:
        pass

    # ── Primary L reading: prefer phasor (most accurate for sinusoidal),
    #    fall back to slope (best for square-wave), fall back to energy ───
    if np.isfinite(L_phasor) and L_phasor > 0:
        L_true_peak = L_phasor
    elif np.isfinite(L_slope) and L_slope > 0:
        L_true_peak = L_slope
    elif np.isfinite(L_energy) and L_energy > 0:
        L_true_peak = L_energy
    else:
        L_true_peak = np.nan

    # Per-winding phase angles (degrees) relative to V_primary fundamental
    def _phase_deg(v_ph, i_ph):
        if abs(v_ph) < 1e-10 or abs(i_ph) < 1e-10: return np.nan
        return float(np.degrees(np.angle(v_ph / i_ph)))

    phi_I1   = _phase_deg(V_ph, I1_ph)
    phi_I2   = _phase_deg(V_ph, I2_ph) if n2 else np.nan
    phi_I3   = _phase_deg(V_ph, I3_ph) if n3 else np.nan
    phi_Imag = _phase_deg(V_ph, Imag_ph)

    # Per-winding real power from phasors (phase-correct even for reactive loads)
    def _phasor_P(v_ph, i_ph):
        if abs(v_ph) < 1e-10 or abs(i_ph) < 1e-10: return 0.0
        return float((v_ph * i_ph.conjugate()).real) * 0.5

    P1_ph = _phasor_P(V_ph, I1_ph)
    P2_ph = _phasor_P(V_ph * (n2/N1) if n2 else complex(0), I2_ph)
    P3_ph = _phasor_P(V_ph * (n3/N1) if n3 else complex(0), I3_ph)

    # ── Time-domain μr' and L arrays for PLOTTING ONLY ────────────────────
    # These go NaN near zero crossings — they are for visualisation, not
    # for scalar readouts. Scalar readouts use the phasor above.
    B_pk      = max(float(np.nanmax(np.abs(base["B"]))), 1e-10)
    Imag_pk   = max(float(np.nanmax(np.abs(I_mag))),     1e-10)
    H_true_pk = max(float(np.nanmax(np.abs(H_true))),    1e-10)
    I1_pk     = max(float(np.nanmax(np.abs(base["I"]))), 1e-10)

    # Use tighter peak-region masks so |I_mag| being tiny after subtraction
    # doesn't explode L_true/μ_true into NaN everywhere
    imag_thresh = max(0.15 * Imag_pk, 0.02 * I1_pk)
    h_thresh    = max(0.15 * H_true_pk, 1.0)
    b_thresh    = 0.15 * B_pk
    mask_true   = (np.abs(I_mag) > imag_thresh) & (np.abs(base["B"]) > b_thresh)

    H_true_safe = np.where(mask_true & (np.abs(H_true) > h_thresh), H_true, np.nan)
    Imag_safe   = np.where(mask_true & (np.abs(I_mag)  > imag_thresh), I_mag, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        mu_true = np.where(np.isfinite(H_true_safe),
                           base["B"] / (mu0 * H_true_safe), np.nan)
        # IMPORTANT: use |I_mag| in denominator to keep L_true ≥ 0 for display.
        # Sign of L is not physically meaningful — the 90° B/I phase makes
        # instantaneous B/I sign-flip during a cycle. Scalar readout comes
        # from the phasor path above which is inherently positive.
        L_true  = np.where(np.isfinite(Imag_safe),
                           N1 * Ae * np.abs(base["B"]) / np.abs(Imag_safe), np.nan)

    mu_true_peak = abs(mu_prime) if np.isfinite(mu_prime) else \
                   float(np.nanmedian(mu_true[mask_true])) \
                   if np.any(np.isfinite(mu_true[mask_true])) else np.nan
    reluc_true   = (N1**2 / L_true_peak) \
                   if (np.isfinite(L_true_peak) and L_true_peak > 0) else np.nan

    # Per-winding instantaneous power (time-domain, for plots)
    P2 = base["V"] * (n2 / N1) * I2 if n2 else np.zeros(n)
    P3 = base["V"] * (n3 / N1) * I3 if n3 else np.zeros(n)

    # ── Flux linkage λ(t) = N·Φ = ∫V dt over capture, in V·s ──────────────
    # Slope of λ-vs-I_mag = L directly, no N or Ae factor needed.
    # We already have B(t) computed in base, so λ = N1·Ae·B.
    flux_linkage_Vs = N1 * Ae * base["B"]   # Wb-turns = V·s

    # ── Loss separation ───────────────────────────────────────────────────
    # P_total at primary terminals = real power into the coil
    #   P_total = ½·Re[V·I*] (phasor) — already computed as P1_ph
    # P_cu (copper) = I_rms² · R_winding   — resistive loss in primary copper
    # P_core = (P_total − P_cu) − reflected secondary load
    #
    # NOTE on sign conventions for loaded mode:
    # P_total = P_cu + P_core + P_reflected_secondary.
    # In open-secondary mode, P_reflected = 0, so P_core = P_total − P_cu.
    # In loaded mode we don't subtract reflected here because we don't know
    # if I2/I3 channels are inverted relative to load polarity. The status
    # bar / decomp window labels these accordingly.
    P_total_W = float(P1_ph)
    P_cu_W   = np.nan
    P_core_W = np.nan
    I1_rms = float(np.sqrt(np.mean(base["I"]**2))) if len(base["I"]) > 0 else np.nan
    if R_winding is not None and R_winding > 0 and np.isfinite(I1_rms):
        P_cu_W   = float(I1_rms ** 2 * R_winding)
        # In open-secondary, reflected load = 0, so this is exactly the core
        # loss. In loaded mode, the user will see P_core inflated by the
        # secondary load — useful for comparison but not pure core loss.
        if open_sec:
            P_core_W = float(P_total_W - P_cu_W)
        else:
            # Loaded mode: subtract the *measured* reflected secondary real
            # power so what's left is core + tertiary + cu_residual
            P_ref_secondary = float(P2_ph + P3_ph)   # phasor, sign-correct
            P_core_W = float(P_total_W - P_cu_W - P_ref_secondary)

    # Core-loss density in standard SMPS-vendor units (kW/m³ ≡ mW/cm³)
    core_volume_m3 = Ae * le
    P_core_density_kWm3 = (P_core_W / core_volume_m3 / 1000.0) \
                           if (np.isfinite(P_core_W) and core_volume_m3 > 0) else np.nan

    # Steinmetz P_core estimate at the operating point.
    # Convention used here: P [mW/cm³] = k · f[Hz]^α · B_pk[mT]^β.
    # This matches the Magnetics Inc. / Ferroxcube convention. If user's
    # vendor uses kHz or different B units they'll need to convert k.
    P_steinmetz_W = np.nan
    f_fund = _est_freq(base["V"], dt)
    if (sm_k is not None and sm_a is not None and sm_b is not None
            and f_fund > 0 and np.isfinite(base["B_peak_mT"])
            and base["B_peak_mT"] > 0 and core_volume_m3 > 0):
        try:
            P_density_mWcm3 = sm_k * (f_fund ** sm_a) * (base["B_peak_mT"] ** sm_b)
            # mW/cm³ × cm³ × 1e-3 = W
            P_steinmetz_W = float(P_density_mWcm3 * core_volume_m3 * 1e6 * 1e-3)
        except Exception:
            pass

    base["decomp"] = {
        "open_secondary": open_sec,
        "I_mag":          I_mag,
        "I_ref2":         I_ref2,
        "I_ref3":         I_ref3,
        "I2":             I2,
        "I3":             I3,
        "H_true":         H_true,
        "mu_true":        mu_true,
        "L_true":         L_true,
        "mask_true":      mask_true,
        "mu_true_peak":   mu_true_peak,
        "mu_prime":       mu_prime,
        "mu_dbl_prime":   mu_dbl_prime,
        "tan_delta":      tan_delta,
        "phi_I1_deg":     phi_I1,
        "phi_I2_deg":     phi_I2,
        "phi_I3_deg":     phi_I3,
        "phi_Imag_deg":   phi_Imag,
        "P1_phasor_W":    P1_ph,
        "P2_phasor_W":    P2_ph,
        "P3_phasor_W":    P3_ph,
        "L_true_peak_uH": L_true_peak * 1e6 if np.isfinite(L_true_peak) else np.nan,
        "L_phasor_uH":    L_phasor    * 1e6 if np.isfinite(L_phasor)    else np.nan,
        "L_slope_uH":     L_slope     * 1e6 if np.isfinite(L_slope)     else np.nan,
        "L_energy_uH":    L_energy    * 1e6 if np.isfinite(L_energy)    else np.nan,
        "L_mu_uH":        L_mu        * 1e6 if np.isfinite(L_mu)        else np.nan,
        "L_harmfit_uH":   L_harmfit   * 1e6 if np.isfinite(L_harmfit)   else np.nan,
        "L_per_harmonic": L_per_harmonic,   # list of (n, freq_Hz, L_uH, |V_n|)
        "reluc_true_MA":  reluc_true / 1e6   if np.isfinite(reluc_true)  else np.nan,
        "P2_inst":        P2,
        "P3_inst":        P3,
        "P2_avg_W":       float(np.mean(P2)),
        "P3_avg_W":       float(np.mean(P3)),
        "N2": n2, "N3": n3,
        "Imag_ripple_A": float(np.nanmax(I_mag) - np.nanmin(I_mag)),
        "n_cycles": n_cycles,
        # Smoothed arrays for BH-loop visualization (None when filter off)
        "I_smoothed":       I_smoothed,
        "I_mag_smoothed":   I_mag_smoothed,
        "H_true_smoothed":  H_true_smoothed,
        "bh_smooth_factor": bh_smooth_factor if bh_smooth_factor is not None else np.nan,
        # New fields for loss separation and ∫Vdt-vs-I plot
        "flux_linkage_Vs":      flux_linkage_Vs,
        "I1_rms_A":             I1_rms,
        "R_winding_ohm":        float(R_winding) if (R_winding is not None and R_winding > 0) else np.nan,
        "P_total_W":            P_total_W,
        "P_cu_W":               P_cu_W,
        "P_core_W":             P_core_W,
        "P_core_density_kWm3":  P_core_density_kWm3,
        "P_steinmetz_W":        P_steinmetz_W,
        "f_fund_Hz":            f_fund,
    }
    return base


def _est_freq(y, dt):
    n = len(y)
    if n < 8 or dt <= 0: return 0.0
    Y     = np.abs(np.fft.rfft((y - np.mean(y)) * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, d=dt)
    return float(freqs[np.argmax(Y[1:]) + 1])
