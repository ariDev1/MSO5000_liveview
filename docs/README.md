# MSO5000 Liveview — Open Source Oscilloscope Monitoring

**MSO5000 Liveview** is a 100% free and open-source GUI application to monitor and log data from RIGOL MSO5000-series oscilloscopes — especially optimized for modified (hacked) firmware devices.

It provides real-time waveform capture, long-term signal logging, and remote access to your oscilloscope — all from a fast desktop GUI or Docker container.

---

![Screenshot](https://raw.githubusercontent.com/ariDev1/MSO5000_liveview/master/docs/screenshot.png)

---

## Why We Built This

Many MSO5000 owners (especially those using custom firmware) find the official tools limited, bloated, or unreliable.

We wanted:
- A fast, lightweight, and reliable viewer
- Multiple measurements per second
- Intuitive GUI with real-time screenshots
- Long-time CSV logging
- No vendor lock-in, no costs

So we built **MSO5000 Liveview** — and made it free for everyone.

---

## Key Features

- SCPI communication over TCP/IP (optimized for hacked firmware)
- Live screenshot viewer from the oscilloscope screen
- Real-time waveform readout with Vpp, Vavg, and Vrms
- Power Analysis with PQ heatmap
- Logging to CSV with timestamps
- Pause / resume / manual stop of measurement
- Docker image with native GUI (X11 support)
- Debug console for SCPI feedback
- Modular and clean Python architecture

---

## Supported Platforms

- **Linux** (fully supported, tested on Ubuntu 24.04)
- Works with **Python 3.12+**
- Docker version supports **GUI over X11**

---

## Technologies Used

- Python 3.12
- Tkinter GUI
- PyVISA for SCPI communication
- PIL (Pillow) for image decoding
- Docker (with GUI support)

---

## System Requirements

- RIGOL MSO5000 Oscilloscope with LAN access  
  (Custom firmware recommended for full functionality)
- Python 3.12+ or Docker
- Git, Linux terminal or Docker client

---

## Getting Started

### Run locally
```bash
git clone https://github.com/ariDev1/MSO5000_liveview.git
cd MSO5000_liveview
python3 main.py
```

### Run via Docker
```bash
docker pull aridev1/mso5000_live:latest
docker run --rm -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix aridev1/mso5000_live:latest
```

---

## License

This software is released under the **MIT License**.  
Use it freely in research, labs, private projects, or education.

---

## Project Links

- [GitHub](https://github.com/ariDev1/MSO5000_liveview)  
- [DockerHub](https://hub.docker.com/r/aridev1/mso5000_liveview)  
- [Latest Release](https://github.com/ariDev1/MSO5000_liveview/releases/latest)
- [MSO5000 Series Digital Oszilloscope Manual](https://aether-research.institute/MSO5000/MSO5000_Series_Digital_Oscilloscope.pdf)
- [MSO5000 Programming Guide](https://aether-research.institute/MSO5000/MSO5000_ProgrammingGuide_EN.pdf)
- [How to jailbreak your MSO5000](https://www.eevblog.com/forum/testgear/hacking-the-rigol-mso5000-dr-mefisto-licensing-method/)

---

## Contributions Welcome

This project is actively developed by EE enthusiasts.  
Bug reports, ideas, and pull requests are always appreciated!

---

## Installation Demo and first run

<div style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%;">
  <iframe
    src="https://www.youtube.com/embed/3BKAten_vXA?si=4xDkLxmeiJK__1J4"
    title="YouTube video"
    frameborder="0"
    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
    allowfullscreen
    style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;">
  </iframe>
</div>

