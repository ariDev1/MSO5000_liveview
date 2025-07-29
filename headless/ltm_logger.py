# headless/ltm_logger.py

import argparse
import time
import sys
from app import app_state
from scpi.interface import connect_scope
from scpi.data import scpi_data
from logger.longtime import start_logging, stop_logging
from utils.debug import set_debug_level

def ask(prompt, default=None, required=True):
    while True:
        val = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
        if val == "" and default is not None:
            return default
        if val:
            return val
        if not required:
            return None

def main():
    parser = argparse.ArgumentParser(description="Headless long-time measurement")
    parser.add_argument("--ip", help="IP address of the scope")
    parser.add_argument("--channels", help="Comma-separated channel list (e.g., 1,2,MATH1)")
    parser.add_argument("--duration", type=float, help="Logging duration in hours")
    parser.add_argument("--interval", type=float, help="Interval between samples in seconds")
    parser.add_argument("--vavg", action="store_true", help="Log Vavg")
    parser.add_argument("--vrms", action="store_true", help="Log Vrms")
    parser.add_argument("--debug", choices=["FULL", "MINIMAL"], default="MINIMAL")
    args = parser.parse_args()

    use_prompt = not any([args.ip, args.channels, args.duration, args.interval])

    if use_prompt:
        print("🔧 Interactive Mode — leave blank to cancel.\n")
        args.ip = ask("Scope IP address")
        args.channels = ask("Channels (e.g., 1,2,MATH1)")
        args.duration = float(ask("Logging duration (hours)", default="0.1"))
        args.interval = float(ask("Interval between samples (seconds)", default="5"))
        args.vavg = ask("Log Vavg? (y/N)", default="n", required=False).lower().startswith("y")
        args.vrms = ask("Log Vrms? (y/N)", default="n", required=False).lower().startswith("y")
        args.debug = ask("Debug level [FULL/MINIMAL]", default="MINIMAL")

    set_debug_level(args.debug)

    scope = connect_scope(args.ip)
    if not scope:
        print("❌ Failed to connect to scope.")
        sys.exit(1)

    app_state.scope = scope
    app_state.scope_ip = args.ip
    scpi_data["ip"] = args.ip

    ch_list = []
    for ch in args.channels.split(","):
        ch = ch.strip().upper()
        if ch.startswith("MATH") and ch[4:].isdigit():
            ch_list.append(ch)
        elif ch.isdigit():
            ch_list.append(int(ch))

    if not ch_list:
        print("❌ No valid channels specified.")
        sys.exit(1)

    def status_callback(msg):
        print(msg)

    print(f"📡 Starting headless logging for {ch_list} at {args.interval}s interval for {args.duration}h")

    start_logging(
        None,
        args.ip,
        ch_list,
        args.duration,
        args.interval,
        args.vavg,
        args.vrms,
        status_callback
    )

    try:
        while app_state.is_logging_active:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Ctrl+C detected — stopping logging...")
        stop_logging()
        while app_state.is_logging_active:
            time.sleep(0.2)  # Give it time to close CSV cleanly
        print("✅ Logging stopped cleanly.")
    finally:
        print("✅ Exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
