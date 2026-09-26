"""Backend selection + GPU spectrum view (qt_app/surface_gl.py).

The GL widget test deliberately never shows any widget: on headless
platforms QOpenGLWidget cannot paint, while construction and data updates
are fully exercisable offscreen.
"""

import numpy as np
import pytest

from qt_app import surface_gl


def _history(n=5, m=50, seed=0):
    rng = np.random.default_rng(seed)
    axis = np.linspace(0.0, 250_000.0, m)
    rows = [(axis, np.abs(rng.standard_normal(m)).cumsum() + 1.0)
            for _ in range(n)]
    return rows, [yy for _, yy in rows]


def test_select_backend_explicit_mpl(monkeypatch):
    monkeypatch.setenv("MSO5000_3D", "mpl")
    assert surface_gl.select_backend() == "mpl"


def test_select_backend_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("MSO5000_3D", "vulkan")
    with pytest.raises(ValueError):
        surface_gl.select_backend()


def test_select_backend_forced_gl_without_stack_raises(monkeypatch):
    monkeypatch.setenv("MSO5000_3D", "gl")
    monkeypatch.setattr(surface_gl, "GL_AVAILABLE", False)
    with pytest.raises(RuntimeError):
        surface_gl.select_backend()


def test_select_backend_auto_without_stack_is_mpl(monkeypatch):
    monkeypatch.setenv("MSO5000_3D", "auto")
    monkeypatch.setattr(surface_gl, "GL_AVAILABLE", False)
    assert surface_gl.select_backend() == "mpl"


def test_select_backend_auto_avoids_headless_platform(monkeypatch):
    monkeypatch.setenv("MSO5000_3D", "auto")
    monkeypatch.setattr(surface_gl, "GL_AVAILABLE", True)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert surface_gl.select_backend() == "mpl"


def test_select_backend_auto_picks_gl_on_desktop(monkeypatch):
    monkeypatch.setenv("MSO5000_3D", "auto")
    monkeypatch.setattr(surface_gl, "GL_AVAILABLE", True)
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    assert surface_gl.select_backend() == "gl"


def test_format_hz_units():
    assert surface_gl.format_hz(500.0) == "500 Hz"
    assert surface_gl.format_hz(2_500.0) == "2.5 kHz"
    assert surface_gl.format_hz(1_500_000.0) == "1.5 MHz"


def test_prepare_values_log_needs_positive_data():
    positive = [np.array([1e-9, 1e-3, 1.0])]
    values, active, note = surface_gl.prepare_values(positive, True)
    assert active is True and note == ""
    assert values[0].tolist() == pytest.approx([-9.0, -3.0, 0.0])

    db_scale = [np.array([-95.0, -40.0, -3.0])]  # already-logged spectra
    values, active, note = surface_gl.prepare_values(db_scale, True)
    assert active is False
    assert values[0].tolist() == [-95.0, -40.0, -3.0]
    assert "Log Z" in note

    values, active, note = surface_gl.prepare_values(db_scale, False)
    assert active is False and note == ""
    assert values[0].tolist() == [-95.0, -40.0, -3.0]


def test_range_hint_flags_crushed_linear_scale():
    assert surface_gl.range_hint(1e-12, 1.0, False) != ""
    assert "Log Z" in surface_gl.range_hint(1e-12, 1.0, False)
    assert surface_gl.range_hint(1e-12, 1.0, True) == ""
    assert surface_gl.range_hint(0.5, 2.0, False) == ""
    assert surface_gl.range_hint(0.0, 0.0, False) == ""


