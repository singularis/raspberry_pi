#!/usr/bin/env bash
# wifi_watchdog.sh — keep Pi Zero W on the LAN when WiFi drops.
#
# Every run (timer every 5 min):
#   1. Ping the default gateway (router).
#   2. If unreachable: bounce wlan0 via NetworkManager.
#   3. If still down: restart NetworkManager.
#   4. After MAX_FAILS consecutive failed cycles: reboot the Pi.

set -uo pipefail

IFACE="${WIFI_IFACE:-wlan0}"
ROUTER="${WIFI_ROUTER:-}"
if [[ -z "$ROUTER" ]]; then
  ROUTER="$(ip -4 route show default 2>/dev/null | awk '/default/ {print $3; exit}')"
fi
ROUTER="${ROUTER:-192.168.0.1}"

PING_COUNT="${PING_COUNT:-3}"
PING_WAIT="${PING_WAIT:-3}"
MAX_FAILS="${MAX_FAILS:-3}"
REBOOT_COOLDOWN_SEC="${REBOOT_COOLDOWN_SEC:-1800}"
STATE_DIR="${STATE_DIR:-/var/lib/wifi-watchdog}"
STATE_FILE="${STATE_DIR}/fail_count"
REBOOT_STAMP="${STATE_DIR}/last_reboot"
LOG_TAG="wifi-watchdog"

log() {
  logger -t "$LOG_TAG" "$*"
  echo "$(date -Is) $*"
}

router_ok() {
  ping -c "$PING_COUNT" -W "$PING_WAIT" -I "$IFACE" "$ROUTER" >/dev/null 2>&1 \
    || ping -c "$PING_COUNT" -W "$PING_WAIT" "$ROUTER" >/dev/null 2>&1
}

read_fails() {
  [[ -f "$STATE_FILE" ]] && cat "$STATE_FILE" || echo 0
}

write_fails() {
  echo "$1" >"$STATE_FILE"
}

bump_fails() {
  local n
  n="$(read_fails)"
  n=$((n + 1))
  write_fails "$n"
  echo "$n"
}

reset_fails() {
  write_fails 0
}

can_reboot() {
  if [[ ! -f "$REBOOT_STAMP" ]]; then
    return 0
  fi
  local last now
  last="$(cat "$REBOOT_STAMP" 2>/dev/null || echo 0)"
  now="$(date +%s)"
  [[ $((now - last)) -ge $REBOOT_COOLDOWN_SEC ]]
}

bounce_wifi() {
  log "bouncing $IFACE (nmcli disconnect/connect)"
  sudo nmcli device disconnect "$IFACE" 2>/dev/null || true
  sleep 2
  sudo nmcli radio wifi on 2>/dev/null || true
  sudo nmcli device connect "$IFACE" 2>/dev/null \
    || sudo nmcli networking on 2>/dev/null \
    || true
  sleep 8
}

restart_nm() {
  log "restarting NetworkManager"
  sudo systemctl restart NetworkManager
  sleep 12
}

reboot_pi() {
  if ! can_reboot; then
    log "reboot skipped — cooldown active (${REBOOT_COOLDOWN_SEC}s)"
    return
  fi
  date +%s | sudo tee "$REBOOT_STAMP" >/dev/null
  log "REBOOTING — WiFi still down after ${MAX_FAILS} cycles (router=${ROUTER})"
  sleep 2
  sudo systemctl reboot
}

mkdir -p "$STATE_DIR" 2>/dev/null || sudo mkdir -p "$STATE_DIR"
sudo chown "$(id -u):$(id -g)" "$STATE_DIR" 2>/dev/null || true

if router_ok; then
  if [[ "$(read_fails)" != "0" ]]; then
    log "router ${ROUTER} reachable again — clearing fail counter"
  fi
  reset_fails
  exit 0
fi

fails="$(bump_fails)"
log "router ${ROUTER} UNREACHABLE via ${IFACE} (fail ${fails}/${MAX_FAILS})"

bounce_wifi
if router_ok; then
  log "wifi bounce restored connectivity to ${ROUTER}"
  reset_fails
  exit 0
fi

restart_nm
if router_ok; then
  log "NetworkManager restart restored connectivity to ${ROUTER}"
  reset_fails
  exit 0
fi

log "still unreachable after wifi + NM recovery"
if [[ "$fails" -ge "$MAX_FAILS" ]]; then
  reboot_pi
fi

exit 1
