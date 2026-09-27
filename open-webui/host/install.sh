#!/usr/bin/env bash
# Install/refresh the host side of the open-webui container (PBI-6). Idempotent. Run with sudo.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
install -m 0755 "$here/owui-firewall.sh" /usr/local/sbin/owui-firewall.sh
for u in owui-firewall.service owui-firewall.timer owui-ollama-bridge.service owui-web-bridge.service; do
  install -m 0644 "$here/$u" "/etc/systemd/system/$u"
done
systemctl daemon-reload
systemctl enable --now owui-firewall.timer
systemctl start owui-firewall.service
systemctl enable --now owui-ollama-bridge.service owui-web-bridge.service
