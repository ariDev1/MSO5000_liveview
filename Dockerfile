# Dockerfile
FROM python:3.12-slim

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# System packages for Tkinter + GUI support
RUN apt update && apt install -y \
    python3-tk \
    fonts-dejavu \
    fonts-noto-color-emoji \
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 \
    libxcursor1 libxdamage1 libxext6 libxfixes3 \
    libxrandr2 libxtst6 libnss3 libatk1.0-0 \
    libatk-bridge2.0-0 libgtk-3-0 libasound2 \
    libpulse0 curl git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory and copy files
WORKDIR /app
COPY . .

ARG MSO5000_VERSION
ARG MSO5000_COMMIT
ARG MSO5000_BUILD_DATE

RUN MSO5000_BUILD_VERSION="$MSO5000_VERSION" \
    MSO5000_BUILD_COMMIT="$MSO5000_COMMIT" \
    MSO5000_BUILD_DATE="$MSO5000_BUILD_DATE" \
    python3 build_version.py \
    && chmod +x /app/entrypoint.sh

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Use custom entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
