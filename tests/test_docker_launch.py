import os
from pathlib import Path
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_executable(path, content):
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_build_version_accepts_explicit_container_metadata(tmp_path):
    environment = os.environ.copy()
    environment.update(
        {
            "MSO5000_BUILD_DATE": "2026-08-24 14:30 UTC",
            "MSO5000_BUILD_COMMIT": "abc1234",
            "MSO5000_BUILD_VERSION": "v-test",
        }
    )

    subprocess.run(
        [str(PROJECT_ROOT / ".venv/bin/python"), str(PROJECT_ROOT / "build_version.py")],
        check=True,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )

    generated = (tmp_path / "version.py").read_text(encoding="utf-8")
    assert 'VERSION = "v-test"' in generated
    assert 'GIT_COMMIT = "abc1234"' in generated
    assert 'BUILD_DATE = "2026-08-24 14:30 UTC"' in generated


def test_docker_build_wrapper_passes_git_metadata_and_requested_image(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker-build.log"

    make_executable(
        bin_dir / "git",
        '#!/bin/sh\ncase "$1" in\n  describe) echo v-test ;;\n  rev-parse) echo abc1234 ;;\nesac\n',
    )
    make_executable(
        bin_dir / "date",
        '#!/bin/sh\necho "2026-08-24 14:30 UTC"\n',
    )
    make_executable(
        bin_dir / "docker",
        '#!/bin/sh\nprintf "<%s>\\n" "$@" > "$DOCKER_LOG"\n',
    )

    environment = os.environ.copy()
    environment.update(
        {
            "DOCKER_LOG": str(docker_log),
            "PATH": f"{bin_dir}:{environment['PATH']}",
        }
    )

    subprocess.run(
        [
            "bash",
            str(PROJECT_ROOT / "build-docker.sh"),
            "registry.example/mso5000_liveview:latest",
        ],
        check=True,
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )

    arguments = docker_log.read_text(encoding="utf-8").splitlines()
    assert "<MSO5000_VERSION=v-test>" in arguments
    assert "<MSO5000_COMMIT=abc1234>" in arguments
    assert "<MSO5000_BUILD_DATE=2026-08-24 14:30 UTC>" in arguments
    assert "<registry.example/mso5000_liveview:latest>" in arguments


def test_run_script_uses_documented_image_and_preserves_mount_path(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    xhost_log = tmp_path / "xhost.log"
    operator_home = tmp_path / "operator home"
    operator_home.mkdir()

    make_executable(
        bin_dir / "docker",
        '#!/bin/sh\nprintf "<%s>\\n" "$@" > "$DOCKER_LOG"\n',
    )
    make_executable(
        bin_dir / "xhost",
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$XHOST_LOG"\n',
    )

    environment = os.environ.copy()
    environment.update(
        {
            "DISPLAY": ":0",
            "DOCKER_LOG": str(docker_log),
            "HOME": str(operator_home),
            "PATH": f"{bin_dir}:{environment['PATH']}",
            "XDG_SESSION_TYPE": "x11",
            "XHOST_LOG": str(xhost_log),
        }
    )

    subprocess.run(
        ["bash", str(PROJECT_ROOT / "run.sh")],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    docker_arguments = docker_log.read_text(encoding="utf-8").splitlines()
    assert "<mso5000_liveview>" in docker_arguments
    assert f"<{operator_home}/oszi_csv:/app/oszi_csv>" in docker_arguments
    assert xhost_log.read_text(encoding="utf-8").splitlines() == [
        "+si:localuser:root",
        "-si:localuser:root",
    ]


def test_run_script_stops_when_xhost_is_missing(tmp_path):
    environment = os.environ.copy()
    environment.update(
        {
            "DISPLAY": ":0",
            "HOME": str(tmp_path),
            "PATH": str(tmp_path),
            "XDG_SESSION_TYPE": "x11",
        }
    )

    result = subprocess.run(
        ["/usr/bin/bash", str(PROJECT_ROOT / "run.sh")],
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "xhost is required" in result.stderr
    assert "xorg-xhost" in result.stderr


def test_entrypoint_resolves_socket_for_active_display(tmp_path):
    environment = os.environ.copy()
    environment.update(
        {
            "DISPLAY": ":7.0",
            "X11_SOCKET_DIR": str(tmp_path / ".X11-unix"),
        }
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; display_socket_path',
            "bash",
            str(PROJECT_ROOT / "entrypoint.sh"),
        ],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == f"{tmp_path}/.X11-unix/X7"
