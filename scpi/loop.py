# scpi/loop.py

import time
import threading
import app.app_state as app_state

from scpi.interface import connect_scope, safe_query, scpi_lock
from scpi.data import scpi_data
from utils.debug import log_debug, set_debug_level
from config import INTERVALL_SCPI


def _truthy(v) -> bool:
    s = str(v).strip().upper()
    return s in ("1", "ON", "TRUE", "ENAB", "ENABLE")


def _to_float(s, default=0.0):
    try:
        return float(str(s).strip())
    except Exception:
        return default


def _read_tcal_seconds(scope, ch_index: int) -> float:
    # Documented: :CHANnel<n>:TCALibrate? → seconds (may be '', '0', or float)
    s = safe_query(scope, f":CHANnel{ch_index}:TCALibrate?", "")
    return _to_float(s, 0.0)


def start_scpi_loop(ip):
    def loop():
        scope = connect_scope(ip)
        scpi_data["scope"] = scope

        if not scope:
            log_debug("❌ SCPI loop failed to connect")
            return

        scpi_data["connected"] = True
        scpi_data["idn"] = safe_query(scope, "*IDN?", "N/A")
        log_debug(f"🔗 SCPI Loop connected: {scpi_data['idn']}")

        try:
            while not app_state.is_shutting_down:
                # Give priority to long-time logging
                if app_state.is_logging_active or getattr(app_state, "is_exporting", False):
                    time.sleep(0.2)
                    continue

                try:
                    # ---------- System / status block (restored) ----------
                    with scpi_lock:
                        tbase        = safe_query(scope, ":TIMebase:SCALe?", "")
                        srate        = safe_query(scope, ":ACQuire:SRATe?", "")
                        trig         = safe_query(scope, ":TRIGger:STATus?", "")
                        acq_type     = safe_query(scope, ":ACQuire:TYPE?", "")
                        interleave   = safe_query(scope, ":ACQuire:INTerleave?", "")

                        # Logic analyzer (restored)
                        la_depth     = safe_query(scope, ":ACQuire:LA:MDEPth?", "")
                        la_srate     = safe_query(scope, ":ACQuire:LA:SRATe?", "")

                        trig_pos     = safe_query(scope, ":TRIGger:POSition?", "")
                        trig_hold    = safe_query(scope, ":TRIGger:HOLDoff?", "")

                        # Display block (restored)
                        brightness   = safe_query(scope, ":DISPlay:GBRightness?", "")
                        grid         = safe_query(scope, ":DISPlay:GRID?", "")
                        grading      = safe_query(scope, ":DISPlay:GRADing:TIME?", "")

                        # Counter block (restored)
                        counter_mode = safe_query(scope, ":COUNter:MODE?", "")
                        counter_src  = safe_query(scope, ":COUNter:SOURce?", "")
                        counter_total= safe_query(scope, ":COUNTER:TOTalize:ENABle?", "")

                        # Measure block (restored)
                        meas_mode    = safe_query(scope, ":MEASure:MODE?", "")
                        meas_type    = safe_query(scope, ":MEASure:TYPE?", "")
                        meas_stats   = safe_query(scope, ":MEASure:STATistic:DISPlay?", "")

                    # Expose system/status data to whoever needs it
                    scpi_data["timebase"]              = tbase
                    scpi_data["sample_rate"]           = srate
                    scpi_data["trigger_status"]        = trig
                    scpi_data["acquire_type"]          = acq_type
                    scpi_data["interleave"]            = interleave
                    scpi_data["la_depth"]              = la_depth
                    scpi_data["la_sample_rate"]        = la_srate
                    scpi_data["trig_pos"]              = trig_pos
                    scpi_data["trig_hold"]             = trig_hold
                    scpi_data["display_brightness"]    = brightness
                    scpi_data["display_grid"]          = grid
                    scpi_data["display_grading_time"]  = grading
                    scpi_data["counter_mode"]          = counter_mode
                    scpi_data["counter_source"]        = counter_src
                    scpi_data["counter_totalize_en"]   = counter_total
                    scpi_data["measure_mode"]          = meas_mode
                    scpi_data["measure_type"]          = meas_type
                    scpi_data["measure_stats_display"] = meas_stats

                    # ---------- Channel info ----------
                    channels = {}

                    with scpi_lock:
                        # Analog CH1..CH4
                        for ch in range(1, 5):
                            if app_state.is_shutting_down:
                                break

                            # Robust display detection (documented long form)
                            if not _truthy(safe_query(scope, f":CHANnel{ch}:DISPlay?", "0")):
                                continue

                            ch_name = f"CH{ch}"

                            # Core fields used by the Channel Data tab
                            scale    = safe_query(scope, f":CHANnel{ch}:SCALe?", "")
                            offset   = safe_query(scope, f":CHANnel{ch}:OFFSet?", "")
                            coupling = safe_query(scope, f":CHANnel{ch}:COUPling?", "")
                            probe    = safe_query(scope, f":CHANnel{ch}:PROBe?", "")

                            channels[ch_name] = {
                                "scale":    scale,
                                "offset":   offset,
                                "coupling": coupling,
                                "probe":    probe,
                            }

                            # Extra per-channel context (documented; read-only)
                            unit      = safe_query(scope, f":CHANnel{ch}:UNITs?", "")     # VOLT/AMP/WATT/UNKN
                            bwlimit   = safe_query(scope, f":CHANnel{ch}:BWLimit?", "")  # OFF/20M/...
                            invert    = safe_query(scope, f":CHANnel{ch}:INVert?", "")   # 0/1
                            impedance = safe_query(scope, f":CHANnel{ch}:IMPedance?", "")# OMEG/FIFT
                            vernier   = safe_query(scope, f":CHANnel{ch}:VERNier?", "")  # 0/1
                            tcal_s    = _read_tcal_seconds(scope, ch)

                            channels[ch_name].update({
                                "unit":      unit,
                                "bwlimit":   bwlimit,
                                "invert":    invert,
                                "impedance": impedance,
                                "vernier":   vernier,
                                "tcal_s":    tcal_s,
                                "tcal_ns":   tcal_s * 1e9,
                            })

                        # MATH1..MATH4 (read-only, documented mnemonics)
                        for m in range(1, 5):
                            if app_state.is_shutting_down:
                                break

                            if not _truthy(safe_query(scope, f":MATH{m}:DISPlay?", "0")):
                                continue

                            m_name  = f"MATH{m}"
                            m_scale = safe_query(scope, f":MATH{m}:SCALe?", "")
                            m_offs  = safe_query(scope, f":MATH{m}:OFFSet?", "")
                            m_oper  = safe_query(scope, f":MATH{m}:OPERator?", "")  # e.g., ADD/SUB/MUL/DIV/FFT
                            m_inv   = safe_query(scope, f":MATH{m}:INVert?", "")    # 0/1 (if available)
                            m_src1  = safe_query(scope, f":MATH{m}:SOURce1?", "")
                            m_src2  = safe_query(scope, f":MATH{m}:SOURce2?", "")

                            channels[m_name] = {
                                "scale":   m_scale,
                                "offset":  m_offs,
                                "type":    m_oper,
                                "invert":  m_inv,
                                "source1": m_src1,
                                "source2": m_src2,
                            }

                    scpi_data["channel_info"] = channels
                    scpi_data["no_displayed_channels"] = not any(
                        info.get("scale", "") for info in channels.values()
                    )

                    # ---------- pacing / cooperative shutdown ----------
                    slices = max(1, int(float(INTERVALL_SCPI) * 10))
                    for _ in range(slices):
                        if app_state.is_shutting_down:
                            break
                        time.sleep(0.1)

                except Exception as e:
                    if app_state.is_shutting_down:
                        break
                    log_debug(f"❌ SCPI loop error: {e}")
                    time.sleep(0.5)

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
