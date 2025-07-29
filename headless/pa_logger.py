# headless/pa_logger.py

import argparse
import time
import csv
import os
import sys
from datetime import datetime

from app import app_state
from scpi.interface import connect_scope, safe_query
from scpi.waveform import compute_power_from_scope
from utils.debug import set_debug_level, log_debug

def parse_args():
    shorthand_map = {
        "--ip": "--ip",
        "--ip:": "--ip",
        "--v:": "--vch",
        "--i:": "--ich",
        "--scale:": "--scale",
        "--int:": "--interval",
        "--c:": "--count",
    }

    args = []
    for arg in sys.argv[1:]:
        if ":" in arg and not arg.startswith("--dc"):
            key, val = arg.split(":", 1)
            fullkey = shorthand_map.get(key + ":", key)
            args.extend([fullkey, val])
        else:
            args.append(arg)

    parser = argparse.ArgumentParser(description="Headless power analyzer")
    parser.add_argument("--ip", required=True, help="IP address of the scope")
    parser.add_argument("--vch", required=True, help="Voltage channel (e.g., 1 or MATH1)")
    parser.add_argument("--ich", required=True, help="Current channel (e.g., 2 or MATH2)")
    parser.add_argument("--scale", type=float, default=1.0, help="Current scaling factor (A/V)")
    parser.add_argument("--dc", action="store_true", help="If present, DO NOT remove DC offset")
    parser.add_argument("--interval", type=float, default=5.0, help="Interval between samples (s)")
    parser.add_argument("--duration", type=float, help="Total duration in hours")
    parser.add_argument("--count", type=int, help="Number of iterations (alternative to duration)")
    parser.add_argument("--output", type=str, help="Output CSV file (default: auto-named)")
    parser.add_argument("--debug", choices=["FULL", "MINIMAL"], default="MINIMAL")
    return parser.parse_args(args)

def main():
    args = parse_args()

    set_debug_level(args.debug)

    scope = connect_scope(args.ip)
    if not scope:
        print("❌ Failed to connect to scope")
        sys.exit(1)

    app_state.scope = scope
    app_state.scope_ip = args.ip

    if args.output:
        csv_path = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs("oszi_csv", exist_ok=True)
        csv_path = f"oszi_csv/power_log_{ts}.csv"

    total_iterations = args.count
    if not total_iterations and args.duration:
        total_iterations = int((args.duration * 3600) // args.interval)
    if not total_iterations:
        print("❌ Please specify either --duration or --count")
        sys.exit(1)

    remove_dc = not args.dc  # Flip logic: default = True

    print(f"📡 Running power analysis for {total_iterations} samples at {args.interval}s interval")
    print(f"💾 Logging to {csv_path}")

    energy_wh = 0.0
    energy_vah = 0.0
    energy_varh = 0.0

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Timestamp", "P (W)", "S (VA)", "Q (VAR)", "PF",
            "PF Angle (°)", "Vrms (V)", "Irms (A)",
            "Real Energy (Wh)", "Apparent Energy (VAh)", "Reactive Energy (VARh)"
        ])

        start_time = time.time()

        try:
            for i in range(total_iterations):
                result = compute_power_from_scope(
                    scope, args.vch, args.ich,
                    remove_dc=remove_dc,
                    current_scale=args.scale
                )

                if result is None:
                    log_debug("⚠️ No result — skipping", level="MINIMAL")
                    time.sleep(args.interval)
                    continue

                now = datetime.now().isoformat()
                elapsed_hr = (time.time() - start_time) / 3600.0

                P = result.get("Real Power (P)", 0.0)
                S = result.get("Apparent Power (S)", 0.0)
                Q = result.get("Reactive Power (Q)", 0.0)

                energy_wh = P * elapsed_hr
                energy_vah = S * elapsed_hr
                energy_varh = Q * elapsed_hr

                row = [
                    now,
                    P,
                    S,
                    Q,
                    result.get("Power Factor", ""),
                    result.get("Phase Angle (deg)", ""),
                    result.get("Vrms", ""),
                    result.get("Irms", ""),
                    energy_wh,
                    energy_vah,
                    energy_varh
                ]
                writer.writerow(row)
                f.flush()

                print(f"[{i+1}/{total_iterations}] ✅ Logged at {now}")
                time.sleep(args.interval)

            print("✅ Power logging completed.")

        except KeyboardInterrupt:
            print("\n🛑 Interrupted by user. Exiting safely...")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
