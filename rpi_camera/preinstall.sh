#!/bin/bash
# Pre-install script for Raspberry Pi Zero W camera streamer
# Requires: Raspberry Pi OS Bookworm (or later). libcamera 0.3 Python binding.
# Do not install python3-picamera2: it pulls NumPy, Pillow and FFmpeg.

set -e

echo "Updating package list..."
sudo apt-get update -y

echo "Installing python3-libcamera and python3-v4l2..."
sudo apt-get install -y --no-install-recommends python3-libcamera python3-v4l2

echo "Verifying installation..."
python3 -c "from libcamera import CameraManager; print('libcamera OK')"
python3 -c "import v4l2; print('v4l2 OK')"

# Ensure the user can access the camera
sudo usermod -aG video dante

echo "Setup completed successfully."