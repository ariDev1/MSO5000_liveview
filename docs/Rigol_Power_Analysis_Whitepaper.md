# Understanding Accurate Power Measurement on Rigol Oscilloscopes

## 1. Introduction

The experiments and observations documented here were performed exclusively on the **Rigol MSO5000 series**. Other Rigol series (e.g., DS1000, DS7000, DHO900/800, or MSO7000) may behave differently. No claims are made regarding their behavior.

Measurement hardware included:

* **Differential Probe**: TT-SI 7005
* **Shunt Resistor**: Isabellenhütte PBV series high-precision resistors (R001 and R01)

These components ensure high signal fidelity and accurate scaling during the tests described.

This paper also references a custom-built external software utility—**MSO5000 Live Monitor**—developed specifically for accurate power analysis based on waveform data from Rigol oscilloscopes. Where terms like "custom tool" or "external analysis" appear, they refer to this software. This tool applies user-defined scaling, corrects for DC offsets, and calculates all power metrics outside the limitations of the scope’s built-in PQ engine.

**Disclaimer:** This paper is based on independent lab measurements and is intended to help engineers achieve scientifically valid results with their instrumentation. It does not serve as an endorsement or criticism of Rigol as a vendor, but rather as a guide for responsible use of their tools in precision applications.

Accurate power analysis is a fundamental requirement in modern electronics laboratories, especially when working with high-efficiency power converters, pulse circuits, and systems involving reactive components. Oscilloscopes with built-in power analysis tools, such as the Rigol MSO5000 series, are commonly used to measure real power (P), apparent power (S), reactive power (Q), impedance (Z), and power factor (PF).

However, a widespread issue goes unnoticed: **incorrect probe configuration can silently invalidate these measurements.** This whitepaper provides a deep technical explanation of how probe type, scaling, and measurement channel configuration impact Rigol's internal power quality (PQ) calculations.

## 2. Fundamentals of Power Analysis

### Instantaneous Power (Fundamental Definition)
Instantaneous power, the fundamental measure of electrical power, is defined as:

<span>\\( P(t) = V(t) \cdot I(t) \\)</span>

Before diving into the instrument-specific behavior, it is essential to understand the standard electrical quantities involved in AC power analysis:

* **Real Power (P)** \[Watts]: <span>\\( P = V_{rms} \cdot I_{rms} \cdot \cos(\phi) \\)</span>
* **Apparent Power (S)** \[Volt-Amps]: <span>\\( S = V_{rms} \cdot I_{rms} \\)</span>
* **Reactive Power (Q)** \[VAr]: <span>\\( Q = V_{rms} \cdot I_{rms} \cdot \sin(\phi) \\)</span>
* **Power Factor (PF)**: <span>\\( PF = \cos(\phi) = \frac{P}{S} \\)</span>
* **Impedance (Z)** \[Ohms]: <span>\\( Z = \frac{V_{rms}}{I_{rms}} \\)</span>
* **Phase Angle** <span>\\( \phi \\)</span>: Angle between voltage and current waveforms

These values are typically derived using FFT or full-cycle RMS analysis of voltage and current waveforms. The phase relationship between voltage and current is particularly important for assessing reactive components and system efficiency.

## 3. Rigol's Built-In Power Quality Tool

Rigol includes a **Tip** in their Power Quality documentation suggesting that users should:

* Use **current clamps** for current measurements
* Use **differential probes** for voltage measurements

While this recommendation is technically valid under ideal probe conditions, it fails to address cases where engineers use a differential probe across a shunt for high-bandwidth current measurements. In such cases, the Rigol PQ analyzer cannot interpret the signal as current without an explicit probe-type mapping, leading to invalid PQ metrics as discussed throughout this paper.

Rigol’s MSO5000 series includes a built-in Power Quality (PQ) analysis tool that calculates real-time electrical metrics from two user-selected channels:

* One configured as the **voltage channel** (e.g., CH2)
* One configured as the **current channel** (e.g., CH4)

To obtain correct results, the current channel must ideally be set with the correct **scaling in mV/A** or A/V depending on the sensor or shunt used. This informs the oscilloscope how to convert input voltage into current values for all downstream calculations.

However, this configuration step is **not always possible**—for example, when using a differential probe across a shunt resistor. In such cases, Rigol offers no way to define the channel as a true current input with proper mV/A scaling. The user may manually set the **unit to “Amps”** in the channel menu, but this is only a cosmetic label and **does not affect Rigol's internal power analysis math**, which still interprets the signal as a voltage waveform.

