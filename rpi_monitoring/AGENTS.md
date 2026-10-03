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
- `rot` 1 = landscape 320×240. Panel MADCTL is `0x28`. A touch cal saved for the previous 180° panel (`rot` 3) is flipped once and stored with `rot: 1`
- Service: `lcd-monitor.service`. One process only (SPI). `hello_lcd.py` is retired
- Pi does no metric checks. It GETs `ui.collector_url` and draws the JSON. On a good fetch it waits `next_in_s` (60). A failed fetch retries after 5s, 10s, 20s, then every 30s
- The one local check is the camera: it looks for `/sys/bus/i2c/drivers/imx519/*-001a`. While that is missing it retries every 5s. Once it is `cam ok` it checks again every 30 min, so a cable pulled while the Pi is up can stay `ok` until that pass
- Home is 4×2: racoon, worker, gpu, pi / eateria, backup, network, camera. Top right is London air temperature (`temp_out`). `all ok` is green, `N warn` amber, `N bad` red. After 90s without a fresh snapshot the status is grey `old Nm`. Camera opens START/STOP. Wake GPU and Run backup are both on the backup screen, right-hand column, confirm armed 0.7s
- Any non-home screen returns home after 5s idle, unless the screen is locked. Night clock 23:00–07:00 Europe/London. Locked: no idle return, and home does not flip to night. A tap in the night theme shows the grid
- Lock is on the 8 inner screens, settings, weather, and the camera page, bottom-right. The hit target is the whole corner. Open lock means idle-return is on. Closed lock is yellow, toast `locked`
- Home tiles are short: short name, one big number, one word. Racoon's word is `cpu`. Inner screens list the rows in larger type (17px when a page has 9 rows). Values are colored ok/warn/crit/off/stale. RAM and disks are free percent plus amount (`70% 43G`, or `M` under 1G). Labels: `ram free`, `/ free`, `ssd free`, `hdd free`, `sd free`, `staging free`, `gpu ram`. Racoon, worker, and GPU end with `k8s` up/down. GPU off paints every row grey `off`
- Camera START/STOP is local `GET http://127.0.0.1:8080/record?on=1|0`. The timer ticks on the Pi from the last snapshot elapsed. Rec stays 1280×960, encoder swap only
- Confirm OK POSTs `{collector}/api/actions` with `{"id":"wake"}` or `{"id":"backup"}`. Toast is `sent`, `denied`, or `failed`
- Fetch timeout 8s. Full red `no link` only after 5 minutes with no good fetch. Before that, the screen says connecting. Tap shows the last grid in grey for 5s. Recording survives idle, night, bang, and restart

## Collector

`rpi_monitoring/collector/` — FastAPI. GitHub Actions (`.github/workflows/lcd-collector.yaml`) builds on `ubuntu-latest` and pushes `ghcr.io/singularis/lcd-collector:<short-sha>` plus `:latest` with `GITHUB_TOKEN`. After the package is public it pins `chart/values.yaml` to that image with `[skip ci]`. Argo Application `rpi_monitoring/collector/argo/application.yaml` syncs `rpi_monitoring/collector/chart` (not a template inside the chart). Do not `kubectl apply` the chart by hand.

Namespace `lcd-monitor`, LoadBalancer `192.168.0.124:8000` (pod listens on 8010, host network, same pattern as Backepr, so LAN checks leave from the node IP). `externalTrafficPolicy: Local`, 2 replicas, Lease `lcd-collector`. A pod is Ready once it has a snapshot; only the leader collects. Repo is public, so Argo uses `https://github.com/singularis/raspberry_pi.git` with no deploy key.

