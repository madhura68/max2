#!/bin/bash
# Gebruik: wacht.sh <map>. Klaar als tmux-sessie m7-<map> weg is én pgrep -s <sid> exit 1 geeft (Vensterprocedure M6/M7).
map=$1; R=/home/janpeter/m7-runs/task-bench-2026-10-03; fouten=0
while :; do
  out=$(ssh -o ConnectTimeout=15 max2 "sid=\$(cat $R/$map.sid 2>/dev/null); [ -n \"\$sid\" ] || { echo LEEG; exit; }; tmux has-session -t '=m7-$map' 2>/dev/null; h=\$?; pgrep -s \"\$sid\" >/dev/null; p=\$?; echo \"\$h \$p\"")
  case "$out" in
    "1 1") echo "klaar $(date -u +%H:%M:%SZ)"; break ;;
    "0 0"|"0 1"|"1 0") fouten=0; sleep 30 ;;
    "") fouten=$((fouten+1)); [ $fouten -ge 5 ] && { echo "ssh faalt herhaald"; exit 2; }; sleep 30 ;;
    *) echo "fout: '$out' (JP)"; exit 3 ;;
  esac
done
ssh max2 "tail -8 $R/$map.log; echo harness-containers: \$(docker ps -aq --filter name=^harness- | wc -l)"
