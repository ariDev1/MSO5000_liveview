"""Runtime environment fixes shared by the Tk and Qt front ends."""

import os
import sys


def ensure_venv_bin_on_path():
    """Prepend the running interpreter's bin/ directory to PATH.

    The app drives helper executables that pip installs *next to the
    interpreter* rather than into the system: ``vncdo`` (from vncdotool) for VNC
    screenshots, and the interpreter itself for the CSV plotting helpers
    (``gui/power_analysis.py`` spawns ``python3 utils/plot_rigol_csv.py``).

    When the app is started through the virtualenv's own interpreter without
    activating it -- e.g. ``./venv/bin/python main.py``, ``run-native.sh`` from a
    clean shell, or a desktop launcher -- that directory is missing from PATH.
    The scope then connects fine over SCPI while every screenshot silently fails
    with ``FileNotFoundError: 'vncdo'``, because the capture thread only logs the
    error to the debug log.

    Activating the virtualenv (or running in Docker) already does this. Doing it
    here makes every launch path behave the same, and keeps the bare ``vncdo`` /
    ``python3`` command names in the call sites unchanged.
    """
    bindir = os.path.dirname(os.path.abspath(sys.executable))
    if not bindir or not os.path.isdir(bindir):
        return

    entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    if bindir in entries:
        return

    os.environ["PATH"] = os.pathsep.join([bindir, *entries])