- `GET /` is the LAN page (`web/index.html`, `web/style.css`), same data as the Pi. `GET /api/display` is view-model schema 1. `POST /api/actions` from the Pi, racoon, or any `192.168.*` address (`wake`, `backup`), fire-and-forget so WoL does not block the caller
- Node metrics from Prometheus `prometheus.lens-metrics.svc` (`kubernetes_node` racoon / racoon-worker / racoon-gpu). Ready/pressure from the node API. Backup and wake via Backepr `http://192.168.0.122:8000`
- Pi health is `GET http://192.168.0.89:8080/health` on the camera Flask, in a background thread: every 60s, 10s timeout, then 5/10/20/40/80/120s after failures. The last good sample is kept for 5 minutes, then the Pi tile goes grey. CPU percent is a delta inside that thread, not from a cached body. Files only. It must not touch Picamera2. `/health` asks `systemctl is-active` once for all four units
- Eateria synthetic user is `singularis314@gmail.com`. JWT from secrets `chater-ui/chater-ui` and `chater-ui-dev/chater-ui-dev` (`JWT_SECRET`), 5 min, never logged, never sent to the Pi. GET only, `User-Agent: lcd-synthetic`. Public fail retries in-cluster `chater-ui.chater-ui:5000` or `chater-ui-dev.chater-ui-dev:5000`. Prod paints the tile. Dev only fills the `dev` row
- OpenClaw (GPU on only): `openclaw health --json` and `openclaw status --json` over SSH. Warn, never crit. GPU powered off is `off`, never red. No `status --all` in the 1-min loop. Map: `ok`, `plugins.errors`, `channels.telegram.connected`, `tasks.failures`, `taskAudit.errors`
- Network up/down is a Cloudflare speed test (4MB down, 1MB up) in a background thread every 5 min, cached on the lease. Do not run it inside `assemble()` or the Pi GETs time out
- Eateria tile color is prod only: red when the public and in-cluster GET both fail, or healthz fails, otherwise green. Dev is one inner row (`up`/`down`) and does not change the tile. Latency and Argo health are ignored. The big number is scans today. Inner rows are today vs yesterday, plus 7 days vs the 7 days before: scans, users, anon, ascans, 7d scans, 7d users (new accounts, anon included). 1 or more is green, 0 is grey. Counts are one SQL query on the eater DB. Today reply is protobuf. Do not use admin `/api/stats`
- Backepr storage (`/api/dashboard/storage/staging` and `archive`) is fetched only while the GPU host is on. While it is off those calls take about 13s and the backup row shows staging `off`
- GPU inner rows, one page: cpu, ram free, gpu load, gpu ram (always green when on), staging free, / free, temp, gpu temp, k8s. OpenClaw is page 2 and only when the host is on. Wake GPU is not on this screen
- London temperature is Open-Meteo `temperature_2m` for 51.51,-0.13, cached 15 min, field `temp_out`
- Argo: chart path `rpi_monitoring/collector/chart`. Application manifest is `rpi_monitoring/collector/argo/application.yaml` (not inside the chart). Public repo, HTTPS, no deploy key

## Camera

`setting/camera.json` + `rpi_camera/stream_video.py`.

- IMX519, `dtoverlay=imx519`, `gpu_mem=64`, KMS `cma-128`. 16 MB is too small for the hardware JPEG encoder (`/dev/video11`)
- Live 1280×960, raw 2328×1748, YUV420, 4 buffers, hflip+vflip (180°, ISP). Live frame time 33–50 ms (the 2-buffer pipeline stalled near 10 fps). Page CSS is rotate(90deg) and shows the full frame, no crop. The ISP drops a 90° transpose. Do not JPEG-rotate (about 250 ms a frame)
- JPEG bitrate is the hardware cap, 25 Mbit/s. Sharpness 2.0 and high-quality denoise are ISP controls
- The streamer is Python stdlib HTTP plus libcamera. Do not import Picamera2 or Flask. Those pulled NumPy, Pillow and FFmpeg and sat at ~73 MB with the camera off. This path is about 15 MB idle and about 20 MB while streaming. C++ would be a bit smaller, but libcamera-dev on this Pi does not match libcamera 0.3. Go and Rust have no armv6 libcamera binding here
- Rec: **same session**, swap encoder only. Never 1080p/4K reopen (OOM on ~364 MB)
- RecFile must be `io.BufferedIOBase`. Do not use `cam.encoder`
- MJPEG must be the hardware encoder (`/dev/video11`). The script waits for the device before importing Picamera2 and exits if Picamera2 picked the software one. `_close` stops the encoder before `close()`
- Clips: `rpi_camera/recordings/` (gitignored). Clips page stops camera. Rec survives refresh
- Service WorkingDirectory `rpi_camera/`, ExecStart `rpi_camera/stream_video.py`
- http://192.168.0.89:8080/ — no AF motor on this module

