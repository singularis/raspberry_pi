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
- Any non-home screen returns home after 5s idle, unless the screen is locked. Night clock 23:00–07:00 Europe/London. Locked: no idle return, and home does not flip to night. A tap in the night theme shows the grid
- Lock is only on the 8 inner screens, bottom-right. The hit target is the whole corner. Open lock means idle-return is on. Closed lock is yellow, toast `locked`
- Home tiles are short: short name, one big number, one word. Inner screens list the full rows in larger type, values colored ok/warn/crit/off/stale. Inner RAM is free. The racoon home line is still used percent
- Camera START/STOP is local `GET http://127.0.0.1:8080/record?on=1|0`. The timer ticks on the Pi from the last snapshot elapsed. Rec stays 1280×960, encoder swap only
- Wake GPU and Run backup show a confirm. The confirm still only toasts. It does not POST `/api/actions`
- Fetch timeout 8s. Six missed fetches (~30s at 5s refresh) after the first 2 min from boot: full red `!`. Before that, the screen says connecting. Tap shows the last grid in grey for 5s. Recording survives idle, night, bang, and restart

## Collector

`rpi_monitoring/collector/` — FastAPI. GitHub Actions (`.github/workflows/lcd-collector.yaml`) builds on `ubuntu-latest` and pushes `ghcr.io/singularis/lcd-collector:<short-sha>` plus `:latest` with `GITHUB_TOKEN`. After the package is public it pins `chart/values.yaml` to that image with `[skip ci]`. Argo Application `rpi_monitoring/collector/argo/application.yaml` syncs `rpi_monitoring/collector/chart` (not a template inside the chart). Do not `kubectl apply` the chart by hand.

Namespace `lcd-monitor`, LoadBalancer `192.168.0.124:8000` (pod listens on 8010, host network, same pattern as Backepr, so LAN checks leave from the node IP). `externalTrafficPolicy: Local`, 2 replicas, Lease `lcd-collector`. A pod is Ready once it has a snapshot; only the leader collects. Repo is public, so Argo uses `https://github.com/singularis/raspberry_pi.git` with no deploy key.

- `GET /api/display` view-model schema 1. `POST /api/actions` only from `192.168.0.89` and `192.168.0.10` (`wake`, `backup`), fire-and-forget so WoL does not block the Pi
- Node metrics from Prometheus `prometheus.lens-metrics.svc` (`kubernetes_node` racoon / racoon-worker / racoon-gpu). Ready/pressure from the node API. Backup and wake via Backepr `http://192.168.0.122:8000`
- Pi health is `GET http://192.168.0.89:8080/health` on the camera Flask. Files only. It must not touch Picamera2
- Eateria synthetic user is `singularis314@gmail.com`. JWT from secrets `chater-ui/chater-ui` and `chater-ui-dev/chater-ui-dev` (`JWT_SECRET`), 5 min, never logged, never sent to the Pi. GET only, `User-Agent: lcd-synthetic`. Public fail retries in-cluster `chater-ui.chater-ui:5000` or `chater-ui-dev.chater-ui-dev:5000` and the tile names that hop
- OpenClaw (GPU on only): `openclaw health --json` and `openclaw status --json` over SSH. Warn, never crit. GPU powered off is `off`, never red. No `status --all` in the 1-min loop. Map: `ok`, `plugins.errors`, `channels.telegram.connected`, `tasks.failures`, `taskAudit.errors`
- Network up/down is a Cloudflare speed test (4MB down, 1MB up) in a background thread every 5 min, cached on the lease. Do not run it inside `assemble()` or the Pi GETs time out
- Eateria home tile is warn (brown) when prod is up but slower than 1s, dev is down, or a Chater/Eater Argo app is not Healthy. Down prod is red. Today reply is protobuf. Today counts are SQL on the eater DB, not admin `/api/stats`
- Argo: chart path `rpi_monitoring/collector/chart`. Application manifest is `rpi_monitoring/collector/argo/application.yaml` (not inside the chart). Public repo, HTTPS, no deploy key

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

## Learnings

- The Pi only draws. Every check, threshold, and color decision lives in the collector. A wrong color is a collector bug, not a drawing bug.
- Pod CIDR cannot reach the router or the Pi. The collector uses hostNetwork, like Backepr. Readiness is "has a snapshot", not "is leader", or a rolling update never finishes. Host port 8010 cannot surge (`maxSurge: 0`).
- Lease renew timestamps need fractional seconds (`.000000Z`). A bare `Z` is HTTP 400 and both replicas stay unready.
- Prometheus `avg`/`max` without `by (kubernetes_node)` mixes the nodes. CPU temp is the coretemp sensor, not the hottest NVMe.
- A speed test on the collector NIC fills the link. Two missed Pi fetches then became "no link". The test is background, and the screen waits about 30s before the bang.
- This repo has no Docker Hub secrets, and Chater's runners are not shared. `GITHUB_TOKEN` pushes `ghcr.io/singularis/lcd-collector`. GitHub's package API returns 404 if you try to set visibility. The public repo's package is anonymously pullable, which is what the cluster needs.
- Eateria "today" is protobuf, not JSON. A JSON parse error looked like the site was down. Admin `/api/stats` has totals only. Today counts are SQL.
- Touch: the IRQ lies, so use Z. The chip is portrait and the panel is landscape, so calibration has to see which raw axis is X. A press stays down until the finger lifts, so the loop must edge-detect. The lock only works if the corner is the hit target, not the icon pixels.
- One SPI process. Full-frame blit every 20ms was ~20% CPU. Skip unchanged frames and poll at 100ms when idle.
- One Picamera2. Recording is an encoder swap at 1280×960. Reopening 1080p/4K OOM'd the Zero. `RecFile` must be a buffered file.

## Rules

- Pi Zero: RAM first. No OpenCV/NumPy on the streamer. LCD app is the Go binary, not Python
- One Picamera2; rec = encoder swap
- SPI on for LCD; CSI overlay stays for camera
- Commit / push only when asked
