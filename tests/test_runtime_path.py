"""Regression tests for the PATH fix that makes `vncdo` findable.

Reported symptom: the app connected to the scope but never produced a
screenshot. Cause: the capture thread runs the bare command name `vncdo`, which
vncdotool installs into the virtualenv's bin/ directory. Launching the app
through the virtualenv's interpreter without activating it (``./venv/bin/python
main.py``, a desktop launcher) left that directory off PATH, so every capture
raised ``FileNotFoundError: 'vncdo'`` and was only written to the debug log.
"""

import os
import sys

from utils import runtime


def _interpreter_bindir():
    return os.path.dirname(os.path.abspath(sys.executable))


def test_venv_bin_is_prepended_when_missing_from_path(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    runtime.ensure_venv_bin_on_path()

    assert os.environ["PATH"].split(os.pathsep)[0] == _interpreter_bindir()


def test_an_already_present_bindir_is_left_alone(monkeypatch):
    bindir = _interpreter_bindir()
    original = os.pathsep.join(["/usr/bin", bindir, "/bin"])
    monkeypatch.setenv("PATH", original)

    runtime.ensure_venv_bin_on_path()

    assert os.environ["PATH"] == original


def test_empty_path_entries_are_not_introduced(monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "", "/bin"]))

    runtime.ensure_venv_bin_on_path()

    entries = os.environ["PATH"].split(os.pathsep)
    assert "" not in entries
    assert entries[0] == _interpreter_bindir()


def test_capture_still_passes_a_bare_vncdo_command(monkeypatch, tmp_path):
    """The fix works via PATH, so call sites keep the injection-safe argv."""
    import subprocess

    from gui import image_display

    recorded = []

    def record_run(command, **options):
        recorded.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(image_display.subprocess, "run", record_run)

    image_display.capture_screenshot("192.168.1.100", tmp_path / "shot.png")

    assert recorded[0][0] == "vncdo"
