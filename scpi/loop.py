import time
import threading
from scpi.interface import connect_scope, safe_query, scpi_lock
from scpi.data import scpi_data
from utils.debug import log_debug
from config import INTERVALL_SCPI
from app.app_state import is_logging_active

def start_scpi_loop(ip):
    def loop():
        scope = connect_scope(ip)
        from scpi.data import scpi_data
        scpi_data["scope"] = scope

        if not scope:
            log_debug("❌ SCPI loop failed to connect")
            return

        # Fetch once
        scpi_data["connected"] = True
        scpi_data["idn"] = safe_query(scope, "*IDN?")
        log_debug(f"🔗 SCPI Loop connected: {scpi_data['idn']}")

        while True:
            if is_logging_active:
                time.sleep(1)
                continue

            try:
                # System Info: update Timebase + Trigger only
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

                    def fmt_si(val):
                        try:
                            val = float(val)
                            if val >= 1e9:
                                return f"{val / 1e9:.3g}G"
                            elif val >= 1e6:
                                return f"{val / 1e6:.3g}M"
                            elif val >= 1e3:
                                return f"{val / 1e3:.3g}k"
                            elif val >= 1:
                                return f"{val:.3g}"
                            elif val > 0:
                                return f"{val:.1e}"
                            else:
                                return str(val)
                        except:
                            return str(val)

                    # Parse IDN
                    idn = scpi_data['idn']
                    try:
                        vendor, model, serial, fw = idn.split(",")
                        idn_line = f"{vendor}, {model} — FW: {fw}"
                    except:
                        idn_line = idn

                    # Format values
                    tbase_fmt     = f"{fmt_si(tbase)}s/div"
                    srate_fmt     = f"{fmt_si(srate)}Sa/s"
                    trig_pos_fmt  = f"{fmt_si(trig_pos)}s"
                    trig_hold_fmt = f"{fmt_si(trig_hold)}s"

                    # Check Logic Analyzer availability
                    la_enabled = False
                    try:
                        la_depth_val = float(la_depth)
                        la_enabled = la_depth_val > 0
                    except:
                        la_enabled = False

                    # Logic Analyzer section (conditionally shown)
                    if la_enabled:
                        la_depth_fmt = fmt_si(la_depth)
                        la_srate_fmt = f"{fmt_si(la_srate)}Sa/s"
                        la_lines = [
                            f"{'LA Depth'      :<18}: {la_depth_fmt:<10}    {'Grading'     :<18}: {grading:<8}    {'Totalize'     :<18}: {counter_total}",
                            f"{'LA SampleRate' :<18}: {la_srate_fmt}"
                        ]
                    else:
                        la_lines = [
                            f"{'Grading'       :<18}: {grading:<8}    {'Totalize'     :<18}: {counter_total}"
                        ]

                    # Build full string
                    scpi_data["system_info"] = "\n".join([
                        f"{idn_line}",
                        "",
                        f"{'Timebase'       :<18}: {tbase_fmt:<12}    {'Sample Rate'   :<18}: {srate_fmt}",
                        f"{'Trigger Status' :<18}: {trig:<12}    {'Trigger Pos'   :<18}: {trig_pos_fmt}",
                        f"{'Trigger Holdoff':<18}: {trig_hold_fmt}",
                        "-" * 90,
                        #f"{'Acquisition'    :<20} {'Display'       :<20} {'Counter'        :<20}",
                        f"{'Mode'           :<18}: {acq_type:<10}    {'Brightness'    :<18}: {brightness:<8}    {'Mode'           :<18}: {counter_mode}",
                        f"{'Interleave'     :<18}: {interleave:<10}    {'Grid'          :<18}: {grid:<8}    {'Source'         :<18}: {counter_src}",
                        *la_lines,
                        "-" * 90,
                        f"{'Measurement'}",
                        f"{'Mode'           :<18}: {meas_mode:<10}    {'Type'          :<18}: {meas_type:<8}    {'Stats'          :<18}: {meas_stats}"
                    ])

                scpi_data["trigger_status"] = trig

                # Channel Info
                channels = {}
                with scpi_lock:
                    for ch in range(1, 5):
                        if safe_query(scope, f":CHAN{ch}:DISP?") != "1":
                            continue
                        channels[f"CH{ch}"] = {
                            "scale": safe_query(scope, f":CHAN{ch}:SCALe?"),
                            "offset": safe_query(scope, f":CHAN{ch}:OFFS?"),
                            "coupling": safe_query(scope, f":CHAN{ch}:COUP?"),
                            "probe": safe_query(scope, f":CHAN{ch}:PROB?"),
                        }
                    #Add MATH channel support
                    for m in range(1, 4):
                        math_name = f"MATH{m}"
                        if safe_query(scope, f":{math_name}:DISP?") != "1":
                            continue
                        #log_debug(f"✅ Detected {math_name} — added to channel_info")
                        channels[math_name] = {
                            "scale": safe_query(scope, f":{math_name}:SCALe?", "N/A"),
                            "offset": safe_query(scope, f":{math_name}:OFFS?", "N/A"),
                            "type": safe_query(scope, f":{math_name}:OPER?", "N/A"),
                        }
    
                scpi_data["channel_info"] = channels
                time.sleep(INTERVALL_SCPI)

            except Exception as e:
                log_debug(f"❌ SCPI loop error: {e}")
                time.sleep(5)

    threading.Thread(target=loop, daemon=True).start()
