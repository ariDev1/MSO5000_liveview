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
                scpi_data["system_info"] = (
                    f"{scpi_data['idn']}\n"
                    f"Timebase: {tbase} s/div\n"
                    f"Sample Rate: {srate} Sa/s\n"
                    f"Trigger: {trig}"
                )
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

                scpi_data["channel_info"] = channels
                time.sleep(INTERVALL_SCPI)

            except Exception as e:
                log_debug(f"❌ SCPI loop error: {e}")
                time.sleep(5)

    threading.Thread(target=loop, daemon=True).start()
