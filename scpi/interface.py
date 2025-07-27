# scpi/interface.py

import pyvisa
from utils.debug import log_debug, set_debug_level
from config import BLACKLISTED_COMMANDS
import threading
scpi_lock = threading.Lock()

def connect_scope(ip):
    try:
        rm = pyvisa.ResourceManager()
        resources = rm.list_resources()
        log_debug(f"🔎 VISA resources: {resources}")

        resource_str = f"TCPIP0::{ip}::INSTR"
        log_debug(f"🔌 Trying to connect to: {resource_str}")
        scope = rm.open_resource(resource_str)

        # Basic setup
        scope.timeout = 5000
        scope.chunk_size = 102400

        # Quick test
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
        response = scope.query(command).strip()
        return response if response else default
    except Exception as e:
        log_debug(f"❌ SCPI error [{command}]: {e}")
        if "TMO" in str(e) or "Timeout" in str(e):
            BLACKLISTED_COMMANDS.append(command)
            log_debug(f"⛔ Blacklisted: {command}")
        return default
