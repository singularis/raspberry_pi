#!/usr/bin/env python3
"""Pi Zero W + Arducam IMX519. libcamera plus the hardware JPEG encoder.

Picamera2 is not imported. It pulls NumPy, Pillow and FFmpeg into a process
that only needs to move frames. C++ would be smaller still, but the Pi's
libcamera-dev packages do not match the installed libcamera 0.3, so this
stays on the Python binding that is already there.
"""

import gc
import json
import os
import selectors
import struct
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ENC_DEV = "/dev/video11"
ENC_RATE = 25_000_000  # hardware maximum, variable bitrate
HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
CLIPS = os.path.join(HERE, "recordings")
LIVE = (1280, 960)
RAW = (2328, 1748)
BOUND = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
HDR = ("Cache-Control", "no-cache, no-store")

_lock = threading.Lock()
_on = False
_mode = None
_nview = 0
_idle = None
_rec_f = None
_rec_path = None
_rec_t0 = None
_rec_timer = None
_cam = None


def _wait_encoder(timeout=120):
    t0 = time.monotonic()
    while True:
        try:
            os.close(os.open(ENC_DEV, os.O_RDONLY))
        except OSError:
            if time.monotonic() - t0 > timeout:
                return False
            time.sleep(1)
            continue
        waited = int(time.monotonic() - t0)
        if waited:
            print("[cam] waited", waited, "s for", ENC_DEV, flush=True)
        return True


class JpegBuf:
    def __init__(self):
        self.frame = None
        self.ready = threading.Condition()

    def write(self, data):
        with self.ready:
            self.frame = data
            self.ready.notify_all()


class RecFile:
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


