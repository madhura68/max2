#!/bin/sh
r=/home/janpeter/m6-runs/refiner-precisie-2026-10-01; map=rooktest-q8; m=$r/$map-metingen.txt
cd /home/janpeter/Development/max2-m6/llm-bench || exit 1
{ echo "## voor het gesprek"; grep -E '^(pswpin|pswpout) ' /proc/vmstat; grep MemAvailable /proc/meminfo; } >> "$m"
PYTHONDONTWRITEBYTECODE=1 ./refiner/run.py --backend harness \
  --harness "node /home/janpeter/Development/agent-harness/dist/cli.js" --variant docs \
  --models qwen3.8-q8-lokaal --cases D03 --seeds 1 --max-output-tokens 16384 --max-wall-seconds 3600 \
  --out "$r/$map" > "$r/$map.log" 2>&1
echo "exit=$?" >> "$r/$map.log"
{ echo "## na het gesprek"; ollama ps; curl -s 127.0.0.1:11434/api/ps; echo
  grep -E '^(pswpin|pswpout) ' /proc/vmstat; grep MemAvailable /proc/meminfo; } >> "$m"
