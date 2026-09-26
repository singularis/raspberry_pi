# rpi_monitoring — memory for future agents

Raspberry Pi Zero W (`dante-pi`). One memory file for this repo. Do not add another `AGENTS.md` or a second README.

## Layout

| Path | What |
|------|------|
| `rpi_camera/` | IMX519 streamer, `web/`, `flask_camera.service`, `preinstall.sh` |
| `rpi_monitoring/` | 2.4" SPI LCD app (`hello_lcd.py`) + this file |
| `setting/` | JSON + wifi watchdog scripts and units |

Camera code stays in `rpi_camera/`. Display code stays here. Wifi and tunables stay in `setting/`.

## Host

`setting/pi.json` — SSH `dante@192.168.0.89`. Dev machine is **racoon**, not the Pi. Deploy with `scp`, then restart systemd. Repo on Pi: `/home/dante/raspberry_pi`.

## Display

`setting/display.json` + `rpi_monitoring/hello_lcd.py` (Pillow, spidev, RPi.GPIO).

- LCDWiki MPI2411, ILI9341 320×240, XPT2046. Wiki: http://www.lcdwiki.com/2.4inch_RPi_Display_For_RPi_3A+
- **Do not** install `goodtft/LCD-show`. It fights camera KMS.
- Boot: `dtparam=spi=on`. Runtime: `sudo dtparam spi=on` → `/dev/spidev0.0` + `0.1`
- BCM: DC=22, RST=27, IRQ=17 (active low). LCD CE0, touch CE1
- Uninit panel is full white
- Touch IRQ is flaky; use Z pressure (`z_min` 80). Test: any tap → "touch working" 3s → Hello World
- `rot` 1 = landscape 320×240 (0–3). Change `setting/display.json` only
- Run: `python3 /home/dante/raspberry_pi/rpi_monitoring/hello_lcd.py` — one process only (SPI)

## Camera

`setting/camera.json` + `rpi_camera/stream_video.py`.

- IMX519, `dtoverlay=imx519`, `gpu_mem=128`
- Live 1280×960, raw 2328×1748, YUV420, 2 buffers, hflip+vflip
- Rec: **same session**, swap encoder only. Never 1080p/4K reopen (OOM on ~364 MB)
- RecFile must be `io.BufferedIOBase`. Do not use `cam.encoder`
- Clips: `rpi_camera/recordings/` (gitignored). Clips page stops camera. Rec survives refresh
- Service WorkingDirectory `rpi_camera/`, ExecStart `rpi_camera/stream_video.py`
- http://192.168.0.89:8080/ — no AF motor on this module

## WiFi watchdog

`setting/wifi.json` + `setting/wifi_watchdog.sh` + timer/service. Ping router, bounce `wlan0`, reboot after repeated fails. Install: `./setting/install_wifi_watchdog.sh`. ExecStart must stay `setting/wifi_watchdog.sh`.

## Rules

- Pi Zero: RAM first. No OpenCV/NumPy on the streamer
- One Picamera2; rec = encoder swap
- SPI on for LCD; CSI overlay stays for camera
- Commit / push only when asked