**As a result:**

* Apparent impedance may be computed as <span>\\(Z = V_{rms} / I_{rms} \\)</span>, yielding invalid values (e.g., several kilo-ohms instead of real load impedance)
* Power values may be scaled incorrectly by orders of magnitude (e.g., 83mW instead of 83W)
* Phase angle and power factor become misleading or meaningless

A correct setup requires that the current signal be acquired using a probe that the scope can interpret properly—such as a standard passive probe or current clamp—with the channel configured using:

* **Display Unit**: Amps
* **Scaling**: 1mV/A (for a 1mΩ shunt, or per clamp datasheet)

This setup allows the internal Power Quality tool to perform valid calculations. For differential probes, it is strongly recommended to perform power analysis externally or through post-processing with proper scaling applied.

## 4. The Critical Role of Probe Configuration

In power analysis, the distinction between a "voltage" signal and a "current" signal is fundamental. Oscilloscopes do not inherently understand the physical nature of a waveform—they rely entirely on the channel configuration provided by the user.

When using standard probes or current clamps, the user can inform the scope that the signal represents current by setting:

* Probe Type: Current
* Units: Amps
* Scaling: Proper mV/A factor for the current sensor or shunt resistor

This tells the oscilloscope to interpret the waveform numerically as current, enabling meaningful calculations for power, impedance, power factor, and reactive energy.

With differential probes, this mechanism breaks down. The scope interprets the differential signal as a voltage difference between two points. Even if the signal is derived from a current-sensing shunt, Rigol has no way to know that the signal should be treated as a current. Setting the unit to “Amps” merely affects the display label—it does not convert volts to amps internally for the PQ calculation.

This distinction is critical. Engineers relying on the internal PQ metrics for validation or design feedback may unknowingly accept invalid numbers. This can lead to mistaken conclusions about efficiency, power factor, and thermal behavior.

A robust power measurement setup must ensure that current signals are acquired through channels configured as current inputs—with known scaling—or processed externally with proper conversion.

Interestingly, even when misconfigured, a differential probe setup may still *appear* to show valid real power in Watts if the output matches a known reference—such as the output of a DC power supply. This coincidence can mislead users into trusting the PQ output without realizing that other quantities like impedance, reactive power, and power factor are fundamentally broken.

Additionally, another common mistake arises from entering the wrong scaling value in the channel configuration. For example, when using a 1mΩ shunt, entering a probe value of `0.01` (intended for 10mΩ) will reduce the calculated current by a factor of 10. This causes the scope to underestimate current and overestimate impedance by 10×. However, if voltage drops proportionally, the resulting real power (P = V × I) may coincidentally appear correct, while impedance and phase angle remain incorrect. This further emphasizes the need to match the probe value **precisely** to the actual shunt resistance.

Therefore, relying solely on matching real power values (P) without verifying correct scaling and probe context is dangerous.

### Important Summary

When using a **differential probe** on the Rigol MSO5000 series to measure current in systems with **reactive power behavior (even under DC excitation)**, the following holds true:

* Rigol's **Power Quality (PQ) screen will show distorted values** for impedance, power factor, reactive power, and current.
* The **custom Power Analysis tool (MSO5000 Live Monitor) will also show incorrect results**, unless it explicitly applies the correct shunt scaling factor to convert differential voltage into current.

Even if the real power (P) occasionally matches the DC supply's output, this can be misleading. Without proper scaling and current-channel interpretation, such a match is a coincidence and all other derived metrics should be considered unreliable.

## 5. Experimental Comparison

To illustrate the impact of probe configuration, we compare two setups measuring the same high-impedance resistive load powered from a DC source:

* **Setup A (Incorrect)**: Differential probe across a 1mΩ shunt, unit set to "Amps" on CH4, but with no scaling
* **Setup B (Correct)**: Standard probe across the same shunt, CH3 configured as a current probe with scaling set to 1mV/A

| Metric             | Setup A: Diff Probe (CH4 = Voltage) | Setup B: Standard Probe (CH3 = Current) |
| ------------------ | ----------------------------------- | --------------------------------------- |
| Vrms (CH2)         | 41.77V                             | 41.76V                                 |
| Irms               | Misinterpreted                      | 834.161mA                              |
| Real Power (P)     | 688.9mW                            | 688.9mW                                |
| Apparent Power (S) | 34.84mVA                           | 34.84VA                                |
| Reactive Power (Q) | 34.88mVAR                          | 34.88VAR                               |
| Power Factor       | 0.0198                              | 0.0198                                  |
| Impedance          | Invalid                             | 50.063Ω                                |

