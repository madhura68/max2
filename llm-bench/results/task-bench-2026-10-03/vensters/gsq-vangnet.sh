#!/bin/bash
# Vangnet (venster tot 2026-10-04 07:00): doet niets vóór 06:40. Leeft de run dan nog: Afbreken (INT, 2 min, TERM, 1 min).
# Daarna Herstellen, tenzij de nazorg dat al deed.
log=/home/janpeter/m7-runs/task-bench-2026-10-03/gsq-vangnet.log
. /home/janpeter/m7-runs/task-bench-2026-10-03/gsq-herstel.sh
deadline=$(date -d "2026-10-04 06:40" +%s)
while [ "$(date +%s)" -lt "$deadline" ]; do sleep 60; done
echo "$(date +%T) vangnet: 06:40 bereikt" >> "$log"
if leeft; then
  echo "$(date +%T) run leeft: pkill -INT -s $sid" >> "$log"; pkill -INT -s "$sid"
  i=0; while leeft && [ $i -lt 12 ]; do sleep 10; i=$((i+1)); done
  if leeft; then
    echo "$(date +%T) leeft na 2 min: pkill -TERM -s $sid" >> "$log"; pkill -TERM -s "$sid"
    i=0; while leeft && [ $i -lt 6 ]; do sleep 10; i=$((i+1)); done
  fi
  if leeft; then echo "$(date +%T) leeft nog na TERM: worker blijft gestopt, JP" >> "$log"; exit 1; fi
  echo "$(date +%T) run afgebroken (stopcode 6; een volgend venster hervat)" >> "$log"
fi
sleep 40   # de nazorg ziet het einde binnen 30 s en herstelt; anders doet het vangnet het
herstel
echo "$(date +%T) vangnet klaar" >> "$log"
