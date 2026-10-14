#!/usr/bin/env bash
# dev-docker-firewall.sh — root, /usr/local/sbin (IDEA-258, spec §4.4).
# Houdt de eigen keten dev-docker-in (LAN-grens voor tcp/55432) en de sprong ernaar op INPUT-positie 1 in stand.
# Positiebewust: iptables -C zegt alleen dat een regel ergens bestaat, niet waar. Een normale tick muteert niets;
# alleen de eigen keten en de eigen sprong worden aangeraakt, nooit andermans regels.
# Nooit een regel zonder matchcriteria en nooit -j RETURN in INPUT (onder ufw-default-deny = DROP voor alle ingress).
set -euo pipefail
R1=(-p tcp --dport 55432 -m conntrack --ctstate NEW ! -i enp4s0 -j DROP)              # elke andere ingress: tailscale0, bridges, lo
R2=(-i enp4s0 -p tcp --dport 55432 -m conntrack --ctstate NEW ! -s 192.168.0.0/24 -j DROP)
chain_ok() {
  iptables -C dev-docker-in "${R1[@]}" 2>/dev/null && iptables -C dev-docker-in "${R2[@]}" 2>/dev/null \
    && iptables -C dev-docker-in -j RETURN 2>/dev/null \
    && c=$(iptables -S dev-docker-in) && [ "$(grep -c '^-A ' <<<"$c")" -eq 3 ] \
    && [ "$(awk '$1 == "-A" {last=$0} END {print last}' <<<"$c")" = "-A dev-docker-in -j RETURN" ]   # RETURN als laatste
}
if ! chain_ok; then                                   # alleen bij eerste installatie of na manipulatie
  iptables -N dev-docker-in 2>/dev/null || true
  iptables -F dev-docker-in
  iptables -A dev-docker-in "${R1[@]}"; iptables -A dev-docker-in "${R2[@]}"; iptables -A dev-docker-in -j RETURN
  logger -t dev-docker-firewall "keten dev-docker-in opnieuw opgebouwd"
fi
inp=$(iptables -S INPUT)                              # eerst vangen, dan lezen: geen SIGPIPE onder pipefail
first=$(awk '$1 == "-A" {print; exit}' <<<"$inp")
case "$first" in
  *" -j dev-docker-in") ;;                            # onafhankelijk van hoe iptables -S het comment serialiseert
  *) while iptables -D INPUT -m comment --comment dev-docker -j dev-docker-in 2>/dev/null; do :; done   # alleen de eigen sprong
     iptables -I INPUT 1 -m comment --comment dev-docker -j dev-docker-in
     logger -t dev-docker-firewall "sprong naar dev-docker-in hersteld op INPUT-positie 1";;
esac
