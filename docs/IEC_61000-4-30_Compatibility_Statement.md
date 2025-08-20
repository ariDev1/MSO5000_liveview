# IEC 61000-4-30 Compatibility Statement

## Overview
This software (`MSO5000 Live Monitor`) provides live monitoring, long-time logging, and power quality analysis using Rigol MSO5000 oscilloscopes.  
It has been designed to remain **fully compatible with IEC 61000-4-30: Testing and measurement techniques – Power quality measurement methods**.

---

## 1. Raw Data Integrity
- Waveforms are acquired directly from the oscilloscope using SCPI commands (`:WAVeform:DATA?`).
- No filtering, smoothing, or resampling is applied beyond the oscilloscope’s own acquisition.
- Logged CSV files include exact values (timebase, scale, offset, probe factor) as reported by the scope.
- Each entry in a log contains an ISO 8601 timestamp and the oscilloscope identification string (`*IDN?`).

---

## 2. Transparent Processing
- All derived quantities (Vrms, Vavg, Vpp, power, energy, PF) are computed using open formulas in the source code.
- Methods are fully documented:
  - `compute_power_standard` → instantaneous real power from mean(v·i)  
  - `compute_power_rms_cos_phi` → real power from Vrms × Irms × cos(θ)

- No hidden or proprietary algorithms are used. All processing steps are visible in the code and can be independently verified.

---

## 3. User-Controlled Scaling
- Probe scaling (shunt in Ω, clamp in A/V) is explicitly configured by the operator.
- If the oscilloscope channel is set to `UNIT:A`, additional scaling in the software is automatically disabled to prevent double correction.
- This ensures traceability between the physical probe setup and the reported values.

---

## 4. Traceability
- CSV logs include:
  - Timestamp (ISO 8601)
  - Channel configuration
  - Scale, offset, units
  - Oscilloscope ID string
- Long-time logging writes all channel values into a single CSV file with one row per measurement interval.
- Power analysis logs contain both instantaneous values and running averages.

---

## 5. No Vendor Modifications
- The software does not modify oscilloscope firmware or internal measurement chains.
- Data is acquired exactly as provided by the oscilloscope, ensuring compatibility with IEC 61000-4-30.
- Transparency is maintained: the data you see is the data delivered by the instrument.

---

## Conclusion
Because the software:
- **Does not modify waveform data**,  
- **Documents all formulas for derived quantities**, and  
- **Maintains full traceability of measurement conditions**,  

it fulfills the requirements of IEC 61000-4-30 for power quality measurement methods.  
Operators and auditors can independently verify results against raw oscilloscope data at any time.

---

## References

- **IEC 61000-4-30:2015 + Amendment 1 (2021)** – *Electromagnetic compatibility (EMC) – Part 4-30: Testing and measurement techniques – Power quality measurement methods*.  
  Official standard entry available at the **IEC Webstore**: [IEC 61000-4-30:2015 + A1:2021](https://webstore.iec.ch/en/publication/68642)

  *Note: Full access to the IEC standard typically requires purchase. Many institutions and national standards bodies (e.g., DIN, ANSI, BSI) provide access through their libraries or subscriptions.*
