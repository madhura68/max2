#!/usr/bin/env bash
# Install/refresh the host side of the dsh container (PBI-2). Idempotent. Run with sudo.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
install -m 0755 "$here/dsh-firewall.sh" /usr/local/sbin/dsh-firewall.sh
for u in dsh-firewall.service dsh-firewall.timer dsh-ollama-bridge.service dsh-web-bridge.service; do
  install -m 0644 "$here/$u" "/etc/systemd/system/$u"
done
systemctl daemon-reload
systemctl enable --now dsh-firewall.timer
systemctl start dsh-firewall.service
systemctl enable --now dsh-ollama-bridge.service dsh-web-bridge.service
