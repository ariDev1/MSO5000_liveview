# scpi/loop.py

import time
import threading
import app.app_state as app_state

from scpi.interface import connect_scope, safe_query, scpi_lock
from scpi.data import scpi_data
from utils.debug import log_debug, set_debug_level
from config import INTERVALL_SCPI

def _read_tcal_seconds(scope, ch_index: int):
    # :CHANnel1:TCALibrate? returns seconds (may be '', '0', or a float string)
    s = safe_query(scope, f":CHANnel{ch_index}:TCALibrate?", "")
    try:
        return float(s)
    except Exception:
        return 0.0

def start_scpi_loop(ip):
    def loop():
        scope = connect_scope(ip)
        from scpi.data import scpi_data
        scpi_data["scope"] = scope

        if not scope:
            log_debug("❌ SCPI loop failed to connect")
            return

        scpi_data["connected"] = True
        scpi_data["idn"] = safe_query(scope, "*IDN?")
        log_debug(f"🔗 SCPI Loop connected: {scpi_data['idn']}")

        try:
            while not app_state.is_shutting_down:
                if app_state.is_logging_active:
                    time.sleep(1)
                    continue

                try:
                    # ---------- existing queries ----------
                    with scpi_lock:
                        tbase = safe_query(scope, ":TIMebase:SCALe?")
                        srate = safe_query(scope, ":ACQuire:SRATe?")
                        trig = safe_query(scope, ":TRIGger:STATus?")
                        acq_type = safe_query(scope, ":ACQuire:TYPE?")
                        interleave = safe_query(scope, ":ACQuire:INTerleave?")
                        la_depth = safe_query(scope, ":ACQuire:LA:MDEPth?")
                        la_srate = safe_query(scope, ":ACQuire:LA:SRATe?")
                        trig_pos = safe_query(scope, ":TRIGger:POSition?")
                        trig_hold = safe_query(scope, ":TRIGger:HOLDoff?")
                        brightness = safe_query(scope, ":DISPlay:GBRightness?")
                        grid = safe_query(scope, ":DISPlay:GRID?")
                        grading = safe_query(scope, ":DISPlay:GRADing:TIME?")
                        counter_mode = safe_query(scope, ":COUNter:MODE?")
                        counter_src = safe_query(scope, ":COUNter:SOURce?")
                        counter_total = safe_query(scope, ":COUNTER:TOTalize:ENABle?")
                        meas_mode = safe_query(scope, ":MEASure:MODE?")
                        meas_type = safe_query(scope, ":MEASure:TYPE?")
                        meas_stats = safe_query(scope, ":MEASure:STATistic:DISPlay?")
                    # ---------- existing formatting & scpi_data updates unchanged ----------

                    # Channel Info
                    channels = {}
                    with scpi_lock:
                        for ch in range(1, 5):
                            if app_state.is_shutting_down:
                                break
                            if safe_query(scope, f":CHAN{ch}:DISP?") != "1":
                                continue
                            ch_name = f"CH{ch}"
                            channels[ch_name] = {
                                "scale":    safe_query(scope, f":CHAN{ch}:SCALe?"),
                                "offset":   safe_query(scope, f":CHAN{ch}:OFFS?"),
                                "coupling": safe_query(scope, f":CHAN{ch}:COUP?"),
                                "probe":    safe_query(scope, f":CHAN{ch}:PROB?"),
                            }
                            tcal_s = _read_tcal_seconds(scope, ch)
                            channels[ch_name]["tcal_s"]  = tcal_s
                            channels[ch_name]["tcal_ns"] = tcal_s * 1e9

                        # MATH channels block unchanged...

                    scpi_data["channel_info"] = channels

                    # Respect shutdown before sleeping/rescheduling
                    for _ in range(int(INTERVALL_SCPI*10)):
                        if app_state.is_shutting_down:
                            break
                        time.sleep(0.1)

                except Exception as e:
                    if app_state.is_shutting_down:
                        break
                    log_debug(f"❌ SCPI loop error: {e}")
                    time.sleep(5)

        finally:
            log_debug("🔗 SCPI loop exiting")
            try:
                with scpi_lock:
                    if scope:
                        try:
                            scope.close()
                        except Exception:
                            pass
            finally:
                scpi_data["connected"] = False
                scpi_data["scope"] = None

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    app_state.scpi_thread = t
    return t
