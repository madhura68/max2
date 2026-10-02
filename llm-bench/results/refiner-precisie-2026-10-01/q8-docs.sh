#!/bin/sh
r=/home/janpeter/m6-runs/refiner-precisie-2026-10-01; map=q8-docs
cd /home/janpeter/Development/max2-m6/llm-bench || exit 1
PYTHONDONTWRITEBYTECODE=1 ./refiner/run.py --backend harness \
  --harness "node /home/janpeter/Development/agent-harness/dist/cli.js" --variant docs \
  --models qwen3.8-q8-lokaal --seeds 1 2 3 --max-output-tokens 16384 --max-wall-seconds 8520 \
  --out "$r/$map" > "$r/$map.log" 2>&1
echo "exit=$?" >> "$r/$map.log"
curl -s 127.0.0.1:11434/api/ps > "$r/$map-api-ps-na.json"
