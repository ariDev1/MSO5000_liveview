# Understanding Current Probe vs Differential Probe (Across Shunt) in Oscilloscope Power Measurements

## Scenario

You are measuring current in a circuit using an oscilloscope.  
You have two options:

1. **Current Probe** (e.g., clamp, Hall effect, Rogowski)
2. **Differential Probe across a shunt resistor**

Configuring your oscilloscope or analysis software as if your diff probe was a “current probe” (unit: AMP) gave incorrect results. Why?

---

## Key Differences

| Probe Type          | Senses               | Output Voltage Means      | Software Conversion Needed?| Example Scaling     |
|---------------------|----------------------|---------------------------|----------------------------|---------------------|
| **Current Probe**   | Magnetic field       | Proportional to current   | No (if scaling correct)    | 1V/A, 10mV/A, etc   |
| **Diff Probe+Shunt**| Voltage difference   | Voltage across shunt      | **Yes, V/Ω**               | —                   |

---

## How They Work

### 1. **Current Probe (Clamp, Hall, Rogowski)**
- **Senses:** Magnetic field around the conductor (no circuit interruption)
- **Outputs:** Voltage **directly proportional to the measured current**
    - e.g., 1V out = 1A flowing (if probe designed for this scaling)
- **Oscilloscope Setup:** Set channel unit to AMP, enter correct probe scaling.
- **Software:** No conversion needed if probe scaling is set—voltage is already "current".

### 2. **Differential Probe (Across Shunt Resistor)**
- **Senses:** Voltage drop across the shunt resistor.
- **Outputs:** Voltage **proportional to current, but must use Ohm's law**:
    - `I = V / R_shunt`
    - e.g., 10mV across 0.01Ω shunt = 1A
- **Oscilloscope Setup:** Channel unit should be VOLT (not AMP).
- **Software:** Enter shunt resistance (Ω) so software converts voltage to current.

---

## **Common Pitfall**

**Setting your oscilloscope channel to “AMP” when using a diff probe + shunt does NOT make the measurement correct.**  
- The scope only changes the displayed unit, not the actual conversion.
- Unless the scope’s probe settings *also* know your shunt value, results will be incorrect.

---

## **Correct Setup for Differential Probe + Shunt**
1. **Scope channel unit:** VOLT
2. **In analysis software:**  
    - Select **Probe Type: Shunt**
    - Enter shunt value in Ω
    - The software will compute current as `I = V / R_shunt`

---

## **Summary Table**

| Setup                         | Scope Unit | Probe Type | Value      | Software Conversion        | Correct? |
|-------------------------------|------------|------------|------------|----------------------------|----------|
| Clamp Current Probe           | AMP        | Clamp      | (V/A)      | None (if scaling set)      | Yes      |
| Diff Probe Across Shunt       | VOLT       | Shunt      | (Ω)        | `I = V / R_shunt`          | Yes      |
| Diff Probe + Shunt, unit: AMP | AMP        | Clamp      | 1.0        | None                       | **No**   |

---

## **Practical Advice**

- **Use current probe + “AMP” only if you have a real current probe.**
- **For shunt+diff probe, always use VOLT and set the correct shunt value in your analysis software.**
- **Double-check your software scaling and units!**

---

**If you see weird current readings or power calculations, check your probe type, scaling, and software settings.**