@pytest.mark.skipif(not surface_gl.GL_AVAILABLE, reason="GPU stack missing")
def test_gl_view_redraws_all_modes_headless():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    view = surface_gl.SpectrumGLView()
    history, values = _history()
    vmin = float(min(v.min() for v in values))
    vmax = float(max(v.max() for v in values))

    view.redraw(history, values, render_mode="lines",
                vmin=vmin, vmax=vmax, level_label="Level")
    assert len(view._trace_items) == len(history)
    assert view._surf_item is None
    assert "5 traces" in view.info.text()
    assert "250 kHz" in view.info.text()

    # Level colors vary along each trace (shared scale), so the legend
    # is meaningful point-by-point instead of one flat trace color.
    first_colors = view._trace_items[0].color
    assert isinstance(first_colors, np.ndarray)
    assert first_colors.shape == (len(history[0][0]), 4)
    assert len(np.unique(first_colors.round(3), axis=0)) > 5

    texts = {key: item.text for key, item in view._texts.items()}
    assert texts["x0"] == "0 Hz"
    assert texts["x1"] == "125 kHz"
    assert texts["x2"] == "250 kHz"
    assert texts["y0"] == "older"
    assert texts["y1"] == "newer"
    assert texts["z0"] == f"{vmin:.3g}"
    assert texts["z2"] == f"{vmax:.3g}"
    assert texts["tx"] == "Frequency (Hz)"
    assert texts["ty"] == "Acquisition"
    assert texts["tz"] == "Level"

    view.redraw(history, values, render_mode="surface",
                vmin=vmin, vmax=vmax, level_label="Level")
    assert view._surf_item is not None
    assert view._trace_items == []

    view.redraw(history, values, render_mode="wire",
                vmin=vmin, vmax=vmax, level_label="log₁₀(Level)")
    assert len(view._trace_items) == len(history)
    assert view._surf_item is None

    # Wire rows share the legend scale per point (not one flat color).
    wire_colors = view._trace_items[0].color
    assert isinstance(wire_colors, np.ndarray)
    assert wire_colors.shape == (len(history[0][0]), 4)
    assert len(np.unique(wire_colors.round(3), axis=0)) > 5

    view.redraw([], [], render_mode="lines",
                vmin=0.0, vmax=1.0, level_label="Level")
    assert view._trace_items == []


@pytest.mark.skipif(not surface_gl.GL_AVAILABLE, reason="GPU stack missing")
def test_gl_view_single_trace_surface_falls_back_to_lines():
    """A one-row mesh has no faces; the first run must still show."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    view = surface_gl.SpectrumGLView()
    axis = np.linspace(0.0, 1000.0, 64)
    spectrum = np.abs(np.random.default_rng(3).standard_normal(64)) + 0.1
    history = [(axis, spectrum)]

    view.redraw(history, [spectrum], render_mode="surface",
                vmin=float(spectrum.min()), vmax=float(spectrum.max()),
                level_label="Level")
    assert view._surf_item is None
    assert len(view._trace_items) == 1


def test_surface_history_db_data_with_log_z_stays_visible():
    """dB spectra + Log Z ticked must fall back to linear, not flatline."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from qt_app.advanced import SurfaceHistory

    surface = SurfaceHistory(None)
    surface.log_z.setChecked(True)
    surface.mode.setCurrentIndex(2)  # surface: single row must fall back
    axis = np.linspace(0.0, 2500.0, 128)
    db_spectrum = -80.0 + 20.0 * np.abs(
        np.random.default_rng(4).standard_normal(128))
    surface.history = [(axis, db_spectrum)]
    surface._redraw()
    if surface._backend == "gl":
        pytest.skip("GL backend needs a display context for paint")
    assert len(surface.plot.axes.get_lines()) == 1
    surface.dialog.close()


@pytest.mark.skipif(not surface_gl.GL_AVAILABLE, reason="GPU stack missing")
def test_gl_view_shows_range_hint_for_crushed_scale():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    view = surface_gl.SpectrumGLView()
    axis = np.linspace(0.0, 2500.0, 64)
    spectrum = np.full(64, 1e-9)
    spectrum[5] = 1.0  # fundamental spike, linear scale
    history = [(axis, spectrum)] * 3
    values = [spectrum] * 3
    hint = surface_gl.range_hint(1e-9, 1.0, False)
    assert "Log Z" in hint
    view.redraw(history, values, render_mode="lines",
                vmin=1e-9, vmax=1.0, level_label="Level",
                range_hint=hint)
    assert "Log Z" in view.info.text()
    assert len(view._trace_items) == 3


@pytest.mark.skipif(not surface_gl.GL_AVAILABLE, reason="GPU stack missing")
def test_gl_view_pivots_at_cube_center():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    view = surface_gl.SpectrumGLView()

    def center():
        point = view.view.opts["center"]
        return (point.x(), point.y(), point.z())

    assert center() == (0.5, 0.5, 0.5)
    view.reset_view()
    assert center() == (0.5, 0.5, 0.5)


