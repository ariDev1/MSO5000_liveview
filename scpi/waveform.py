# scpi/waveform.py

import os
import time
import csv
import math
import numpy as np
import app.app_state as app_state

from utils.debug import log_debug
from config import WAV_POINTS
from scpi.interface import safe_query, scpi_lock
from scpi.power_formulas import compute_power_standard, compute_power_rms_cos_phi


def _normalize_channel(ch):
    """Consistent channel normalization across all functions."""
    s = str(ch).strip().upper()
    if s.startswith("CHAN") or s.startswith("MATH"):
        return s
    return f"CHAN{s}"


def _fetch_wave(scope, channel: str, use_raw: bool):
    """
    Unified waveform fetch function with consistent scaling between NORM and RAW modes.
    Returns (t, y_volts, xinc) for the given channel.
    """
    RAW_MAX_POINTS = int(os.getenv("RAW_MAX_POINTS", "5000000"))
    
    old_timeout = getattr(scope, "timeout", None)
    old_chunk = getattr(scope, "chunk_size", None)

    try:
        with scpi_lock:
            # Query channel settings for validation; skip for MATH sources
            is_math = channel.startswith("MATH")
            if not is_math:
                chan_scale = float(safe_query(scope, f":{channel}:SCALe?", "1.0"))
                chan_offset = float(safe_query(scope, f":{channel}:OFFSet?", "0.0"))
            else:
                chan_scale = 1.0
                chan_offset = 0.0
            
            scope.write(":WAV:FORM BYTE")

            if use_raw:
                # RAW mode: stop scope and optimize I/O
                try: 
                    scope.write(":STOP")
                    time.sleep(0.1)
                except Exception: 
                    pass
                    
                # Increase timeout and chunk size for large transfers
                try:
                    if old_timeout is None or old_timeout < 180000:
                        scope.timeout = 180000
                    if old_chunk is None or old_chunk < 8 * 1024 * 1024:
                        scope.chunk_size = 8 * 1024 * 1024
                except Exception:
                    pass

                scope.write(":WAV:MODE RAW")
                scope.write(":WAV:POIN:MODE RAW")
                scope.write(f":WAV:SOUR {channel}")

                # Request maximum points, then cap if needed
                scope.write(":WAV:POIN 25000000")
                try:
                    accepted = int(scope.query(":WAV:POIN?"))
                    req = min(accepted, RAW_MAX_POINTS)
                    if req != accepted:
                        scope.write(f":WAV:POIN {req}")
                except Exception:
                    pass
            else:
                # NORM mode with correct point mode
                scope.write(":WAV:MODE NORM")
                scope.write(":WAV:POIN:MODE NORM")
                scope.write(f":WAV:POIN {WAV_POINTS}")
                scope.write(f":WAV:SOUR {channel}")

            # Robust PRE query with validation
            pre_data = None
            for attempt in range(3):
                try:
                    scope.query(":WAV:PRE?")  # Prime the query
                    time.sleep(0.1 if use_raw else 0.05)
                    
                    pre = scope.query(":WAV:PRE?").split(",")
                    
                    if len(pre) >= 10:
                        xinc = float(pre[4])
                        xorig = float(pre[5]) 
                        yinc = float(pre[7])
                        yorig = float(pre[8])
                        yref = float(pre[9])
                        
                        # Validate PRE data
                        if (xinc > 0 and abs(yinc) > 1e-12 and 
                            0 <= yref <= 255 and abs(yorig) < 1e6):
                            pre_data = (xinc, xorig, yinc, yorig, yref)
                            break
                        else:
                            log_debug(f"Invalid PRE attempt {attempt+1}: xinc={xinc}, yinc={yinc}, yref={yref}")
                            
                except Exception as e:
                    log_debug(f"PRE query attempt {attempt+1} failed: {e}")
                    time.sleep(0.05)
            
            if pre_data is None:
                log_debug("Failed to get valid PRE data")
                return None, None, None
                
            xinc, xorig, yinc, yorig, yref = pre_data

            # Debug logging
            log_debug(f"{channel} {'RAW' if use_raw else 'NORM'} PRE: xinc={xinc:.2e}, yinc={yinc:.2e}, yref={yref}, yorig={yorig:.2e}")
            if not is_math:
                log_debug(f"{channel} Settings: scale={chan_scale}V/div, offset={chan_offset}V")

            # Fetch waveform data
            t0 = time.time()
            raw = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)
            dt = time.time() - t0

        if raw is None or len(raw) == 0:
            return None, None, None

        # Log transfer performance for RAW mode
        if use_raw:
            try:
                mb = len(raw) / (1024.0 * 1024.0)
                rate = (mb / dt) if dt > 0 else 0.0
                log_debug(f"RAW/{channel}: {len(raw)} pts ({mb:.1f} MiB) in {dt:.2f}s -> {rate:.2f} MiB/s")
            except Exception:
                pass

        # Convert to voltage with validation
        t = xorig + np.arange(len(raw)) * xinc
        y = (raw.astype(np.float64) - yref) * yinc + yorig
        
        # Sanity check: compare with expected range (skip for MATH channels)
        if not is_math:
            expected_range = chan_scale * 8  # ±4 divisions
            actual_range = np.ptp(y)
            scale_ratio = actual_range / expected_range if expected_range > 0 else 1.0
            
            log_debug(f"{channel} Range: expected~{expected_range:.3f}V, actual={actual_range:.3f}V, ratio={scale_ratio:.3f}")
            
            if scale_ratio > 10 or scale_ratio < 0.1:
                log_debug(f"Suspicious scaling for {channel} - ratio {scale_ratio:.3f}")
        
        return t, y, xinc

    except Exception as e:
        log_debug(f"_fetch_wave({channel}, RAW={use_raw}) failed: {e}")
        return None, None, None

    finally:
        # Restore I/O settings and resume acquisition
        try:
            if use_raw:
                if old_timeout is not None: 
                    scope.timeout = old_timeout
                if old_chunk is not None: 
                    scope.chunk_size = old_chunk
                try: 
                    scope.write(":RUN")
                except Exception: 
                    pass
        except Exception:
            pass