This result confirms that once a standard probe is used with proper scaling and current interpretation, the Power Quality popup and the custom Power Analysis tool **match perfectly**. All values, including P, S, Q, and impedance, align.

This underscores the conclusion that Rigol’s PQ analyzer can only be trusted when the current signal is interpreted properly at the channel level.


## When the Built-in PQ Tool Can Be Trusted

While many of the limitations described stem from misinterpreted current signals (especially when using differential probes), the internal Power Quality feature of the Rigol MSO5000 series **can yield accurate results** when used under the following conditions:

- The **current is measured using a standard current probe or clamp**, recognized by the oscilloscope.
- The **Probe Type is set to "Current"** in the channel menu.
- The **scaling factor (e.g., 1mV/A)** matches the datasheet value for the current probe or shunt.
- The **input signal amplitude** is within the oscilloscope’s dynamic range and not affected by excessive noise or bandwidth limitations.
- The **signal is sinusoidal or quasi-periodic**, avoiding pulsed or highly transient shapes that confuse phase calculations.

### Example: Accurate PQ Results with a Properly Configured Current Clamp

To validate this, we used a **known resistive load** powered from a 24V DC supply. A **standard current clamp** (1mV/A sensitivity) was connected to CH4, and CH2 was used to monitor voltage across the load. Both channels were configured as follows:

| Channel | Probe Type | Unit  | Scale      |
|---------|-------------|--------|-------------|
| CH2     | Voltage     | Volts | 5.00 V/div |
| CH4     | Current     | Amps  | 1.00 mV/A  |

The Power Quality inputs were set as:

- **Voltage Channel**: CH2
- **Current Channel**: CH4

Under this configuration, the internal PQ analyzer produced:

| Metric             | Value           |
|--------------------|------------------|
| Real Power (P)     | 18.24 W         |
| Apparent Power (S) | 18.25 VA        |
| Reactive Power (Q) | 0.12 VAR        |
| Power Factor       | 0.999           |
| Impedance (Z)      | 31.6 Ω          |

These values matched an external power meter and our custom MSO5000 Live Monitor analysis within 1%.

### Summary

> ✅ When current is measured via an **official current probe** or **standard passive probe** across a known shunt with correct settings, the Rigol PQ tool is **accurate and reliable**.

> ⚠️ In contrast, using **differential probes across shunts without internal scaling** leads to **systematic errors** unless corrected externally.


## ⚠️ Vendor Limitation Warning: Rigol PQ Tool Can Mislead

Despite offering a dedicated Power Quality (PQ) measurement feature, the Rigol MSO5000 series exhibits a critical design flaw: it **does not apply the configured "Probe Value" or scaling factor in its internal PQ calculations unless the channel is explicitly set to a supported "Current Probe" type.**

Even if the channel unit is set to “Amps” and the correct shunt resistance (e.g., 0.01Ω for 10mΩ) is entered, Rigol will still process the waveform as a voltage input in its PQ math. This leads to:

* Real Power (P) values off by 10× to 100×
* Impedance estimates off by multiple orders of magnitude
* Completely invalid apparent and reactive power calculations

This issue persists even when:

* A standard Rigol probe is used on the current channel
* The probe is scaled and labeled correctly in the GUI
* The waveform clearly corresponds to known electrical behavior

In contrast, the custom Power Analysis tool described in this paper **uses the probe scaling explicitly and produces correct results.** For example, a side-by-side test with a 10mΩ shunt showed:

| Parameter      | Rigol PQ Output | Custom Tool Output |
| -------------- | --------------- | ------------------ |
| Real Power (P) | 770.9mW        | 82.3W             |
| Apparent Power | 3.14VA         | 368.9VA           |
| Reactive Power | 3.15VAR        | 359.6VAR          |
| Impedance (Z)  | 507Ω           | 4.69Ω             |

This discrepancy makes Rigol’s PQ tool **scientifically unusable for many applications unless all of the following are met**:

* Current channel uses an officially recognized current probe (not differential)
* Probe type is selected explicitly from Rigol’s menu
* Scaling is supported and internally propagated (not just visual)

