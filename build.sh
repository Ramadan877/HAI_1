#!/usr/bin/env bash
# exit on error
set -o errexit

# Install Python 3.11
python3.11 -m pip install --upgrade pip

# Install system dependencies
apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    libsndfile1 \
    portaudio19-dev \
    python3-pyaudio

# Install dependencies
python3.11 -m pip install -r requirements.txt