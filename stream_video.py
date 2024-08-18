from flask import Flask, Response, jsonify, render_template, send_from_directory
import os
import datetime
import time
import threading
import logging
import random
from picamera2 import Picamera2
import cv2

app = Flask(__name__)

# Constants
SAVE_DIRECTORY = "/home/dante/recordings"
DAYS_OLD = 30
FRAME_RATE = 2  # Limit frame rate to 2 FPS
RESOLUTION = (320, 240)  # Set low resolution for better performance
ROTATION = 270  # Set rotation to 0, 90, 180, or 270 degrees
SCALE_FACTOR = 3  # Scale the image by this factor

# Paths for recordings and screenshots
RECORDINGS_PATH = os.path.join(SAVE_DIRECTORY, "videos")
SCREENSHOTS_PATH = os.path.join(SAVE_DIRECTORY, "screenshots")

# Ensure the directories exist
os.makedirs(RECORDINGS_PATH, exist_ok=True)
os.makedirs(SCREENSHOTS_PATH, exist_ok=True)

# Initialize logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Initialize Picamera2
camera = Picamera2()
video_config = camera.create_video_configuration(main={"size": RESOLUTION})
camera.configure(video_config)
camera.start()

# Global variables
recording = False


def rotate_and_scale_image(image, angle, scale_factor):
    """Rotate an image by the given angle and scale it."""
    if angle == 90:
        rotated_image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif angle == 180:
        rotated_image = cv2.rotate(image, cv2.ROTATE_180)
    elif angle == 270:
        rotated_image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    else:
        rotated_image = image

    # Scaling the image
    scaled_image = cv2.resize(
        rotated_image,
        None,
        fx=scale_factor,
        fy=scale_factor,
        interpolation=cv2.INTER_LINEAR,
    )
    return scaled_image


def cleanup_old_files(directory, days_old=DAYS_OLD):
    """Remove files older than `days_old` days from `directory`."""
    current_time = time.time()
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        if os.path.isfile(file_path):
            file_age = current_time - os.path.getmtime(file_path)
            if file_age > days_old * 86400:  # 86400 seconds in a day
                os.remove(file_path)
                logging.info(f"Removed old file: {file_path}")


def take_scheduled_screenshots():
    """Continuously schedule screenshots at random intervals 5 times per day."""
    while True:
        time_to_wait = random.randint(0, 5 * 3600)  # Random wait up to ~5 hours
        threading.Timer(time_to_wait, save_screenshot).start()
        time.sleep(86400 / 5)  # Schedule 5 times per day


def save_screenshot():
    """Capture and save a screenshot."""
    frame = camera.capture_array()
    rotated_scaled_frame = rotate_and_scale_image(frame, ROTATION, SCALE_FACTOR)
    filename = os.path.join(
        SCREENSHOTS_PATH,
        f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg",
    )
    cv2.imwrite(filename, rotated_scaled_frame)
    logging.info(f"Screenshot saved: {filename}")


@app.route("/")
def video_feed():
    def generate_frames():
        while True:
            frame = camera.capture_array()
            rotated_scaled_frame = rotate_and_scale_image(frame, ROTATION, SCALE_FACTOR)
            ret, buffer = cv2.imencode(".jpg", rotated_scaled_frame)
            frame = buffer.tobytes()
            yield (b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            time.sleep(1 / FRAME_RATE)  # Control the frame rate

    return Response(
        generate_frames(), mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/screenshot", methods=["POST"])
def screenshot():
    cleanup_old_files(SCREENSHOTS_PATH)  # Clean up old files before saving new one
    save_screenshot()
    return jsonify({"status": "success"})


@app.route("/record", methods=["POST"])
def record():
    global recording

    cleanup_old_files(
        RECORDINGS_PATH
    )  # Clean up old files before starting new recording

    if not recording:
        filename = os.path.join(
            RECORDINGS_PATH,
            f"recording_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.h264",
        )
        camera.start_recording(filename)
        recording = True
        logging.info(f"Started recording: {filename}")
        return jsonify({"status": "recording", "filename": filename})
    else:
        camera.stop_recording()
        recording = False
        logging.info("Stopped recording")
        return jsonify({"status": "stopped"})


@app.route("/recordings")
def list_recordings():
    """Render a webpage showing all available recordings and screenshots."""
    recordings = sorted(os.listdir(RECORDINGS_PATH))
    screenshots = sorted(os.listdir(SCREENSHOTS_PATH))
    return render_template(
        "recordings.html", recordings=recordings, screenshots=screenshots
    )


@app.route("/view/<filename>")
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

    app.run(host="0.0.0.0", port=5000)
