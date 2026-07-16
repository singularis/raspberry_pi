# Raspberry Pi Zero W Camera Streamer (IMX519 16MP)

Ultra-lean MJPEG camera streamer built for the **Raspberry Pi Zero W** (single-core ARMv6, 427 MB RAM) paired with the **Arducam IMX519 16MP** camera.

## Design

Every byte and CPU cycle matters on Pi Zero. This streamer is built around three key principles:

1. **Zero OpenCV / NumPy** — JPEG encoding is handled entirely by Picamera2's built-in `MJPEGEncoder` (backed by libjpeg-turbo), eliminating ~80 MB of library overhead.
2. **YUV420 pixel format** — 1.5 bytes/pixel instead of 3 (BGR888), halving frame-buffer memory. The MJPEG encoder accepts YUV natively with no conversion.
3. **ISP-offloaded rotation** — 90° rotation via `libcamera.Transform`, zero CPU cost.

Additional optimisations:
- Single shared encode → broadcast to N viewers (no per-client encoding)
- 2 capture buffers (minimum for smooth pipeline)
- All ISP post-processing disabled (noise reduction, sharpening)
- Camera auto-starts on first viewer, auto-stops after last viewer leaves

### Measured Performance (640×480 @ 15 fps target)

| Metric | Value |
|--------|-------|
| RSS (idle) | ~70 MB |
| RSS (streaming) | ~72 MB |
| CPU (idle) | 0% |
| CPU (streaming) | ~31% |
| Threads (idle) | 3 |
| Actual FPS | ~37 fps |

## Setup

### 1. Install Dependencies

```bash
chmod +x preinstall.sh
sudo ./preinstall.sh
```

### 2. Hardware Configuration

Edit `/boot/firmware/config.txt` and ensure:

```text
dtoverlay=imx519
gpu_mem=128
```

Reboot after changes.

### 3. Deploy as a Systemd Service

```bash
sudo cp flask_camera.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable flask_camera.service
sudo systemctl start flask_camera.service
```

Check status:

```bash
sudo systemctl status flask_camera.service
journalctl -u flask_camera.service -f
```

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `http://<pi-ip>:8080/` | HTML page with embedded live stream |
| `http://<pi-ip>:8080/video_feed` | Raw MJPEG stream (for Home Assistant, etc.) |

## WiFi watchdog

Keeps the Pi on the LAN when WiFi drops (common on Pi Zero W).

Every **5 minutes** it pings the router. If unreachable:

1. Bounce `wlan0` (`nmcli` disconnect/connect)
2. Restart NetworkManager
3. After 3 failed cycles (~15 min): reboot (30 min cooldown)

```bash
./install_wifi_watchdog.sh
journalctl -t wifi-watchdog -f
```
