#!/usr/bin/env bash
# sampler.sh — janpeter op max2, geen argumenten (IDEA-258, spec §8.2). Licht en zonder blokkerende vmstat.
# Elke 5 s één regel `<UTC> <MemAvailable kB> <vrije bytes /var/lib/docker>` naar ~/dev-docker-proef-sampler.log, plus een regel
# `<UTC> ALARM MemAvailable=<kB> kB < 12582912` zodra de operationele vloer van 12,0 GiB wordt onderschreden. Stopt op SIGTERM.
#   nohup bash ~/sampler.sh >/dev/null 2>&1 &
set -euo pipefail
LOG=$HOME/dev-docker-proef-sampler.log
FLOOR_KB=12582912
trap 'exit 0' TERM INT
while :; do
  ts=$(date -u +%FT%TZ)
  mem=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
  avail=$(df -B1 --output=avail /var/lib/docker 2>/dev/null | tail -n 1 | tr -d ' ' || true)
  printf '%s %s %s\n' "$ts" "${mem:-NA}" "${avail:-NA}" >>"$LOG"
  if [ -n "${mem:-}" ] && [ "$mem" -lt "$FLOOR_KB" ]; then printf '%s ALARM MemAvailable=%s kB < %s\n' "$ts" "$mem" "$FLOOR_KB" >>"$LOG"; fi
  sleep 5
done
