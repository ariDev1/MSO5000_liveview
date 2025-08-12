# MSO5000 Liveview — Power Analysis Signal Chain and Math

**Goal:** Transparently document how the app acquires waveforms from a Rigol MSO5000, converts them to physical units, scales current from probe settings, and computes P, S, Q, PF, phase, and energy. This is a read-only spec of the current code path (v0.9.8h-testing).

**Version:** 2025-08-12 11:00 UTC

---

## 1) Measurement topology (operator responsibilities)

- **Voltage channel (V):** select a scope channel (e.g., CH1) that measures the line/load voltage. Keep the scope channel **UNIT = VOLT**. Enable **20 MHz BW limit** on the scope if high-frequency noise hurts RMS/PF.
- **Current channel (I):** two supported modes:
  - **Shunt mode:** measure the shunt’s voltage drop with a differential probe. In the GUI set **Probe Type = Shunt** and **Value = R_shunt in Ω** (e.g., `0.01` for 10 mΩ). The app converts this to a current scale **A/V** by `1/R_shunt`.
  - **Clamp mode:** measure the probe’s **volts-per-amp** output. In the GUI set **Probe Type = Clamp** and **Value = mV/A** (e.g., a 10 mV/A clamp → enter `10`). The app converts to **A/V** via `1 / (mV/A ÷ 1000)`.
- **Scope unit guardrail:** if the current channel is set to **UNIT = AMP** on the scope, the app forces **scale = 1** to avoid double-scaling. Keep the current channel in **VOLT** unless the scope itself is doing the current conversion.
- **Probe factors:** if your differential probe is set to **5×**, set the channel **PROB=5×** so the scope reports the *true* voltage. With shunts this cancels to unity overall (you still enter the shunt value in ohms).
- **Kelvin at the shunt:** sense directly across the shunt pads, short twisted leads, minimal loop area. Prefer **low-side shunt** to avoid common-mode issues.

---

## 2) SCPI acquisition and conversion to volts

The app fetches waveforms over SCPI in **NORM** or **RAW-25M** modes using `:WAV:*` commands. For each selected channel:

1. Configure:
   - `:WAV:FORM BYTE`  
   - `:WAV:MODE NORM` *(or `RAW` for 25M)*  
   - `:WAV:POIN:MODE RAW` and set `:WAV:POIN` (NORM) or 25M points (RAW)
2. Select source and read preamble + data:
   - `:WAV:SOUR CHANn` (or MATHn)  
   - `:WAV:PRE?` → parse `XINC, XORIG, YINC, YORIG, YREF`  
   - `:WAV:DATA?` → raw byte array
3. Convert raw to physical volts:  
   \[ v(t) = (raw - YREF)\cdot YINC + YORIG \]

If 25M mode is used, the app **stops** the scope, fetches, then **RUN** resumes. If the two channels’ lengths mismatch, the longer one is **resampled** so V and I align sample-by-sample.

---

## 3) Current scaling (V → A)

After converting the current channel to volts, the app multiplies by a **current scale** (A/V):

- **Shunt:** `scale = 1 / R_shunt` (R in Ω).  
- **Clamp:** `scale = 1 / (mV_per_A / 1000)` (Value field is **mV/A**).  
- **Scope in AMP:** if the current channel unit is **AMP**, the app sets `scale = 1` (no extra scaling) to avoid double conversion.

Then:  
\[ i(t) = v_{\text{current}}(t) \times \text{scale} \]

A user **Correction Factor** multiplies the base scale (default **1.0**) and is applied uniformly.

---

## 4) Optional conditioning

- **DC removal:** by default the compute path removes mean values of V and I prior to power/phase calculations:  
  \[ v \leftarrow v - \overline{v}, \quad i \leftarrow i - \overline{i} \]  
  This protects against small offsets skewing PF/phase on AC. (Configurable at call site.)
- **Bandwidth:** any BW limiting is performed **on the scope** (e.g., 20 MHz). The app uses whatever the scope sends.

---

## 5) Core calculations

Given aligned arrays \( v(t), i(t) \) with sampling interval \( \Delta t = XINC \):

### 5.1 RMS
\[
V_\mathrm{rms} = \sqrt{\mathrm{mean}(v^2)}, \qquad
I_\mathrm{rms} = \sqrt{\mathrm{mean}(i^2)}.
\]

### 5.2 Instantaneous power and real power
\[
p(t) = v(t)\,i(t), \qquad P = \mathrm{mean}(p(t)).
\]

### 5.3 Apparent power
\[
S = V_\mathrm{rms}\, I_\mathrm{rms}.
\]