## WiFi watchdog

`setting/wifi.json` + `setting/wifi_watchdog.sh` + timer/service. Ping router, bounce `wlan0`, reboot after repeated fails. Install: `./setting/install_wifi_watchdog.sh`. ExecStart must stay `setting/wifi_watchdog.sh`.

## Learnings

- The Pi draws. Thresholds and colors live in the collector, except the Pi screen's `cam` row, which is a local file check. A wrong color on any other row is a collector bug.
- Pod CIDR cannot reach the router or the Pi. The collector uses hostNetwork, like Backepr. Readiness is "has a snapshot", not "is leader", or a rolling update never finishes. Host port 8010 cannot surge (`maxSurge: 0`).
- Lease renew timestamps need fractional seconds (`.000000Z`). A bare `Z` is HTTP 400 and both replicas stay unready.
- Prometheus `avg`/`max` without `by (kubernetes_node)` mixes the nodes. CPU temp is the coretemp sensor, not the hottest NVMe.
- A speed test on the collector NIC fills the link. Two missed Pi fetches then became "no link". The test is background. The screen now waits 5 minutes with no good fetch before `no link`, and failed fetches back off to 30s.
- The Pi RAM row was always red because it used the worker's free-GB thresholds, and 219M is always under 0.7G. The Pi is red only when 70% or more of its RAM is used.
- Backepr storage takes about 13s while the GPU host is off. Do not call it on that path.
- On a successful fetch the display waits `next_in_s` (60), not the `-refresh 5s` flag.
- A cached `/health` body breaks the Pi CPU delta, because both samples are the same jiffies. Compute the percent in the poller, from two different replies.
- This repo has no Docker Hub secrets, and Chater's runners are not shared. `GITHUB_TOKEN` pushes `ghcr.io/singularis/lcd-collector`. GitHub's package API returns 404 if you try to set visibility. The public repo's package is anonymously pullable, which is what the cluster needs.
- Eateria "today" is protobuf, not JSON. A JSON parse error looked like the site was down. Admin `/api/stats` has totals only. Today counts are SQL.
- Touch: the IRQ lies, so use Z. The chip is portrait and the panel is landscape, so calibration has to see which raw axis is X. A press stays down until the finger lifts, so the loop must edge-detect. The lock only works if the corner is the hit target, not the icon pixels.
- One SPI process. Full-frame blit every 20ms was ~20% CPU. Skip unchanged frames and poll at 100ms when idle.
- One Picamera2. Recording is an encoder swap at 1280×960. Reopening 1080p/4K OOM'd the Zero. `RecFile` must be a buffered file.
- Picamera2 probes `/dev/video11` once at import and silently falls back to FFmpeg software MJPEG (8 threads). At boot udev gave the `video` group access at ~85 s, after the import had finished. That cost 100% CPU, 4 fps, ~125 MB RSS. The hardware path is ~60% CPU, 8 fps, ~74 MB. Native C++ `rpicam-vid` is ~13 MB but only a few points less CPU, because libcamera and the WiFi send dominate.

## Rules

- Pi Zero: RAM first. No OpenCV/NumPy on the streamer. LCD app is the Go binary, not Python
- One Picamera2; rec = encoder swap
- SPI on for LCD; CSI overlay stays for camera
- Commit / push only when asked