class HwEnc:
    """Hardware MJPEG on /dev/video11. Frames stay in dma-buf; only the JPEG is copied."""

    def __init__(self, on_jpeg):
        self.on_jpeg = on_jpeg
        self._running = False
        self.vd = None

    def start(self, w, h, stride, frame_size):
        import ctypes
        import fcntl
        import mmap
        import queue
        import select
        from v4l2 import (
            VIDEO_MAX_PLANES, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
            V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE, V4L2_CID_MPEG_VIDEO_BITRATE,
            V4L2_CID_MPEG_VIDEO_BITRATE_MODE, V4L2_COLORSPACE_DEFAULT,
            V4L2_COLORSPACE_JPEG, V4L2_FIELD_ANY, V4L2_FIELD_NONE,
            V4L2_MEMORY_DMABUF, V4L2_MEMORY_MMAP, V4L2_PIX_FMT_MJPEG,
            V4L2_PIX_FMT_YUV420, VIDIOC_DQBUF, VIDIOC_G_CTRL, VIDIOC_QBUF,
            VIDIOC_QUERYBUF, VIDIOC_REQBUFS, VIDIOC_S_CTRL, VIDIOC_S_FMT,
            VIDIOC_STREAMON, v4l2_buffer, v4l2_buf_type, v4l2_control,
            v4l2_format, v4l2_plane, v4l2_requestbuffers,
        )
        self._c, self._f, self._mm = ctypes, fcntl, mmap
        self._v = sys.modules["v4l2"]
        self.frame_size = frame_size
        self.vd = open(ENC_DEV, "rb+", buffering=0)
        self.buf_available = queue.Queue()
        self.buf_done = queue.Queue()
        self.bufs = {}
        fmt = v4l2_format()
        fmt.type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE
        fmt.fmt.pix_mp.width = w
        fmt.fmt.pix_mp.height = h
        fmt.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_YUV420
        fmt.fmt.pix_mp.plane_fmt[0].bytesperline = stride
        fmt.fmt.pix_mp.field = V4L2_FIELD_ANY
        fmt.fmt.pix_mp.colorspace = V4L2_COLORSPACE_JPEG
        fmt.fmt.pix_mp.num_planes = 1
        fcntl.ioctl(self.vd, VIDIOC_S_FMT, fmt)
        fmt = v4l2_format()
        fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        fmt.fmt.pix_mp.width = w
        fmt.fmt.pix_mp.height = h
        fmt.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_MJPEG
        fmt.fmt.pix_mp.field = V4L2_FIELD_ANY
        fmt.fmt.pix_mp.colorspace = V4L2_COLORSPACE_DEFAULT
        fmt.fmt.pix_mp.num_planes = 1
        fmt.fmt.pix_mp.plane_fmt[0].sizeimage = 1024 * 1024
        fcntl.ioctl(self.vd, VIDIOC_S_FMT, fmt)
        # Variable bitrate. Constant bitrate on this chip did not spend the budget.
        mode = self._ctrl(V4L2_CID_MPEG_VIDEO_BITRATE_MODE, 0)
        rate = self._ctrl(V4L2_CID_MPEG_VIDEO_BITRATE, ENC_RATE)
        print("[cam] encoder mode", mode, "bitrate", rate, flush=True)
        self._reqbufs(6, V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE, V4L2_MEMORY_DMABUF, map_it=False)
        self._reqbufs(4, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, V4L2_MEMORY_MMAP, map_it=True)
        for kind in (V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE):
            fcntl.ioctl(self.vd, VIDIOC_STREAMON, v4l2_buf_type(kind))
        self._running = True
        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()

    def _ctrl(self, cid, value):
        ctrl = self._v.v4l2_control()
        ctrl.id = cid
        ctrl.value = value
        self._f.ioctl(self.vd, self._v.VIDIOC_S_CTRL, ctrl)
        ctrl.value = 0
        self._f.ioctl(self.vd, self._v.VIDIOC_G_CTRL, ctrl)
        return ctrl.value

    def _reqbufs(self, count, kind, memory, map_it):
        v = self._v
        req = v.v4l2_requestbuffers()
        req.count = count
        req.type = kind
        req.memory = memory
        self._f.ioctl(self.vd, v.VIDIOC_REQBUFS, req)
        if not map_it:
            for i in range(req.count):
                self.buf_available.put(i)
            return
        for i in range(req.count):
            planes = (v.v4l2_plane * v.VIDEO_MAX_PLANES)()
            buf = v.v4l2_buffer()
            self._c.memset(self._c.byref(buf), 0, self._c.sizeof(buf))
            buf.type = kind
            buf.memory = memory
            buf.index = i
            buf.length = 1
            buf.m.planes = planes
            self._f.ioctl(self.vd, v.VIDIOC_QUERYBUF, buf)
            self.bufs[i] = (
                self._mm.mmap(
                    self.vd.fileno(), buf.m.planes[0].length,
                    self._mm.PROT_READ | self._mm.PROT_WRITE, self._mm.MAP_SHARED,
                    offset=buf.m.planes[0].m.mem_offset,
                ),
                buf.m.planes[0].length,
            )
            self._f.ioctl(self.vd, v.VIDIOC_QBUF, buf)

    def submit(self, fd, done):
        v = self._v
        planes = (v.v4l2_plane * v.VIDEO_MAX_PLANES)()
        buf = v.v4l2_buffer()
        buf.type = v.V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE
        buf.index = self.buf_available.get(timeout=2)
        buf.field = v.V4L2_FIELD_NONE
        buf.memory = v.V4L2_MEMORY_DMABUF
        buf.length = 1
        buf.m.planes = planes
        buf.m.planes[0].m.fd = fd
        buf.m.planes[0].bytesused = self.frame_size
        buf.m.planes[0].length = self.frame_size
        self._f.ioctl(self.vd, v.VIDIOC_QBUF, buf)
        self.buf_done.put(done)

    def _poll(self):
        import select
        v = self._v
        poll = select.poll()
        poll.register(self.vd, select.POLLIN)
        while self._running or not self.buf_done.empty():
            if not poll.poll(400):
                if not self._running:
                    break
                continue
            self._dq(v.V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE, v.V4L2_MEMORY_DMABUF, capture=False)
            self._dq(v.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, v.V4L2_MEMORY_MMAP, capture=True)

    def _dq(self, kind, memory, capture):
        v = self._v
        planes = (v.v4l2_plane * v.VIDEO_MAX_PLANES)()
        buf = v.v4l2_buffer()
        self._c.memset(self._c.byref(buf), 0, self._c.sizeof(buf))
        buf.type = kind
        buf.memory = memory
        buf.length = 1
        buf.m.planes = planes
        try:
            self._f.ioctl(self.vd, v.VIDIOC_DQBUF, buf)
        except OSError:
            return
        if not capture:
            self.buf_available.put(buf.index)
            return
        mm, length = self.bufs[buf.index]
        mm.seek(0)
        data = mm.read(buf.m.planes[0].bytesused)
        planes2 = (v.v4l2_plane * v.VIDEO_MAX_PLANES)()
        buf2 = v.v4l2_buffer()
        buf2.type = kind
        buf2.memory = memory
        buf2.index = buf.index
        buf2.length = 1
        buf2.m.planes = planes2
        buf2.m.planes[0].length = length
        self._f.ioctl(self.vd, v.VIDIOC_QBUF, buf2)
        try:
            self.on_jpeg(data)
        finally:
            done = self.buf_done.get()
            done()

    def stop(self):
        self._running = False
        if getattr(self, "thread", None):
            self.thread.join(timeout=2)
        while self.vd and not self.buf_done.empty():
            self.buf_done.get()()
        if not self.vd:
            return
        v = self._v
        for kind, memory in (
            (v.V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE, v.V4L2_MEMORY_DMABUF),
            (v.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, v.V4L2_MEMORY_MMAP),
        ):
            try:
                self._f.ioctl(self.vd, v.VIDIOC_STREAMOFF, v.v4l2_buf_type(kind))
                req = v.v4l2_requestbuffers()
                req.count = 0
                req.type = kind
                req.memory = memory
                self._f.ioctl(self.vd, v.VIDIOC_REQBUFS, req)
            except OSError as exc:
                print("[cam] encoder stop", exc)
        for mm, _ in self.bufs.values():
            mm.close()
        self.bufs = {}
        self.vd.close()
        self.vd = None


