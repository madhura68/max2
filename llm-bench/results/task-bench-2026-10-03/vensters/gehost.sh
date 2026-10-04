#!/bin/sh
# M7 Taak 9: de 12 taken met qwen3.8-openrouter (Vensterprocedure, gehost venster met sleutelstap).
r=/home/janpeter/m7-runs/task-bench-2026-10-03; map=gehost
cd /home/janpeter/Development/max2-m7/llm-bench || exit 1
export OPENROUTER_API_KEY="$(cat /run/user/1000/m7-openrouter.key)"
PYTHONDONTWRITEBYTECODE=1 ./task_bench/run.py --harness "/usr/bin/node /home/janpeter/Development/agent-harness-m7/dist/cli.js" --models qwen3.8-openrouter --cases task_bench/cases.jsonl --task-config task_bench/task-config.json --out "$r/$map" --ledger "$r/ledger.jsonl" > "$r/$map.log" 2>&1
echo "exit=$?" >> "$r/$map.log"
