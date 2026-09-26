#!/bin/bash
# Convenience wrapper: activate venv if present, then run the GUI chooser.
# Usage: ./start.sh [--gui tk|qt] [--ip 192.168.1.10] [...]
set -euo pipefail
cd "$(dirname "$0")"
if [[ -f "venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "venv/bin/activate"
fi
exec python3 start.py "$@"
