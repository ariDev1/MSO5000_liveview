#utils/metadata.py

import os
from datetime import datetime
from scpi.interface import safe_query
from app.app_state import scope

def load_operator_info(path="utils/operator-info.txt"):
    info = {}
    try:
        with open(path, "r") as f:
            for line in f:
                if ":" in line:
                    key, val = line.strip().split(":", 1)
                    info[key.strip()] = val.strip()
    except Exception as e:
        info["Metadata Error"] = f"Could not read {path}: {e}"
    return info

def collect_context_info(vch, ich, probe_type, scale, dc_remove):
    context = {}

    # Get scope ID
    try:
        idn = safe_query(scope, "*IDN?", "N/A") if scope else "N/A"
    except:
        idn = "N/A"
    context["Scope ID"] = idn

    context["Voltage Channel"] = vch
    context["Current Channel"] = ich
    context["Probe Type"] = probe_type
    context["Scale (A/V)"] = scale
    context["DC Offset Removal"] = "ON" if dc_remove else "OFF"
    context["Timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return context

def get_combined_metadata(vch, ich, probe_type, scale, dc_remove):
    info = load_operator_info()
    ctx = collect_context_info(vch, ich, probe_type, scale, dc_remove)
    return {**info, **ctx}
