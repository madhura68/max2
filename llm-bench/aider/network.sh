#!/usr/bin/env bash
# Sandbox network for the Aider benchmark: containers on the internal Docker network
# "llm-bench-internal" reach only Ollama (socat on the bridge gateway -> 127.0.0.1:11434).
# No internet, LAN or tailnet; host ports other than 11434 are dropped by iptables.
#   ./network.sh up | down | check
set -euo pipefail
NET=llm-bench-internal
case "${1:-}" in
  up)
    docker network inspect $NET >/dev/null 2>&1 || docker network create --internal $NET >/dev/null
    gw=$(docker network inspect $NET -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}')
    br=br-$(docker network inspect $NET -f '{{.Id}}' | cut -c1-12)
    sudo iptables -C INPUT -i "$br" -p tcp --dport 11434 -m comment --comment llm-bench -j ACCEPT 2>/dev/null \
      || sudo iptables -I INPUT 1 -i "$br" -p tcp --dport 11434 -m comment --comment llm-bench -j ACCEPT
    sudo iptables -C INPUT -i "$br" -m comment --comment llm-bench -j DROP 2>/dev/null \
      || sudo iptables -I INPUT 2 -i "$br" -m comment --comment llm-bench -j DROP
    pgrep -f "socat TCP-LISTEN:11434,bind=$gw" >/dev/null \
      || nohup socat TCP-LISTEN:11434,bind="$gw",fork,reuseaddr TCP:127.0.0.1:11434 >/dev/null 2>&1 &
    echo "up: $NET gw=$gw bridge=$br"
    ;;
  down)
    gw=$(docker network inspect $NET -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null || true)
    [ -n "$gw" ] && pkill -f "socat TCP-LISTEN:11434,bind=$gw" || true
    while read -r rule; do sudo iptables ${rule/-A/-D}; done < <(sudo iptables -S INPUT | grep 'comment llm-bench')
    docker network rm $NET >/dev/null 2>&1 || true
    echo down
    ;;
  check)
    docker run --rm --network $NET python:3.12-slim python -c "
import socket, urllib.request
gw = '$(docker network inspect $NET -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}')'
print('ollama', urllib.request.urlopen(f'http://{gw}:11434/api/version', timeout=5).read().decode())
for h, p in [(gw, 22), ('1.1.1.1', 443), ('192.168.0.154', 22)]:
    s = socket.socket(); s.settimeout(3)
    try: s.connect((h, p)); print(h, p, 'OPEN  <-- not isolated')
    except OSError: print(h, p, 'blocked')
"
    ;;
  *) echo "usage: $0 up|down|check" >&2; exit 2 ;;
esac
