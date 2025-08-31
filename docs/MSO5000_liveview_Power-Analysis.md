# MSO5000 Live Power Analysis

**Project:** MSO5000 Liveview Power Analyzer  
**Goal:** Scientifically transparent, repeatable, and defensible computation of power quantities (P, S, Q₁, PF, φ₁) from oscilloscope waveforms.  

---

## 1) Physical-to-Digital Signal Path

Signals pass through the scope’s analog front-end (attenuation, coupling, offset, BW limit), are sampled by the ADC, then retrieved via SCPI with scaling metadata (`:WAV:PRE?`). The software decodes raw bytes into **calibrated** voltage/current arrays using probe factors and channel units; each sample has a known time step \( \Delta t \). These arrays are the basis for RMS, power, energy, and spectral/phasor analysis.

---

## 2) Acquisition

- **Instrument:** Rigol MSO5000 (SCPI over TCP/IP)  
- **Channels:** any pair (e.g., CH3 = voltage, CH4 = current)  
- **Waveform mode:** `RAW/NORM` via `:WAV:DATA?`  
- **Record length:** configurable; choose windows covering **≥ 5–10 fundamental cycles** (e.g., ~200 ms at 50 Hz) for stable \(f_0\) and phasors  
- **Scope settings:** vertical scales, offsets, inversion (`:CHANx:INVert`), and BW limit are honored

---

## 3) Current Measurement Models

### a) Shunt Resistor
\(
I(t) = \frac{V_\text{shunt}(t)}{R_\text{shunt}}
\)
- Example: **R010** \(= 0.01\ \Omega\) low-side; use **Kelvin** sensing if possible.

### b) Current Clamp / Probe
If the clamp outputs **voltage proportional to current** (typical datasheet sensitivity in **mV/A**):
\(
I(t) = V_\text{clamp}(t)\times \underbrace{\left(\frac{\mathrm{A}}{\mathrm{V}}\right)}_{\text{Probe value in software}}
\)
- Example: **100 mV/A** ⇒ \(0.1\ \mathrm{V/A}\) ⇒ **A/V = 10**. Enter **10.0** as the probe value.

If the channel already reports **AMP** (rare, via dedicated interface), set the software probe value to **1.0** to avoid double scaling.

> **Clarification:** We express the software’s clamp value as **A/V** (amps per volt). Avoid “× attenuation” wording for clamps; use **A/V sensitivity**.

---

## 4) Power & RMS Computation (corrected)

Given scaled arrays \( v(n] \) (volts) and \( i(n] \) (amps) with \( n=1..N \):

- **RMS**
\(
V_\mathrm{rms}=\sqrt{\tfrac1N\sum_n v[n]^2},\quad
I_\mathrm{rms}=\sqrt{\tfrac1N\sum_n i[n]^2}
\)

- **Instantaneous & Real Power**
\(
p[n]=v[n]\cdot i[n],\qquad P=\tfrac1N\sum_n p[n]
\)
(valid for **any waveform**)

- **Apparent Power**
\(
S = V_\mathrm{rms}\,I_\mathrm{rms}
\)

- **Fundamental Phasors (for \(Q_1,P_1,\varphi_1\))**  
  Estimate \( f_0 \) in the window; form RMS phasors \(U_1,I_1\) by orthogonal projection at \( f_0 \) (DC removed for the phasor step). Then:
\(
S_1 = U_1\,I_1^*,\quad
P_1=\Re\{S_1\},\quad
Q_1=\Im\{S_1\}
\)
with the **sign convention** \(Q_1>0\) **inductive** (current lags), \(Q_1<0\) **capacitive** (current leads).
- **Power Factor**
\(
\mathrm{PF}=\frac{P}{S}\quad(\text{signed by }P),\qquad
\mathrm{PF}_1=\frac{P_1}{|S_1|}
\)
- **Phase Angle (reported)**
\(
\varphi_1=\arg(S_1)=\arctan2(Q_1,P_1)
\)
> **Important:** We **do not** use \(Q=\sqrt{S^2-P^2}\); it is **signless** and **invalid** under distortion. \(Q_1\) from fundamental phasors is IEEE-1459-consistent and ensures **correct sign**.

---

## 5) Energy Integration

Integrate over elapsed time (window-averaged values):

- **Real energy (Wh):** \( E_P = \sum P_\text{avg}\,\Delta t \)  
- **Apparent energy (VAh):** \( E_S = \sum S_\text{avg}\,\Delta t \)  
- **Reactive energy (varh):** \( E_Q = \sum Q_{1,\text{avg}}\,\Delta t \)  *(reactive energy of the fundamental)*

---

## 6) Scientific Validity & Standards Alignment

- **IEEE Std 1459-2010:** \(P\) from time-domain average of \(v\cdot i\); **\(Q_1\)**, \(P_1\), \(\varphi_1\) from **fundamental phasors**; \(S=V_\mathrm{rms}I_\mathrm{rms}\); PF definitions as above.  
- **IEC 61000-4-30 (method compatibility):** Use **cycle-based** windows (e.g., 10 cycles @ 50 Hz) for stable aggregation; preserve raw waveforms & metadata for **traceability**.  
- Valid for **sinusoidal and distorted** waveforms; sign of \(P\) supports **reverse power**; sign of \(Q_1\) distinguishes **inductive vs capacitive** behavior.

---

## 7) Known Limitations

- Accuracy depends on probe/shunt tolerances, clamp phase/magnitude vs frequency, vertical resolution, ADC pairing, and scope BW.  
- Fixed inter-channel delays (probe/filter) are not automatically de-embedded; keep voltage/current on the **same ADC pair** when possible and use BW limit for stability.  
- Harmonic KPIs (IEC 61000-4-7), flicker (-4-15), dips/swells/RVC are out of scope unless enabled by separate workflows.

---

## 8) Data Logging

Each CSV row contains timestamped metrics:
- \(P\) (W), \(S\) (VA), **\(Q_1\) (var)**, **PF** (signed), **\(\varphi_1\) (deg)**, \(V_\mathrm{rms}\), \(I_\mathrm{rms}\), \(f_0\) (Hz), and energies \(E_P, E_S, E_Q\) (Wh/VAh/varh).

**Example**
Timestamp,P,S,Q1,PF,phi1_deg,Vrms,Irms,f0,EP,ES,EQ
2025-07-21T09:21:44.049118,0.303,1.069,1.023,0.284,73.7,42.894,0.024861,50.00,10.740e-3,3.923e-3,42.583e-3


---

## 9) Practical Tips

- **Shunt (low-side):** Kelvin wiring; CH3=voltage (10×), CH4=shunt drop (1×); enable **20 MHz BW limit** on both; verify polarity (invert if \(P<0\) for a known consumer).  
- **Clamp:** Enter **A/V** sensitivity (e.g., 10.0 for 100 mV/A). If the scope channel is already in **AMP**, use 1.0 in software.  
- **Windows:** Prefer ≥5–10 cycles; for fluctuating \(f_0\), estimate \(f_0\) per window; use rectangular windows for final power averages (cycle-exact) and Hann only for **estimation** when needed.

---

## Conclusion

The revised method delivers:
- **Time-domain \(P\)** (general, distortion-proof)  
- **IEEE-1459 \(Q_1\)** with **correct sign**, \(P_1\), \(\varphi_1\), and PF/PF₁  
- Transparent scaling for **shunt** and **clamp (A/V)**  
- Windowing and logging that support **traceable, reproducible** results

This brings the MSO5000 Liveview Power Analyzer in line with **best-practice definitions** for modern PQ analysis while staying fully auditable and open.