@pytest.mark.skipif(not surface_gl.GL_AVAILABLE, reason="GPU stack missing")
def test_gl_view_spin_turntable():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    view = surface_gl.SpectrumGLView()
    assert not view._spin_timer.isActive()
    view.spin_button.setChecked(True)
    assert view._spin_timer.isActive()
    before = float(view.view.opts["azimuth"])
    view._spin_step()
    after = float(view.view.opts["azimuth"])
    assert (after - before) % 360.0 == pytest.approx(1.5)
    view.spin_button.setChecked(False)
    assert not view._spin_timer.isActive()


def test_surface_controls_apply_live():
    """Stride/Mode/Log-Z take effect without pressing APPLY."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from qt_app.advanced import SurfaceHistory

    surface = SurfaceHistory(None)
    assert surface.stride_n == 1
    surface.stride.setValue(3)
    assert surface.stride_n == 3
    surface.mode.setCurrentIndex(1)  # wire
    assert surface.render_mode == "wire"
    surface.log_z.setChecked(True)
    assert surface.use_log is True
    surface.dialog.close()
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    view = surface_gl.SpectrumGLView()

    def center():
        point = view.view.opts["center"]
        return (point.x(), point.y(), point.z())

    assert center() == (0.5, 0.5, 0.5)
    view.reset_view()
    assert center() == (0.5, 0.5, 0.5)


def _noise_tab():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from qt_app.advanced import NoiseTab

    class Scope:
        def _connected(self):
            return self

    def submit(operation, done):
        try:
            done(operation())
        except Exception as error:
            done(error)

    return NoiseTab(submit, Scope(), lambda *args: None)


def test_noise_image_result_feeds_surface_history():
    tab = _noise_tab()
    rng = np.random.default_rng(1)
    image = rng.standard_normal((129, 48))  # (n_freq, n_time)

    tab._feed_surface_from_image(
        {"image": image, "extent": [0.0, 1.0, 0.0, 2500.0]})

    assert tab.surface is not None
    assert 0 < len(tab.surface.history) <= 8
    axis, spectrum = tab.surface.history[0]
    assert len(axis) == len(spectrum) == 250  # default pts/line
    assert axis[0] == pytest.approx(0.0)
    assert axis[-1] == pytest.approx(2500.0)


def test_noise_image_feed_skips_bad_columns():
    tab = _noise_tab()
    rng = np.random.default_rng(2)
    image = rng.standard_normal((65, 16))
    image[:, 2] = np.nan
    image[:, 10] = np.inf

    tab._feed_surface_from_image(
        {"image": image, "extent": [0.0, 1.0, 0.0, 1000.0]})

    assert tab.surface is not None
    assert len(tab.surface.history) == 6  # step 2 visits 8 cols, 2 skipped


def test_noise_image_feed_ignores_bad_shapes():
    tab = _noise_tab()
    tab._feed_surface_from_image({"image": np.zeros((1, 5))})
    tab._feed_surface_from_image({"image": "not an array"})
    tab._feed_surface_from_image({})
    assert tab.surface is None


def test_surface_history_log_z_default_per_tab():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from qt_app.advanced import SurfaceHistory

    assert SurfaceHistory(None).use_log is False
    assert SurfaceHistory(None, default_log_z=True).use_log is True


@pytest.mark.skipif(not surface_gl.GL_AVAILABLE, reason="GPU stack missing")
def _stage_with_models(monkeypatch):
    """One shared window + two tab models (never shown: headless-safe)."""
    pytest.importorskip("PySide6")
    monkeypatch.setenv("MSO5000_3D", "gl")
    surface_gl.drop_shared_stage()
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from qt_app.advanced import SurfaceHistory

    stage = surface_gl.get_shared_stage()
    first = SurfaceHistory(None, source_name="Harmonics")
    second = SurfaceHistory(None, source_name="Noise")
    axis_a = np.linspace(0.0, 1_000.0, 32)
    axis_b = np.linspace(0.0, 250_000.0, 32)
    first.history = [(axis_a, np.abs(
        np.random.default_rng(11).standard_normal(32)) + 0.1)]
    second.history = [(axis_b, np.abs(
        np.random.default_rng(12).standard_normal(32)) + 0.1)]
    return stage, first, second


@pytest.mark.skipif(not surface_gl.GL_AVAILABLE, reason="GPU stack missing")
def test_shared_stage_switches_models(monkeypatch):
    """One window app-wide: switching tabs reloads controls + data.

    Regression: with one GL widget per dialog, the second-opened 3D
    view rendered blank (per-context GL resources vs process-wide
    shader cache). A single permanent window cannot hit that.
    """
    stage, first, second = _stage_with_models(monkeypatch)

    stage._load_model(first, first.source_name)
    stage._redraw_current()
    assert stage.current is first
    assert stage.current_name == "Harmonics"
    assert stage.windowTitle().endswith("Harmonics")
    assert stage.source.text() == "Harmonics"
    assert "Harmonics" in stage.gl_view.info.text()
    assert "1 kHz" in stage.gl_view.info.text()

    stage._load_model(second, second.source_name)
    stage._redraw_current()
    assert stage.current is second
    assert "Noise" in stage.gl_view.info.text()
    assert "250 kHz" in stage.gl_view.info.text()
    # Controls mirror the newly shown tab (noise: Log Z off by default).
    assert second.use_log is False
    assert stage.log_z.isChecked() is False

    # Background redraws from the non-shown tab must not steal the screen.
    first.history.append(first.history[0])
    first._redraw()
    assert stage.current is second
    assert "250 kHz" in stage.gl_view.info.text()

    # Reloading the first tab restores its controls and data.
    stage._load_model(first, first.source_name)
    stage._redraw_current()
    assert "Harmonics" in stage.gl_view.info.text()
    assert "1 kHz" in stage.gl_view.info.text()


@pytest.mark.skipif(not surface_gl.GL_AVAILABLE, reason="GPU stack missing")
def test_shared_stage_releases_current_on_close(monkeypatch):
    stage, first, _second = _stage_with_models(monkeypatch)
    from PySide6.QtGui import QCloseEvent
    stage._load_model(first, first.source_name)
    assert stage.current is first
    stage.closeEvent(QCloseEvent())
    assert stage.current is None


@pytest.mark.skipif(not surface_gl.GL_AVAILABLE, reason="GPU stack missing")
def test_shared_stage_empty_state_names_the_fix(monkeypatch):
    stage, first, _second = _stage_with_models(monkeypatch)
    first.history = []
    stage._load_model(first, first.source_name)
    stage._redraw_current()
    assert "MEASURE" in stage.gl_view.info.text()


@pytest.mark.skipif(not surface_gl.GL_AVAILABLE, reason="GPU stack missing")
def test_shared_stage_redraw_failure_is_shown_not_raised(monkeypatch):
    stage, first, _second = _stage_with_models(monkeypatch)
    stage._load_model(first, first.source_name)

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic GL failure")

    monkeypatch.setattr(stage.gl_view, "redraw", boom)
    stage._redraw_current()  # must not propagate into measurements
    assert "3D error" in stage.gl_view.info.text()
    assert "synthetic GL failure" in stage.gl_view.info.text()


@pytest.mark.skipif(not surface_gl.GL_AVAILABLE, reason="GPU stack missing")
def test_shared_stage_controls_write_through_model(monkeypatch):
    stage, _first, second = _stage_with_models(monkeypatch)
    stage._load_model(second, second.source_name)
    stage.stride.setValue(4)
    assert second.stride_n == 4
    stage.mode.setCurrentIndex(2)  # surface
    assert second.render_mode == "surface"
    stage.log_z.setChecked(True)
    assert second.use_log is True


def test_harmonics_records_surface_history_before_dialog_opened():
    """Regression: measuring before opening 3D HISTORY must keep data.

    Harmonics used to drop spectra when the dialog had never been opened
    (``if self.surface is not None``), so opening it later showed an
    empty cube. It now records on demand like the noise inspector.
    """
    pytest.importorskip("PySide6")
    import numpy as np
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from qt_app import advanced
    from qt_app import analysis
    from qt_app.advanced import HarmonicsTab

    fs = 5000
    t = np.arange(fs) / fs
    wave = np.sqrt(2) * np.sin(2 * np.pi * 50 * t)
    analysis.acquire = lambda scope, channel, raw=False: (t, wave, fs)
    advanced.acquire = analysis.acquire

    class Scope:
        def _connected(self):
            return self

    def submit(operation, done):
        try:
            done(operation())
        except Exception as error:
            done(error)

    tab = HarmonicsTab(submit, Scope(), lambda *args: None)
    assert tab.surface is None
    tab.run()
    assert tab.surface is not None
    assert tab.surface.use_log is True  # harmonics Log-Z default
    assert len(tab.surface.history) == 1
    axis, spectrum = tab.surface.history[0]
    assert len(axis) == len(spectrum) == 250
    assert np.isfinite(spectrum).all()
