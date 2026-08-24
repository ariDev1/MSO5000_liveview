import math

import numpy as np
import pytest

from gui.power.formulas import compute_power


SAMPLE_RATE_HZ = 5_000.0
MAINS_FREQUENCY_HZ = 50.0
DURATION_S = 1.0
RELATIVE_TOLERANCE = 1e-10
ABSOLUTE_TOLERANCE = 1e-10


def sine_rms(rms_value, phase_rad=0.0, harmonic=1):
    sample_count = int(SAMPLE_RATE_HZ * DURATION_S)
    time_s = np.arange(sample_count) / SAMPLE_RATE_HZ
    angle = 2.0 * math.pi * harmonic * MAINS_FREQUENCY_HZ * time_s
    return math.sqrt(2.0) * rms_value * np.sin(angle + phase_rad)


def assert_close(actual, expected):
    assert actual == pytest.approx(
        expected,
        rel=RELATIVE_TOLERANCE,
        abs=ABSOLUTE_TOLERANCE,
    )


def test_dc_input_preserves_real_power_when_dc_is_allowed():
    voltage = np.full(1_000, 12.0)
    current = np.full(1_000, 2.0)

    result = compute_power(voltage, current, method="standard", fs=1_000.0)

    assert_close(result["Real Power (P)"], 24.0)
    assert_close(result["Apparent Power (S)"], 24.0)
    assert_close(result["Power Factor"], 1.0)


def test_in_phase_sine_has_unity_power_factor():
    voltage = sine_rms(230.0)
    current = sine_rms(2.0)

    result = compute_power(
        voltage,
        current,
        method="standard",
        fs=SAMPLE_RATE_HZ,
        mains_hint=MAINS_FREQUENCY_HZ,
    )

    assert_close(result["Real Power (P)"], 460.0)
    assert_close(result["Apparent Power (S)"], 460.0)
    assert_close(result["Reactive Power (Q)"], 0.0)
    assert_close(result["Power Factor"], 1.0)


def test_lagging_current_has_positive_reactive_power():
    voltage = sine_rms(230.0)
    current = sine_rms(2.0, phase_rad=-math.pi / 2.0)

    result = compute_power(
        voltage,
        current,
        method="fft_phase",
        fs=SAMPLE_RATE_HZ,
        mains_hint=MAINS_FREQUENCY_HZ,
    )

    assert_close(result["Real Power (P)"], 0.0)
    assert_close(result["Reactive Power (Q)"], 460.0)
    assert_close(result["phi1_deg"], 90.0)


def test_time_domain_power_includes_harmonic_real_power():
    voltage = sine_rms(230.0) + sine_rms(10.0, harmonic=3)
    current = sine_rms(2.0) + sine_rms(1.0, harmonic=3)

    result = compute_power(
        voltage,
        current,
        method="standard",
        fs=SAMPLE_RATE_HZ,
        mains_hint=MAINS_FREQUENCY_HZ,
    )

    assert_close(result["Real Power (P)"], 470.0)


def test_empty_input_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        compute_power([], [], method="standard", fs=SAMPLE_RATE_HZ)


def test_unequal_input_lengths_are_rejected_consistently():
    for method in ("standard", "rms_cos_phi", "fft_phase"):
        with pytest.raises(ValueError, match="length"):
            compute_power([1.0, 2.0], [1.0], method=method, fs=SAMPLE_RATE_HZ)


@pytest.mark.parametrize("invalid_value", [math.nan, math.inf, -math.inf])
def test_non_finite_input_is_rejected(invalid_value):
    with pytest.raises(ValueError, match="finite"):
        compute_power([1.0, invalid_value], [1.0, 1.0], method="standard", fs=SAMPLE_RATE_HZ)
