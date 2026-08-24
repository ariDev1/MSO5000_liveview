# ✅ MSO5000 Live Monitor — Power Analysis Setup (Low-Side Shunt + Two Standard Probes)

Use two **standard passive probes** that ship with the MSO5000 and a **R010 (10 mΩ) low-side shunt**.
This setup works for **DC** and **AC (50/60 Hz or other fundamentals)** with highest practical safety when the shunt is truly **low-side** (near ground).

---

## 🧰 Hardware

- **Shunt:** 10 mΩ (R010), mounted **in the return path** (between load return and supply negative).
  Prefer **Kelvin (4-wire)** connections at the shunt pads for sensing.
- **Probes:** the two standard Rigol passive probes (switchable 1×/10×).
- **Scope:** RIGOL MSO5000 (earth-referenced BNC shell).

> ⚠️ Bench scopes tie the probe **ground clip to protective earth (PE)**.
> Low-side shunt means the most negative node is near ground potential → **safe** to clip grounds there. Never clip probe grounds to two different potentials.

---
## 🔌 Wiring (low-side)

![Screenshot](low_side_shunt_wiring.svg)

- **CH4** measures the **shunt drop** (mV). Tip on the **load side** of the shunt, ground on **Supply(−)**.
- **CH3** measures **voltage vs Supply(−)** (DC bus or AC line vs neutral/return).

> Tip: Keep shunt sense leads short/twisted. If available, solder thin sense wires directly at the shunt pads.

---

## 🛠 Oscilloscope Setup (recommended)

### Channel pairing for minimal skew
- Use the **same ADC pair**: **CH3 (voltage)** + **CH4 (shunt)** share one pair on MSO5000 → best phase alignment.

### CH3 — Voltage
- **Unit:** `VOLT`
- **Probe switch:** **10×** (mandatory for high voltage; 1× is limited to a few volts)
- **20 MHz BW Limit:** ✅ (cleaner PF/phase)
- **Vertical scale:** match your bus/grid voltage (e.g., 100–200 V/div for ~160 V DC with 10×)

### CH4 — Shunt (current via V/R)
- **Unit:** `VOLT`
- **Probe switch:** **1×** (maximize mV sensitivity)
- **20 MHz BW Limit:** ✅
- **Vertical scale:** mV/div (start around 5–20 mV/div)
- **Invert:** *off* initially (we’ll verify polarity in “Sanity Checks”)

### Acquisition
- **Sample rate:** high enough to capture your spectrum (≥10× highest relevant freq)
- **Record length:** cover ≥ 5–10 periods of the fundamental (for stable φ/Q)
- **Coupling:** `DC` on both channels

---

## ⚙️ Live Monitor — Power Analysis Settings

| Field                  | Set To                                        | Notes |
|------------------------|-----------------------------------------------|-------|
| `Voltage Ch`           | `3`                                           | Uses CH3 waveform (volts) |
| `Current Ch`           | `4`                                           | Uses CH4 shunt drop (volts) |
| `Current Probe Type`   | `Shunt` ✅                                     | Enables V→I = V/R |
| `Probe Value`          | `0.01` (for 10 mΩ)                             | In **ohms** |
| `Correction Factor`    | `1.0`                                         | Use for calibration only |
| `DC Offset`            | For **DC**: enable and zero CH4 at no-load if needed. For **AC**: usually **off**. |
| `25M [v]/[i]`          | `Off` for mains/DC unless you need wideband   |     |
| ➤ `⚡ Measure`          | Click to start                                |     |

**What the software does:**
- Computes **P = ⟨v·i⟩** directly in time domain (valid for any waveform).
- Converts CH4 to current via **I = Vshunt / 0.01 Ω**.
- For AC, extracts the **fundamental phasors** to get **Q₁** with **correct sign** (+ inductive, − capacitive) and **φ₁**.

---

## 🧪 Sanity Checks (5 quick steps)

1) **No-load zero (optional, DC):** Power supply on, load disconnected.
   - CH4 should read ~0 mV (small offset is okay). If needed, use `DC Offset` zero in the app.

2) **Resistive load test:** Connect a purely resistive load (lamp/resistor).
   - Expect **PF ≈ 1**, **Q ≈ 0** (AC), **P ≈ U×I** (both DC & AC).

3) **Polarity:** With normal power into the load, **P should be positive**.
   - If **P is negative**, toggle **Invert (CH4)** in the scope *or* the app’s **“Invert current”** option.

4) **Magnitude sanity:**
   - At 5 A, shunt drop ≈ **50 mV**. If you see ~5 mV (×10 error) or ~500 mV (×10 too big), check **probe 1×/10×** and scope **Probe** menu.

5) **Noise:** Enable **20 MHz BW limit** on both channels. Use 1× on CH4 for better mV resolution.

---

## 🎯 Precision Tips

- **Kelvin sense:** If your shunt carrier has separate sense pads, use them. Avoid sensing across long copper pours.
- **Grounding:** One single ground reference at **Supply(−)**. Don’t make a second ground connection elsewhere.
- **ADC pair:** Prefer CH3+CH4 (or CH1+CH2) to minimize inter-channel delay.
- **Phase trim (rare):** If you still see a fixed φ offset with a purely resistive load, note it and apply a tiny correction factor or offset in software.
- **Bandwidth:** For fast pulsed loads, raise sample rate and record length; keep BW limit **on** unless you need the HF content.

---

## 🛡 Safety

- **Never** clip a probe ground to a live/hot node. Bench scope grounds are **earth-bonded**.
- Verify the supply is **floating** or that bonding **Supply(−) → PE** is acceptable for your setup.
- High-energy DC (e.g., 160 V) requires appropriate probe voltage ratings (use **10×** on CH3).
- Keep leads short; secure the shunt mechanically (it runs hot at high current).

---

## 🏁 Quick Reference Table

| Signal                    | CH | Scope Unit | Probe switch | BW Limit | App Probe Type | App Probe Value |
|--------------------------|----|------------|--------------|----------|----------------|-----------------|
| Voltage vs Supply(−)     | 3  | `VOLT`     | **10×**      | On       | —              | —               |
| Shunt drop (V across R)  | 4  | `VOLT`     | **1×**       | On       | **Shunt**      | **0.01 Ω**      |

---

## 📌 Troubleshooting

| Symptom                                   | What to check |
|-------------------------------------------|---------------|
| P negative on a normal load               | Flip CH4 **Invert** (scope) / reverse clamp orientation if you used one |
| Current too small/large by ×10            | CH4 probe switch (1× vs 10×) and scope **Probe** menu; `Probe Value = 0.01 Ω` |
| PF jitter / noisy Q                       | Enable BW limit; increase record length; improve shunt wiring (Kelvin) |
| Disagreement vs external meter (AC)       | Confirm line frequency lock (window covers ≥5–10 periods); ensure shunt value is exact (measure it) |

---

### Formula reminder
- **Current from shunt:** \( I(t) = \dfrac{V_{\text{shunt}}(t)}{0.01\,\Omega} \)
- **Instantaneous power:** \( p(t) = v(t)\,i(t) \), **P** = average of \(p(t)\)
- **AC fundamental (for Q₁):** \( Q_1 = \Im\{U_1\,I_1^*\} \) (positive = inductive, negative = capacitive)
