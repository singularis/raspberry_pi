#!/usr/bin/env bash
# pi_reboot.sh — daily reboot at 07:00 (pi-reboot.timer).
#
#   1. Skip if the Pi booted less than 10 min ago. There is no RTC: after a
#      power cut fake-hwclock restores an older time, so a slot can fire at boot.
#   2. Let a camera recording finish. Recordings stop by themselves at 30 min.
#   3. Log uptime, free RAM and WiFi firmware timeouts, then reboot.

set -uo pipefail

MIN_UP_S="${MIN_UP_S:-600}"
REC_WAIT_S="${REC_WAIT_S:-1860}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/health}"
LOG_TAG="pi-reboot"

log() {
  logger -t "$LOG_TAG" "$*"
  echo "$(date -Is) $*"
}

recording() {
  curl -s -m 5 "$HEALTH_URL" 2>/dev/null | grep -q '"recording": *true'
}

up="$(cut -d. -f1 /proc/uptime)"
if [[ "$up" -lt "$MIN_UP_S" ]]; then
  log "skip: up ${up}s, under ${MIN_UP_S}s"
  exit 0
fi

waited=0
while recording && [[ "$waited" -lt "$REC_WAIT_S" ]]; do
  if [[ "$waited" -eq 0 ]]; then
    log "camera is recording; waiting up to ${REC_WAIT_S}s"
  fi
  sleep 30
  waited=$((waited + 30))
done

up="$(cut -d. -f1 /proc/uptime)"
free_mb="$(awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo)"
wifi_timeouts="$(dmesg | grep -c 'status -110')"
log "rebooting: up ${up}s, ${free_mb}M free, ${wifi_timeouts} wifi timeouts"
systemctl reboot
