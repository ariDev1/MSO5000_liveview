#!/bin/bash

IMAGE="mso5000_liveview"

if ! command -v xhost >/dev/null 2>&1; then
    echo "Error: xhost is required. On Omarchy or Arch Linux, install xorg-xhost." >&2
    exit 1
fi

revoke_xhost_access() {
    xhost -si:localuser:root >/dev/null 2>&1 || true
}

trap revoke_xhost_access EXIT

# Detect display server
if [[ $XDG_SESSION_TYPE == "wayland" ]]; then
    echo "🧠 Wayland detected – enabling XWayland bridge"

    # Allow access
    xhost +si:localuser:root

    docker run -it --rm \
        --env "WAYLAND_DISPLAY=$WAYLAND_DISPLAY" \
        --env "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR" \
        --env "DISPLAY=$DISPLAY" \
        --volume "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY:/tmp/$WAYLAND_DISPLAY" \
        --volume /tmp/.X11-unix:/tmp/.X11-unix \
        --volume "$HOME/oszi_csv:/app/oszi_csv" \
        --network host \
        "$IMAGE"

else
    echo "🖥️ X11 detected"

    # Allow X11 connections
    xhost +si:localuser:root

    docker run -it --rm \
        --env "DISPLAY=$DISPLAY" \
        --volume /tmp/.X11-unix:/tmp/.X11-unix \
        --volume "$HOME/oszi_csv:/app/oszi_csv" \
        --network host \
        "$IMAGE"
fi
