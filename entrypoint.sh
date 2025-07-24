#!/bin/bash

echo "[entrypoint] 🖥️ Detecting host display environment..."

# Check if DISPLAY is set and X11 socket is mounted
if [ -n "$DISPLAY" ] && [ -S /tmp/.X11-unix/X0 ]; then
    echo "[entrypoint] ✅ DISPLAY is set to $DISPLAY"
    echo "[entrypoint] ✅ X11 socket detected"
else
    echo "[entrypoint] ❌ Cannot connect to host display."
    echo "[entrypoint] 💡 Try running this on your host before starting:"
    echo "    xhost +local:docker"
    exit 1
fi

# Start the actual Python GUI
exec python3 /app/main.py
