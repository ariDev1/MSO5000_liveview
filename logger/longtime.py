import csv
import os
import time
import threading
from datetime import datetime, timedelta
from utils.debug import log_debug
from scpi.waveform import get_channel_waveform_data
from scpi.interface import safe_query
from scpi.interface import scpi_lock
from app.app_state import is_logging_active
import app.app_state as app_state
from scpi.interface import connect_scope

is_logging = False
pause_flag = False
stop_flag = False

from scpi.data import scpi_data

def start_logging(_scope_unused, ip, channels, duration, interval, vavg_enabled, vrms_enabled, status_callback):
    scope = connect_scope(ip)
    if not scope:
        status_callback("❌ Scope not ready")
        return
    global is_logging, pause_flag, stop_flag

    if is_logging:
        status_callback("⚠️ Already running")
        return

    session_dir = f"oszi_csv/session_{datetime.now():%Y%m%d_%H%M%S}"
    os.makedirs(session_dir, exist_ok=True)
    csv_path = os.path.join(session_dir, "session_log.csv")
    total = int((duration * 3600) // interval)
    end_time = datetime.now() + timedelta(seconds=duration * 3600)

    log_debug(f"📁 Logging to {csv_path}")
    log_debug(f"🕒 Estimated end time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")

    is_logging = True
    pause_flag = False
    stop_flag = False
    app_state.is_logging_active = True

    def loop():
        with scpi_lock:
            log_debug(f"🧪 Logging scope ID: {safe_query(scope, '*IDN?', 'N/A')}")
        nonlocal csv_path
        try:
            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                header = ["Timestamp"]
                for ch in channels:
                    chname = f"CH{ch}" if isinstance(ch, int) else ch
                    header.append(f"{chname}_Vpp")
                    if vavg_enabled:
                        header.append(f"{chname}_Vavg")
                    if vrms_enabled:
                        header.append(f"{chname}_Vrms")
                writer.writerow(header)

                start_time = time.time()

                for i in range(total):
                    if stop_flag:
                        log_debug("🛑 Logging stopped by user")
                        break

                    while pause_flag:
                        status_callback("⏸ Paused")
                        time.sleep(0.5)

                    row = [datetime.now().isoformat()]
                    for ch in channels:
                        vpp, vavg, vrms = get_channel_waveform_data(scope, ch, use_simple_calc=True)
                        row.append(f"{vpp:.4f}" if vpp is not None else "")
                        if vavg_enabled:
                            row.append(f"{vavg:.4f}" if vavg is not None else "")
                        if vrms_enabled:
                            row.append(f"{vrms:.4f}" if vrms is not None else "")
                    writer.writerow(row)

                    if (i + 1) % 5 == 0 or i == total - 1:
                        status_callback(f"✅ Saved {i+1}/{total}")

                    next_sample = start_time + (i + 1) * interval
                    delay = next_sample - time.time()
                    if delay > 0:
                        time.sleep(delay)
                    else:
                        log_debug(f"⚠️ Behind schedule by {-delay:.2f}s")

            log_debug("✅ Logging finished")
            status_callback("✅ Logging finished")

        except Exception as e:
            log_debug(f"❌ Logging error: {e}")
            status_callback("❌ Error — see Debug Log")

        finally:
            global is_logging
            is_logging = False
            app_state.is_logging_active = False

    threading.Thread(target=loop, daemon=True).start()

def pause_resume():
    global pause_flag
    pause_flag = not pause_flag
    return pause_flag

def stop_logging():
    global stop_flag
    stop_flag = True