def get_channel_waveform_data(scope, channel, use_simple_calc=True, retries=1):
    """
    Get basic waveform statistics for a channel.
    """
    chan = _normalize_channel(channel)

    for attempt in range(1, retries + 2):
        try:
            if safe_query(scope, f":{chan}:DISP?") != "1":
                log_debug(f"Channel {chan} not displayed")
                return None, None, None

            # Use unified fetch function
            t, volts, xinc = _fetch_wave(scope, chan, use_raw=False)
            if volts is None or len(volts) == 0:
                log_debug(f"Empty waveform on attempt {attempt} for {chan}")
                continue

            vpp = volts.max() - volts.min()
            vavg = volts.mean()
            vrms = np.sqrt(np.mean(np.square(volts)))
            return vpp, vavg, vrms

        except Exception as e:
            log_debug(f"Attempt {attempt} failed for {chan}: {e}")
            time.sleep(0.3)

    log_debug(f"All waveform fetch attempts failed for {chan}")
    return None, None, None

def fetch_waveform_with_fallback(scope, chan, retries=1):

    def try_fetch(mode_label):
        try:
            with scpi_lock:
                scope.write(":WAV:FORM BYTE")
                scope.write(f":WAV:MODE {mode_label}")
                scope.write(":WAV:POIN:MODE RAW")
                scope.write(f":WAV:POIN {WAV_POINTS}")
                scope.write(f":WAV:SOUR {chan}")
                scope.query(":WAV:PRE?")
                time.sleep(0.1)
                pre = scope.query(":WAV:PRE?").split(",")
                xinc  = float(pre[4])
                xorig = float(pre[5])
                yinc  = float(pre[7])
                yorig = float(pre[8])
                yref  = float(pre[9])

                # Optional: what the scope actually accepted
                try:
                    accepted = int(scope.query(":WAV:POIN?"))
                except Exception:
                    accepted = None

                # Timed binary transfer
                t0  = time.time()
                raw = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)
                dt  = time.time() - t0

                # Throughput / size log
                try:
                    pts   = int(len(raw))
                    mb    = getattr(raw, "nbytes", pts) / (1024.0 * 1024.0)
                    rate  = (mb / dt) if dt > 0 else 0.0
                    io_to = getattr(scope, "timeout", None)
                    io_cs = getattr(scope, "chunk_size", None)
                    req   = WAV_POINTS  # what we asked for in this call

                    if accepted is not None:
                        log_debug(f"⏬ {mode_label}/{chan}: {pts} pts ({mb:.1f} MiB) in {dt:.2f}s → {rate:.2f} MiB/s; requested={req}, accepted={accepted}, chunk={io_cs}, timeout={io_to}ms")
                    else:
                        log_debug(f"⏬ {mode_label}/{chan}: {pts} pts ({mb:.1f} MiB) in {dt:.2f}s → {rate:.2f} MiB/s; requested={req}, chunk={io_cs}, timeout={io_to}ms")
                except Exception:
                    pass

                # Small safety guard
                if raw is None or len(raw) == 0:
                    log_debug(f"⚠️ {mode_label}/{chan}: empty DATA block")
                    return [], xinc, xorig, yinc, yorig, yref

                return raw, xinc, xorig, yinc, yorig, yref

        except Exception as e:
            log_debug(f"❌ {mode_label} fetch failed: {e}")
            return None
        

    #Disable RAW completely during long-time logging
    if app_state.is_logging_active:
        log_debug("⚠️ Skipping RAW mode during long-time logging")
        app_state.raw_mode_failed_once = True  # avoid future RAW attempts

    # --- Try RAW mode ---
    if not app_state.raw_mode_failed_once:
        for attempt in range(retries):
            result = try_fetch("RAW")
            if result is None or len(result[0]) < WAV_POINTS * 0.8:
                log_debug(f"⚠️ RAW attempt {attempt+1} failed or incomplete")
                continue
            return result
        log_debug("⚠️ RAW mode failed — fallback to NORM")
        app_state.raw_mode_failed_once = True

    # --- Always fallback to NORM ---
    result = try_fetch("NORM")
    if result:
        return result
    else:
        raise RuntimeError("🛑 Both RAW and NORM fetch failed")
        
