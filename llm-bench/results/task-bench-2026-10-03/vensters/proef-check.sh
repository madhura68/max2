#!/bin/sh
r=/home/janpeter/m7-runs/task-bench-2026-10-03; map=proef-check
/usr/bin/node /home/janpeter/Development/agent-harness-m7/dist/cli.js task-bench --check-case --case "$r/case-AH-01.json" --task-config "$r/task-config.json" --out "$r/$map" > "$r/$map.log" 2>&1
echo "exit=$?" >> "$r/$map.log"