class Camera:
    def __init__(self):
        self.enc = None
        self._run = False
        self._qlock = threading.Lock()
        self.dur_id = None
        self.dur = (33333, 50000)

    def open(self):
        import libcamera
        from libcamera import CameraManager, Orientation, Request, Size, StreamRole
        self.lc = libcamera
        self.Request = Request
        self.cm = CameraManager.singleton()
        cam = self.cm.cameras[0]
        cam.acquire()
        self.cam = cam
        cfg = cam.generate_configuration([StreamRole.VideoRecording, StreamRole.Raw])
        main, raw = cfg.at(0), cfg.at(1)
        main.size = Size(*LIVE)
        raw.size = Size(*RAW)
        main.buffer_count = raw.buffer_count = 4
        cfg.orientation = Orientation.Rotate180
        cfg.validate()
        cam.configure(cfg)
        self.stream = main.stream
        self.raw = raw.stream
        self.size = (main.size.width, main.size.height)
        self.stride = main.stride
        self.frame_size = main.frame_size
        self.alloc = libcamera.FrameBufferAllocator(cam)
        for stream in (self.stream, self.raw):
            if self.alloc.allocate(stream) < 0:
                raise RuntimeError("buffer allocate failed")
        self.nbuf = len(self.alloc.buffers(self.stream))
        ctrl = {}
        for cid, _info in cam.controls.items():
            if cid.name == "FrameDurationLimits":
                self.dur_id = cid
                ctrl[cid] = self.dur
            elif cid.name == "Sharpness":
                ctrl[cid] = 3.0
            elif cid.name in ("AeEnable", "AwbEnable"):
                ctrl[cid] = True
            elif cid.name == "NoiseReductionMode":
                ctrl[cid] = 2
        cam.start(ctrl)
        self._run = True
        self.loop = threading.Thread(target=self._listen, daemon=True)
        self.loop.start()
        for i in range(self.nbuf):
            req = cam.create_request()
            for stream in (self.stream, self.raw):
                req.add_buffer(stream, self.alloc.buffers(stream)[i])
            cam.queue_request(req)
        print("[cam] open", self.size[0], "x", self.size[1], "bufs", self.nbuf, flush=True)

    def _listen(self):
        sel = selectors.DefaultSelector()
        sel.register(self.cm.event_fd, selectors.EVENT_READ)
        while self._run:
            if not sel.select(0.2):
                continue
            try:
                ready = self.cm.get_ready_requests()
            except RuntimeError:
                break
            for req in ready:
                if req.status != self.Request.Status.Complete or self.enc is None:
                    self._requeue(req)
                    continue
                try:
                    fb = req.buffers[self.stream]
                    self.enc.submit(fb.planes[0].fd, lambda req=req: self._requeue(req))
                except Exception as exc:
                    print("[cam] submit", exc)
                    self._requeue(req)
        sel.unregister(self.cm.event_fd)
        sel.close()

    def _requeue(self, req):
        try:
            if self.dur_id is not None:
                req.set_control(self.dur_id, self.dur)
        except Exception:
            self.dur_id = None
        req.reuse()
        with self._qlock:
            if self._run and self.cam is not None:
                self.cam.queue_request(req)

    def start_enc(self, on_jpeg):
        if self.enc:
            self.enc.stop()
        self.enc = HwEnc(on_jpeg)
        self.enc.start(self.size[0], self.size[1], self.stride, self.frame_size)

    def close(self):
        self._run = False
        if getattr(self, "loop", None):
            self.loop.join(timeout=2)
        if self.enc:
            self.enc.stop()
            self.enc = None
        with self._qlock:
            if getattr(self, "cam", None):
                try:
                    self.cam.stop()
                except Exception as exc:
                    print("[cam] stop", exc)
                self.cam.release()
                self.cam = None
        self.alloc = None
        time.sleep(0.25)
        gc.collect()


