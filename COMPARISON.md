# 🚀 Why RIGOL MSO5000 Liveview Is Lightyears Ahead

This project isn't just an open-source alternative — it outperforms many commercial tools in real-world usability, flexibility, and data accessibility.

---

## 🧾 1. Clean, Usable CSV Export

**This Tool:**
- ✅ Proper timestamps
- ✅ Per-channel values with `Vpp`, `Vavg`, `Vrms`
- ✅ Single-file export for long-time measurements
- ✅ Works with Python, Excel, LibreOffice
- ✅ No proprietary format traps

**Commercial Tools:**
- ❌ Binary blobs (`.wfm`, `.trc`, `.bin`)
- ❌ Fragmented per-channel files
- ❌ No timestamps or inconsistent time base
- ❌ Locale-specific formatting (e.g., decimal commas)
- ❌ Often unreadable without Windows software

---

## 🧠 2. Full SCPI + VNC Integration

**This Tool:**
- ✅ Real-time waveform capture via SCPI
- ✅ Live VNC screenshot view
- ✅ Tabbed GUI for controls, logs, and measurement
- ✅ Robust support for hacked firmware quirks
- ✅ SCPI Console with self-test and live command injection
- ✅ Auto-blacklisting of failing SCPI queries for stability

**Commercial Tools:**
- ❌ Often support only SCPI or screenshot, not both
- ❌ Timeouts with non-standard firmware
- ❌ No visual feedback outside Windows GUIs
- ❌ GUI freezes on large captures

---

## 🐳 3. Dockerized, Reproducible, Cross-Platform

**This Tool:**
- ✅ Runs on any Docker-capable system (Linux, WSL, CI)
- ✅ No dependency hell
- ✅ Fully containerized GUI with X11 or Wayland support
- ✅ Pull-and-run image via Docker Hub

**Commercial Tools:**
- ❌ Windows-only
- ❌ Complex installation
- ❌ Hardware driver dependencies
- ❌ Impossible to use in headless or CI environments

---

## 💻 4. Modern GUI with Dark Mode

**This Tool:**
- ✅ Tkinter GUI with tabs and dark theme
- ✅ Real-time debug log
- ✅ Channel controls, measurement toggles
- ✅ Pause/resume/stop control
- ✅ Live debug verbosity toggle (FULL vs MINIMAL)
- ✅ Auto-calibration of probe correction based on expected power
- ✅ Real-time energy display: Wh, VARh, VAh
- ✅ Dynamic PQ plot with quadrant detection and trail fading

**Commercial Tools:**
- ❌ Outdated WinForms-style UI
- ❌ No theme or customization
- ❌ Poor responsiveness
- ❌ Often locked to 1024x768 layouts

---

## 💰 5. Pricing & Accessibility

**This Tool:**
- ✅ 100% free and open source
- ✅ Works with hacked firmware
- ✅ No serial checks or online activation

**Commercial Tools:**
- ❌ Licensing or activation required
- ❌ Features gated behind optional modules
- ❌ No updates unless under support contract
- ❌ OS version restrictions

---

## ✅ Summary Comparison

| Feature                          | This Tool ✅                     | Common Commercial ❌          |
|----------------------------------|----------------------------------|-------------------------------|
| CSV export with timestamps       | ✅ Single-file, per-sample, scaled | ❌ Often broken or missing     |
| Works on Linux / Docker          | ✅ Fully portable via Docker      | ❌ Rare or unsupported         |
| Combined SCPI + screenshot       | ✅ Seamless + tabbed GUI          | ❌ Fragmented or absent        |
| Power analysis with PQ plot      | ✅ Real-time with θ, energy, PF   | ❌ Expensive add-ons or missing|
| Logging + Power modes            | ✅ Clean separation + GUI toggles | ❌ One-shot or blocking modes  |
| Free, open source, reproducible  | ✅ Fully                          | ❌ Locked-down, Windows-only   |
| Modular, themed GUI              | ✅ Tkinter + Dark Mode            | ❌ Outdated WinForms           |

---

## 🏁 Conclusion

This tool was built for real users, not just checkboxes.  
It works where others fail — and it costs nothing.

Add it to your toolbox, automate your lab, and never go back.
