#!/bin/sh
# M7 Taak 8: --check-case voor de kandidaten in selectie/lijst.txt, na elkaar, zonder sleutel (Vensterprocedure).
# Een stop (INT/TERM via pkill -s) zet alleen een vlag: de lopende check ruimt zelf op, daarna start er geen volgende.
r=/home/janpeter/m7-runs/task-bench-2026-10-03; d=$r/selectie; stop=
trap 'stop=1' INT TERM
for id in $(cat "$d/lijst.txt"); do
  [ -n "$stop" ] && break
  echo "== $id $(date -u +%H:%M:%SZ)" >> "$r/selectie.log"
  /usr/bin/node /home/janpeter/Development/agent-harness-m7/dist/cli.js task-bench --check-case --case "$d/cases/$id.json" --task-config "$r/task-config.json" --out "$d/$id" >> "$r/selectie.log" 2>&1
  echo "exit-$id=$?" >> "$r/selectie.log"
done
[ -n "$stop" ] && echo "afgebroken" >> "$r/selectie.log"
echo "exit=0" >> "$r/selectie.log"
