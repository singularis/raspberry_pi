from flask import Flask, Response, jsonify, render_template, send_from_directory
import os
import datetime
import time
import threading
from picamera2 import Picamera2
import cv2
import random

app = Flask(__name__)

# Constants
SAVE_DIRECTORY = "/home/dante/recordings"
DAYS_OLD = 30
FRAME_RATE = 2  # Frames per second
RESOLUTION = (640, 480)  # Set resolution to 640x480
ROTATION = 270  # Rotation in degrees (0, 90, 180, 270)

# Paths for recordings and screenshots
RECORDINGS_PATH = os.path.join(SAVE_DIRECTORY, "videos")
SCREENSHOTS_PATH = os.path.join(SAVE_DIRECTORY, "screenshots")

# Ensure the directories exist
os.makedirs(RECORDINGS_PATH, exist_ok=True)
os.makedirs(SCREENSHOTS_PATH, exist_ok=True)

# Initialize Picamera2
camera = Picamera2()
camera_config = camera.create_video_configuration(main={"size": RESOLUTION})
camera.configure(camera_config)
camera.start()

# Global variable to manage recording state
recording = False

def rotate_image(image, angle):
    """Rotate an image by the given angle."""
    rotation_map = {
        90: cv2.ROTATE_90_CLOCKWISE,
        180: cv2.ROTATE_180,
        270: cv2.ROTATE_90_COUNTERCLOCKWISE
    }
    return cv2.rotate(image, rotation_map[angle]) if angle in rotation_map else image

def cleanup_old_files(directory, days_old=DAYS_OLD):
    """Remove files older than `days_old` days from `directory`."""
    current_time = time.time()
    cutoff_time = current_time - days_old * 86400  # 86400 seconds in a day

    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        if os.path.isfile(file_path) and os.path.getmtime(file_path) < cutoff_time:
            os.remove(file_path)

def take_scheduled_screenshots():
    """Schedule screenshots at random intervals 5 times per day."""
    while True:
        time_to_wait = random.randint(0, 5 * 3600)  # Random wait up to 5 hours
        time.sleep(time_to_wait)
        save_screenshot()
        time.sleep(86400 / 5 - time_to_wait)  # Ensure 5 times per day

def save_screenshot():
    """Capture and save a screenshot."""
    frame = camera.capture_array()
    rotated_frame = rotate_image(frame, ROTATION)
    filename = os.path.join(SCREENSHOTS_PATH, f"screenshot_{datetime.datetime.now():%Y%m%d_%H%M%S}.jpg")
    cv2.imwrite(filename, rotated_frame)

@app.route('/')
def video_feed():
    def generate_frames():
        while True:
            frame = camera.capture_array()
            rotated_frame = rotate_image(frame, ROTATION)
            _, buffer = cv2.imencode('.jpg', rotated_frame)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(1 / FRAME_RATE)  # Control the frame rate

    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/screenshot', methods=['POST'])
def screenshot():
    cleanup_old_files(SCREENSHOTS_PATH)  # Clean up old files before saving a new one
    save_screenshot()
    return jsonify({"status": "success"})

@app.route('/record', methods=['POST'])
def record():
    global recording

    cleanup_old_files(RECORDINGS_PATH)  # Clean up old files before starting a new recording

    if not recording:
        filename = os.path.join(RECORDINGS_PATH, f"recording_{datetime.datetime.now():%Y%m%d_%H%M%S}.h264")
        camera.start_recording(filename)
        recording = True
        status = "recording"
    else:
        camera.stop_recording()
        recording = False
        status = "stopped"

    return jsonify({"status": status})

@app.route('/recordings')
def list_recordings():
    """Render a webpage showing all available recordings and screenshots."""
    recordings = sorted(os.listdir(RECORDINGS_PATH))
    screenshots = sorted(os.listdir(SCREENSHOTS_PATH))
    return render_template('recordings.html', recordings=recordings, screenshots=screenshots)

@app.route('/view/<filename>')
def view_file(filename):
    """View a specific recording or screenshot."""
    if filename.startswith("recording_"):
        directory = RECORDINGS_PATH
    elif filename.startswith("screenshot_"):
        directory = SCREENSHOTS_PATH
    else:
        return "File not found", 404

    return send_from_directory(directory, filename)

if __name__ == "__main__":
    # Start a background thread for taking scheduled screenshots
    threading.Thread(target=take_scheduled_screenshots, daemon=True).start()

    app.run(host='0.0.0.0', port=5000)
