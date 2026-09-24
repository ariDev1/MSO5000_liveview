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
    monkeypatch.setattr("scpi.licenses.get_license_options", lambda ip: [])
    monkeypatch.setattr(qt_window.MainWindow, "capture_image", lambda self: None)
    app = QApplication.instance() or QApplication([])
    viewer = qt_window.MainWindow("127.0.0.1")
    viewer.show()
    QTimer.singleShot(100, viewer.close)
    QTimer.singleShot(150, app.quit)
    app.exec()
    assert viewer.idn == "SIMULATED SCOPE"
    assert viewer.closing


def test_scope_display_grows_with_splitter_instead_of_pixmap(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QPixmap
    from PySide6.QtWidgets import QApplication
    from qt_app import window as qt_window

    monkeypatch.setattr(qt_window.MainWindow, "connect_scope", lambda self: None)
    monkeypatch.setattr("scpi.licenses.get_license_options", lambda ip: [])
    app = QApplication.instance() or QApplication([])
    viewer = qt_window.MainWindow("127.0.0.1")
    viewer.resize(1500, 1000)
    viewer.show()
    app.processEvents()
    image = QPixmap(1024, 600)
    image.fill(QColor("#ffffff"))
    viewer.display.set_image(image)
    app.processEvents()
    assert viewer.display.height() > 250
    assert viewer.display.height() > viewer.tabs.height()
    assert viewer.display.sizeHint().height() == 500
    assert viewer.display.image.size() == image.size()
    rendered = viewer.display.grab().toImage()
    assert rendered.pixelColor(rendered.width() // 2, rendered.height() // 2) == QColor("#ffffff")
    viewer.close()


def test_advanced_analysis_reuses_harmonic_and_noise_algorithms(monkeypatch):
    import numpy as np
    from qt_app import analysis

    fs = 5000
    t = np.arange(fs) / fs
    voltage = np.sqrt(2) * np.sin(2 * np.pi * 50 * t)
    monkeypatch.setattr(analysis, "acquire", lambda scope, channel, raw=False: (t, voltage, fs))
    result, freq, amplitude = analysis.harmonics(None, "CHAN1")
    assert result.f1_hz == pytest.approx(50, rel=0.01)
    assert result.thd < 0.01
    assert freq.shape == amplitude.shape
    spectrum = analysis.noise(voltage, fs, "PSD+CFAR", {"nfft": 1024, "seglen": 1024})
    assert "plot_x" in spectrum and "detections" in spectrum


def test_bh_reconstruction_uses_shared_waveform_fetch(monkeypatch):
    import numpy as np
    from qt_app import analysis

    fs = 1000
    t = np.arange(2000) / fs
    waveforms = {"CHAN1": np.cos(2 * np.pi * 10 * t),
                 "CHAN2": np.sin(2 * np.pi * 10 * t)}
    monkeypatch.setattr(analysis, "acquire",
                        lambda scope, channel, raw=False: (t, waveforms[channel], fs))
    h, b, dt = analysis.bh_curve(None, "CHAN1", "CHAN2", 20, 25, 50,
                                  "shunt", 0.1, cycle=False)
    assert len(h) == len(b) == len(t)
    assert np.isfinite(b).all()
    assert np.max(np.abs(h)) == pytest.approx(4000, rel=0.01)
    assert dt == pytest.approx(1 / fs)


@pytest.mark.parametrize("method", [
    "PSD+CFAR", "Spectrogram", "MSC", "Multitaper", "Spectral Kurtosis",
    "Cepstrum", "Matched Filter", "AR Spectrum", "Cyclostationary", "Bicoherence",
])
def test_qt_noise_modes_call_existing_algorithms(method, tmp_path):
    import numpy as np
    from qt_app.analysis import noise

    fs = 2048
    t = np.arange(2048) / fs
    signal = np.sin(2 * np.pi * 50 * t)
    template = tmp_path / "template.csv"
    np.savetxt(template, signal[:128], delimiter=",")
    result = noise(signal, fs, method, {"nfft": 256, "seglen": 256, "hop": 128},
                   other=signal, template_path=str(template))
    assert result["method"] == method


def test_qt_advanced_tabs_render_existing_analysis_results(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import numpy as np
    from PySide6.QtWidgets import QApplication
    from qt_app import analysis
    from qt_app import advanced
    from qt_app.advanced import BHCurveTab, HarmonicsTab, NoiseTab

    app = QApplication.instance() or QApplication([])
    fs = 5000
    t = np.arange(fs) / fs
    waves = {"CHAN1": np.sqrt(2) * np.sin(2 * np.pi * 50 * t),
             "CHAN2": np.sqrt(2) * np.cos(2 * np.pi * 50 * t)}
    monkeypatch.setattr(analysis, "acquire",
                        lambda scope, channel, raw=False: (t, waves[channel], fs))
    monkeypatch.setattr(advanced, "acquire", analysis.acquire)

    class Scope:
        def _connected(self):
            return self

    def submit(operation, done):
        try:
            done(operation())
        except Exception as error:
            done(error)

    notices = []
    harmonic = HarmonicsTab(submit, Scope(), notices.append)
    harmonic.run()
    assert harmonic.last.f1_hz == pytest.approx(50, rel=0.01)
    assert harmonic.table.rowCount() > 0
    harmonic.show_surface()
    harmonic.run()
    assert harmonic.surface.history
    harmonic.surface.dialog.close()
    bh = BHCurveTab(submit, Scope(), notices.append)
    bh.cycle.setChecked(False)
    bh.run()
    assert bh.last is not None, notices
    inspector = NoiseTab(submit, Scope(), notices.append)
    inspector.nfft.setValue(1024)
    inspector.run()
    assert inspector.last is not None, notices
    inspector.show_surface()
    inspector.run()
    assert inspector.surface.history
    inspector.surface.dialog.close()
    assert not notices
    for tab in (harmonic, bh, inspector):
        tab.close()


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
    tab.resize(1100, 700)
    tab.show()
    app.processEvents()
    assert not tab.plot.grab().isNull()
    assert calls == [("CHAN1", "CHAN2", 100.0, False, "standard", False, False)]
    assert "Real power (W)" in tab.results.toPlainText()
    assert "230" in tab.results.toPlainText()
    assert os.path.isfile(tab.log.path)
    tab.expected_power.setText("460")
    tab.calibrate()
    assert tab.correction.text() == "2.0000"
    assert calls[-1] == ("CHAN1", "CHAN2", 200.0, False, "standard", False, False)
    assert tab.log.count == 2
    tab.show_3d()
    assert tab.pq3d is not None
    tab.measure()
    tab.pq3d[0].close()
    assert not notices
    tab.close()