def _rec():
    return _rec_f is not None


def _idle_off():
    global _idle
    if _idle:
        _idle.cancel()
        _idle = None


def _on_jpeg(data):
    if _mode == "record" and _rec_f is not None:
        _rec_f.write(data)
    else:
        _buf.write(data)


def cam_start(mode):
    global _cam, _on, _mode
    with _lock:
        if mode == "live" and _rec():
            return
        if _on and _mode == mode:
            return
        _idle_off()
        _mode = mode
        cam = _cam
        if cam is None:
            cam = Camera()
            try:
                cam.open()
            except Exception:
                cam.close()
                _mode = None
                raise
            _cam = cam
            _on = True
        lo, hi = (50000, 80000) if mode == "record" else (33333, 50000)
        cam.dur = (lo, hi)
        cam.start_enc(_on_jpeg)
        print("[cam]", mode, LIVE[0], "x", LIVE[1], flush=True)


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


def cam_stop(force=False):
    global _cam, _on, _mode
    with _lock:
        if not force and _rec():
            return
        cam, _cam, _on, _mode = _cam, None, False, None
    if cam:
        cam.close()
    with _lock:
        if force:
            _end_file()
        _idle_off()
    _buf.frame = None
    print("[cam] stop", flush=True)


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


def rec_off():
    if _cam and _cam.enc:
        _cam.enc.stop()
        _cam.enc = None
    with _lock:
        _end_file()
    cam_start("live")
    _later_stop()


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


def _status():
    return {
        "recording": _rec(),
        "elapsed_s": int(time.time() - _rec_t0) if _rec_t0 else 0,
        "max_s": 1800,
        "size": f"{LIVE[0]}x{LIVE[1]}" if _rec() else None,
        "file": os.path.basename(_rec_path) if _rec_path else None,
    }


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


def _play(path, wfile):
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
        wfile.write(BOUND + fr + b"\r\n")
        wfile.flush()


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _mem():
    total = free = None
    text = _read("/proc/meminfo") or ""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[0] == "MemTotal:":
            total = int(parts[1]) // 1024
        elif parts[0] == "MemAvailable:":
            free = int(parts[1]) // 1024
    return total, free


def _disk():
    try:
        st = os.statvfs("/")
    except OSError:
        return None, None
    return (
        st.f_blocks * st.f_frsize // (1024 * 1024),
        st.f_bavail * st.f_frsize // (1024 * 1024),
    )


def _cpu_jiff(which):
    text = _read("/proc/stat") or ""
    for line in text.splitlines():
        if not line.startswith("cpu "):
            continue
        nums = []
        for p in line.split()[1:]:
            try:
                nums.append(int(p))
            except ValueError:
                return None
        if len(nums) < 4:
            return None
        return nums[3] if which == "idle" else sum(nums)
    return None


_rssi_mono = 0.0
_rssi_val = None


def _rssi():
    global _rssi_mono, _rssi_val
    now = time.monotonic()
    if _rssi_mono and now - _rssi_mono < 600:
        return _rssi_val
    _rssi_mono = now
    text = _read("/proc/net/wireless") or ""
    val = None
    for line in text.splitlines():
        if "wlan" not in line:
            continue
        parts = line.replace(".", " ").split()
        if len(parts) >= 4:
            try:
                val = int(float(parts[3]))
            except ValueError:
                val = None
            break
    _rssi_val = val
    return val


def _units(names):
    lines = []
    try:
        import subprocess
        r = subprocess.run(
            ["systemctl", "is-active", *names],
            capture_output=True, text=True, timeout=2,
        )
        lines = (r.stdout or "").splitlines()
    except Exception:
        lines = []
    out = {}
    for i, name in enumerate(names):
        key = name.replace(".service", "").replace(".timer", "").replace("-", "_")
        state = lines[i].strip() if i < len(lines) else ""
        out[key] = state or "unknown"
    return out


def _clips_stat():
    n = size = 0
    if not os.path.isdir(CLIPS):
        return n, size
    for name in os.listdir(CLIPS):
        if not name.endswith(".mjpg"):
            continue
        n += 1
        try:
            size += os.path.getsize(os.path.join(CLIPS, name))
        except OSError:
            pass
    return n, size