def export_channel_csv(scope, channel, outdir="oszi_csv", retries=2):
    """
    Export channel waveform to CSV file.
    """
    # Normalize channel name consistently
    chan = _normalize_channel(channel)
    is_math = chan.startswith("MATH")

    for attempt in range(1, retries + 2):
        try:
            # Use unified fetch function (NORM mode for CSV export)
            t, volts, xinc = _fetch_wave(scope, chan, use_raw=False)
            
            if volts is None or len(volts) == 0:
                log_debug(f"Empty waveform data on attempt {attempt} for {chan}")
                continue

            # Get probe factor (skip for MATH channels)
            if is_math:
                probe = 1.0
            else:
                probe = float(safe_query(scope, f":{chan}:PROB?", "1.0"))

            # Prepare output path
            os.makedirs(outdir, exist_ok=True)
            timestamp = time.strftime("%Y-%m-%dT%H-%M-%S")
            filename = f"{chan}_{timestamp}.csv"
            path = os.path.join(outdir, filename)

            # Write CSV with metadata
            with open(path, "w", newline="") as f:
                f.write(f"# Device: {safe_query(scope, '*IDN?', 'Unknown')}\n")
                f.write(f"# Channel: {chan}\n")
                f.write(f"# Timebase: {safe_query(scope, ':TIMebase:SCALe?', 'N/A')} s/div\n")
                f.write(f"# Scale: {safe_query(scope, f':{chan}:SCALe?', 'N/A')} V/div\n")
                f.write(f"# Offset: {safe_query(scope, f':{chan}:OFFSet?', 'N/A')} V\n")
                f.write(f"# Trigger: {safe_query(scope, ':TRIGger:STATus?', 'N/A')}\n")
                f.write(f"# Probe: {probe}x\n")
                f.write(f"# Timestamp: {timestamp}\n")
                
                writer = csv.writer(f)
                writer.writerow(["Time (s)", "Voltage (V)"])
                writer.writerows(zip(t, volts))

            log_debug(f"Exported {chan} waveform to {path}")
            return path

        except Exception as e:
            log_debug(f"Export attempt {attempt} failed for {chan}: {e}")
            time.sleep(0.3)

    log_debug(f"All export attempts failed for {chan}")
    return None


