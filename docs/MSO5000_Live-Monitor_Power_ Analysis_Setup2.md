# ✅ MSO5000 Live Monitor — Power Analysis Setup Checklist  
### 🔌 For Grid Power Measurement with Differential Current Probe (High-Voltage AC)

---

## 🧰 Hardware Assumptions

- **Voltage probe**: CH1 — measures 230V AC (grid voltage)
- **Current probe**: CH4 — differential current probe with attenuation (e.g. 5×), placed around load/live wire
- **Scope type**: RIGOL MSO5000
- **Load type**: AC (resistive or reactive), 50Hz
- **Direction**: Current flows *into* the load (positive power)

---

## 🛠 Oscilloscope Setup (on RIGOL MSO5000)

### CH1 — Grid Voltage
- Connect across L–N (line to neutral)
- Set **unit**: `VOLT`
- Set **probe**: `1X` *(or 10X depending on your voltage probe)*
- Enable **20MHz BW Limit** ✅ *(filters noise, improves PF accuracy)*

### CH4 — Grid Current (Differential Probe)
- Connect current probe around **line wire**
- Set **unit**: `AMP` ✅ *(crucial!)*
- Set **probe**: `5X` *(match your differential probe attenuation)*
- Enable **Invert** ✅ *(if current direction is flipped — makes power positive)*  
- Enable **20MHz BW Limit** ✅ *(stabilizes power factor and FFT phase)*

---

## ⚙️ Live Monitor: Power Analysis Tab Setup

| Field                | Value / Action                         | Why                                      |
|----------------------|----------------------------------------|-------------------------------------------|
| `Voltage Ch`         | `1`                                    | CH1 measures grid voltage                 |
| `Current Ch`         | `4`                                    | CH4 measures current                      |
| `Correction Factor`  | `1.0`                                  | No scaling needed — scope already shows real amps |
| `Current Probe Type` | `Clamp` ✅                              | Internally handled as unit = AMP         |
| `Probe Value`        | `1.0`                                  | ⚠️ Leave at 1.0 → no further scaling      |
| `DC Offset`          | ❌ Usually off                         | Optional — turn on if baseline is offset |
| `25M [v]/[i]`        | ❌ Off                                 | Not needed for 50Hz AC                  |
| ➤ `⚡ Measure`        | Click to start                         | Done ✅                                   |

---

## 🧾 Recommended Checks

- ✅ **Vrms** should be around **230V**
- ✅ **Irms** should match what clamp/differential probe shows
- ✅ **Real Power (W)** should be positive (if direction is correct)
- ✅ **Apparent Power (VA)** = Vrms × Irms
- ✅ **Power Factor** matches scope (~0.04 for small reactive loads)
- Use `📈 Plot Last` to view PQ triangle with S/P/Q vectors

---

## ⚠️ Notes on Accuracy

| Case                       | What to Do                          |
|----------------------------|--------------------------------------|
| Current reads negative     | ✅ Enable `Invert` on CH4            |
| Power is 10× too low       | ✅ Check probe setting: `5X` vs `1X` |
| PF is unstable             | ✅ Enable `BW Limit` on CH1 & CH4    |
| Scope reads wrong amps     | ✅ Make sure CH4 unit = `AMP`        |

---

## ✅ Why This Setup “Just Works”

> Because CH4 is set to **AMP** and the scope knows the probe attenuation (`5X`), both the Rigol and Live Monitor treat the data as real-world **Amps**, no manual scaling needed.

**Inversion**, **probe setting**, and **unit type** are all respected by both systems — so the numbers match perfectly.

---

## 🏁 Quick Reference Table

| Signal         | CH | Scope Unit | Probe Setting | GUI Probe Type | GUI Probe Value |
|----------------|----|------------|----------------|----------------|-----------------|
| Grid Voltage   | 1  | `VOLT`     | `1X` or `10X`  | —              | —               |
| Grid Current   | 4  | `AMP`      | `5X`           | `Clamp`        | `1.0`           |

---

🧠 *If Rigol PQ and Live Monitor match exactly — you're doing it right.*
