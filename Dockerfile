# Dockerfile
FROM python:3.12-slim

# System packages for Tkinter + VNC support
RUN apt update && apt install -y \
    python3-tk \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxtst6 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libasound2 \
    libpulse0 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy your app into the container
WORKDIR /app
COPY . .

# Set up virtual environment inside Docker (optional)
RUN pip install --no-cache-dir -r requirements.txt

# For X11 GUI to work from host
ENV DISPLAY=:0

CMD ["python3", "main.py"]
