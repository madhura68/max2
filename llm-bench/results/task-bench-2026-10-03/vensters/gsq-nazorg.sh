#!/bin/bash
# Nazorg: wacht tot de run klaar is (sessie weg en pgrep -s geeft 1), dan eindvoorwaarde en Herstellen; ruimt daarna het vangnet op.
log=/home/janpeter/m7-runs/task-bench-2026-10-03/gsq-nazorg.log
. /home/janpeter/m7-runs/task-bench-2026-10-03/gsq-herstel.sh
echo "$(date +%T) nazorg wacht op de run" >> "$log"
while leeft; do sleep 30; done
echo "$(date +%T) run klaar: $(tail -1 "$R/$map.log")" >> "$log"
herstel
tmux kill-session -t "=m7-gsq-vangnet" 2>/dev/null && echo "$(date +%T) vangnet opgeruimd" >> "$log"
echo "$(date +%T) nazorg klaar" >> "$log"
