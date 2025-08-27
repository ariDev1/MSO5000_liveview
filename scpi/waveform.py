# scpi/waveform.py

import os
import time
import csv
import math
import numpy as np
import app.app_state as app_state

from utils.debug import log_debug, set_debug_level
from config import WAV_POINTS
from scpi.interface import safe_query
from scpi.interface import scpi_lock
from scpi.power_formulas import compute_power_standard, compute_power_rms_cos_phi

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
    Export one channel (CH1..CH4 or MATHn) to CSV.
    - For MATH channels, skip :PROB? (not supported) to avoid 60 s timeouts.
    - All SCPI-critical parts remain under scpi_lock; file I/O is outside.
    """
    from .interface import scpi_lock, safe_query
    import numpy as np
    import os, time, csv
    from utils.debug import log_debug
    from config import WAV_POINTS

    # Normalize to SCPI source name expected by the scope
    is_math = str(channel).upper().startswith("MATH")
    chan = str(channel).upper() if is_math else f"CHAN{int(channel)}"

    for attempt in range(1, retries + 2):
        try:
            with scpi_lock:
                try:
                    scope.write(":STOP")
                    time.sleep(0.2)
                    scope.write(":WAV:FORM BYTE")
                    scope.write(":WAV:MODE NORM")
                    scope.write(":WAV:POIN:MODE RAW")
                    scope.write(f":WAV:POIN {WAV_POINTS}")
                    scope.write(f":WAV:SOUR {chan}")

                    # Rigol quirk: prime header, then read it
                    scope.query(":WAV:PRE?")
                    time.sleep(0.1)
                    pre = scope.query(":WAV:PRE?").split(",")
                    xinc  = float(pre[4]); xorig = float(pre[5])
                    yinc  = float(pre[7]); yorig = float(pre[8]); yref = float(pre[9])

                    # 🔑 Key change: do NOT query :MATHn:PROB?
                    if is_math:
                        probe = 1.0
                    else:
                        probe = float(safe_query(scope, f":{chan}:PROB?", "1.0"))

                    raw = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)

                finally:
                    scope.write(":RUN")
                    log_debug("▶️ Scope acquisition resumed after export")

            if len(raw) == 0:
                log_debug(f"⚠️ Empty waveform data on attempt {attempt} for {chan}")
                continue

            # Convert to engineering units
            times = xorig + np.arange(len(raw)) * xinc
            volts = ((raw - yref) * yinc + yorig)

            # Prepare output path
            os.makedirs(outdir, exist_ok=True)
            timestamp = time.strftime("%Y-%m-%dT%H-%M-%S")
            filename = f"{chan}_{timestamp}.csv"
            path = os.path.join(outdir, filename)

            # Header + data (header uses safe_query; benign if loop is running)
            with open(path, "w", newline="") as f:
                f.write(f"# Device: {safe_query(scope, '*IDN?', 'Unknown')}\n")
                f.write(f"# Channel: {chan}\n")
                f.write(f"# Timebase: {safe_query(scope, ':TIMebase:SCALe?', 'N/A')} s/div\n")
                f.write(f"# Scale: {safe_query(scope, f':{chan}:SCALe?', 'N/A')} V/div\n")
                f.write(f"# Offset: {safe_query(scope, f':{chan}:OFFS?', 'N/A')} V\n")
                f.write(f"# Trigger: {safe_query(scope, ':TRIGger:STATus?', 'N/A')}\n")
                f.write(f"# Timestamp: {timestamp}\n")
                writer = csv.writer(f)
                writer.writerow(["Time (s)", "Voltage (V)"])
                writer.writerows(zip(times, volts))

            log_debug(f"🔍 Probe factor for {chan} = {probe}")
            log_debug(f"✅ Exported {chan} waveform to {path}")
            return path

        except Exception as e:
            log_debug(f"❌ Attempt {attempt} failed for {chan}: {e}")
            time.sleep(0.3)

    log_debug(f"🛑 All attempts failed to export {chan}")
    return None


def get_channel_waveform_data(scope, channel, use_simple_calc=True, retries=1):
    import numpy as np
    from utils.debug import log_debug
    from .interface import scpi_lock, safe_query
    from .waveform import fetch_waveform_with_fallback

    chan = channel if str(channel).startswith("MATH") else f"CHAN{channel}"

    for attempt in range(1, retries + 2):
        try:
            if safe_query(scope, f":{chan}:DISP?") != "1":
                log_debug(f"⚠️ Channel {chan} not displayed")
                return None, None, None

            # Try waveform fetch with fallback logic
            raw, xinc, xorig, yinc, yorig, yref = fetch_waveform_with_fallback(scope, chan)
            if len(raw) == 0:
                log_debug(f"⚠️ Empty waveform on attempt {attempt} for {chan}")
                continue

            volts = (raw - yref) * yinc + yorig
            vpp = volts.max() - volts.min()
            vavg = volts.mean()
            vrms = np.sqrt(np.mean(np.square(volts)))
            return vpp, vavg, vrms

        except Exception as e:
            log_debug(f"❌ Attempt {attempt} failed for {chan}: {e}")
            import time
            time.sleep(0.3)

    log_debug(f"🛑 All waveform fetch attempts failed for {chan}")
    return None, None, None


def compute_power_from_scope(scope, voltage_ch, current_ch, remove_dc=True, current_scale=1.0, use_25m_v=False, use_25m_i=False, method="standard"):
    from scpi.interface import scpi_lock, safe_query
    import numpy as np
    from utils.debug import log_debug
    import math

    chan_v = voltage_ch if str(voltage_ch).startswith("MATH") else f"CHAN{voltage_ch}"
    chan_i = current_ch if str(current_ch).startswith("MATH") else f"CHAN{current_ch}"

    log_debug(f"🧮 Power method: {method}")

    unit_i = safe_query(scope, f":{chan_i}:UNIT?", "VOLT").strip().upper()
    log_debug(f"🧪 {chan_i} UNIT? → {unit_i}")
    if unit_i == "AMP" and current_scale != 1.0:
        log_debug(f"⚠️ {chan_i} is in AMP mode, but current_scale = {current_scale:.4f}. Set probe = 1.0")
    if unit_i == "AMP":
        current_scale = 1.0
        log_debug(f"⚠️ {chan_i} is in AMP mode — forcing current_scale = 1.0 to prevent double-scaling")

    log_debug(f"📊 Analyzing: Voltage = {chan_v}, Current = {chan_i}", level="MINIMAL")
    log_debug(f"⚙️ Current scaling factor: {current_scale:.4f} A/V")
    probe_reported = safe_query(scope, f":{chan_i}:PROB?", "1.0")
    log_debug(f"🧪 {chan_i} :PROB? = {probe_reported}")

    if use_25m_v or use_25m_i:
        log_debug("⏸️ Stopping scope for full waveform read")
        scope.write(":STOP")
        time.sleep(0.2)

    def fetch_waveform(channel, use_25m_flag):
        # Uses outer `scope`, as in your original.
        old_timeout = getattr(scope, "timeout", None)
        old_chunk   = getattr(scope, "chunk_size", None)

        try:
            accepted = None

            if use_25m_flag:
                # Be generous for large transfers (temporary).
                try:
                    scope.timeout = max(scope.timeout, 180000)
                except Exception:
                    pass
                try:
                    scope.chunk_size = max(scope.chunk_size, 16 * 1024 * 1024)
                except Exception:
                    pass

                scope.write(":WAV:MODE RAW")
                scope.write(":WAV:FORM BYTE")
                scope.write(":WAV:POIN:MODE RAW")
                scope.write(":WAV:POIN 25000000")
                # Ask what the scope actually accepted (it may cap this):
                try:
                    accepted = int(scope.query(":WAV:POIN?"))
                    log_debug(f"📝 {channel} accepted points = {accepted}")
                except Exception:
                    accepted = None
                log_debug("🧪 Fetching 25M samples in RAW mode")
            else:
                scope.write(":WAV:MODE NORM")
                scope.write(":WAV:FORM BYTE")
                scope.write(":WAV:POIN:MODE RAW")
                from config import WAV_POINTS
                scope.write(f":WAV:POIN {WAV_POINTS}")
                log_debug(f"🔹 Fetching {WAV_POINTS} samples in NORM mode")

            scope.write(f":WAV:SOUR {channel}")

            # Header twice with a small delay tends to stabilize PRE on MSO5000
            scope.query(":WAV:PRE?")
            time.sleep(0.2)
            pre = scope.query(":WAV:PRE?").split(",")
            xinc  = float(pre[4])
            xorig = float(pre[5])
            yinc  = float(pre[7])
            yorig = float(pre[8])
            yref  = float(pre[9])

            raw = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)

            if use_25m_flag:
                # Decide if RAW is "too short" vs what the scope accepted.
                # If :WAV:POIN? wasn’t available, keep your original ~18M heuristic.
                threshold = int(0.9 * accepted) if (accepted and accepted > 0) else 18_000_000
                if len(raw) < max(1000, threshold):
                    log_debug(f"⚠️ {channel}: got {len(raw)} < {threshold}, falling back to NORM")
                    # Auto-fallback: try again in NORM (no recursion loop when use_25m_flag=False)
                    return fetch_waveform(channel, False)

            return raw, xinc, xorig, yinc, yorig, yref

        except Exception as e:
            log_debug(f"❌ fetch_waveform() failed for {channel}: {e}")
            if use_25m_flag:
                # One graceful retry in NORM before giving up
                log_debug(f"↩️ {channel}: RAW failed — trying NORM fallback")
                try:
                    return fetch_waveform(channel, False)
                except Exception as e2:
                    log_debug(f"❌ NORM fallback failed for {channel}: {e2}")
            return [], 1.0, 0.0, 1.0, 0.0, 0.0

        finally:
            # Restore I/O settings
            try:
                if old_timeout is not None:
                    scope.timeout = old_timeout
                if old_chunk is not None:
                    scope.chunk_size = old_chunk
            except Exception:
                pass

            
    raw_v, xinc_v, xorig_v, yinc_v, yorig_v, yref_v = fetch_waveform(chan_v, use_25m_v)
    raw_i, xinc_i, xorig_i, yinc_i, yorig_i, yref_i = fetch_waveform(chan_i, use_25m_i)


    if use_25m_v or use_25m_i:
        scope.write(":RUN")
        log_debug("▶️ Resuming scope acquisition")

    if len(raw_v) == 0 or len(raw_i) == 0:
        log_debug("⚠️ Empty waveform data — aborting power analysis")
        return None

    # Build raw waveforms (keep original timing)
    v_raw = ((raw_v - yref_v) * yinc_v + yorig_v)
    i_raw = ((raw_i - yref_i) * yinc_i + yorig_i) * current_scale

    # Per-channel time bases
    t_v = xorig_v + np.arange(len(raw_v)) * xinc_v
    t_i = xorig_i + np.arange(len(raw_i)) * xinc_i


    # --- Fast path: if both streams already share the same grid, skip interpolation ---
    same_len  = (len(raw_v) == len(raw_i))
    same_xinc = abs(xinc_v - xinc_i) <= max(1e-15, 1e-9 * xinc_v)
    same_xorg = abs((xorig_v - xorig_i)) <= (xinc_v + xinc_i)

    if same_len and same_xinc and same_xorg:
        t = t_v  # identical to t_i within tolerance
        v = v_raw
        i = i_raw
        xinc_eff = xinc_v
    else:
        # (keep your existing overlap + np.interp() block here)
        t0 = max(t_v[0], t_i[0])
        t1 = min(t_v[-1], t_i[-1])
        if not np.isfinite(t0) or not np.isfinite(t1) or t1 <= t0:
            log_debug("🛑 No valid time overlap between V and I — aborting power analysis")
            return None
        N_common = max(8, min(len(raw_v), len(raw_i)))
        t = np.linspace(t0, t1, N_common)
        v = np.interp(t, t_v, v_raw)
        i = np.interp(t, t_i, i_raw)
        xinc_eff = (t[-1] - t[0]) / (len(t) - 1)


    # Log quick stats on current before any interpolation
    try:
        log_debug(f"🧪 Raw CH3 stats: max = {np.max(i_raw):.4f} A, min = {np.min(i_raw):.4f} A, RMS = {np.sqrt(np.mean(i_raw**2)):.4f} A")
    except Exception:
        pass

    # Optional DC removal (after alignment)
    if remove_dc:
        v -= np.mean(v)
        i -= np.mean(i)

    # Effective dt for integration/FFT
    xinc_eff = (t[-1] - t[0]) / (len(t) - 1)


    # --- Robust & fast phase: dominant spectral bin on decimated copy ---
    # We keep P/S/Q on full v,i; we only decimate for phase detection.
    MAX_PHASE_SAMPLES = 16384

    if len(v) > MAX_PHASE_SAMPLES:
        idx = np.linspace(0, len(v) - 1, MAX_PHASE_SAMPLES).astype(np.int64)
        v_phase = v[idx]
        i_phase = i[idx]
        dt_phase = (t[-1] - t[0]) / (MAX_PHASE_SAMPLES - 1)
    else:
        v_phase = v
        i_phase = i
        dt_phase = xinc_eff

    Vspec = np.fft.rfft(v_phase)
    Ispec = np.fft.rfft(i_phase)
    freqs = np.fft.rfftfreq(len(v_phase), d=dt_phase)

    from scpi.data import scpi_data
    import re

    # Prefer bin nearest the scope’s frequency reference, if present
    k = None
    ref = scpi_data.get("freq_ref")
    if isinstance(ref, str):
        m = re.search(r"([\d.]+)", ref)   # handles "49.999 Hz"
        if m and len(freqs) > 1:
            f_ref = float(m.group(1))
            k = int(np.argmin(np.abs(freqs - f_ref)))

    # Fallback: dominant non-DC bin from V
    if (k is None) or (k <= 0) or (k >= len(freqs)):
        k = 1 + np.argmax(np.abs(Vspec[1:])) if len(Vspec) > 2 else 0

    # dominant non-DC bin from V
    if len(Vspec) > 2:
        k = 1 + np.argmax(np.abs(Vspec[1:]))
    else:
        k = 0

    if k > 0 and k < len(freqs):
        f0 = freqs[k]
        phase_shift_rad = np.angle(Vspec[k]) - np.angle(Ispec[k])
    else:
        f0 = 0.0
        phase_shift_rad = 0.0

    # Normalize to [-180, 180]
    phase_shift_deg = (np.degrees(phase_shift_rad) + 180.0) % 360.0 - 180.0
    log_debug(f"📐 f0≈{f0:.3f} Hz, phase={phase_shift_deg:.2f}°")



    # Always compute RMS values before using them
    Vrms = np.sqrt(np.mean(v**2))
    Irms = np.sqrt(np.mean(i**2))
    S = Vrms * Irms

    # Compute power based on method
    if method == "standard":
        p_inst, P = compute_power_standard(v, i, xinc_eff)
    elif method == "rms_cos_phi":
        p_inst, P = compute_power_rms_cos_phi(v, i, xinc_eff)
    else:
        raise ValueError(f"Unsupported power method: {method}")

    Q = S * np.sin(phase_shift_rad)
    PF = P / S if S != 0 else 0.0
    PF = math.copysign(abs(PF), P)

    log_debug(f"🔢 Received {len(raw_v)} V-samples, {len(raw_i)} I-samples")
    log_debug(f"🧪 Analyzer Vrms = {Vrms:.3f} V — Should match {chan_v}")
    log_debug(f"🧪 Analyzer Irms = {Irms:.3f} A — Should match {chan_i}")
    log_debug(f"📐 Phase shift (v vs i): {phase_shift_deg:.2f}°")

    return {
        "Time": t,
        "Voltage": v,
        "Current": i,
        "Power": p_inst,
        "Real Power (P)": P,
        "Apparent Power (S)": S,
        "Reactive Power (Q)": Q,
        "Power Factor": PF,
        "Phase Angle (deg)": phase_shift_deg,
        "Vrms": Vrms,
        "Irms": Irms
    }
