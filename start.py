#!/usr/bin/env python3
"""Unified launcher: let the operator choose between the Tk and Qt GUIs.

Usage:
    python3 start.py [--gui {tk,qt,ask}] [args forwarded to the GUI ...]
    python3 start.py --gui qt --ip 192.168.1.10
    python3 start.py --gui tk --ip 192.168.1.10 --noMarquee
    MSO5000_GUI=qt python3 start.py --ip 192.168.1.10

Behavior:
    --gui tk   launch classic Tk app (main.py)
    --gui qt   launch Qt viewer (qt_app.main)
    --gui ask  (default) interactive terminal menu when stdin is a TTY,
               otherwise fall back to Tk for backward compatibility
               (old `python3 main.py` / Docker behavior).

All other arguments are forwarded verbatim to the chosen GUI, so
--ip, --samples, --noMarquee, --version, --help keep working. Use only
stdlib here so the chooser itself never fails on missing GUI deps.
"""

import argparse
import importlib.util
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TK_ENTRY = os.path.join(PROJECT_ROOT, "main.py")
QT_MODULE = "qt_app.main"

TK_LABEL = "Tk  (classic, stable, default)"
QT_LABEL = "Qt  (modern viewer, needs PySide6)"


def gui_available(name: str) -> bool:
    """Check importability without heavy side effects (no QApplication)."""
    try:
        if name == "tk":
            return importlib.util.find_spec("tkinter") is not None
        if name == "qt":
            return importlib.util.find_spec("PySide6") is not None
    except Exception:
        return False
    return False


def parse_launcher_args(argv):
    parser = argparse.ArgumentParser(
        description="MSO5000 Live Monitor - choose Tk or Qt GUI. "
        "Extra args are forwarded to the selected GUI.",
        epilog="Examples:\n"
        "  python3 start.py                  # interactive choice\n"
        "  python3 start.py --gui tk --ip 192.168.1.10\n"
        "  python3 start.py --gui qt --ip 192.168.1.10\n"
        "  MSO5000_GUI=qt python3 start.py   # env-var default (Docker friendly)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--gui",
        choices=["tk", "qt", "ask"],
        default=os.environ.get("MSO5000_GUI", "ask"),
        help="Which GUI to run (default: $MSO5000_GUI or 'ask').",
    )
    args, forward = parser.parse_known_args(argv)
    # Normalize env-provided values like "TK" / "Qt".
    args.gui = str(args.gui).lower()
    if args.gui not in ("tk", "qt", "ask"):
        parser.error("--gui must be one of: tk, qt, ask")
    return args, forward


def prompt_choice() -> str:
    tk_ok = gui_available("tk")
    qt_ok = gui_available("qt")
    print("MSO5000 Live Monitor - select GUI:")
    print(f"  1) {TK_LABEL} {'[available]' if tk_ok else '[tkinter MISSING]'}")
    print(f"  2) {QT_LABEL} {'[available]' if qt_ok else '[PySide6 MISSING]'}")
    try:
        answer = input("Choice [1/2] (Enter = auto): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return "tk"  # backward-compatible default
    if answer in ("1", "tk", "t"):
        return "tk"
    if answer in ("2", "qt", "q"):
        return "qt"
    # Empty/invalid: prefer Qt only if Tk is missing but Qt exists.
    if not tk_ok and qt_ok:
        return "qt"
    return "tk"


def resolve_gui(choice: str) -> str:
    if choice in ("tk", "qt"):
        return choice
    # "ask": prompt only when interactive, else keep old default (Tk).
    if sys.stdin.isatty():
        return prompt_choice()
    return "tk"


def fail_missing_dependency(gui: str) -> int:
    if gui == "qt":
        print(
            "ERROR: Qt GUI requested but PySide6 is not installed.\n"
            "  pip install -r requirements-qt.txt\n"
            "On Ubuntu/Debian you may also need: sudo apt install libxcb-cursor0",
            file=sys.stderr,
        )
    else:
        print(
            "ERROR: Tk GUI requested but tkinter is not installed.\n"
            "  Ubuntu/Debian: sudo apt install python3-tk",
            file=sys.stderr,
        )
    return 2


def build_command(gui: str, forward_args) -> list:
    if gui == "qt":
        return [sys.executable, "-m", QT_MODULE] + forward_args
    return [sys.executable, TK_ENTRY] + forward_args


def main(argv=None) -> int:
    args, forward = parse_launcher_args(argv if argv is not None else sys.argv[1:])
    gui = resolve_gui(args.gui)

    if not gui_available(gui):
        return fail_missing_dependency(gui)

    if gui == "tk" and not os.path.isfile(TK_ENTRY):
        print(f"ERROR: Tk entry point not found: {TK_ENTRY}", file=sys.stderr)
        return 2

    cmd = build_command(gui, forward)
    print(f"Starting {gui.upper()} GUI: {' '.join(cmd)}")
    os.chdir(PROJECT_ROOT)
    os.execv(cmd[0], cmd)
    return 0  # unreachable (exec replaces the process)


if __name__ == "__main__":
    sys.exit(main())