def compute_power_from_scope(scope, voltage_ch, current_ch, remove_dc=True, 
                           current_scale=1.0, use_25m_v=False, use_25m_i=False, 
                           method="standard"):
    """
    Compute power analysis from voltage and current channels.
    """
    chan_v = _normalize_channel(voltage_ch)
    chan_i = _normalize_channel(current_ch)

    log_debug(f"Power method: {method}")
    log_debug(f"Analyzing: Voltage = {chan_v}, Current = {chan_i}")

    # Determine current scaling based on unit
    unit_i = safe_query(scope, f":{chan_i}:UNIT?", "VOLT").strip().upper()
    scale_req = float(current_scale or 1.0)

    if unit_i == "AMP":
        # Apply user scale/correction in AMP mode (so we can emulate mV/A in software)
        scale_eff = scale_req
        if abs(scale_eff - 1.0) > 1e-12:
            log_debug(f"{chan_i} UNIT=A — applying amp-correction ×{scale_eff:.6g} (from Value/Corr)")
    else:
        # VOLT mode: scale is A/V (from Value/Corr)
        scale_eff = scale_req

    log_debug(f"Current UNIT = {unit_i} | effective scale = {scale_eff:.6g} {'(A correction)' if unit_i=='AMP' else 'A/V'}")

    # Fetch both channels using unified function
    t_v, yv, xinc_v = _fetch_wave(scope, chan_v, use_25m_v)
    t_i, yi, xinc_i = _fetch_wave(scope, chan_i, use_25m_i)

    if t_v is None or t_i is None:
        log_debug("Empty waveform(s) - abort")
        return None

    # Log pre-scale current analysis
    i_vrms_volt = float(np.sqrt(np.mean((yi - np.mean(yi))**2)))
    i_peak_volt = float(np.ptp(yi))
    unit_label = "A" if unit_i == "AMP" else "V"
    log_debug(f"{chan_i} pre-scale: Vrms={i_vrms_volt:.6g}{unit_label}, Vpp={i_peak_volt:.6g}{unit_label}")

    # Convert current to amps
    i = yi * scale_eff
    v = yv

    # Log post-scale current
    i_rms_amp = float(np.sqrt(np.mean((i - np.mean(i))**2)))
    log_debug(f"{chan_i} post-scale: Irms={i_rms_amp:.6g}A (scale factor={scale_eff:.6g})")

    # Align timebases if needed
    tol = max(1e-15, 1e-9 * max(xinc_v, xinc_i))
    same_len = (len(v) == len(i))
    same_xinc = (abs(xinc_v - xinc_i) <= tol)
    same_xorg = (abs(t_v[0] - t_i[0]) <= (xinc_v + xinc_i))

    if not (same_len and same_xinc and same_xorg):
        log_debug("Aligning voltage and current timebases...")
        t0 = max(t_v[0], t_i[0])
        t1 = min(t_v[-1], t_i[-1])
        if not (np.isfinite(t0) and np.isfinite(t1) and (t1 > t0)):
            log_debug("No valid time overlap - abort")
            return None
        N = max(8, min(len(v), len(i)))
        t = np.linspace(t0, t1, N)
        v = np.interp(t, t_v, v)
        i = np.interp(t, t_i, i)
        xinc_eff = (t[-1] - t[0]) / (len(t) - 1)
    else:
        t = t_v
        xinc_eff = xinc_v

    # Optional DC removal
    if remove_dc:
        v_dc = np.mean(v)
        i_dc = np.mean(i)
        v = v - v_dc
        i = i - i_dc
        log_debug(f"DC removed: V_dc={v_dc:.6g}V, I_dc={i_dc:.6g}A")

    # Calculate power metrics
    Vrms = float(np.sqrt(np.mean(v**2)))
    Irms = float(np.sqrt(np.mean(i**2)))
    S = Vrms * Irms

    # Compute instantaneous and average power
    if method == "standard":
        p_inst, P = compute_power_standard(v, i, xinc_eff)
    elif method == "rms_cos_phi":
        p_inst, P = compute_power_rms_cos_phi(v, i, xinc_eff)
    else:
        raise ValueError(f"Unsupported power method: {method}")

    # PF and phase magnitude from P and S
    PF = 0.0 if S == 0 else math.copysign(abs(P / S), P)
    try:
        phase_rad = math.acos(max(0.0, min(1.0, abs(PF))))
    except ValueError:
        phase_rad = 0.0
    phase_deg = math.degrees(phase_rad)

    # --- Signed Q using fundamental phase (robust & wrap-safe) ---
    try:
        # Window the sequences for a stable fundamental phase (no impact on P/S magnitudes).
        w = np.hanning(len(v))
        vw = v * w
        iw = i * w

        # FFT of windowed signals
        Vf = np.fft.rfft(vw)
        If = np.fft.rfft(iw)
        freqs = np.fft.rfftfreq(len(vw), d=xinc_eff)

        # Lock to mains fundamental: prefer ~50 Hz, then ~60 Hz (narrow ±3 Hz window)
        k = None
        for f0 in (50.0, 60.0):
            band = (freqs >= f0 - 3.0) & (freqs <= f0 + 3.0)
            if np.any(band):
                band_idx = np.where(band)[0]
                # Choose the strongest voltage line in that band (exclude DC by construction)
                k = band_idx[np.argmax(np.abs(Vf[band]))]
                break

        # Fallback: previous “largest non-DC anywhere” behavior if fundamental window missing
        if k is None:
            k = 1 + np.argmax(np.abs(Vf[1:])) if len(Vf) > 2 else 1

        # Wrap-safe phase via cross-spectrum; φ = angle(V·I*)  (I lags → φ>0 inductive; I leads → φ<0 capacitive)
        phi = np.angle(Vf[k] * np.conj(If[k]))
        sign_q = 1.0 if phi >= 0 else -1.0

    except Exception:
        # Conservative default if anything above fails
        sign_q = 1.0

    Q = sign_q * S * math.sin(phase_rad)
    phase_deg_signed = phase_deg if sign_q >= 0 else -phase_deg


    log_debug(f"Results: P={P:.6g}W | S={S:.6g}VA | Q={Q:.6g}VAr | PF={PF:.6g} | angle={phase_deg_signed:.4g}° ({'inductive' if sign_q >= 0 else 'capacitive'})")
    scale_label = "A-corr" if unit_i == "AMP" else "A/V"
    log_debug(f"Final: Vrms={Vrms:.6g}V | Irms={Irms:.6g}A | scale_used={scale_eff:.6g}{scale_label}")

    return {
        "Time": t,
        "Voltage": v,
        "Current": i,
        "Power": p_inst,
        "Real Power (P)": P,
        "Apparent Power (S)": S,
        "Reactive Power (Q)": Q,
        "Power Factor": PF,
        "Phase Angle (deg)": phase_deg_signed,
        "Vrms": Vrms,
        "Irms": Irms,
    }
