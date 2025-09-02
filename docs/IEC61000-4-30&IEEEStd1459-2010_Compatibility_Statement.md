# IEC 61000-4-30 & IEEE Std 1459-2010 — Methodological Compatibility Statement

**Software:** MSO5000 Live Monitor  
**Purpose:** Live/long-term waveform logging and power analysis (P, S, Q, PF) from Rigol MSO5000 oscilloscopes.

This document states how the software’s **measurement chain, processing windows, and definitions** are aligned with:
- **IEC 61000-4-30** (*Power quality measurement methods* — acquisition, aggregation, traceability),
- **IEEE Std 1459-2010** (*Definitions for electric power quantities in sinusoidal and non-sinusoidal conditions* — P/S/Q/PF, fundamental components).

> **Scope note (honest framing):** This software implements **methodological compatibility** for the quantities it reports (P, S, PF, Q₁, φ₁, Vrms/Irms) and for **time aggregation**. It does **not** claim full instrument certification (e.g., Class A type tests) nor does it implement every PQ index (e.g., flicker per IEC 61000-4-15, RVC, event detection suites) out of the box. It keeps raw-data integrity and traceability so results are auditable and reproducible.

---

## 1) Raw-Data Integrity & Traceability (IEC 61000-4-30)
- Waveforms are acquired **verbatim** via SCPI (e.g., `:WAV:DATA?`) with the oscilloscope’s native sampling; the software **does not modify** the instrument’s raw samples beyond optional, transparent steps chosen by the operator (e.g., bandwidth limit in the scope itself).
- Metadata captured with each record (timebase, scales, offsets, probe factors, channel units) and the instrument ID (`*IDN?`) are logged alongside **ISO-8601 timestamps** for audit trails.
- Long-term logs and power-analysis CSVs include all derived quantities, enabling post-hoc verification against the raw waveforms.

**Implication:** This satisfies IEC 61000-4-30 expectations around **data transparency** and **traceability** for the quantities the tool reports.

---

## 2) Time Aggregation & Windows (IEC 61000-4-30 alignment)
- RMS and power quantities are computed over user-selectable windows that can be aligned to **10 cycles @ 50 Hz** / **12 cycles @ 60 Hz** (~200 ms) for short-term values, and over longer rolling windows (e.g., 3 s / 10 min) for reporting/averaging, matching common IEC practice.  
- For fluctuating fundamentals (e.g., drives), the tool can estimate **f₀** per window and process whole-cycle windows to minimize spectral leakage (Hann windowing optional for estimation; cycle-exact rectangular windows for the final metrics).

**Implication:** Aggregation behavior is **consistent with IEC 61000-4-30 methodology** for PQ measurement windows (where applicable to the quantities reported).

---

## 3) Power-Quantity Definitions (IEEE 1459-2010 alignment)
The software uses **two complementary layers**:

### 3.1 Real Power (time-domain, general)
- **Instantaneous power:** \( p(t) = v(t)\,i(t) \)  
- **Real (active) power:** \( P = \langle p(t) \rangle \) (sample-synchronous mean).  
This is valid for **any waveform**, sinusoidal or not.

### 3.2 Fundamental Phasor Layer (Q₁, P₁, PF₁, φ₁)
- **Fundamental extraction** (per analysis window): estimate \( f_0 \), form RMS phasors \( U_1, I_1 \) by orthogonal projection at \( f_0 \).
- **Complex power at fundamental:** \( S_1 = U_1\,I_1^* \).  
  - \( P_1 = \Re\{S_1\} \)  
  - \( Q_1 = \Im\{S_1\} \) with **sign convention:** \( Q_1>0 \) **inductive** (current **lags**), \( Q_1<0 \) **capacitive** (current **leads**).  
  - \( \varphi_1 = \arg(S_1) = \arctan2(Q_1, P_1) \), \( \text{PF}_1 = P_1 / |S_1| \).
