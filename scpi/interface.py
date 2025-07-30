# scpi/interface.py

import pyvisa
from utils.debug import log_debug, set_debug_level
from config import BLACKLISTED_COMMANDS
import threading
import app.app_state as app_state

scpi_lock = threading.Lock()


# LAN only
# def connect_scope(ip):
#     try:
#         rm = pyvisa.ResourceManager()
#         resources = rm.list_resources()
#         log_debug(f"🔎 VISA resources: {resources}")

#         resource_str = f"TCPIP0::{ip}::INSTR"
#         log_debug(f"🔌 Trying to connect to: {resource_str}")
#         scope = rm.open_resource(resource_str)

#         # Basic setup
#         scope.timeout = 5000
#         scope.chunk_size = 102400

#         # Quick test
#         idn = scope.query("*IDN?")
#         log_debug(f"✅ Connected: {idn}")

#         return scope

#     except Exception as e:
#         log_debug(f"❌ SCPI connect error: {e}")
#         return None

def connect_scope(ip=None):
    from types import SimpleNamespace
    from utils.debug import log_debug
    import time

    if ip:
        # Normal LAN connection
        import pyvisa
        rm = pyvisa.ResourceManager()
        try:
            scope = rm.open_resource(f"TCPIP0::{ip}::INSTR")
            scope.timeout = 5000
            scope.chunk_size = 102400
            idn = scope.query("*IDN?")
            log_debug(f"✅ Connected (LAN): {idn}")
            return scope
        except Exception as e:
            log_debug(f"❌ LAN connect error: {e}")
            return None

    # Raw USB via /dev/usbtmc0
    log_debug("🔌 Attempting raw USB /dev/usbtmc0 fallback")

    def write(cmd):
        with open("/dev/usbtmc0", "wb", buffering=0) as f:
            f.write((cmd.strip() + '\n').encode())

    def query(cmd, timeout=0.2):
        with open("/dev/usbtmc0", "wb+", buffering=0) as f:
            f.write((cmd.strip() + '\n').encode())
            time.sleep(timeout)
            return f.read(512).decode(errors="ignore").strip()

    scope = SimpleNamespace()
    scope.query = query
    scope.write = write
    scope.timeout = 5000
    scope.chunk_size = 102400

    try:
        idn = scope.query("*IDN?")
        log_debug(f"✅ Connected (USB raw): {idn}")
        return scope
    except Exception as e:
        log_debug(f"❌ USB /dev/usbtmc0 error: {e}")
        return None

def safe_query(scope, command, default="N/A"):
    if command in BLACKLISTED_COMMANDS:
        log_debug(f"⚠️ Skipped blacklisted SCPI: {command}")
        return default
    try:
        app_state.is_scpi_busy = True   #scpi busy now
        response = scope.query(command).strip()
        app_state.is_scpi_busy = True   #scpi done
        return response if response else default
    except Exception as e:
        app_state.is_scpi_busy = False  #ensure it's reset on error too!
        log_debug(f"❌ SCPI error [{command}]: {e}")
        if "TMO" in str(e) or "Timeout" in str(e):
            BLACKLISTED_COMMANDS.append(command)
            log_debug(f"⛔ Blacklisted: {command}")
        return default
