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
    import pyvisa
    from utils.debug import log_debug

    try:
        rm = pyvisa.ResourceManager('@py')

        if ip:
            resource_str = f"TCPIP0::{ip}::INSTR"
            log_debug(f"🔌 Trying LAN: {resource_str}")
        else:
            # Manual fallback for known MSO5000 USBTMC ID
            resource_str = "USB0::0x1AB1::0x04CE::?*::INSTR"
            log_debug(f"🔌 Trying USB: {resource_str}")

        scope = rm.open_resource(resource_str)
        scope.timeout = 5000
        scope.chunk_size = 102400

        idn = scope.query("*IDN?")
        log_debug(f"✅ Connected: {idn}")
        return scope

    except Exception as e:
        log_debug(f"❌ SCPI connect error: {e}")
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
