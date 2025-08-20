# Accurate Current & Power Measurement with Oscilloscope, Shunt, and Differential Probe

## Introduction

Measuring current and power accurately with an oscilloscope is a common but surprisingly tricky task. Many engineers, even experienced ones, encounter misleading results due to subtle pitfalls with ground reference, shunt placement, probe type, and instrument settings. This note walks you through real-world scenarios, pitfalls, and *best-practice solutions* for precise, defensible power analysis.

## 1. Why Is This Difficult?

- **Oscilloscopes reference probe GND to earth** (unless floated).
- **Power supplies display average current (Iavg)**, not RMS (Irms).
- **Shunt measurement is highly sensitive** to probe ground, return paths, and offset.
- **DC offset or phantom voltage** can inflate or distort current readings.

## 2. Test Setup: The Classic Trap

**Initial setup:**
- **Power Supply:** DC 40V, showing 1.5A output
- **Shunt resistor:** R010 (0.01Ω), placed on the negative (low) side
- **Oscilloscope:**
  - **CH2:** Measures load voltage (10x probe)
  - **CH3:** Ordinary probe (1x), GND to supply minus, tip after shunt
  - **CH4:** Differential probe (set to 5x), across shunt

### Observation:
- With the shunt on the low side and CH3 (ordinary probe), results seemed “mostly logical,” but **Irms was far too high** (e.g., 10A when supply showed 1.5A), and when the supply was turned off, the scope still reported significant current.

## 3. Root Cause: Ground Loops and Offset

- **Low-side shunt:** Safe for reference, but if any alternative ground path or leakage exists, the scope may not measure the true load current.
- **Oscilloscope GND and probe GND:** If not at the same true potential, you can get **phantom voltages**—causing high RMS readings and false power measurement, even when no real current flows.

> **Key Experiment:**  
> With the power supply OFF, the scope still reported ~1.1A current—a clear sign of offset or ground loop error!

## 4. Why Is Irms (RMS Current) So Sensitive?

- **RMS calculation includes any offset:**  
  If the current channel (shunt voltage) has a DC offset, RMS explodes—even if there’s no real current!
- **Power calculation (mean V·I):**  
  Often less sensitive to offset, but still affected if both channels are biased.

## 5. The Fix: Differential Probing and Shunt Placement

### a. High-Side vs. Low-Side Shunt

- **Low-side:** Simple, but vulnerable to ground loop/parallel return error.
- **High-side:** Avoids ground loop but requires isolation (dangerous if not floated).

### b. Differential Probe

- **Differential probes** measure only the voltage across the shunt, *independent of ground*.
- Immune to ground loops, EMI, and reference errors.

#### Visual Example:  
![Single-ended vs Differential](oszi-probe_comparison1.png)

## 6. The DC Offset Button: What It Really Does

- **DC Offset removal** subtracts the mean value from each waveform (voltage and current) before analysis.
- **Removes phantom offset**—fixes false RMS/Irms readings due to ground loop or bias.
- **For steady DC signals:**  
  **Do NOT enable DC Offset**—it will zero out true current/power as well.

## 7. Power Supply Readout: Iavg vs Irms

- **Most supplies display Iavg (average current), not Irms.**
- For DC: Iavg ≈ Irms.
- For pulsed or AC loads: Irms > Iavg.
- Oscilloscope gives you *both* (mean and RMS) for full waveform analysis.

## 8. Best Practice: Measurement Configuration

**Recommended setup for DC/AC or mixed loads:**

| Channel | Function         | Probe Type      | Scope Unit | Probe Value | GUI Setting         | Notes                |
|---------|------------------|-----------------|------------|-------------|---------------------|----------------------|
| CH2     | Load voltage     | Voltage probe   | VOLT       | 10x         | Voltage Ch: 2       | Should match supply  |
| CH4     | Shunt voltage    | Differential    | VOLT/AMP   | 5x          | Current Ch: 4       | Use shunt in “shunt” |
|         |                  |                 |            |             | Probe Type: Shunt   | Value: 0.01 (10mΩ)  |

- **Enable 20MHz BW limit** for cleaner measurements unless you need full bandwidth.
- **Only enable DC Offset Removal if you suspect phantom currents.**
- **Check probe attenuation and units in the scope and software match.**

## 9. Real Data Example

**Correct Setup Screenshot:**  
![Correct Diff Probe Setup](oszi-DiffProbe-setup1.png)

- Vrms: 41.7 V
- Irms: 3.1 A
- Real Power (P): 38.6 W
- Power Factor: 0.297
- Apparent Power: 130.5 VA
- Reactive Power: -42.1 VAR


