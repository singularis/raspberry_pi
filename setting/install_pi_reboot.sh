#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$ROOT/pi_reboot.sh"
sudo cp "$ROOT/pi-reboot.service" /etc/systemd/system/
sudo cp "$ROOT/pi-reboot.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pi-reboot.timer
echo "Installed."
systemctl list-timers pi-reboot.timer --no-pager || true
echo "Logs: journalctl -t pi-reboot"
