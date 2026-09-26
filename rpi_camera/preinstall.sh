#!/bin/bash
# Pre-install script for Raspberry Pi Zero W camera streamer
# Requires: Raspberry Pi OS Bookworm (or later) with python3-picamera2

set -e

echo "Updating package list..."
sudo apt-get update -y

# Only the essentials — no OpenCV, no numpy, no ffmpeg needed
echo "Installing python3-flask and python3-picamera2..."
sudo apt-get install -y --no-install-recommends python3-flask python3-picamera2

# Verify installation
echo "Verifying installation..."
python3 -c "import flask; print('Flask', flask.__version__, 'OK')"
python3 -c "from picamera2 import Picamera2; print('Picamera2 OK')"
python3 -c "from picamera2.encoders import MJPEGEncoder; print('MJPEGEncoder OK')"

# Ensure the user can access the camera
sudo usermod -aG video dante

echo "Setup completed successfully."