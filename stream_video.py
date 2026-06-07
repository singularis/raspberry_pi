#!/usr/bin/env python3
"""
Ultra-lean MJPEG streamer for Raspberry Pi Zero W + Arducam IMX519.
───────────────────────────────────────────────────────────────────
Hardware: single-core ARMv6 @ 1 GHz, 427 MB RAM, 64-128 MB GPU.

Key design decisions (every byte and cycle matters):
  ▸ NO OpenCV, NO numpy at runtime — saves ~80 MB RSS.
  ▸ JPEG encoding via Picamera2's MJPEGEncoder which delegates to
    the hardware-accelerated ISP / libjpeg-turbo internally, instead
    of doing capture_array() → cvtColor() → imencode() on the CPU.
  ▸ Rotation done by the ISP via libcamera Transform (zero CPU cost).
  ▸ YUV420 main stream — 1.5 bytes/pixel vs 3 bytes/pixel (BGR888),
    halving frame-buffer memory. The MJPEG encoder accepts YUV natively.
  ▸ 2 buffers only (minimum for smooth pipeline, saves ~2 MB).
  ▸ All ISP post-processing disabled (noise reduction, sharpening).
  ▸ Single shared frame broadcast — encode once, fan out to N viewers.
  ▸ Camera starts on first viewer, stops after last viewer leaves.
  ▸ Flask with minimal middleware — no static files, no sessions.

Endpoints:
  GET /           → simple HTML page with embedded <img>
  GET /video_feed → raw MJPEG stream
"""

import io
import time
import threading

from flask import Flask, Response
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder, Quality
from picamera2.outputs import FileOutput
from libcamera import Transform

# ──── Tunables ──────────────────────────────────────────────────────────
RESOLUTION      = (640, 480)    # Sweet-spot for Pi Zero
TARGET_FPS      = 15            # Achievable at 640×480 on Pi Zero
JPEG_QUALITY    = Quality.MEDIUM  # LOW/MEDIUM/HIGH/VERY_HIGH
BUFFER_COUNT    = 2             # Minimum for smooth capture
IDLE_TIMEOUT_S  = 5.0           # Seconds after last viewer → stop camera
# ────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = None  # No request size limit needed


# ── Shared circular JPEG buffer ────────────────────────────────────────

class FrameBuffer(io.BufferedIOBase):
    """Thread-safe single-frame buffer that the MJPEGEncoder writes into.

    MJPEGEncoder calls write() with complete JPEG frames.  We store the
    latest frame and wake up any waiting client generators.
    """

    def __init__(self):
        self.frame = None
        self.condition = threading.Condition()

    def write(self, data):
        with self.condition:
            self.frame = data
            self.condition.notify_all()
        return len(data)

    def writable(self):
        return True


# ── Global state ────────────────────────────────────────────────────────

_camera       = None
_encoder      = None
_output       = None
_frame_buf    = FrameBuffer()
_running      = False
_viewer_count = 0
_idle_timer   = None
_lock         = threading.Lock()


# ── Camera lifecycle ────────────────────────────────────────────────────

def _start_camera():
    """Bring up camera + encoder pipeline."""
    global _camera, _encoder, _output, _running, _idle_timer

    with _lock:
        if _running:
            return

        if _idle_timer is not None:
            _idle_timer.cancel()
            _idle_timer = None

        _camera = Picamera2()

        video_cfg = _camera.create_video_configuration(
            main={
                "size": RESOLUTION,
                "format": "YUV420",       # 1.5 B/px — half of BGR888
            },
            transform=Transform(rotation=270),  # ISP rotation (free)
            buffer_count=BUFFER_COUNT,
        )
        _camera.configure(video_cfg)

        # Lock frame rate and disable expensive ISP post-processing
        frame_us = int(1_000_000 / TARGET_FPS)
        _camera.set_controls({
            "FrameDurationLimits": (frame_us, frame_us),
            "NoiseReductionMode":  0,     # Off
            "Sharpness":          0.0,    # Off
            "Saturation":         1.0,    # Neutral
            "AeEnable":           True,
            "AwbEnable":          True,
        })

        # Attempt continuous AF (non-fatal if unsupported)
        try:
            _camera.set_controls({"AfMode": 2, "AfSpeed": 1})
        except Exception:
            pass

        # Set up the MJPEG encoder → our in-memory FrameBuffer
        _encoder = MJPEGEncoder()
        _output = FileOutput(_frame_buf)
        _camera.start_encoder(_encoder, _output, quality=JPEG_QUALITY)

        _camera.start()
        _running = True
        print("[cam] started")


def _stop_camera():
    """Tear down encoder and camera."""
    global _camera, _encoder, _output, _running, _idle_timer

    with _lock:
        if not _running:
            return
        _running = False

    try:
        _camera.stop_encoder()
    except Exception:
        pass
    try:
        _camera.stop()
    except Exception:
        pass
    try:
        _camera.close()
    except Exception:
        pass

    _camera = None
    _encoder = None
    _output = None
    _idle_timer = None
    print("[cam] stopped")


def _schedule_idle_stop():
    """Deferred camera shutdown after last viewer disconnects."""
    global _idle_timer
    if _idle_timer is not None:
        _idle_timer.cancel()

    def _maybe_stop():
        with _lock:
            if _viewer_count != 0:
                return
        _stop_camera()

    _idle_timer = threading.Timer(IDLE_TIMEOUT_S, _maybe_stop)
    _idle_timer.daemon = True
    _idle_timer.start()


# ── Per-client MJPEG generator ──────────────────────────────────────────

_BOUNDARY = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
_CRLF = b"\r\n"

def _stream_generator():
    """Yield MJPEG multipart chunks for one connected viewer."""
    global _viewer_count

    try:
        while True:
            with _frame_buf.condition:
                if not _running:
                    return
                if not _frame_buf.condition.wait(timeout=1.0):
                    # Timeout — keep connection alive, retry
                    if not _running:
                        return
                    continue
                frame = _frame_buf.frame

            if frame is None:
                continue

            yield _BOUNDARY + frame + _CRLF
    finally:
        with _lock:
            _viewer_count = max(0, _viewer_count - 1)
            if _viewer_count == 0:
                _schedule_idle_stop()


# ── Flask routes ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return (
        "<h1>Raspberry Pi Camera (Picamera2 + IMX519)</h1>"
        "<img src='/video_feed' style='width:50%; max-width:640px;'/>"
        "<p>Stream starts on first viewer and stops shortly after "
        "the last one leaves.</p>"
    )


@app.route("/video_feed")
def video_feed():
    global _viewer_count
    with _lock:
        _viewer_count += 1
        if not _running:
            pass  # release lock before heavy camera init
    if not _running:
        _start_camera()
        # Give encoder a moment to produce the first frame
        time.sleep(0.25)

    return Response(
        _stream_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "keep-alive",
        },
    )


# ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