def _health():
    temp_raw = _read("/sys/class/thermal/thermal_zone0/temp")
    temp = int(temp_raw) / 1000 if temp_raw and temp_raw.isdigit() else None
    total, free = _mem()
    disk_total, disk_free = _disk()
    clips_n, clips_b = _clips_stat()
    return {
        "temp_c": temp,
        "ram_mb": total,
        "ram_free_mb": free,
        "sd_mb": disk_total,
        "sd_free_mb": disk_free,
        "throttled": _read("/sys/devices/platform/soc/soc:firmware/get_throttled"),
        "wifi_rssi": _rssi(),
        "cpu_total": _cpu_jiff("total"),
        "cpu_idle": _cpu_jiff("idle"),
        "clips": clips_n,
        "clips_bytes": clips_b,
        "camera": _status(),
        "units": _units([
            "flask_camera.service",
            "wifi-watchdog.timer",
            "motor-hours.service",
            "lcd-monitor.service",
        ]),
    }


_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if self.path.startswith("/health"):
            return
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, body, content_type, extra=()):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header(*HDR)
        for item in extra:
            self.send_header(*item)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/delete":
            self._delete(parse_qs(u.query).get("f", [None])[0])
            return
        self._send(404, b"not found", "text/plain")

    def do_GET(self):
        u = urlparse(self.path)
        path = unquote(u.path)
        if path == "/health":
            self._json(_health())
            return
        if path == "/record":
            self._record(parse_qs(u.query).get("on", [None])[0])
            return
        if path == "/video_feed":
            self._feed()
            return
        if path == "/":
            self._file(os.path.join(WEB, "index.html"), "text/html; charset=utf-8")
            return
        if path == "/clips":
            self._clips()
            return
        if path.startswith("/clip/"):
            self._clip_play(path[6:])
            return
        if path.startswith("/web/"):
            name = path[5:]
            if name in ("style.css", "live.js"):
                self._file(os.path.join(WEB, name), _MIME.get(os.path.splitext(name)[1], "application/octet-stream"))
                return
        self._send(404, b"not found", "text/plain")

    def _file(self, path, content_type):
        try:
            data = open(path, "rb").read()
        except OSError:
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, data, content_type)

    def _record(self, on):
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
        self._json(_status())

    def _feed(self):
        global _nview
        if _rec() or _mode == "record":
            self._send(204, b"", "text/plain")
            return
        if not _on:
            try:
                cam_start("live")
            except Exception as exc:
                print("[cam] live failed", exc)
                self._send(503, b"camera off", "text/plain")
                return
        if not _on:
            self._send(503, b"camera off", "text/plain")
            return
        with _lock:
            _nview += 1
        try:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header(*HDR)
            self.send_header("Connection", "close")
            self.end_headers()
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
                    self.wfile.write(BOUND + fr + b"\r\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            with _lock:
                _nview = max(0, _nview - 1)
                if _nview == 0 and not _rec():
                    _later_stop()

    def _clips(self):
        cam_stop(True)
        rows = []
        if os.path.isdir(CLIPS):
            for name in sorted(os.listdir(CLIPS), reverse=True):
                if name.endswith(".mjpg"):
                    st = os.stat(os.path.join(CLIPS, name))
                    rows.append(
                        f'<div class="row"><button type="button" data-f="{name}">{name}'
                        f'<span>{datetime.fromtimestamp(st.st_mtime).strftime("%d %b %H:%M")} · {st.st_size/1048576:.1f} MB</span></button>'
                        f'<button type="button" class="del" data-f="{name}">Delete</button></div>'
                    )
        html = open(os.path.join(WEB, "clips.html"), encoding="utf-8").read()
        html = html.replace("__LIST__", "".join(rows) or '<p class="empty">No clips yet</p>')
        self._send(200, html, "text/html; charset=utf-8")

    def _delete(self, name):
        path = _clip(name)
        if not path:
            self._send(404, b"not found", "text/plain")
            return
        if _rec_path and os.path.realpath(_rec_path) == path:
            self._send(409, b"recording", "text/plain")
            return
        os.unlink(path)
        ts = path[:-5] + ".ts"
        if os.path.isfile(ts):
            os.unlink(ts)
        self._json({"ok": True, "file": os.path.basename(path)})

    def _clip_play(self, name):
        path = _clip(name)
        if not path:
            self._send(404, b"not found", "text/plain")
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header(*HDR)
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            _play(path, self.wfile)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass


def main():
    if not _wait_encoder():
        sys.exit(f"[cam] {ENC_DEV} not usable")
    httpd = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    httpd.daemon_threads = True
    print("[cam] http://0.0.0.0:8080", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
