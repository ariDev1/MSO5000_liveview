import os
import time
import csv
import numpy as np
from utils.debug import log_debug
from config import WAV_POINTS
from scpi.interface import safe_query
from scpi.interface import scpi_lock

def export_channel_csv(scope, channel, outdir="oszi_csv"):
    chan = f"CHAN{channel}"
    try:
        if safe_query(scope, f":{chan}:DISP?") != "1":
            return None

        with scpi_lock:
            # Setup waveform transfer
            scope.write(":WAV:FORM BYTE")
            scope.write(":WAV:MODE NORM")
            scope.write(":WAV:POIN:MODE RAW")
            scope.write(f":WAV:POIN {WAV_POINTS}")
            scope.write(f":WAV:SOUR {chan}")
            time.sleep(0.2)

            pre = scope.query(":WAV:PRE?").split(",")
            xinc = float(pre[4])
            xorig = float(pre[5])
            yinc = float(pre[7])
            yorig = float(pre[8])
            yref = float(pre[9])

            raw = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)

        if len(raw) == 0:
            log_debug(f"⚠️ No waveform data for {chan}")
            return None

        times = xorig + np.arange(len(raw)) * xinc
        volts = (raw - yref) * yinc + yorig

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
        chan = f"CHAN{channel}"

        with scpi_lock:
            if safe_query(scope, f":{chan}:DISP?") != "1":
                return None, None, None

            scope.write(":WAV:FORM BYTE")
            scope.write(":WAV:MODE NORM")
            scope.write(":WAV:POIN:MODE RAW")
            scope.write(f":WAV:POIN {WAV_POINTS}")
            scope.write(f":WAV:SOUR {chan}")
            time.sleep(0.2)
            raw = scope.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)

            if not use_simple_calc:
                pre = scope.query(":WAV:PRE?").split(",")

        if len(raw) == 0:
            return None, None, None

        if use_simple_calc:
            # Get scaling from preamble
            pre = scope.query(":WAV:PRE?").split(",")
            yinc = float(pre[7])
            yorig = float(pre[8])
            yref = float(pre[9])
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
