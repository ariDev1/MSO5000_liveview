# MSO5000 Power Analyzer — Technical Overview

**Project Title:** Real-Time Power Analyzer using Rigol MSO5000  
**Author:** Aether Research Institute (ariDev1)  
**Date:** 2025-08-31 
**Repository:** [GitHub/MSO5000_liveview](https://github.com/ariDev1/MSO5000_liveview)

---

## Purpose

This project turns a Rigol MSO5000 into a **real-time power analyzer** for high-resolution measurements of power, energy, and phase relationships, using open software and SCPI-based waveform extraction. It aims to **approach (and in some cases exceed) commercial meter functionality** while remaining transparent and auditable.

---

## ⚙ System Overview

- 🖥️ Python GUI (`Tkinter` + `matplotlib`)  
- 🔌 Live waveform acquisition via SCPI (VISA)  
- 🧮 Real-time computation of:
  - **Active Power (P)**
  - **Apparent Power (S)**
  - **Reactive Power at the fundamental (Q₁)** with **correct sign** (inductive +, capacitive −)
  - **Power Factor (PF = P/S)** and **fundamental angle φ₁**
- 📈 Live PQ plotting with quadrant display  
- 🧪 Calibration via expected power or correction factor

---

## Methodology

### 1) Waveform Extraction

Voltage and current are acquired from the oscilloscope via SCPI, rescaled, and converted to NumPy arrays for analysis, e.g.:

```
:WAV:SOUR CHANx
:WAV:MODE NORM
:WAV:DATA?
```

Acquisition settings (sample rate, record length, channel scales/units, probe factors) are preserved for traceability.

Given sampled waveforms \( v[n] \) and \( i[n] \) (with proper scaling to volts and amps):

- **Vrms**   
  \(
  V_\mathrm{rms}=\sqrt{\tfrac1N\sum_n v[n]^2}
  \)
- **Irms**   
  \(
  I_\mathrm{rms}=\sqrt{\tfrac1N\sum_n i[n]^2}
  \)
- **Active power (time-domain average of instantaneous power)**  
  \(
  P=\tfrac1N\sum_n v[n]\cdot i[n]
  \)
- **Apparent power**  
  \(
  S=V_\mathrm{rms}\,I_\mathrm{rms}
  \)
- **Reactive power (fundamental) — IEEE 1459 compliant**  
  Estimate the fundamental frequency \(f_0\) in the window, form RMS phasors \(U_1, I_1\) at \(f_0\) (orthogonal projection), then
  \(
  S_1=U_1\,I_1^*,\quad P_1=\Re\{S_1\},\quad Q_1=\Im\{S_1\}
  \)
  with **sign convention**: \(Q_1>0\) inductive (current lags), \(Q_1<0\) capacitive (current leads).
- **Power Factor (total, signed)**  
  \(
  \mathrm{PF}=\frac{P}{S}\quad(\text{sign}(PF)=\text{sign}(P))
  \)

> **Important correction:** the earlier \(Q=\sqrt{S^2-P^2}\) is **not used** (it is signless and invalid under distortion). We now report **\(Q_1\)** from fundamental phasors with correct sign.

---

### 3) Phase / Angle

For reporting the phase relation, the tool uses the **fundamental phasor angle**  
\(
\varphi_1=\arg(U_1 I_1^*)=\arctan2(Q_1, P_1)
\)
Cross-correlation can be employed internally for **rough delay alignment** or diagnostics, but the **authoritative phase** for PF/Q is the **fundamental angle \(\varphi_1\)**. This is robust for distorted waveforms and consistent with the Q₁ definition.
---

## 📊 Visualization Features

- Real-time **PQ vector plot** using \(P\) and **\(Q_1\)** with quadrant classification  
- Live **PF** and **φ₁** display  
- Time-based **energy integration**:
  - Real energy (Wh) from \(P\)
  - Apparent energy (VAh) from \(S\)
  - Reactive energy (varh) from **\(Q_1\)**

![Screenshot](power-analysis_demo2.png)

---

## Calibration Options

| Method | Description |
|---|---|
| **Correction Factor** | Manual scalar applied to current path (for probe/clamp calibration). |
| **Auto Calibration** | Enter an **expected power**; the tool computes a correction factor. |
| **Unit Detection** | The scope’s `CHANx:UNIT?` is queried to determine if a channel is in V or A, preventing double scaling. |

These options mirror the original design while ensuring scaling is traceable.

---

## Data Logging

- CSV logs (e.g., under `/oszi_csv/`) capture timestamped results: **P, Q₁, S, PF, Vrms, Irms, φ₁, f₀** and energy counters (Wh/VAh/varh).  
- Session summary plots saved as PNG alongside logs for audit.

---

## Error Handling and Stability

- Blocks conflicting actions (e.g., power analysis vs. long-term logging simultaneously)  
- Detects non-finite results and skips invalid reads  
- Tracks DC-offset settings; handles scope disconnections gracefully

---

## What You Gain

- Open, transparent power analyzer with raw-data traceability  
- Reproducible results and configurable probing/scaling  
- **Sign-correct \(Q_1\)** and robust PF/angle in distorted conditions  
- Practical accuracy without vendor lock-in

![Screenshot](power-analysis_demo3.png)

---

## License

Open-source; use at your own risk. Accuracy depends on oscilloscope bandwidth, probe/clamp/shunt calibration, and SCPI reliability.