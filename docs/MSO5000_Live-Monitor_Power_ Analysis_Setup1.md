# ✅ MSO5000 Live Monitor — Power Analysis Setup Checklist  
### 🧪 For Shunt-Based DC Power Measurements (Low-Side Current Sensing)

---

## 🧰 Hardware Assumptions

- **DC power supply** (e.g., 40V / 3.5A)
- **Shunt resistor** on the **negative rail** (e.g., R010 = 0.01Ω)
- **Voltage measurement**: CH2
- **Shunt voltage measurement**: CH3

---

## 🛠 Oscilloscope Setup (on RIGOL MSO5000)

### CH2 — Voltage Channel
- Connect to the positive side of your load or power supply
- Set **unit**: `VOLT`
- Set **probe**: `10X` *(or `1X`, depending on your probe type)*
- Enable **20 MHz BW Limit** ✅

### CH3 — Shunt Voltage (Current)
- Connect across the shunt resistor (GND/negative side)
- Set **unit**: `VOLT` ⚠️ *(not AMP!)*
- Set **probe**: `1X` *(unless using attenuated probe or amp clamp)*
- Enable **Invert** if waveform is upside down
- Enable **20 MHz BW Limit** ✅

---

## ⚙️ Live Monitor: Power Analysis Tab Setup

| Field                | Value / Action                          | Why                                                   |
|----------------------|-----------------------------------------|--------------------------------------------------------|
| `Voltage Ch`         | `2`                                     | CH2 measures supply/load voltage                      |
| `Current Ch`         | `3`                                     | CH3 connected across shunt                            |
| `Correction Factor`  | `1.0`                                   | Leave as-is unless doing manual calibration           |
| `Current Probe Type` | `Shunt` ✅                               | Required for converting volts → amps                  |
| `Probe Value (Ω)`    | `0.01` for R010                         | Your shunt's resistance                               |
| `Expected P (W)`     | *(Optional)* e.g. `250` → hit ⚙ Cal     | Auto-tune if you know expected power                  |
| `DC Offset`          | ✅ Check if signal has DC baseline drift | Improves PF and FFT accuracy                          |
| `25M [v]/[i]`        | ❌ Leave off unless needed               | Only enable for high-resolution waveform fetches      |
| ➤ `⚡ Measure`        | Click to run power analysis             | You’re done ✅                                         |

---

## 🧾 Cross-Check (Recommended)

- ✅ Does `Real Power` ≈ Voltage × Current from your DC supply?
- ✅ Is `Irms` ~ what your shunt should show?
- ✅ Does PF or phase angle make sense for your load?

Use `📈 Plot Last` to visualize your PQ triangle.

---

## ⚠️ Important: Rigol PQ Will Be Wrong

> **Rigol’s Power Quality feature assumes CH3 is already in Amps.**  
> If you're measuring shunt voltage, Rigol will report 100× too little power.

📌 **Only Live Monitor properly scales shunt measurements.**

---

## 🏁 Quick Reference Table

| Signal           | CH | Scope Unit | GUI Probe Type | Probe Value |
|------------------|----|-------------|----------------|-------------|
| Voltage (V)      | 2  | `VOLT`      | —              | —           |
| Shunt Voltage    | 3  | `VOLT`      | `Shunt`        | `0.01`      |
| Current Clamp    | 3  | `VOLT`      | `Clamp`        | e.g. `1000` |
| Current Direct   | 3  | `AMP`       | `Clamp`        | e.g. `1.0`  |

---

🧠 *Still confused? If Rigol says “2.5W” and Live Monitor says “250W” — the latter is correct.*
