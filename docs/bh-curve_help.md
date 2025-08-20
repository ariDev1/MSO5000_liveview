# BH-Curve — Operator Help

**Purpose.** This tab computes and plots the magnetic hysteresis loop \(B(H)\) from two scope inputs:
- **Current through the winding** (I) → used to compute \(H = \tfrac{N\,I}{l_e}\).
- **Voltage across the same winding** (V) → integrated to flux \(\Phi = \int V\,dt\), then \(B = \tfrac{\Phi}{N\,A_e}\).

Accurate **geometry** (N, \(A_e\), \(l_e\)) and **probe scaling** (shunt/clamp) are mandatory. Deskew compensates instrument delays only—never to “tune” physics.

---

## 1) What you can set

### Toolbar
- **Acquire & Plot** — capture current waveforms and draw B-H.
- **Auto** + **Interval (s)** — periodic capture; Interval = refresh period.
- **T=1** + **Avg cycles** — extract exactly one electrical period and (optionally) average the last *N* periods to improve SNR.
- **Ref for cycle detect: I / V / Auto** — which trace to lock the period on (use the cleaner, more periodic one).
- **💾 Save PNG / Detailed CSV** — export plot and per-sample data (t, V, I, H, B) for traceability.
- **⭮ Clear** — clear current plot/history.
- **Plot focus / Data** — toggle control visibility and numeric diagnostics pane.

### Core Geometry
- **Turns N** — turns of the *sense* winding used in both formulas.
- **Ae (mm²)** — effective cross-section area (entered in mm²; converted internally).
- **le (mm)** — effective magnetic path length (mm; converted internally).

### Channels & Probe
- **Current channel** — scope channel carrying current.
- **Voltage channel** — scope channel across the same winding.
- **Deskew Δt (V−I) [µs]** — positive means V arrives *later* than I; the app delays I by +Δt to align instrumentation paths.
- **Probe type & value**  
  - *Shunt:* enter R (Ω); current is \(I = V/R\).  
  - *Clamp:* enter sensitivity (A/V); current is \(I = V·(A/V)\).

### Sampling & Processing
- **Mode: NORM / RAW** — RAW can deliver higher point density; NORM is most robust.
- **Pts** — requested points per acquisition.
- **Stop/Fetch** — briefly stop the scope to fetch a stable frame, then resume.
- **Remove DC / Detrend** — suppress offsets/drift **before** integration (critical for \(\int V dt\)).
- **Equal aspect / Tight fit / Overlay prev.** — plot cosmetics and comparison.

---

## 2) Signal classes & recommended settings

Use these recipes depending on whether your waveforms are sinusoidal or pulsed/oscillatory. The **Ref**, **T=1**, **Avg**, and **Mode** choices are the big levers.

| Case | Typical waveforms | Ref (cycle detect) | T=1 | Avg cycles | Auto | Mode | Pts | Deskew Δt | Remove DC / Detrend |
|---|---|---|---|---:|---|---|---:|---:|---|
| **A. Sinusoidal (50/60 Hz or LF sine)** | I, V ~ sinusoidal | **I** (cleaner zero-cross) | **On** | 4–16 | On (1–2 s) | NORM | 1–5k | 0–20 µs (as measured) | **On / On** |
| **B. Steady PWM / square (kHz)** | I trapezoid, V pulse & ringing | **I** (if shunt), else V | **On** | 8–64 (if period-stable) | On (0.2–1 s) | **RAW** | **≥10k** | 0–2 µs typical | **On / On** |
| **C. Burst / single-shot / flyback** | One pulse + ring-down | **V** (edges are crisp) | **Off** | 1 | **Off** | **RAW** | **Max** | Use prior calibration | **On / On** |
| **D. Aperiodic startup / sweep** | Non-repeating | **V** or **I** (whichever has features) | Off | 1 | Off | RAW | High | Use prior calibration | **On / On** |

> **Rationale**  
> • *T=1 + Avg cycles* improves SNR **only** for periodic/stable excitations.  
> • For pulses/transients, averaging smears physics → keep Avg = 1.  
> • RAW + high Pts captures fast edges/ringing needed for accurate \(\int V dt\).

---

## 3) Cycle detection guidance

1. **Choose Ref wisely.** Use the cleaner, more periodic channel:  
   - With a **shunt**, current (I) is usually best for both sine and PWM.  
   - Voltage (V) has crisp edges; better for bursts, but excessive ringing can confuse period finding.
