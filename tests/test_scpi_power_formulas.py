import math

import numpy as np
import pytest

from scpi.power_formulas import compute_power_rms_cos_phi, compute_power_standard


RELATIVE_TOLERANCE = 1e-10
ABSOLUTE_TOLERANCE = 1e-10


def assert_close(actual, expected):
    assert actual == pytest.approx(
        expected,
        rel=RELATIVE_TOLERANCE,
        abs=ABSOLUTE_TOLERANCE,
    )


def test_standard_method_averages_instantaneous_power():
    voltage = np.array([2.0, -2.0, 2.0, -2.0])
    current = np.array([3.0, -3.0, 3.0, -3.0])

    instantaneous_power, real_power = compute_power_standard(voltage, current, 0.001)

    np.testing.assert_array_equal(instantaneous_power, [6.0, 6.0, 6.0, 6.0])
    assert_close(real_power, 6.0)


def test_rms_phase_method_handles_one_complete_fundamental_cycle():
    sample_count = 1_000
    angle = 2.0 * math.pi * np.arange(sample_count) / sample_count
    voltage = math.sqrt(2.0) * 230.0 * np.sin(angle)
    current = math.sqrt(2.0) * 2.0 * np.sin(angle - math.pi / 3.0)

    _, real_power = compute_power_rms_cos_phi(voltage, current, 0.00002)

    assert_close(real_power, 230.0)


@pytest.mark.xfail(
    strict=True,
    reason="Original measurement behavior uses FFT bin 1; hardware behavior is preserved.",
)
def test_rms_phase_method_handles_multiple_fundamental_cycles():
    sample_rate_hz = 5_000.0
    sample_count = 5_000
    time_s = np.arange(sample_count) / sample_rate_hz
    angle = 2.0 * math.pi * 50.0 * time_s
    voltage = math.sqrt(2.0) * 230.0 * np.sin(angle)
    current = math.sqrt(2.0) * 2.0 * np.sin(angle - math.pi / 3.0)

    _, real_power = compute_power_rms_cos_phi(voltage, current, 1.0 / sample_rate_hz)

    assert_close(real_power, 230.0)


def test_empty_input_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        compute_power_standard(np.array([]), np.array([]), 0.001)


def test_unequal_input_lengths_are_rejected():
    with pytest.raises(ValueError, match="length"):
        compute_power_standard(np.array([1.0, 2.0]), np.array([1.0]), 0.001)


@pytest.mark.parametrize("invalid_value", [math.nan, math.inf, -math.inf])
def test_non_finite_input_is_rejected(invalid_value):
    voltage = np.array([1.0, invalid_value])
    current = np.array([1.0, 1.0])

    with pytest.raises(ValueError, match="finite"):
        compute_power_standard(voltage, current, 0.001)
