#!/bin/sh
r=/home/janpeter/m7-runs/task-bench-2026-10-03; map=proef
export OPENROUTER_API_KEY="$(cat /run/user/1000/m7-openrouter.key)"
/usr/bin/node /home/janpeter/Development/agent-harness-m7/dist/cli.js task-bench --case "$r/case-AH-01.json" --model-config "$r/model-qwen3.8-openrouter.json" --task-config "$r/task-config.json" --label qwen3.8-openrouter --out "$r/$map" --api-key-env OPENROUTER_API_KEY --retry-transient > "$r/$map.log" 2>&1
echo "exit=$?" >> "$r/$map.log"
