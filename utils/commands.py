"""Resolve helper executables that pip installs alongside the interpreter."""

import os
import shutil
import sys


def resolve_command(name):
    """Return an absolute path for `name`, preferring the running virtualenv.

    Tools installed by pip live next to the interpreter that runs the app:
    ``vncdo`` (from vncdotool) is written to ``venv/bin/`` alongside
    ``venv/bin/python``. That directory is only on PATH when the virtualenv is
    activated, so starting the app as ``./venv/bin/python main.py`` -- or from a
    desktop launcher -- made every VNC capture fail with ``FileNotFoundError:
    'vncdo'`` while the scope still connected fine over SCPI.

    Looking next to the interpreter first keeps the call sites independent of
    PATH. PATH is still consulted so a system-wide install keeps working, and
    the bare name is returned as a last resort so a genuinely missing tool
    still raises the original error rather than failing somewhere subtler.
    """
    bindir = os.path.dirname(os.path.abspath(sys.executable))
    return shutil.which(name, path=bindir) or shutil.which(name) or name