- **Total apparent power:** \( S = V_\mathrm{rms} I_\mathrm{rms} \).  
- **Total PF (signed):** \( \text{PF} = P/S \) (sign follows \(P\)).

> We **do not** use \( Q = \sqrt{S^2 - P^2} \) (non-sinusoidal case → wrong and signless). Instead, **Q₁** is reported from fundamental phasors per **IEEE 1459**. This yields **correct sign** and robust behavior with distortion.

**Implication:** Definitions for P, S, PF, and **reactive power at the fundamental (Q₁)** are **IEEE 1459-compliant**, ensuring meaningful results under distortion and unbalance.

---

## 4) Multi-Phase Support (method level)
- Per-phase \( P = \langle v_k i_k \rangle \) with **sum over phases** \( P_\Sigma = \sum_k P_k \) when all waveforms are available.  
- For 3-wire balanced systems, the well-known **two-wattmeter** formulation can be derived from the same principles; the software’s recommended approach is still **per-phase time-domain multiplication** when phase waveforms are available (highest fidelity).

---

## 5) Scaling & Units (traceable configuration)
- **Current via shunt:** set **Shunt** (Ω) → \( i(t) = v_\text{shunt}(t)/R \).  
- **Current via clamp:** set **Clamp** (A/V sensitivity) → \( i(t) = v_\text{clamp}(t) \times (\mathrm{A}/\mathrm{V}) \).  
- If the scope channel itself is already in **AMP**, software scaling is disabled to avoid **double correction**.

---

## 6) Accuracy & Limitations (transparent)
- **Instrument chain dominates** uncertainty: probe factors, shunt tolerance, clamp phase/magnitude vs. frequency, ADC alignment.  
- **Windows:** For best accuracy, use cycle-exact windows (≥ 5–10 periods) and appropriate sampling/bandwidth.  
- **No full PQ suite:** Events like flicker (IEC 61000-4-15), RVC, dips/swells detection, mains signaling, and harmonic grouping (IEC 61000-4-7) are **outside** the current scope unless explicitly enabled by user workflows.
- **Certification:** No claim of formal **Class A** certification. The software provides a **method-compatible** path with full raw-data traceability so laboratories can audit/validate.

---

## 7) Verification (operator checklist)
1. **Resistive test load:** expect \( \text{PF} \approx 1 \), \( Q_1 \approx 0 \).  
2. **Known inductive/capacitive load:** verify \( \text{sign}(Q_1) \) (inductive \(+\), capacitive \(−\)) and \( |\varphi_1| \) vs. expectation.  
3. **3-phase (if applicable):** per-phase \(P_k\) sum to system \(P\); signs match energy flow.  
4. **Cross-check:** Compare \( P \) to a calibrated meter over the same interval; differences should be explainable by probe scaling and bandwidth.

---

## Conclusion

By:
- preserving **raw waveform integrity** with complete **traceability**,  
- aligning **aggregation windows** and reporting practices with **IEC 61000-4-30**, and  
- using **IEEE 1459** power-quantity definitions (especially **Q₁** from fundamental phasors, **not** \( \sqrt{S^2-P^2} \)),

**MSO5000 Live Monitor** is **methodologically compatible** with IEC 61000-4-30 and **conforms to IEEE Std 1459-2010** for the power quantities it reports. This ensures **reproducible, sign-correct, and audit-ready** measurements across sinusoidal and non-sinusoidal conditions.

---

## References

- **IEC 61000-4-30:2015 + A1:2021** — *Electromagnetic compatibility (EMC) – Part 4-30: Testing and measurement techniques – Power quality measurement methods.* (Available via IEC Webstore / national standards bodies.)
- **IEEE Std 1459-2010** — *Definitions for the Measurement of Electric Power Quantities Under Sinusoidal, Nonsinusoidal, Balanced, or Unbalanced Conditions.*
- Related (contextual): **IEC 61000-4-7** (harmonic measurement methods), **IEC 61000-4-15** (flicker measurement).

