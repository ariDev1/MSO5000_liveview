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

def export_channel_csv(scope, channel, outdir="oszi_csv"):
    chan = channel if str(channel).startswith("MATH") else f"CHAN{channel}"
    try:
        if safe_query(scope, f":{chan}:DISP?") != "1":
            return None

        with scpi_lock:
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

        if len(raw) == 0:
            log_debug(f"⚠️ No waveform data for {chan}")
            return None

        times = xorig + np.arange(len(raw)) * xinc
        volts = ((raw - yref) * yinc + yorig) * probe


        times = xorig + np.arange(len(raw)) * xinc
        probe = float(safe_query(scope, f":{chan}:PROB?", "1.0"))
        volts = ((raw - yref) * yinc + yorig) * probe

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

        log_debug(f"✅ Exported {chan} waveform to {path}")
        return path

    except Exception as e:
        log_debug(f"❌ Error exporting {chan}: {e}")
        return None


def get_channel_waveform_data(scope, channel, use_simple_calc=True):
    try:
        chan = channel if str(channel).startswith("MATH") else f"CHAN{channel}"
        with scpi_lock:
            if safe_query(scope, f":{chan}:DISP?") != "1":
                return None, None, None

            scope.write(":WAV:FORM BYTE")
            scope.write(":WAV:MODE NORM")
            scope.write(":WAV:POIN:MODE RAW")
            scope.write(f":WAV:POIN {WAV_POINTS}")
            scope.write(f":WAV:SOUR {chan}")
            scope.query(":WAV:PRE?")  # Rigol quirk workaround
            time.sleep(0.1)

            pre = scope.query(":WAV:PRE?").split(",")
            yinc = float(pre[7])
            yorig = float(pre[8])
            yref = float(pre[9])
            raw = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)

        if len(raw) == 0:
            return None, None, None

        volts = (raw - yref) * yinc + yorig

        vpp = volts.max() - volts.min()
        vavg = volts.mean()
        vrms = np.sqrt(np.mean(np.square(volts)))
        return vpp, vavg, vrms

        with scpi_lock:
            pre = scope.query(":WAV:PRE?").split(",")
        xinc = float(pre[4])
        yinc = float(pre[7])
        yorig = float(pre[8])
        yref = float(pre[9])

        volts = (raw - yref) * yinc + yorig
        vpp = volts.max() - volts.min()
        vavg = volts.mean()
        vrms = np.sqrt(np.mean(np.square(volts)))
        return vpp, vavg, vrms

    except Exception as e:
        log_debug(f"❌ Error reading waveform for CH{channel}: {e}")
        return None, None, None

def compute_power_from_scope(scope, voltage_ch, current_ch, remove_dc=True, current_scale=1.0):
    from scpi.interface import scpi_lock, safe_query
    import numpy as np
    from utils.debug import log_debug
    import math

    chan_v = voltage_ch if str(voltage_ch).startswith("MATH") else f"CHAN{voltage_ch}"
    chan_i = current_ch if str(current_ch).startswith("MATH") else f"CHAN{current_ch}"

    # Check if scope channel is already showing current in Amps
    unit_i = safe_query(scope, f":{chan_i}:UNIT?", "VOLT").strip().upper()
    log_debug(f"🧪 {chan_i} UNIT? → {unit_i}")

    if unit_i == "AMP" and current_scale != 1.0:
        log_debug(f"⚠️ {chan_i} is in AMP mode, but current_scale = {current_scale:.4f}. For correct results, set probe value = 1.0", level="FULL")

    log_debug(f"📊 Analyzing: Voltage = {chan_v}, Current = {chan_i}", level="MINIMAL")
    log_debug(f"⚙️ Current scaling factor: {current_scale:.4f} A/V")
    probe_reported = safe_query(scope, f":{chan_i}:PROB?", "1.0")
    log_debug(f"🧪 {chan_i} :PROB? = {probe_reported}")

    with scpi_lock:
        scope.write(":WAV:FORM BYTE")
        scope.write(":WAV:MODE NORM")
        scope.write(":WAV:POIN:MODE RAW")

        # Voltage channel
        scope.write(f":WAV:SOUR {chan_v}")
        pre_v = scope.query(":WAV:PRE?").split(",")
        xinc = float(pre_v[4])
        xorig = float(pre_v[5])
        yinc_v = float(pre_v[7])
        yorig_v = float(pre_v[8])
        yref_v = float(pre_v[9])
        raw_v = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)

        # Current channel
        scope.write(f":WAV:SOUR {chan_i}")
        pre_i = scope.query(":WAV:PRE?").split(",")
        yinc_i = float(pre_i[7])
        yorig_i = float(pre_i[8])
        yref_i = float(pre_i[9])
        raw_i = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)

    if len(raw_v) == 0 or len(raw_i) == 0:
        log_debug("⚠️ Empty waveform data — aborting power analysis")
        return None

    # Decode waveforms
    t = xorig + np.arange(len(raw_v)) * xinc
    v = ((raw_v - yref_v) * yinc_v + yorig_v)
    i = ((raw_i - yref_i) * yinc_i + yorig_i) * current_scale

    if remove_dc:
        v -= np.mean(v)
        i -= np.mean(i)

    # Instantaneous power
    p_inst = v * i
    P = np.mean(p_inst)
    Vrms = np.sqrt(np.mean(v**2))
    Irms = np.sqrt(np.mean(i**2))
    S = Vrms * Irms

    # Phase shift via FFT
    fft_v = np.fft.fft(v)
    fft_i = np.fft.fft(i)
    phase_v = np.angle(fft_v[1])
    phase_i = np.angle(fft_i[1])
    phase_shift_rad = phase_v - phase_i
    phase_shift_deg = (np.rad2deg(phase_shift_rad) + 180) % 360 - 180

    Q = S * np.sin(phase_shift_rad)
    PF = P / S if S != 0 else 0.0
    PF = math.copysign(abs(PF), P)  # PF sign follows P

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
