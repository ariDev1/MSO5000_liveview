# scpi/interface.py

import pyvisa
import threading
import app.app_state as app_state

from utils.debug import log_debug, set_debug_level
from config import BLACKLISTED_COMMANDS

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
        scope.timeout = 60000
        scope.chunk_size = 102400

        # Quick test
        idn = scope.query("*IDN?")
        log_debug(f"✅ Connected: {idn}")

        return scope

    except Exception as e:
        log_debug(f"❌ SCPI connect error: {e}")
        return None

def safe_query(scope, command, default="N/A"):
    """Query the scope safely with blacklist + busy flag handling."""
    if command in BLACKLISTED_COMMANDS:
        log_debug(f"⚠️ Skipped blacklisted SCPI: {command}")
        return default

    app_state.is_scpi_busy = True
    try:
        response = scope.query(command)
        response = response.strip() if isinstance(response, str) else response
        return response if response else default
    except Exception as e:
        log_debug(f"❌ SCPI error [{command}]: {e}")
        if "TMO" in str(e) or "Timeout" in str(e):
            if command not in BLACKLISTED_COMMANDS:
                BLACKLISTED_COMMANDS.append(command)
            log_debug(f"⛔ Blacklisted: {command}")
        return default
    finally:
        # Always clear the busy flag on success OR error
        app_state.is_scpi_busy = False

def safe_write(scope, command, wait_opc=True, default_ok="OK"):
    """
    Send a write-only SCPI command. Optionally block on *OPC? for completion.
    Returns 'OK' (or the OPC reply) on success; logs and returns '' on failure.
    """
    import app.app_state as app_state
    from utils.debug import log_debug
    from config import BLACKLISTED_COMMANDS

    if not scope:
        log_debug("❌ safe_write: no scope handle")
        return ""

    # Don’t treat writes as queries
    if "?" in command:
        log_debug(f"❗ safe_write called with query-like command: {command}")
    
    try:
        app_state.is_scpi_busy = True
        scope.write(command)
        if wait_opc:
            # Synchronize and also produce a short, visible response in the console
            resp = scope.query("*OPC?").strip()
            return resp if resp else default_ok
        return default_ok
    except Exception as e:
        log_debug(f"❌ SCPI write error [{command}]: {e}")
        # Don’t blacklist write commands just because they have no response
        return ""
    finally:
        app_state.is_scpi_busy = False

def multi_query(scope, commands, defaults=None):
    """
    Try to batch several queries using a single SCPI request.
    Falls back to individual safe_query() if batching fails.
    """
    from .interface import scpi_lock
    if defaults is None:
        defaults = ["N/A"] * len(commands)

    try:
        with scpi_lock:
            joined = ";".join(commands)
            resp = scope.query(joined)
        parts = [p.strip() for p in resp.split(";")]
        if len(parts) != len(commands):
            raise RuntimeError("Split mismatch")
        return parts
    except Exception:
        # Fallback: one by one (keeps your blacklist / busy flag behavior)
        return [safe_query(scope, cmd, default=defaults[i]) for i, cmd in enumerate(commands)]