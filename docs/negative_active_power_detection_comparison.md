# Reverse Power Detection Test — MSO5000 Liveview Validation

## Scenario: Zero Net Power Consumption, Net Energy Return

This experiment demonstrates the ability of various measurement tools to correctly detect **reverse real power** (i.e., energy being fed back to the source) in a test circuit specifically designed to **consume zero net power** but return energy to its input terminals over time.

---

## Purpose

To verify if consumer-grade or professional instruments are capable of correctly identifying and quantifying negative real power in scenarios such as:

- Resonant LC networks,
- Capacitive injection,
- Non-linear energy-return systems.

---

## Test Setup

- **Circuit Goal:** No net energy consumed; periodic energy return to source.
- **Voltage and Current Channels:** Precisely synchronized using the Rigol MSO5000 series oscilloscope.
- **Measurement Methods:**
  - Direct waveform capture with oscilloscope (shunt-based).
  - Electromechanical analog wattmeter (torque-based).
  - CT-based smart meter and consumer plug meter (e.g., EMONIO P3).
  - MSO5000 Liveview Power Analysis (custom real-time P/Q/S computation).

---

## Results Summary

| Test Condition | Rigol Oscilloscope | MSO5000 Power Analysis | EMONIO P3 | Smart Meter | Mechanical Wattmeter |
|----------------|--------------------|-------------------------|-----------|--------------|------------------------|
| **Load: ON**   | -11W              | -13W                   | 13W, 0VAR | -Q, +P       | stopped (0 W)          |
| **Load: OFF**  | -12W              | -13W                   | -12W, -358VAR | +Q, +P     | stopped (0 W)          |

- Measurements from **Rigol and MSO5000 Liveview** clearly show **negative real power**.
- **Smart meters** fail to detect direction — falsely show **positive power** with reactive component.
- **Mechanical wattmeter** stops (indicating 0 W net torque), consistent with zero net consumption.
- **EMONIO P3** shows conflicting values, likely due to CT inaccuracies.

Date of test: **2025-08-04**

---

## Why CT-Based Devices Fail in This Scenario

- **Current Transformers (CTs)** are AC-only and do **not convey direction** of current.
- Without high-resolution, synchronized voltage sampling, they **cannot resolve phase angles accurately**.
- Many consumer smart meters **clip or average near-zero or bidirectional power** flows to zero or small values.
- Reverse power often gets filtered or ignored by firmware logic to avoid confusing the end-user.

---

## Key Insights

- **Shunt-based or waveform-based** systems (like the MSO5000 + Liveview) capture full time-domain polarity and phase information.
- Reverse power can only be **accurately measured** if both **voltage and current** are sampled **simultaneously and with sufficient resolution**.
- **Mechanical wattmeters** still outperform most digital consumer meters when it comes to **true power direction detection**.

---

## Conclusion

This test validates that the **MSO5000 Liveview** power analysis tool — built on waveform-level analysis — provides **physically correct and direction-sensitive** power measurements.

It outperforms several commercial devices by:
- Respecting waveform phase,
- Avoiding false assumptions based on RMS-only math,
- Accurately detecting **reverse power flow**.

Such capabilities are critical for advanced applications, including:
- Reactive compensation tuning,
- Energy harvesting validation,
- Power quality analysis in complex loads.

---
Author: MSO5000 Liveview Development Team*  
