#!/bin/bash
# M7 Taak 10, starter op de Mac (JP: nachtvenster 2026-10-03 22:00 – 2026-10-04 07:00). Arm met:
#   nohup caffeinate -is bash ~/Development/m7-runs/task-bench-2026-10-03/scripts-mac/start-gsq.sh >/dev/null 2>&1 &
# Wacht tot 22:00; is het dan later dan 22:30 (de Mac sliep), dan doet hij niets. Anders: controles en dienststand op max2,
# de M4-stop vanaf de Mac (max2 bereikt de database op scrum4me-srv niet), dan run, nazorg en vangnet op max2. Daarna mag de
# Mac slapen: de run, het herstel na afloop en het vangnet (06:40) draaien zelfstandig op max2.
set -u
R=/home/janpeter/m7-runs/task-bench-2026-10-03
D=$HOME/Development/m7-runs/task-bench-2026-10-03/scripts-mac
LOG=$D/start-gsq.log
M4=$HOME/Development/max2/llm-bench/results/refiner-precisie-2026-10-01/m4-stop.sh
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
start=$(date -j -f '%Y-%m-%d %H:%M:%S' '2026-10-03 22:00:00' +%s); laatst=$((start + 1800))
log "starter gewapend (pid $$), wacht tot 2026-10-03 22:00"
while [ "$(date +%s)" -lt "$start" ]; do sleep 20; done
[ "$(date +%s)" -le "$laatst" ] || { log "te laat ($(date +%T)): niets gedaan"; exit 1; }
log "controles op max2"
out=$(ssh -o ConnectTimeout=30 max2 "bash $R/gsq-start-controle.sh" 2>&1); rc=$?
log "$out (exit $rc)"; [ $rc -eq 0 ] || { log "geen start"; scp -q "$LOG" "max2:$R/gsq-start.log"; exit 1; }
log "M4-stop"
out=$(bash "$M4" 2>&1); rc=$?
log "$out (exit $rc)"; [ $rc -eq 0 ] || { log "M4-stop niet schoon: geen start, JP"; scp -q "$LOG" "max2:$R/gsq-start.log"; exit 1; }
log "start run, nazorg en vangnet op max2"
out=$(ssh -o ConnectTimeout=30 max2 "bash $R/gsq-start-run.sh" 2>&1); rc=$?
log "$out (exit $rc)"
scp -q "$LOG" "max2:$R/gsq-start.log"
exit $rc
