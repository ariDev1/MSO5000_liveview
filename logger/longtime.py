# #logger/longtime.py

import csv
import os
import time
import threading
from datetime import datetime, timedelta
from scpi.waveform import get_channel_waveform_data
from scpi.interface import safe_query
from scpi.interface import scpi_lock
from app.app_state import is_logging_active
import app.app_state as app_state
from scpi.data import scpi_data

is_logging = False
pause_flag = False
stop_flag = False

def start_logging(_scope_unused, ip, channels, duration, interval, vavg_enabled, vrms_enabled, status_callback, current_scale=1.0):
    if app_state.is_power_analysis_active:
        status_callback("⚠️ Cannot start long-time logging during power analysis.")
        return
    from app.app_state import scope
    if not scope:
        log_debug("❌ Scope not connected")
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

    log_debug(f"📁 Logging to {csv_path}", level="MINIMAL")
    log_debug(f"🕒 Estimated end time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}", level="MINIMAL")

    is_logging = True
    pause_flag = False
    stop_flag = False
    app_state.is_logging_active = True

    def loop():
        with scpi_lock:
            log_debug(f"🧪 Logging scope ID: {safe_query(scope, '*IDN?', 'N/A')}", level="MINIMAL")
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
                        log_debug("🛑 Logging stopped by user", level="MINIMAL")
                        break

                    if pause_flag:
                        status_callback("⏸ Paused")
                    while pause_flag and not stop_flag:
                        time.sleep(0.5)
                    if stop_flag:
                        log_debug("🛑 Logging stopped during pause", level="MINIMAL")
                        break


                    row = [datetime.now().isoformat()]
                    for ch in channels:
                        vpp, vavg, vrms = get_channel_waveform_data(scope, ch, use_simple_calc=True)
                        chname = f"CH{ch}" if isinstance(ch, int) else ch
                        log_debug(f"{chname} ➜ Vpp={vpp:.3f}  Vavg={vavg:.3f}  Vrms={vrms:.3f}")

                        try:
                            chnum = str(ch).replace("CH", "").strip()
                            unit = safe_query(scope, f":CHAN{chnum}:UNIT?", default="VOLT").strip().upper()
                            if unit == "AMP":
                                scale = 1.0
                                log_debug(f"⚙️ {chname} is in AMP — no scaling applied")
                            else:
                                scale = current_scale
                                log_debug(f"⚙️ {chname} is in VOLT — applying scale {scale}")
                        except Exception as e:
                            log_debug(f"⚠️ Unit detection failed for {chname}: {e}")
                            scale = current_scale

                        row.append(f"{vpp * scale:.4f}" if vpp is not None else "")
                        if vavg_enabled:
                            row.append(f"{vavg * scale:.4f}" if vavg is not None else "")
                        if vrms_enabled:
                            row.append(f"{vrms * scale:.4f}" if vrms is not None else "")

                    writer.writerow(row)
                    log_debug(f"📈 Sample {i+1}/{total} complete")
                    if (i + 1) % 5 == 0 or i == total - 1:
                        status_callback(f"✅ Saved {i+1}/{total}")

                    actual_sample_time = time.time()
                    next_sample = actual_sample_time + interval
                    delay = next_sample - time.time()

                    if delay > 0:
                        time.sleep(delay)
                    else:
                        log_debug(f"⚠️ Behind schedule by {-delay:.2f}s")

            log_debug("✅ Logging finished", level="MINIMAL")
            status_callback("✅ Logging finished")
            log_debug("✅ Long-time logging completed successfully", level="MINIMAL")

        except Exception as e:
            log_debug(f"❌ Logging error: {e}", level="MINIMAL")
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