- Supply shows: **41.6 V, 1.5 A** (Iavg)
- Scope shows: **Irms = 3.1 A**  
  **→ Higher due to AC or pulsed component in current**

**PQ plot and vector match, all values consistent.**

## 10. Single-Ended vs Differential Probing

### Single-Ended (ordinary probe):  
- Sensitive to GND errors, shows noisy and offset results, phantom currents, especially in low-side shunt.

![CH3/CH4 comparison](oszi-probe_comparison1.png)

### Differential Probe:  
- Accurate, clean measurement of true current.
- No phantom offset; power analysis is reliable.

Differential probes inherently introduce a propagation delay compared to passive oscilloscope probes, typically ranging from tens to hundreds of nanoseconds. Although small, this delay can significantly affect the accuracy of power measurements, especially at higher frequencies, by introducing measurable phase shifts between voltage and current waveforms.

### Why This Matters

* **Phase Angle & Power Factor (PF)**: A delay between voltage and current measurements introduces phase errors, affecting reactive (Q), apparent (S), and instantaneous power (p(t)) accuracy.
* **Instantaneous Power**: Defined as $p(t) = V(t) \cdot I(t)$, even minor delays can cause inaccuracies, particularly in systems with rapid voltage/current changes.

### Example Phase Shift Calculations

The phase shift due to probe delay can be calculated as follows:

$$
\text{Phase Shift (degrees)} = 360^\circ \times \frac{\text{Probe Delay (seconds)}}{\text{Signal Period (seconds)}}
$$

| Frequency | Signal Period | Delay (Example: 100ns) | Phase Shift          |
| --------- | ------------- | ---------------------- | -------------------- |
| 50 Hz     | 20 ms         | 100 ns                 | 0.0018° (negligible) |
| 1 kHz     | 1 ms          | 100 ns                 | 0.036° (small)       |
| 100 kHz   | 10 µs         | 100 ns                 | 3.6° (significant)   |
| 1 MHz     | 1 µs          | 100 ns                 | 36° (critical)       |

### Recommended Best Practices

* **Delay Verification**: Always measure delay using a known zero-delay reference signal.
* **Calibration Procedure**:

  * Simultaneously measure a calibration signal with both ordinary and differential probes.
  * Determine the delay offset.
  * Apply delay compensation in your software-based analysis.

## 11. Key Lessons & Checklist

1. **Always check your baseline:** With supply off, measured current must be zero!
2. **Be suspicious of large Irms when Iavg is small.**
3. **Prefer differential probes for shunt measurements**—especially in nontrivial systems.
4. **Understand your instrument displays:**  
   - Power supply = average (Iavg)
   - Oscilloscope = both Iavg and Irms (see which your analysis uses)
5. **Enable DC Offset only to remove error—not for true DC signals.**

## 12. Quick Troubleshooting Table

| Symptom                                | Cause                                 | Solution                 |
|-----------------------------------------|---------------------------------------|--------------------------|
| Irms too high, even with no load        | Offset/phantom voltage                | Use DC Offset Removal    |
| Current = 0A but Irms not zero          | Ground loop, bias, or EMI             | Float scope or use diff probe |
| Measured voltage/current too low/high   | Probe attenuation mismatch            | Check scope settings     |
| Supply current ≠ scope Irms             | Pulsed/AC load, or measurement error  | Compare Iavg vs Irms     |
| Power/energy values inconsistent        | Offset, calculation settings, or math | Check config & math      |

## 13. References & Further Reading
- MSO5000 Live Monitor Docs: [GitHub Repo](https://github.com/ariDev1/MSO5000_liveview)
- [Keysight Application Note: Shunt Measurements](https://www.keysight.com/us/en/assets/7018-03199/application-notes/5991-1987.pdf)
- [Tektronix: Power Measurement Fundamentals](https://www.tek.com/en/documents/primer/abc-power-measurements)

## 14. Appendix: Example Screenshots

- **Correct Differential Probe Measurement:**  
  ![Correct Diff Probe Setup](oszi-DiffProbe-setup1.png)

- **Comparison: Ordinary vs Differential Probe:**  
  ![Single-ended vs Differential](oszi-probe_comparison1.png)

## 15. Summary

> **Precise oscilloscope-based power analysis is only possible when the probe reference, shunt placement, and software settings are all correct. Understanding the difference between Iavg and Irms, and knowing when to use DC offset removal, is critical. Differential probes are worth their cost for reliable results.**