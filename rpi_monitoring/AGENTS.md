# rpi_monitoring — memory for future agents

Raspberry Pi Zero W (`dante-pi`). One memory file for this repo. Do not add another `AGENTS.md` or a second README.

## Layout

| Path | What |
|------|------|
| `rpi_camera/` | IMX519 streamer, `web/`, `flask_camera.service`, `preinstall.sh` |
| `rpi_monitoring/` | Go LCD app (`display/`), collector (`collector/`), this file |
| `setting/` | JSON + wifi watchdog scripts and units |

Camera code stays in `rpi_camera/`. Display code stays here. Wifi and tunables stay in `setting/`.

## Host

`setting/pi.json` — SSH `dante@192.168.0.89`. Dev machine is **racoon**, not the Pi. Deploy with `scp`, then restart systemd. Repo on Pi: `/home/dante/raspberry_pi`.

## Display

`setting/display.json` + `rpi_monitoring/display/` (Go, `GOARCH=arm GOARM=6`, `-tags pi`). One static binary. No Pillow, numpy, or RPi.GPIO on the Pi.

- LCDWiki MPI2411, ILI9341 320×240, XPT2046. Wiki: http://www.lcdwiki.com/2.4inch_RPi_Display_For_RPi_3A+
- **Do not** install `goodtft/LCD-show`. It fights camera KMS.
- Boot: `dtparam=spi=on`. Devices: `/dev/spidev0.0` (LCD 16 MHz) + `0.1` (touch 500 kHz)
- BCM: DC=22, RST=27, IRQ=17 (active low). LCD CE0, touch CE1
- Uninit panel is full white. Backlight has no pin; brightness is colour scale (day 7/8 solid fills, night 1/8 black + dim red text)
- Touch IRQ is flaky; use Z pressure (`z_min` 80). 4-point cal is `touch.cal` in `setting/display.json` (hold the clock 3s)
- `rot` 1 = landscape 320×240
- Service: `lcd-monitor.service`. One process only (SPI). `hello_lcd.py` is retired
- Pi does no checks. It GETs `ui.collector_url` every `ui.refresh_s` (5 while debugging, 60 after sign-off) and draws the JSON
- Home is 4×2: racoon, worker, gpu, pi / eateria, backup, network, camera. Camera opens START/STOP. Wake GPU and Run backup need a confirm (armed 0.7s, after finger up)
- Any non-home screen returns home after 5s idle. Night clock 23:00–07:00 Europe/London; a tap shows the grid for 60s in the night theme
- Two missed fetches after 2 min from boot: full red `!`. Tap shows the last grid in grey for 5s. Recording survives idle, night, bang, and restart

## Collector

`rpi_monitoring/collector/` — FastAPI. Same delivery as Backepr and Chater: GitHub Actions (`.github/workflows/lcd-collector.yaml`) builds on the self-hosted runner and pushes `docker.io/singularis314/lcd-collector:<short-sha>` plus `:latest`, then pins `chart/values.yaml` with `[skip ci]`. Argo Application `rpi_monitoring/collector/argo/application.yaml` syncs `rpi_monitoring/collector/chart` (not a template inside the chart). Do not `kubectl apply` the chart by hand.

Namespace `lcd-monitor`, LoadBalancer `192.168.0.124:8000` (pod listens on 8010, host network, same pattern as Backepr, so LAN checks leave from the node IP). `externalTrafficPolicy: Local`, 2 replicas, Lease `lcd-collector`. A pod is Ready once it has a snapshot; only the leader collects. Repo is public, so Argo uses `https://github.com/singularis/raspberry_pi.git` with no deploy key. Actions needs repo secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (same names as Chater).

- `GET /api/display` view-model schema 1. `POST /api/actions` only from `192.168.0.89` and `192.168.0.10` (`wake`, `backup`), fire-and-forget so WoL does not block the Pi
- Node metrics from Prometheus `prometheus.lens-metrics.svc` (`kubernetes_node` racoon / racoon-worker / racoon-gpu). Ready/pressure from the node API. Backup and wake via Backepr `http://192.168.0.122:8000`
- Pi health is `GET http://192.168.0.89:8080/health` on the camera Flask. Files only. It must not touch Picamera2
- Eateria synthetic user is `singularis314@gmail.com`. JWT from secrets `chater-ui/chater-ui` and `chater-ui-dev/chater-ui-dev` (`JWT_SECRET`), 5 min, never logged, never sent to the Pi. GET only, `User-Agent: lcd-synthetic`. Public fail retries in-cluster `chater-ui.chater-ui:5000` or `chater-ui-dev.chater-ui-dev:5000` and the tile names that hop
- OpenClaw (GPU on only): `openclaw health --json` and `openclaw status --json` over SSH. Warn, never crit. GPU powered off is `off`, never red. No `status --all` in the 1-min loop. Map: `ok`, `plugins.errors`, `channels.telegram.connected`, `tasks.failures`, `taskAudit.errors`
- Argo: chart path `rpi_monitoring/collector/chart`. Needs a read-only deploy key secret (same pattern as `argocd-repo-racoon-server`), not the org PAT. The Application manifest is `chart/templates/argo-app.yaml`

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

- Pi Zero: RAM first. No OpenCV/NumPy on the streamer. LCD app is the Go binary, not Python
- One Picamera2; rec = encoder swap
- SPI on for LCD; CSI overlay stays for camera
- Commit / push only when asked
