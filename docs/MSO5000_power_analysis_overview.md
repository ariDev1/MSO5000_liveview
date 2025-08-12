# MSO5000 Power Analyzer — Technical Overview

**Project Title:** Real-Time Power Analyzer using Rigol MSO5000  
**Author:** Aether Research Institute (ariDev1)  
**Date:** 2025-07-26  
**Repository:** [GitHub/MSO5000_liveview](https://github.com/ariDev1/MSO5000_liveview)

---

## Purpose

This project transforms a Rigol MSO5000 oscilloscope into a **real-time power analyzer** capable of high-resolution electrical measurements including power, energy, and phase relationships.

It is designed to **match or exceed the functionality** of commercial power meters by leveraging open software and SCPI-based waveform extraction.

---

## ⚙System Overview

The system is composed of:

- 🖥️ A Python-based GUI using `Tkinter` and `matplotlib`
- 🔌 Live waveform acquisition via SCPI (VISA)
- 🧮 Real-time computation of:
  - **Active Power (P)**
  - **Reactive Power (Q)**
  - **Apparent Power (S)**
  - **Power Factor (PF)** and **phase angle**
- 📈 Live PQ plotting with quadrant display
- 🧪 Calibration via expected power or correction factor

---

## Methodology

### 1. Waveform Extraction

Voltage and current waveforms are acquired from the oscilloscope using SCPI commands like:

```
:WAV:SOUR CHAN2
:WAV:MODE NORM
:WAV:DATA?
```

The data is rescaled and processed into NumPy arrays for numerical computation.

---

### 2. Power Calculation

Given voltage \( v(t) \) and current \( i(t) \), the following are computed:

- **Vrms** = \( \sqrt{\frac{1}{N} \sum v_i^2} \)
- **Irms** = \( \sqrt{\frac{1}{N} \sum i_i^2} \)
- **P** = \( \frac{1}{N} \sum v_i \cdot i_i \)
- **S** = \( \text{Vrms} \cdot \text{Irms} \)
- **Q** = \( \sqrt{S^2 - P^2} \)
- **PF** = \( \frac{P}{S} \)

Optional: DC offset can be removed from each waveform before RMS/P computation.

---

### 3. Phase Detection

The phase shift between voltage and current is calculated using cross-correlation to identify the time delay between the two waveforms. This delay is then converted to a phase angle in degrees, based on the fundamental waveform frequency, yielding an accurate measure of the phase relationship.

---

## 📊 Visualization Features

- Real-time **PQ Vector Plot**
- Live **quadrant tracking**
- Time-based **energy accumulation**:
  - Real energy (Wh)
  - Apparent energy (VAh)
  - Reactive energy (VARh)

---

## Calibration Options

| Method | Description |
|--------|-------------|
| **Correction Factor** | Manually entered scaling applied to current input |
| **Auto Calibration** | User enters **expected power** value; correction factor is calculated automatically |
| **Unit Detection** | Scope’s CHANx:UNIT? is queried to determine whether input is in V or A |

---

## Data Logging

- Power logs are stored as CSV files under `/oszi_csv/`
- Logs include timestamp, P, Q, S, PF, Vrms, Irms, and energy metrics
- Last session summary plot saved as PNG

---

## Error Handling and Stability

- Prevents power analysis during long-term logging
- Detects non-finite results and skips invalid reads
- Tracks DC offset toggle status
- Scope disconnection is handled gracefully

---

## What You Gain

- Fully open and transparent power analyzer
- Reproducible results
- Custom scaling, probing, and filtering logic
- Scientific accuracy without vendor lock-in

---

## License

This software is released under an open-source license. Use at your own risk. Accuracy depends on oscilloscope bandwidth, probe calibration, and SCPI reliability.

---
