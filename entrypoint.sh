#!/bin/bash

display_socket_path() {
    local display_id
    local display_number
    local socket_dir="${X11_SOCKET_DIR:-/tmp/.X11-unix}"

    display_id="${DISPLAY##*:}"
    display_number="${display_id%%.*}"

    case "$display_number" in
        ""|*[!0-9]*) return 1 ;;
    esac

    printf '%s/X%s\n' "$socket_dir" "$display_number"
}

main() {
    local display_socket

    echo "[entrypoint] 🖥️ Detecting host display environment..."

    if [ -z "${DISPLAY:-}" ] || ! display_socket="$(display_socket_path)"; then
        echo "[entrypoint] ❌ DISPLAY is missing or invalid."
        exit 1
    fi

    if [ -S "$display_socket" ]; then
        echo "[entrypoint] ✅ DISPLAY is set to $DISPLAY"
        echo "[entrypoint] ✅ X11 socket detected: $display_socket"
    else
        echo "[entrypoint] ❌ Cannot find X11 socket: $display_socket"
        echo "[entrypoint] 💡 Confirm that the host X11 socket is mounted."
        exit 1
    fi

    exec python3 /app/main.py
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
