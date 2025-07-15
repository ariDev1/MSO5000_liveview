#!/bin/bash

IMAGE="mso5000_live"

# Detect display server
if [[ $XDG_SESSION_TYPE == "wayland" ]]; then
    echo "🧠 Wayland detected – enabling XWayland bridge"

    # Allow access
    xhost +si:localuser:root

    docker run -it --rm \
        --env WAYLAND_DISPLAY=$WAYLAND_DISPLAY \
        --env XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR \
        --env DISPLAY=$DISPLAY \
        --volume $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY:/tmp/$WAYLAND_DISPLAY \
        --volume /tmp/.X11-unix:/tmp/.X11-unix \
	--volume $HOME/oszi_csv:/app/oszi_csv \
        --network host \
        $IMAGE

else
    echo "🖥️ X11 detected"

    # Allow X11 connections
    xhost +local:root

    docker run -it --rm \
        --env DISPLAY=$DISPLAY \
        --volume /tmp/.X11-unix:/tmp/.X11-unix \
	--volume $HOME/oszi_csv:/app/oszi_csv \
        --network host \
        $IMAGE
fi