### 5.4 Phase and reactive power
The app estimates the fundamental phase of V and I from the **FFT bin 1**:
\[
\phi_v = \angle \mathrm{FFT}(v)[1], \quad
\phi_i = \angle \mathrm{FFT}(i)[1], \quad
\Delta \phi = \phi_v - \phi_i.
\]
Reactive power is computed as:
\[
Q = S \cdot \sin(\Delta \phi).
\]

### 5.5 Power factor
\[
\mathrm{PF} = \frac{P}{S} \quad (\text{signed with }\mathrm{sign}(P)).
\]

> **Note:** Using the fundamental for phase is robust for periodic signals. For non-sinusoidal waveforms, \(P\) still comes from \( \mathrm{mean}(v\,i) \), while \(Q\) is derived from the fundamental phase. This is stated here for traceability.

---

## 6) Numeric integration for energy

During a session the app reports energy by multiplying the **running averages** by elapsed time \(T\) (hours):
\[
E_\mathrm{Wh} = \overline{P}\,T,\;\;
E_\mathrm{VAh} = \overline{S}\,T,\;\;
E_\mathrm{VARh} = \overline{Q}\,T.
\]
These are logged periodically to CSV together with Vrms/Irms and PF.

---

## 7) Safety/guardrails in the compute path

- **Unit check:** if the current channel **UNIT? = AMP**, force `scale = 1.0` to avoid double-scaling and log that choice.
- **Probe reporting:** the app logs the current channel’s `:PROB?` for visibility (no extra math).
- **Length mismatch:** if V and I sample counts differ, the longer series is **interpolated** to align lengths before FFT and power math.

---

## 8) Logging and reproducibility

- **On-screen “Analysis Output”** shows instantaneous and running averages for **P, S, Q, PF, Vrms, Irms**, impedance \(Z = V_\mathrm{rms}/I_\mathrm{rms}\), PF angle \( \theta = \arccos(\mathrm{PF}) \), and elapsed iterations/time.
- **CSV logging (Power tab):** `oszi_csv/power_log_YYYYMMDD_HHMMSS.csv` with columns:  
  `Timestamp, P (W), S (VA), Q (VAR), PF, PF Angle (°), Vrms (V), Irms (A), Real Energy (Wh), Apparent Energy (VAh), Reactive Energy (VARh)`.
- **Long-time logger:** when logging channels, if a channel’s UNIT is **AMP** the logger writes values as-is; otherwise it applies the provided **current scale**. Results per channel include Vpp/Vavg/Vrms (optionally) multiplied by the scale.
- **Channel snapshot:** the SCPI loop records `scale, offset, coupling, probe` for active CH1–CH4 and MATH types for MATH1–3; the “Channel Data” tab renders this, aiding traceability of scope-side settings.

---

## 9) Operator checklist (to maximize accuracy)

1. **Topology:** Prefer **low-side shunt**; Kelvin connections on shunt pads; twisted pair, small loop.
2. **Scope config:** VOLT units on both channels; **PROB** matches hardware (e.g., 5×/5×); enable **20 MHz BW** limit when appropriate.
3. **GUI entries:** 
   - Shunt: enter **R (Ω)** exactly (e.g., `0.01` for 10 mΩ).  
   - Clamp: enter **mV/A** exactly (e.g., `10` for 10 mV/A).  
   - **Corr = 1.0** unless you have a traceable calibration factor.
4. **Sanity check:** compare CH(current) **Vrms** on scope vs. expected \( I \cdot R \) (shunt) or \( V/A \) (clamp). For shunt=10 mΩ at 1.7–1.8 A you should see **~17–18 mV** on the current channel.
5. **Phase reference:** keep the frequency reference stable; deskew at the scope if needed.

---

## 10) Definitions summary

- \( p(t) = v(t)\,i(t) \) — instantaneous power  
- \( P = \mathrm{mean}(p) \) — real/active power (W)  
- \( S = V_\mathrm{rms} I_\mathrm{rms} \) — apparent power (VA)  
- \( Q = S \sin\Delta\phi \) — reactive power (var)  
- \( \mathrm{PF} = P/S \) (signed by \(P\))  
- \( Z = V_\mathrm{rms}/I_\mathrm{rms} \) — magnitude only; angle from \( \theta = \arctan2(Q, P) \)

---

## 11) Notes on limitations

- The phase angle \( \Delta\phi \) comes from the **fundamental** (FFT bin 1). With heavily non-sinusoidal waveforms, \(P\) remains exact from \(v\cdot i\), while \(Q\) and PF reflect the fundamental component’s phase.
- Energy numbers are **average-based** (not trapezoidal time integration of \(p(t)\)). Over long windows this matches within the averaging tolerance.

