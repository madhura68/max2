#!/usr/bin/env bash
# Install crashloop-watch on max2 (needs sudo). Idempotent.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
sudo install -m 0755 "$here/crashloop-watch.sh" /usr/local/bin/crashloop-watch
sudo install -m 0644 "$here/crashloop-watch.service" "$here/crashloop-watch.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crashloop-watch.timer
systemctl list-timers crashloop-watch.timer --no-pager
