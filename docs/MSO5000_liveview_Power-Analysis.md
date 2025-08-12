# MSO5000 Live Power Analysis

### Calculation Model and Scientific Methodology

This document outlines how the **MSO5000 Liveview Power Analyzer** calculates power metrics from oscilloscope waveform data. It is designed for scientific transparency, repeatability, and defensibility in academic and industrial contexts.

---


### Physical-to-Digital Conversion Path

An analog voltage or current signal enters the oscilloscope’s input and passes through analog conditioning stages (attenuation, coupling, offset, filtering). The oscilloscope’s ADC then samples this signal at a fixed rate, producing a sequence of digital values with defined `Δt` and quantized amplitude resolution.

Upon SCPI request, the scope provides raw byte-encoded waveform data and its associated scaling preamble (`:WAV:PRE?`). This includes time and voltage resolution (`XINCREMENT`, `YINCREMENT`), offsets, and references. Our software decodes this binary stream into real-time voltage and current arrays using probe scaling and unit detection.

Each decoded sample thus represents a calibrated, timestamped point on the original waveform. This reconstructed signal enables all downstream processing: RMS, power, energy, and FFT-based phase analysis.


## 1. Signal Acquisition

- **Device**: Rigol MSO5000-series oscilloscope (via SCPI over TCP/IP)
- **Channels**: Any voltage and current source (e.g., CHAN2 for voltage, CHAN4 for current)
- **Acquisition Mode**: `RAW` waveform sampling via `:WAV:DATA?`
- **Sample Size**: 1200 points (default, runtime-configurable)

**Note**: All scope-side settings like vertical scale, offset, and inversion (`:CHANx:INVert ON`) are automatically reflected in analysis.

---

## 2. Current Measurement Models

Current is reconstructed based on the selected probe type:

### a. Shunt Resistor

$I(t) = \frac{V_{meas}(t)}{R_{shunt}}$

- $V_{meas}(t)$: Measured voltage across shunt
- $R_{shunt}$: Resistance value in ohms

### b. Current Clamp / Probe

$I(t) = V_{meas}(t) \cdot \text{scale}$

Where:

- `scale = 1 / \text{(A/V ratio)}`
- Example: a 100 A/V probe → `scale = 0.01` V/A

---

## 3. Power Calculation

For every sample $t_i$:

### a. Instantaneous Power

$p(t_i) = V(t_i) \cdot I(t_i)$

### b. Real Power (P)

$P = \frac{1}{N} \sum_{i=1}^{N} p(t_i)$

### c. True RMS Values

$V_{rms} = \sqrt{\frac{1}{N} \sum_{i=1}^{N} V(t_i)^2}, \quad I_{rms} = \sqrt{\frac{1}{N} \sum_{i=1}^{N} I(t_i)^2}$

### d. Apparent Power (S)

$S = V_{rms} \cdot I_{rms}$

### e. Reactive Power (Q)

$Q = \sqrt{S^2 - P^2}$

### f. Power Factor and Phase Angle

$PF = \frac{P}{S}, \quad \theta = \cos^{-1}(PF)$

---

## 4. Energy Integration

Energy is computed by integrating real and apparent power over time:

- Real Energy (Wh):

$E_P = \sum P_{avg}(t) \cdot \Delta t$

- Apparent Energy (VAh):

$E_S = \sum S_{avg}(t) \cdot \Delta t$

- Reactive Energy (VARh):

$E_Q = \sum Q_{avg}(t) \cdot \Delta t$

Where $\Delta t$ is the time between samples (user-defined logging interval).

---

## 5. Scientific Validity

- Based on **IEEE Std 1459** formulas
- Uses true RMS and instantaneous sample multiplication
- Compatible with inverted channels, offset signals, and any scale
- Valid for sinusoidal and distorted waveforms (e.g., switching loads)

---

## 6. Known Limitations

- Dependent on oscilloscope bandwidth, vertical resolution, and timebase
- No FFT/harmonic analysis yet (planned)
- Phase shift due to probe delays or filter capacitance is not auto-compensated
- No calibration against known reference standard (user responsibility)

---

## 7. Data Logging Format

Each row in the CSV log includes:

- Timestamp
- Instantaneous and average power metrics:
  - Real Power (W)
  - Apparent Power (VA)
  - Reactive Power (VAR)
  - Power Factor and Phase Angle (°)
  - Vrms / Irms
  - Real, Apparent, and Reactive Energy (Wh, VAh, VARh)

Example:

```
Timestamp,P,S,Q,PF,Angle,Vrms,Irms,E_P,E_S,E_Q
2025-07-21T09:21:44.049118,0.303,1.069,1.023,0.2835,73.66,42.894,0.024861,10.740e-3,3.923e-3,42.583e-3
```

---

## Conclusion

The MSO5000 Power Analyzer is not a toy — it is a **scientifically defensible**, transparent, and flexible tool built by engineers for engineers. Everything it does is visible, testable, and modifiable.

Use it with pride. Measure with confidence.

---

Project: [MSO5000 Liveview](https://github.com/ariDev1/MSO5000_liveview)  
Author: **ariDev1**  
License: MIT  
<p align="right" style="font-size: 0.9em; color: #888;">
  <a href="https://aether-research.institute/MSO5000/cop-calculation.html">
    ↪ View COP Calculation
  </a>
</p>
