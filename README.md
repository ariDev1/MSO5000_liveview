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
- 🐳 **Docker support for easy deployment and portability**

---

## 🛠️ Installation (Tested on Ubuntu 24.04 Noble)

### 📦 Native Python Setup

```bash
sudo apt install python3-tk

git clone https://github.com/ariDev1/MSO5000_liveview.git
cd MSO5000_liveview/
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Or use the prewritten installation script:

```bash
bash how-to-install.txt
```

> 💡 Tested on Ubuntu 24.04 LTS with Python 3.12 and VNC enabled on the Rigol scope.

---

## 🐳 Docker Support (X11 and Wayland compatible)

You can now run this app in a **self-contained Docker container** with GUI support.

### 🔧 Build the Image

```bash
docker build -t mso5000_liveview .
```

### 🚀 Run It

```bash
./run.sh
```

The script automatically detects whether you're running **X11 or Wayland**, sets up the display bridge, and launches the GUI.

### 📁 Where Are My CSV Files?

All exported CSV files are saved to:

```bash
~/oszi_csv/
```

This folder is automatically mapped into the container and persists even after exit.

> Requires: Docker, X11 or Wayland+XWayland, and VNC + SCPI enabled on the oscilloscope.

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
├── Dockerfile
├── run.sh
├── .dockerignore
├── main.py
├── rigol_vnc_liveview8.py
├── requirements.txt
├── how-to-install.txt
├── oszi_csv/              ← (inside Docker mapped to ~/oszi_data/)
├── docs/
│   └── screenshot.png
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
