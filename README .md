# 🧠 RIGOL MSO5000 Live Monitor (Hacked FW Compatible)

This tool provides a live view and SCPI-based data extraction from a **Rigol MSO5000** oscilloscope with **hacked firmware** via VNC and VISA (SCPI) interfaces.

The script displays:
- Live screenshots from the oscilloscope (via VNC)
- Channel information including coupling, bandwidth, scale, offset, and probe settings
- Trigger and timebase settings
- Raw waveform statistics (Vpp, Vavg, Vrms) for up to 4 channels
- A scrollable debug log for diagnostics

## 📦 Requirements

This script is written in Python 3 and depends on the following libraries:

| Library    | Purpose                            |
|------------|------------------------------------|
| `tkinter`  | GUI interface                      |
| `Pillow`   | Image processing for screenshots   |
| `numpy`    | Numerical processing of waveforms  |
| `pyvisa`   | SCPI communication over TCP/IP     |
| `vncdo`    | VNC client to capture screen image |

### 🔧 Install dependencies

Make sure you have Python 3 installed, then:

```bash
sudo apt install python3-tk python3-pip
pip3 install pillow numpy pyvisa
sudo apt install vncdo
```

> Note: On Debian/Ubuntu systems, `vncdo` is often available as a package. If not, install it via `pip install vncdo`.

## 🚀 How to Use

```bash
python3 rigol_vnc_liveview4.py
```

You will be prompted in the terminal to enter the IP address of your RIGOL MSO5000.

Make sure:
- The oscilloscope is on the same network.
- VNC is enabled on the oscilloscope.
- The oscilloscope responds to SCPI commands over TCP/IP.

## ⚠️ Hacked Firmware Notice

This script is optimized to **avoid crashing or hanging** when used with unofficial / hacked firmware:
- Timeouts are reduced
- Some known problematic SCPI queries are skipped or blacklisted after failure

## 📁 Screenshot Path

By default, screenshots are saved temporarily at:
```
/tmp/oszi_screenshot.png
```

## 🛠️ Customization

You can adjust these in the script:
- `INTERVALL_BILD`: How often to update the screenshot (seconds)
- `INTERVALL_SCPI`: How often to fetch SCPI data (seconds)
- `WAV_POINTS`: Number of waveform points to request per channel

## 🧾 License

This project is for **personal use only**. Use at your own risk. Not affiliated with Rigol Technologies.
