# 🧠 RIGOL MSO5000 Live Monitor (Hacked FW Compatible)

This tool provides a live view and SCPI-based data extraction from a **Rigol MSO5000** oscilloscope with **hacked firmware**, using VNC for screenshots and VISA (SCPI) for waveform data.

![Screenshot](docs/screenshot.png)

---

## 🧩 Features

- 📷 Live screenshots from the oscilloscope (via VNC)
- 📊 Channel settings: coupling, bandwidth, scale, offset, probe
- ⏱️ Trigger and timebase information
- 📈 Waveform measurements: Vpp, Vavg, Vrms (up to 4 channels)
- 📤 CSV export of waveform data
- 🧪 Long-time measurement mode with pause/resume/stop
- 🐞 Scrollable debug log
- 🌙 Dark mode GUI with resizable window and tabs

---

## 🛠️ Installation (Tested on Ubuntu 24.04 Noble)

Run these commands in your terminal:

```bash
sudo apt install python3-tk

git clone https://github.com/ariDev1/MSO5000_liveview.git
cd MSO5000_liveview/
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Alternatively, you can use the prewritten installation script:

```bash
bash how-to-install.txt
```

> 💡 This setup is tested on Ubuntu 24.04 LTS with Python 3.12 and VNC enabled on the Rigol scope.

---

## 📦 Python Requirements

Listed in `requirements.txt`, install with:
```bash
pip install -r requirements.txt
```

Dependencies include:
- `pillow`, `numpy`, `pyvisa`, `pyvisa-py`
- `requests`, `vncdotool`, `psutil`, `zeroconf`

---

## 🖧 Prerequisites

- Your Rigol MSO5000 is on the **same local network** as your PC
- **VNC** is enabled on the oscilloscope
- **SCPI over TCP/IP** is working
- You know the IP address of the scope

---

## 🚀 How to Use

After launching the app:
```bash
python3 main.py
```

You’ll be prompted to enter the IP address of the oscilloscope. The GUI will show:

- Live screenshot (top)
- Tabbed interface:
  - **System Info**
  - **Channel Data**
  - **Debug Log**
  - **Licenses**
  - **Long-Time Measurement** (with CSV export)

---

## 📁 File Structure

```
MSO5000_liveview/
├── main.py
├── rigol_vnc_liveview8.py
├── requirements.txt
├── how-to-install.txt
├── oszi_csv/              ← CSV exports stored here
├── docs/
│   └── screenshot.png     ← Screenshot shown in README
```

---

## ⚠️ Firmware Notice

This tool is optimized for **hacked firmware** (unofficial). Adjustments have been made to:

- Skip unstable SCPI queries
- Avoid timeouts and hangs
- Maintain compatibility with patched behavior

---

## 📃 License

This project is for **educational and personal use only**.  
Not affiliated with Rigol Technologies.
