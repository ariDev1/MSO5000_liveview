# 🧠 RIGOL MSO5000 Live Monitor (Hacked FW Compatible)

> **Current Version:** v0.9.8i-stable
> 📦 See [Release Notes](https://github.com/ariDev1/MSO5000_liveview/releases/tag/v0.9.8i-stable)

This tool provides a live view and SCPI-based data extraction from a **Rigol MSO5000** oscilloscope with **hacked firmware**, using VNC for screenshots and VISA (SCPI) for waveform data.

![Screenshot](docs/screenshot.png)


**True power computation** is performed via pointwise multiplication of voltage and current waveforms followed by averaging:

# $P = \frac{1}{N} \sum_{n=1}^{N} v_n \cdot i_n$

This method remains accurate for arbitrary waveshapes and is not dependent on sinusoidal assumptions.

---

## 🧩 Features

- 📷 Live screenshots from the oscilloscope (via VNC)
- 📊 Channel settings: coupling, bandwidth, scale, offset, probe
- ⏱️ Trigger and timebase information
- 📈 Waveform measurements: Vpp, Vavg, Vrms (up to 4 channels)
- 📤 CSV export of waveform data
- 🧪 **Long-time measurement mode with pause/resume/stop**  
  ↪️ Saves all data to a single timestamped CSV  
  ↪️ Timestamped rows at user-defined intervals  
  ↪️ Performance tips built into the UI
- 🧠 **Live Power Analyzer** with PQ chart and scaling  
  ↪️ Real-time P/S/Q/PF/Vrms/Irms calculations  
  ↪️ Probe scaling (shunt/clamp + unit conversion)  
  ↪️ Display of PF angle and cumulative energy  
  ↪️ Heatmap-style PQ trail with fading  
  ↪️ Shows `Reference: CURRENT` or `VOLTAGE` from scope
- 🐞 Scrollable debug log
- ⚙️ Manual SCPI tab with command input and response log  
  ↪️ Command list from `scpi_command_list.txt` (click or double-click to load)  
  ↪️ Error-safe querying with response log  
  ↪️ Full debug trace included
- 🌙 Dark mode GUI with resizable window and tabs
- 🐳 **Docker support** for easy deployment (X11 + Wayland)

---

## 📘 Whitepaper: Understanding Accurate Power Measurement

We published a technical whitepaper detailing how to achieve scientifically valid power analysis using the Rigol MSO5000 series oscilloscopes. It compares the internal PQ tool vs. our custom MSO5000 Live Monitor.

🔗 [Read the Whitepaper (Markdown)](docs/Rigol_Power_Analysis_Whitepaper.md)

> Covers probe configuration, scaling errors, and real-world lab results with shunts and differential probes.

---

## 🛠️ Installation (Tested on Ubuntu 24.04 Noble)

### Qt preview (feature/qt-ui)

The Qt viewer is an **alternative application** alongside the tested Tk version.
It uses the existing SCPI waveform, power and long-time logger modules. To try it
from this branch, install the additional Qt dependencies into a Python virtual
environment and run:

```bash
pip install -r requirements-qt.txt
python -m qt_app.main --ip 192.168.1.100
```

On Ubuntu/Debian, Qt's X11 plugin also needs `sudo apt install libxcb-cursor0`.
On Arch/Omarchy, install `xcb-util-cursor` instead. On Wayland, you can run
with `QT_QPA_PLATFORM=wayland` if the X11 plugin is unavailable.

Omit `--ip` to enter the address in a dialog. Core workflows available now are
resizable live VNC screenshots (with an enlarge button), detailed system and
channel status, licensed options, documentation, CSV waveform export and copy,
long-time logging with pause/resume, power measurement with CSV, PQ and 3D
views, SCPI console with command list, B-H Curve, Harmonics/THD, and Noise
Inspector. Analysis views share the existing calculation functions; their
control layouts and some specialized Tk-only options still differ. Outputs use
`oszi_csv/` as before. `python main.py` and the current Docker image still
launch the established Tk application.

Qt communication runs in a background I/O queue; a failed connection can be
retried with **Reconnect**. A scope and VNC service are needed to check live
operation; the automated tests use simulated connections.

### 📦 Native Python Setup

```bash
sudo apt install python3-tk python3.12-venv

git clone https://github.com/ariDev1/MSO5000_liveview.git
cd MSO5000_liveview/
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Or use the prewritten install script:

```bash
bash how-to-install.txt
```

> 💡 Tested on Ubuntu 24.04 LTS with Python 3.12 and VNC enabled on the Rigol scope.

### 🧓 Ubuntu 22.04 LTS Compatibility

If you're using **Ubuntu 22.04 LTS**:

```bash
sudo apt install python3 python3-pip python3-tk libxcb-xinerama0
```

Then install dependencies manually:

```bash
python3 -m venv venv
source venv/bin/activate
pip install pillow numpy pyvisa pyvisa-py requests vncdotool psutil zeroconf
```

---

## 🐳 Docker Support (X11 and Wayland compatible)

You can run this app in a **Docker container with GUI**.

On Omarchy or Arch Linux, install the host X11 authorization tool first:

```bash
sudo pacman -S xorg-xhost
```

### 🔧 Build the Image

```bash
./build-docker.sh
```

The build script stamps the image with the current Git version, commit, and UTC build date.

### 🚀 Run It

```bash
./run.sh
```

The script auto-detects X11 or Wayland and sets up display bridging.
It stops with a prerequisite message if `xhost` is not installed.

### 📁 Where Are My CSV Files?

All exported CSV files go to:

```bash
~/oszi_csv/
```

This folder is mounted into the container.

---

## 📦 Python Requirements

Create a virtual environment first:

```bash
python3 -m venv venv
```
Then install with:

```bash
pip install -r requirements.txt
```

Required packages:
- `pillow`, `numpy`, `pyvisa`, `pyvisa-py`
- `requests`, `vncdotool`, `psutil`, `zeroconf`

---

## 🖧 Prerequisites

- Rigol MSO5000 on **same local network**
- **VNC enabled** on the oscilloscope
- **SCPI over TCP/IP enabled**
- Know the IP address of the scope

---

## 🚀 How to Use

Launch the app:

```bash
python3 main.py
```

Enter the oscilloscope’s IP when prompted. GUI includes:

- 🔍 Live screenshot
- 📂 Tabbed interface:
  - System Info
  - Channel Data
  - Debug Log
  - Licenses
  - Long-Time Measurement (with CSV export)
  - SCPI
  - Power Analysis

---

## 📁 File Structure

```
MSO5000_liveview/
├── app/
├── docs/
├── gui/
├── Dockerfile
├── run.sh
├── .dockerignore
├── headless/
├── logger/
├── scpi/
├── main.py
├── build_version.py
├── version.py          ← auto-generated
├── requirements.txt
├── how-to-install.txt
├── oszi_csv/           ← output folder for logs
├── utils/
```

---

## ⚠️ Firmware Notice

This tool targets **hacked firmware** (unofficial). Compatibility improvements include:

- Skipping problematic SCPI commands
- Handling timeouts gracefully
- Adapting to patched behavior

---

## 📃 License

This project is for **educational and personal use only**.  
Not affiliated with Rigol Technologies.

---

## Branches

- `master`: Stable, tested version — always works
- `testing`: Work-in-progress branch — may break

👉 Please do **not** push directly to `master`. All changes go into `testing` first.

---

## 📖 Changelog

See [CHANGELOG.md](CHANGELOG.md) for full version history.

---
## 🐶 Fuel This Project With Dogecoin

Much wow. So helpful. Very accurate. If you like what you see:

**DOGE:** `DCeBDHshvL36ZnkctdFzhsZUUhknW1zzbC`  
[![Donate DOGE](https://img.shields.io/badge/-Donate%20in%20DOGE-yellow?logo=dogecoin)](dogecoin:DCeBDHshvL36ZnkctdFzhsZUUhknW1zzbC)

![Doge QR](https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=dogecoin:DCeBDHshvL36ZnkctdFzhsZUUhknW1zzbC)

---

![REPO Card](docs/mso5000_repo_card2.png)
