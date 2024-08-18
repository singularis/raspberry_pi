# Update package list and upgrade all packages
echo "Updating package list and upgrading installed packages..."
sudo apt-get update -y
sudo apt-get upgrade -y

# Install Python3, OpenCV, and Flask
echo "Installing python3-opencv and python3-flask..."
sudo apt-get install -y python3-opencv python3-flask ffmpeg python3-picamera2

# Verify installation
echo "Verifying installation..."
if python3 -c "import cv2" &> /dev/null; then
    echo "OpenCV successfully installed."
else
    echo "Failed to install OpenCV."
fi

if python3 -c "import flask" &> /dev/null; then
    echo "Flask successfully installed."
else
    echo "Failed to install Flask."
fi

sudo usermod -aG video dante

echo "Setup completed successfully."