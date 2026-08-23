#!/usr/bin/env python3
"""Pi Zero W + Arducam IMX519: live MJPEG, record, clip playback."""

import gc
import io
import os
import struct
import threading
import time
from datetime import datetime

from flask import Flask, Response, jsonify, request, send_from_directory
from libcamera import Transform
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder, Quality
from picamera2.outputs import FileOutput

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
CLIPS = os.path.join(HERE, "recordings")
RAW = (2328, 1748)          # IMX519 2×2 bin, full FOV
LIVE = (1280, 960)
FLIP = Transform(hflip=True, vflip=True)
HDR = {"Cache-Control": "no-cache, no-store"}
BOUND = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"

app = Flask(__name__, static_folder=WEB, static_url_path="/web")

_lock = threading.Lock()
_cam = None
_on = False
_mode = None
_nview = 0
_idle = None
_rec_f = None
_rec_path = None
_rec_t0 = None
_rec_timer = None
_rec_size = None
_buf = None


class JpegBuf(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.ready = threading.Condition()

    def write(self, data):
        with self.ready:
            self.frame = data
            self.ready.notify_all()
        return len(data)

    def writable(self):
        return True


class RecFile(io.BufferedIOBase):
    def __init__(self, path):
        self.j = open(path, "wb", buffering=64 * 1024)
        self.t = open(path[:-5] + ".ts", "wb", buffering=16 * 1024)
        self.t0 = time.monotonic()
        self.n = 0

    def write(self, data):
        self.j.write(data)
        self.t.write(struct.pack("<I", max(0, int((time.monotonic() - self.t0) * 1000))))
        self.n += 1
        if self.n >= 8:
            self.flush()
            self.n = 0
        return len(data)

    def writable(self):
        return True

    def flush(self):
        self.j.flush()
        self.t.flush()

    def close(self):
        if self.j.closed:
            return
        self.flush()
        self.j.close()
        self.t.close()


_buf = JpegBuf()


def _close(cam):
    if cam is None:
        return
    cam.close()
    time.sleep(0.25)


def _idle_off():
    global _idle
    if _idle:
        _idle.cancel()
        _idle = None


def _rec():
    return _rec_f is not None


def _setup(cam, main, raw, record):
    cam.configure(cam.create_video_configuration(
        main={"size": main, "format": "YUV420"},
        raw={"size": raw},
        transform=FLIP,
        buffer_count=2,
        queue=False,
    ))
    lo, hi = (150000, 250000) if record else (55000, 125000)
    cam.set_controls({
        "FrameDurationLimits": (lo, hi),
        "AeEnable": True,
        "AwbEnable": True,
        "Sharpness": 1.0,
        "NoiseReductionMode": 0,
    })
    return Quality.HIGH


def _status():
    return {
        "recording": _rec(),
        "elapsed_s": int(time.time() - _rec_t0) if _rec_t0 else 0,
        "max_s": 1800,
        "size": f"{_rec_size[0]}x{_rec_size[1]}" if _rec_size else None,
        "file": os.path.basename(_rec_path) if _rec_path else None,
    }


def _end_file():
    global _rec_f, _rec_path, _rec_t0, _rec_timer
    if _rec_timer:
        _rec_timer.cancel()
        _rec_timer = None
    path = _rec_path
    if _rec_f:
        _rec_f.close()
    _rec_f = _rec_path = _rec_t0 = None
    if not path:
        return
    try:
        if os.path.getsize(path) == 0:
            os.unlink(path)
            ts = path[:-5] + ".ts"
            if os.path.isfile(ts):
                os.unlink(ts)
            print("[rec] removed empty", path)
            return
    except OSError:
        pass
    print("[rec] stopped", path)


def cam_start(mode):
    global _cam, _on, _mode, _rec_size
    with _lock:
        if mode == "live" and _rec():
            return
        if _on and _mode == mode:
            return
        _idle_off()
        _mode = mode
        cam = _cam
        if cam is None:
            cam = Picamera2()
            try:
                q = _setup(cam, LIVE, RAW, mode == "record")
                cam.start()
            except Exception:
                _close(cam)
                _mode = None
                raise
            _cam, _on = cam, True
        else:
            lo, hi = (150000, 250000) if mode == "record" else (55000, 125000)
            cam.set_controls({"FrameDurationLimits": (lo, hi)})
            q = Quality.HIGH
        cam.stop_encoder()
        dest = _rec_f if mode == "record" else _buf
        cam.start_encoder(MJPEGEncoder(), FileOutput(dest), quality=q)
        _rec_size = LIVE if mode == "record" else None
        print("[cam]", mode, LIVE[0], "x", LIVE[1])


def rec_begin():
    global _rec_f, _rec_path, _rec_t0, _rec_timer
    os.makedirs(CLIPS, exist_ok=True)
    path = os.path.join(CLIPS, datetime.now().strftime("clip_%Y%m%d_%H%M%S.mjpg"))
    _rec_f, _rec_path, _rec_t0 = RecFile(path), path, time.time()

    def cap():
        rec_off()
        print("[rec] 30 min")

    _idle_off()
    _rec_timer = threading.Timer(1800, cap)
    _rec_timer.daemon = True
    _rec_timer.start()
    print("[rec]", path)


def cam_stop(force=False):
    global _cam, _on, _mode
    with _lock:
        if not force and _rec():
            return
        cam, _cam, _on, _mode = _cam, None, False, None
    _close(cam)
    with _lock:
        if force:
            _end_file()
        _idle_off()
    _buf.frame = None
    gc.collect()
    print("[cam] stop")


def rec_off():
    with _lock:
        if _cam:
            _cam.stop_encoder()
        _end_file()
    cam_start("live")


def _later_stop():
    global _idle
    if _rec() or _mode == "record":
        return
    _idle_off()

    def go():
        with _lock:
            if _nview or _rec() or _mode == "record":
                return
        cam_stop()

    _idle = threading.Timer(5, go)
    _idle.daemon = True
    _idle.start()


def _clip(name):
    if not name or "/" in name or "\\" in name or not name.endswith(".mjpg"):
        return None
    p = os.path.realpath(os.path.join(CLIPS, name))
    return p if p.startswith(os.path.realpath(CLIPS) + os.sep) and os.path.isfile(p) else None


def _jpegs(path):
    buf = b""
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                return
            buf += chunk
            while True:
                a = buf.find(b"\xff\xd8")
                if a < 0:
                    buf = buf[-1:] if buf else b""
                    break
                b = buf.find(b"\xff\xd9", a + 2)
                if b < 0:
                    buf = buf[a:]
                    break
                yield buf[a:b + 2]
                buf = buf[b + 2:]


def _play(path):
    ts = path[:-5] + ".ts"
    times = None
    if os.path.isfile(ts):
        data = open(ts, "rb").read()
        times = [struct.unpack_from("<I", data, i * 4)[0] / 1000.0 for i in range(len(data) // 4)]
    t0 = time.monotonic()
    for i, fr in enumerate(_jpegs(path)):
        if times and i < len(times):
            w = times[i] - (time.monotonic() - t0)
            if w > 0:
                time.sleep(min(w, 2))
        else:
            time.sleep(0.15)
        yield BOUND + fr + b"\r\n"


def _live():
    global _nview
    try:
        while True:
            if _mode == "record":
                return
            with _buf.ready:
                if not _on:
                    return
                if not _buf.ready.wait(timeout=1):
                    continue
                fr = _buf.frame
            if fr:
                yield BOUND + fr + b"\r\n"
    finally:
        with _lock:
            _nview = max(0, _nview - 1)
            if _nview == 0 and not _rec():
                _later_stop()


@app.route("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.route("/clips")
def clips():
    cam_stop(True)
    rows = []
    if os.path.isdir(CLIPS):
        for name in sorted(os.listdir(CLIPS), reverse=True):
            if name.endswith(".mjpg"):
                st = os.stat(os.path.join(CLIPS, name))
                rows.append(
                    f'<button type="button" data-f="{name}">{name}'
                    f'<span>{datetime.fromtimestamp(st.st_mtime).strftime("%d %b %H:%M")} · {st.st_size/1048576:.1f} MB</span></button>'
                )
    html = open(os.path.join(WEB, "clips.html"), encoding="utf-8").read()
    html = html.replace("__LIST__", "".join(rows) or '<p class="empty">No clips yet</p>')
    return Response(html, mimetype="text/html", headers=HDR)


@app.route("/clip/<name>")
def clip(name):
    path = _clip(name)
    if not path:
        return "not found", 404
    return Response(_play(path), mimetype="multipart/x-mixed-replace; boundary=frame", headers=HDR)


@app.route("/record")
def record():
    on = request.args.get("on")
    if on in ("1", "true", "on"):
        if not _rec():
            rec_begin()
            try:
                cam_start("record")
            except Exception as exc:
                print("[rec] start failed", exc)
                cam_stop(True)
    elif on in ("0", "false", "off"):
        rec_off()
    return jsonify(_status())


@app.route("/video_feed")
def video_feed():
    global _nview
    if _rec() or _mode == "record":
        return Response("recording", status=204)
    if not _on:
        try:
            cam_start("live")
        except Exception as exc:
            print("[cam] live failed", exc)
            return Response("camera off", status=503)
    if not _on:
        return Response("camera off", status=503)
    with _lock:
        _nview += 1
    return Response(_live(), mimetype="multipart/x-mixed-replace; boundary=frame", headers=HDR)


if __name__ == "__main__":
    app.run("0.0.0.0", 8080, threaded=True)
