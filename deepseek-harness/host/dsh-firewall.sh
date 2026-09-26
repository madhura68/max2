#!/usr/bin/env bash
# Host firewall for the dsh container (PBI-2). Idempotent; run by dsh-firewall.service at boot
# and by dsh-firewall.timer every few minutes, so a recreated Caddy (new IP) is picked up.
#  - from the dsh bridge (br-dsh) the host accepts only tcp/11434 (Ollama bridge) and replies to
#    connections the host itself opened (the web bridge), nothing else;
#  - 172.18.0.1:3080 (web bridge) accepts only the current IP of scrum4me-caddy.
# Fails closed: without a Caddy IP no one reaches 3080.
set -euo pipefail
C=dsh-firewall
ipt() { iptables "$@"; }
ensure() { ipt -C INPUT "$@" 2>/dev/null || ipt -I INPUT 1 "$@"; }

# 1. Container -> host: only Ollama. Insert DROP first, then ACCEPT above it.
ensure -i br-dsh -m comment --comment "$C" -j DROP
ensure -i br-dsh -p tcp --dport 11434 -m comment --comment "$C" -j ACCEPT
# Replies to connections the host opened (web bridge -> container) must come back in.
ensure -i br-dsh -m conntrack --ctstate ESTABLISHED,RELATED -m comment --comment "$C" -j ACCEPT

# 2. Web bridge: default drop, then allow the current Caddy IP.
ensure -d 172.18.0.1/32 -p tcp --dport 3080 -m comment --comment "$C web-drop" -j DROP
caddy_ip=$(docker inspect scrum4me-caddy -f '{{with index .NetworkSettings.Networks "scrum4me_default"}}{{.IPAddress}}{{end}}' 2>/dev/null || true)
# Remove allow rules for any other source (stale Caddy IP).
while read -r rule; do
  src=$(sed -n 's/.*-s \([0-9.]*\)\/32.*/\1/p' <<<"$rule")
  [ "$src" != "$caddy_ip" ] && ipt ${rule/-A/-D}
done < <(ipt -S INPUT | grep -- '--comment "dsh-firewall web-allow"' || true)
if [ -n "$caddy_ip" ]; then
  ensure -s "$caddy_ip/32" -d 172.18.0.1/32 -p tcp --dport 3080 -m comment --comment "$C web-allow" -j ACCEPT
fi
