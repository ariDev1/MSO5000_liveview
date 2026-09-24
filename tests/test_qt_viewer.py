import os
from types import SimpleNamespace

import pytest

from qt_app.backend import PowerLog, ScopeBackend, channel_name, current_scale, logging_channels


@pytest.mark.parametrize("input_name, expected", [
    ("1", "CHAN1"), ("CH1", "CHAN1"), ("chan2", "CHAN2"),
    ("MATH4", "MATH4"),
])
def test_qt_channel_inputs_match_existing_waveform_source_names(input_name, expected):
    assert channel_name(input_name) == expected


@pytest.mark.parametrize("name", ["", "0", "5", "MATH5", "CHAN1;:STOP"])
def test_qt_rejects_invalid_channel_names(name):
    with pytest.raises(ValueError):
        channel_name(name)


def test_qt_probe_scaling_uses_existing_shunt_and_clamp_conventions():
    assert current_scale("shunt", "0.01", "1.1") == pytest.approx(110)
    assert current_scale("clamp", "100", "1") == pytest.approx(10)
    with pytest.raises(ValueError):
        current_scale("shunt", "0", "1")


def test_qt_logging_passes_analog_channels_as_integers_to_existing_logger():
    assert logging_channels("1,CH2,MATH3") == [1, 2, "MATH3"]


def test_qt_backend_detects_lost_scope_connection(monkeypatch):
    class BrokenScope:
        def query(self, command):
            raise OSError("network cable unplugged")

    backend = ScopeBackend("192.168.1.10")
    backend.scope = BrokenScope()
    with pytest.raises(ConnectionError, match="connection lost"):
        backend.snapshot()


def test_qt_power_csv_keeps_existing_columns_and_sample_average(tmp_path, monkeypatch):
    values = iter((100.0, 110.0))
    monkeypatch.setattr("qt_app.backend.time", SimpleNamespace(time=lambda: next(values)))
    log = PowerLog(str(tmp_path))
    result = {"Real Power (P)": 100.0, "Apparent Power (S)": 100.0,
              "Reactive Power (Q)": 0.0, "Power Factor": 1.0,
              "Phase Angle (deg)": 0.0, "Vrms": 100.0, "Irms": 1.0}
    log.add(result, {"Method": "standard"})
    result["Real Power (P)"] = 200.0
    average, energy = log.add(result, {"Method": "standard"})
    assert average["P"] == 150.0
    assert energy[0] == pytest.approx(1500 / 3600)
    with open(log.path, encoding="utf-8") as output:
        rows = output.read()
    assert "Real Energy (Wh)" in rows
    assert "# Method,standard" in rows


def test_qt_shell_handles_background_callbacks_without_a_scope(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from qt_app import window as qt_window

    monkeypatch.setattr(qt_window.ScopeBackend, "connect", lambda self: "SIMULATED SCOPE")
    monkeypatch.setattr(qt_window.MainWindow, "capture_image", lambda self: None)
    app = QApplication.instance() or QApplication([])
    viewer = qt_window.MainWindow("127.0.0.1")
    viewer.show()
    QTimer.singleShot(100, viewer.close)
    QTimer.singleShot(150, app.quit)
    app.exec()
    assert viewer.idn == "SIMULATED SCOPE"
    assert viewer.closing


def test_qt_power_measurement_uses_shared_backend_and_writes_csv(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from qt_app.tabs import PowerTab

    app = QApplication.instance() or QApplication([])
    calls = []
    notices = []
    result = {"Real Power (P)": 230.0, "Apparent Power (S)": 460.0,
              "Reactive Power (Q)": 398.37, "Power Factor": 0.5,
              "Phase Angle (deg)": 60.0, "Vrms": 230.0, "Irms": 2.0}

    class SimulatedBackend:
        def measure(self, *args):
            calls.append(args)
            return result

    def submit(operation, done):
        done(operation())

    tab = PowerTab(submit, SimulatedBackend(), notices.append)
    tab.log = PowerLog(str(tmp_path))
    tab.probe_value.setText("0.01")
    tab.measure()
    assert calls == [("CHAN1", "CHAN2", 100.0, False, "standard", False, False)]
    assert "230.000 W" in tab.results.toPlainText()
    assert os.path.isfile(tab.log.path)
    tab.expected_power.setText("460")
    tab.calibrate()
    assert tab.correction.text() == "2.0000"
    assert calls[-1] == ("CHAN1", "CHAN2", 200.0, False, "standard", False, False)
    assert tab.log.count == 2
    assert not notices
    tab.close()
