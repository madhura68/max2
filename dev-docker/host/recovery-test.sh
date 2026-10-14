#!/usr/bin/env bash
# recovery-test.sh — root, eenmalig in de praktijkproef (IDEA-258, spec §4.4 "Herstelproef").
# Dwingt een verplaatsing van de sprong af met een onschadelijke testregel (TEST-NET-1, matcht geen echt verkeer),
# laat dev-docker-firewall.service herstellen en toont het bewijs. De EXIT-trap ruimt de testregel bij elke afloop op.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "root vereist"; exit 1; }
T=(-s 192.0.2.254/32 -m comment --comment dd-recovery-test -j DROP)     # TEST-NET-1: matcht geen echt verkeer
trap 'while iptables -D INPUT "${T[@]}" 2>/dev/null; do :; done' EXIT
iptables -I INPUT 1 "${T[@]}"
iptables -S INPUT | awk '$1 == "-A" {print; exit}'                          # → de testregel (sprong verplaatst)
systemctl start dev-docker-firewall.service
iptables -S INPUT | awk '$1 == "-A" {print; exit}'                          # → de sprong naar dev-docker-in
iptables -S INPUT | grep -c -- '-j dev-docker-in'                           # → 1
journalctl -t dev-docker-firewall --since '-2min' --no-pager                # → herstelmelding (op syslog-identifier, niet op unit)
