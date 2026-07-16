#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
sudo mkdir -p /var/lib/wifi-watchdog
sudo chown dante:dante /var/lib/wifi-watchdog
chmod +x "$ROOT/wifi_watchdog.sh"
sudo cp "$ROOT/wifi-watchdog.service" /etc/systemd/system/
sudo cp "$ROOT/wifi-watchdog.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wifi-watchdog.timer
sudo systemctl start wifi-watchdog.service || true
echo "Installed."
systemctl status wifi-watchdog.timer --no-pager || true
systemctl list-timers wifi-watchdog.timer --no-pager || true
echo "Logs: journalctl -t wifi-watchdog -f"
