import subprocess

import pytest

import main
from gui import image_display


@pytest.mark.parametrize(
    ("raw_address", "expected"),
    [
        ("192.168.1.100", "192.168.1.100"),
        (" 10.0.0.5 ", "10.0.0.5"),
        ("127.0.0.1", "127.0.0.1"),
    ],
)
def test_scope_ipv4_address_is_validated_and_normalized(raw_address, expected):
    assert main.normalize_scope_ipv4(raw_address) == expected


@pytest.mark.parametrize(
    "raw_address",
    [
        "192.168.1.100; touch /tmp/unwanted",
        "192.168.1.100 && id",
        "scope.example.test",
        "999.1.1.1",
        "",
    ],
)
def test_invalid_scope_ipv4_address_is_rejected(raw_address):
    with pytest.raises(ValueError, match="valid IPv4"):
        main.normalize_scope_ipv4(raw_address)


def test_screenshot_capture_uses_an_argument_list_without_a_shell(monkeypatch, tmp_path):
    calls = []

    def record_run(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(image_display.subprocess, "run", record_run)
    output_path = tmp_path / "scope screenshot.tmp.png"

    image_display.capture_screenshot("192.168.1.100", output_path)

    assert calls == [
        (
            ["vncdo", "-s", "192.168.1.100", "capture", str(output_path)],
            {"check": True},
        )
    ]
