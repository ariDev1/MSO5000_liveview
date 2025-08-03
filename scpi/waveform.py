# scpi/waveform.py

import os
import time
import csv
import math
import numpy as np
from utils.debug import log_debug, set_debug_level
from config import WAV_POINTS
from scpi.interface import safe_query
from scpi.interface import scpi_lock
from scpi.power_formulas import compute_power_standard, compute_power_rms_cos_phi

def fetch_waveform_with_fallback(scope, chan, retries=1):
    import app.app_state as app_state

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
                xinc = float(pre[4])
                xorig = float(pre[5])
                yinc = float(pre[7])
                yorig = float(pre[8])
                yref = float(pre[9])
                raw = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)
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
    from .interface import scpi_lock, safe_query
    import numpy as np
    import os, time, csv
    from utils.debug import log_debug
    from config import WAV_POINTS

    chan = channel if str(channel).startswith("MATH") else f"CHAN{channel}"
    
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
                    scope.query(":WAV:PRE?")  # Rigol quirk workaround
                    time.sleep(0.1)

                    pre = scope.query(":WAV:PRE?").split(",")
                    xinc = float(pre[4])
                    xorig = float(pre[5])
                    yinc = float(pre[7])
                    yorig = float(pre[8])
                    yref = float(pre[9])
                    probe = float(safe_query(scope, f":{chan}:PROB?", "1.0"))

                    raw = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)
                finally:
                    scope.write(":RUN")
                    log_debug("▶️ Scope acquisition resumed after export")

            if len(raw) == 0:
                log_debug(f"⚠️ Empty waveform data on attempt {attempt} for {chan}")
                continue

            times = xorig + np.arange(len(raw)) * xinc
            volts = ((raw - yref) * yinc + yorig)

            os.makedirs(outdir, exist_ok=True)
            timestamp = time.strftime("%Y-%m-%dT%H-%M-%S")
            filename = f"{chan}_{timestamp}.csv"
            path = os.path.join(outdir, filename)

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
        log_debug(f"⚠️ {chan_i} is in AMP mode, but current_scale = {current_scale:.4f}. Set probe = 1.0", level="FULL")

    log_debug(f"📊 Analyzing: Voltage = {chan_v}, Current = {chan_i}", level="MINIMAL")
    log_debug(f"⚙️ Current scaling factor: {current_scale:.4f} A/V")
    probe_reported = safe_query(scope, f":{chan_i}:PROB?", "1.0")
    log_debug(f"🧪 {chan_i} :PROB? = {probe_reported}")

    if use_25m_v or use_25m_i:
        log_debug("⏸️ Stopping scope for full waveform read")
        scope.write(":STOP")
        time.sleep(0.2)

    def fetch_waveform(channel, use_25m_flag):
        try:
            if use_25m_flag:
                scope.write(":WAV:MODE RAW")
                scope.write(":WAV:FORM BYTE")
                scope.write(":WAV:POIN:MODE RAW")
                scope.write(":WAV:POIN 25000000")
                log_debug("🧪 Fetching 25M samples in RAW mode")
            else:
                scope.write(":WAV:MODE NORM")
                scope.write(":WAV:FORM BYTE")
                scope.write(":WAV:POIN:MODE RAW")
                from config import WAV_POINTS
                scope.write(f":WAV:POIN {WAV_POINTS}")
                log_debug(f"🔹 Fetching {WAV_POINTS} samples in NORM mode")

            scope.write(f":WAV:SOUR {channel}")
            scope.query(":WAV:PRE?")
            time.sleep(0.2)
            pre = scope.query(":WAV:PRE?").split(",")
            xinc = float(pre[4])
            xorig = float(pre[5])
            yinc = float(pre[7])
            yorig = float(pre[8])
            yref = float(pre[9])
            raw = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)

            if use_25m_flag and len(raw) < 18000000:
                log_debug(f"⚠️ Only got {len(raw)} samples — treating as fallback")
                raise RuntimeError("RAW_TOO_SHORT")

            return raw, xinc, xorig, yinc, yorig, yref

        except Exception as e:
            log_debug(f"❌ fetch_waveform() failed for {channel}: {e}")
            return [], 1.0, 0.0, 1.0, 0.0, 0.0
            
    raw_v, xinc, xorig, yinc_v, yorig_v, yref_v = fetch_waveform(chan_v, use_25m_v)
    raw_i, _,    _,     yinc_i, yorig_i, yref_i = fetch_waveform(chan_i, use_25m_i)

    if use_25m_v or use_25m_i:
        scope.write(":RUN")
        log_debug("▶️ Resuming scope acquisition")

    if len(raw_v) == 0 or len(raw_i) == 0:
        log_debug("⚠️ Empty waveform data — aborting power analysis")
        return None

    t = xorig + np.arange(len(raw_v)) * xinc
    v = ((raw_v - yref_v) * yinc_v + yorig_v)
    i = ((raw_i - yref_i) * yinc_i + yorig_i) * current_scale

    if remove_dc:
        v -= np.mean(v)
        i -= np.mean(i)

    if len(v) != len(i):
        log_debug(f"⚠️ Length mismatch: V={len(v)} samples, I={len(i)} samples — resampling")
        if len(v) > len(i):
            v = np.interp(np.linspace(0, len(v)-1, len(i)), np.arange(len(v)), v)
        elif len(i) > len(v):
            i = np.interp(np.linspace(0, len(i)-1, len(v)), np.arange(len(i)), i)

    # Compute FFT and phase info first
    fft_v = np.fft.fft(v)
    fft_i = np.fft.fft(i)
    phase_v = np.angle(fft_v[1])
    phase_i = np.angle(fft_i[1])
    phase_shift_rad = phase_v - phase_i
    phase_shift_deg = (np.rad2deg(phase_shift_rad) + 180) % 360 - 180

    # Always compute RMS values before using them
    Vrms = np.sqrt(np.mean(v**2))
    Irms = np.sqrt(np.mean(i**2))
    S = Vrms * Irms

    # Compute power based on method
    if method == "standard":
        p_inst, P = compute_power_standard(v, i, xinc)
    elif method == "rms_cos_phi":
        p_inst, P = compute_power_rms_cos_phi(v, i, xinc)
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