Users must be aware of this limitation. Otherwise, they risk designing, verifying, or publishing systems based on invalid data.

---

## 6. Practical Setup Guidelines

To ensure accurate power analysis on the Rigol MSO5000 series, users must configure their probe and channel settings with care. Below is a checklist for practical setup:

* ✅ Use a standard passive probe or a current clamp when measuring current.
* ✅ Set the probe type to **Current** on the channel menu (if available).
* ✅ Input the correct scaling factor: e.g., **1mV/A** for a 1mΩ shunt.
* ✅ Set the display unit to **Amps** (this is cosmetic but helps interpretation).
* ⚠️ Avoid relying on differential probes for current measurement unless using external tools such as MSO5000 Live Monitor that apply proper scaling.
* ⚠️ If using differential probes, record the waveform and apply current conversion in post-processing.

Recommended practice:

* Validate results using a known resistive load (e.g., power resistor) to check if the calculated impedance and power match expected values.
* Cross-check with a handheld power meter or DMM for sanity validation.

## 7. Integration into Custom Power Analysis Tools

To overcome the limitations of the Rigol MSO5000's internal PQ calculations, users may implement their own software tools that correctly interpret probe inputs. For example, in the MSO5000 Live Monitor project, the power analysis module explicitly supports:

* Manual selection of voltage and current channels
* Shunt-mode interpretation (converting differential voltage into current using user-defined resistance)
* Removal of DC offset for reactive measurements
* Real-time calculation of P, Q, S, PF, phase angle, and impedance
* Logging and graphical representation over time

In this setup, even if the signal is acquired via a differential probe, accurate power calculations are possible—provided the correct shunt resistance is entered. The analysis software performs the current conversion and downstream computations externally, without relying on the scope’s internal interpretation.

This highlights the value of independent measurement pipelines such as MSO5000 Live Monitor: they allow flexibility in probe usage while preserving scientific validity.

## 8. Summary and Checklist for Reliable Power Measurements

---

## 9. How to Reproduce This Issue (Step-by-Step)

To independently verify the Rigol MSO5000's flawed PQ behavior, follow these steps:

### A. Setup with Differential Probe (Incorrect Results)

1. Connect CH2 across a DC load to measure voltage.
2. Connect a **differential probe** (e.g., CH4) across a 1mΩ shunt resistor.
3. Set CH4 unit to “Amps” (optional cosmetic step).
4. Open **Power Quality** analysis and assign:

   * Voltage = CH2
   * Current = CH4
5. Observe the following:

   * PQ values for Real Power (P), Reactive Power (Q), and Z are **incorrect**.
   * Impedance may show **hundreds or thousands of ohms**.
   * Real Power may appear **too low by 10×–100×**.

### B. Setup with Standard Probe (Correct Results)

1. Connect CH2 across the same DC load (voltage).
2. Connect **CH3** using a standard probe across the same 1mΩ shunt.
3. In CH3 settings:

   * Set **Probe Type = Current** (if supported)
   * Set **Probe Value = 0.01** (for 1mΩ shunt)
   * Set **Unit = Amps**
4. Assign Power Quality inputs:

   * Voltage = CH2
   * Current = CH3
5. Observe:

   * Real Power (P), Q, S, and PF now **match known values**.
   * Impedance (Z) is correct (e.g., \~5Ω)
   * Power matches DC PSU output

This test can be performed without high voltages or complex circuits—just a resistor load, low-voltage supply, and 1mΩ shunt. Screenshots and logs will confirm the tool’s internal misbehavior.

---

For accurate and meaningful power analysis on the Rigol MSO5000, users should follow this checklist:

* [ ] Are the voltage and current signals captured using separate channels?
* [ ] Is the current signal from a standard probe or properly scaled differential probe?
* [ ] If using a shunt, is the probe value (Ω) correctly set?
* [ ] Is the probe mode configured as “Current” if supported?
* [ ] Have you verified that the real power (P) aligns with external measurements (e.g., PSU or DMM)?
* [ ] Does the impedance match expectations (e.g., based on known resistors)?
* [ ] Are reactive power and PF values within expected ranges?

Failure to meet these conditions can result in misinterpretation of the system under test, even if some individual values (like P) seem correct.

With rigorous setup, validation, and post-processing when necessary, Rigol scopes—supplemented with external tools—can serve as precise instruments for power analysis, even in complex reactive or pulsed environments.
