"""Tests for helper-command resolution.

Reported symptom: the app connected to the scope but never produced a
screenshot. Cause: the capture threads ran the bare command name ``vncdo``,
which vncdotool installs next to the interpreter (``venv/bin/vncdo``). Starting
the app through that interpreter without activating it left the directory off
PATH, so every capture raised ``FileNotFoundError: 'vncdo'`` and only reached
the debug log. ``resolve_command`` now looks next to the interpreter first.
"""

import sys

from utils.commands import resolve_command


def _write_executable(directory, name):
    path = directory / name
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_prefers_the_executable_next_to_the_running_interpreter(monkeypatch, tmp_path):
    bindir = tmp_path / "venv-bin"
    bindir.mkdir()
    expected = _write_executable(bindir, "vncdo")
    monkeypatch.setattr(sys, "executable", str(bindir / "python3"))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    assert resolve_command("vncdo") == str(expected)


def test_falls_back_to_path_for_a_system_wide_install(monkeypatch, tmp_path):
    bindir = tmp_path / "empty-venv-bin"
    bindir.mkdir()
    on_path = tmp_path / "usr-bin"
    on_path.mkdir()
    expected = _write_executable(on_path, "vncdo")
    monkeypatch.setattr(sys, "executable", str(bindir / "python3"))
    monkeypatch.setenv("PATH", str(on_path))

    assert resolve_command("vncdo") == str(expected)


def test_non_executable_neighbour_is_ignored(monkeypatch, tmp_path):
    bindir = tmp_path / "venv-bin"
    bindir.mkdir()
    (bindir / "vncdo").write_text("data file, not a program")
    monkeypatch.setattr(sys, "executable", str(bindir / "python3"))
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))

    assert resolve_command("vncdo") == "vncdo"


def test_missing_tool_keeps_the_bare_name_for_a_clear_error(monkeypatch, tmp_path):
    bindir = tmp_path / "venv-bin"
    bindir.mkdir()
    monkeypatch.setattr(sys, "executable", str(bindir / "python3"))
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))

    assert resolve_command("vncdo") == "vncdo"