2. **What T=1 does.** The app detects one period from Ref and resamples both I and V onto that window before computing H and B.  
3. **Aperiodic/Transient.** Turn **T=1 Off**. The app integrates over the whole captured window; ensure the window fully covers the event.

---

## 4) Deskew (Δt) for accuracy

- **Definition in this app:** Δt = (V − I). If Δt > 0, voltage arrives *later* than current → the app delays I to match V.  
- **How to set:** excite the winding with a clean edge or a stable sine. Adjust Δt so **simultaneous physical events align** (edge onset, zero-cross). Do **not** “tune for pretty loops.”  
- **Why it matters:** Any relative delay between I and V distorts the loop area (loss) and the apparent coercivity.

---

## 5) Tips per signal class

### A) Sinusoidal
- **Ref = I**, **T=1 On**, **Avg 4–16**, **Auto On**.  
- Keep **Remove DC/Detrend On** to avoid integrator drift from probe offset.  
- With mains hum, prefer **Stop/Fetch On** for consistent headers.

### B) Steady PWM / Square
- Prefer **RAW** and **high Pts** to resolve edges and ringing.  
- **Ref = I** (if shunt), else **V** when I is noisy.  
- **T=1 On** only if period is stable (constant frequency & duty). Otherwise set **Avg=1**.

### C) Burst / Single-Shot / Flyback
- Set the scope to **Single** acquisition; trigger on the pulse edge.  
- In the app: **Auto Off**, **T=1 Off**, click **Acquire & Plot** once.  
- Use **Detailed CSV** for later verification.  
- If the baseline drifts between runs, re-zero probes (Remove DC/Detrend stay **On**).

### D) Aperiodic Startup / Sweep
- **Auto Off**, **T=1 Off**. Choose **Ref** with the most distinctive features to anchor the time window.  
- Consider **Equal aspect Off** and **Tight fit On** to see the full loop excursion.

---

## 6) Measurement wiring and scope setup (must-do’s)

- **Measure across the same winding** for V that you use N for in the geometry. Use a **differential probe** or a truly floating scope input.  
- **Current sense**:  
  - *Shunt*: 4-wire/Kelvin if possible; minimize loop area; know the exact R at operating temperature.  
  - *Clamp*: enter A/V correctly; disable built-in scope scaling (set the probe to 1× in the scope if the app handles scaling).  
- **Scope configuration**: DC coupling, sufficient bandwidth (avoid 20 MHz limit for fast pulses), adequate vertical scale without clipping.  
- **Sampling**: choose timebase so one or more complete periods (or the entire pulse) are in view. Increase **Pts** when using short timebases.

---

## 7) Validation & sanity checks

- **Air-core check**: with the core removed, slope \(\frac{B}{H}\) ≈ \(\mu_0\). Good for geometry sanity.  
- **Datasheet check**: small-signal slope near H≈0 should be ≈ \(\mu_r\mu_0\). Saturation knee should appear at expected H.  
- **Repeatability**: with the same settings, repeated runs should overlay within noise. If not, check trigger stability, deskew, and DC offsets.
- **CSV traceability**: keep **Detailed CSV** when publishing results. It documents (t, V, I, H, B) for independent re-analysis.

---

## 8) Troubleshooting quick list

- **Loop drifting vertically** → turn **Remove DC** and **Detrend** on; check probe zero.  
- **Area looks too big/small** → verify **Ae, le, N**, and **Deskew Δt**; ensure V is across the correct winding.  
- **Noisy, fuzzy loop** → increase **Avg cycles** (only if periodic), increase **Pts**, reduce bandwidth limiting, improve probe grounding.  
- **Cycle detection fails** → switch **Ref** from I↔V, reduce noise, or turn **T=1 Off** for transients.  
- **Integration blow-up on pulses** → window the event cleanly (trigger earlier), keep **Detrend** on.

---

## 9) Safety and data integrity

- Deskew compensates instrumentation delay only. **Do not** use it to “fix” physics.  
- Never apply math scalings twice (scope probe settings vs. app). Decide where scaling lives.  
- Use differential probes for high-voltage windings; obey their CAT ratings.  
- Exports include instrument ID and geometry metadata; raw measurements are **never** altered beyond the stated processing (DC removal, detrend, resampling for T=1).

---

### Formula summary
\(H = \frac{N\,I}{l_e} \quad B = \frac{1}{N\,A_e}\int V\,dt \)

with \(N\) in turns, \(A_e\) in m², \(l_e\) in m, **I** in A from shunt/clamp scaling, **V** in V across the same winding.

---

**Version:** 2025-08-10 20:01 UTC
