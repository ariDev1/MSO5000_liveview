import requests
from utils.debug import log_debug, set_debug_level

def get_license_options(ip_addr):
    """
    Retrieve license options via Rigol HTTP endpoint.
    """
    try:
        res = requests.post(f"http://{ip_addr}/cgi-bin/options.cgi", timeout=3)
        if res.status_code != 200:
            log_debug("❌ License query failed (non-200 response)")
            return []

        items = res.text.strip().split('#')
        options = []
        for item in items:
            parts = item.split('$')
            if len(parts) == 3:
                code, status, desc = parts
                options.append({
                    "code": code.strip(),
                    "status": status.strip(),
                    "desc": desc.strip()
                })
        return options

    except Exception as e:
        log_debug(f"❌ License query error: {e}")
        return []
