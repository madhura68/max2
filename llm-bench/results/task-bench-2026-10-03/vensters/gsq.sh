#!/bin/sh
# M7 Taak 10: de 12 taken met gsq-lokaal (Vensterprocedure, nachtvenster 2026-10-03 22:00 – 2026-10-04 07:00, zonder sleutel).
r=/home/janpeter/m7-runs/task-bench-2026-10-03; map=gsq
cd /home/janpeter/Development/max2-m7/llm-bench || exit 1
PYTHONDONTWRITEBYTECODE=1 ./task_bench/run.py --harness "/usr/bin/node /home/janpeter/Development/agent-harness-m7/dist/cli.js" --models gsq-lokaal --cases task_bench/cases.jsonl --task-config task_bench/task-config.json --out "$r/$map" --ledger "$r/ledger.jsonl" > "$r/$map.log" 2>&1
echo "exit=$?" >> "$r/$map.log"
curl -s 127.0.0.1:11434/api/ps > "$r/$map-api-ps-na.json"
