#!/bin/bash
# Launch the MSO5000 Live Monitor natively from the local virtualenv.
#
# Native counterpart to run.sh (which runs the Docker image). No display
# bridging is needed: the Tk app talks to XWayland and the Qt viewer to
# Wayland directly.
#
# Usage:
#   ./run-native.sh                          # interactive Tk/Qt choice
#   ./run-native.sh --gui qt --ip 192.168.1.10
#   ./run-native.sh --gui tk --ip 192.168.1.10 --noMarquee
#   MSO5000_GUI=qt ./run-native.sh           # env-var default
#
# All arguments are forwarded to start.py.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/venv/bin/python"

if [[ ! -x "$PY" ]]; then
    echo "Error: no virtualenv at $HERE/venv" >&2
    echo "Create it first:" >&2
    echo "  python3 -m venv venv" >&2
    echo "  ./venv/bin/pip install -r requirements-qt.txt   # Tk + Qt, or -r requirements.txt for Tk only" >&2
    exit 1
fi

cd "$HERE"
exec "$PY" start.py "$@"
