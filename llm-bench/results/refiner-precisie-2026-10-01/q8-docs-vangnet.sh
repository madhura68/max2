#!/bin/sh
# Vangnet voor het einde van het venster (M6 Taak 3, venster tot 2026-10-02 08:00). Doet niets voor 07:40.
# Leeft de run dan nog: "Afbreken" uit de Vensterprocedure. Daarna "Herstellen" naar de dienststand vooraf
# (worker active, open-webui en dsh draaiden, tei-gpu niet) en de dienststand na. Normaal ruimt de operator
# dit vangnet op na zijn eigen herstel; dan gebeurt hier niets.
R=/home/janpeter/m6-runs/refiner-precisie-2026-10-01; map=q8-docs; log=$R/$map-vangnet.log
deadline=$(date -d '2026-10-02 07:40' +%s)
while [ "$(date +%s)" -lt "$deadline" ]; do sleep 60; done
echo "$(date +%T) vangnet: 07:40 bereikt" >> "$log"
sid=$(cat "$R/$map.sid")
[ -n "$sid" ] || { echo "$(date +%T) lege sid: niets gedaan, JP" >> "$log"; exit 1; }
leeft() {
  tmux has-session -t "=m6-$map" 2>/dev/null && return 0
  pgrep -s "$sid" >/dev/null; rc=$?
  [ $rc -eq 0 ] && return 0
  [ $rc -eq 1 ] && return 1
  echo "$(date +%T) pgrep exit $rc: niets hersteld, JP" >> "$log"; exit 1
}
if leeft; then
  echo "$(date +%T) run leeft: pkill -INT -s $sid" >> "$log"; pkill -INT -s "$sid"
  i=0; while leeft && [ $i -lt 12 ]; do sleep 10; i=$((i+1)); done
  if leeft; then
    echo "$(date +%T) leeft na 2 min: pkill -TERM -s $sid" >> "$log"; pkill -TERM -s "$sid"
    i=0; while leeft && [ $i -lt 6 ]; do sleep 10; i=$((i+1)); done
  fi
  if leeft; then echo "$(date +%T) leeft nog na TERM: worker blijft gestopt, JP" >> "$log"; exit 1; fi
  echo "$(date +%T) run afgebroken: deze map geeft geen oordeel" >> "$log"
fi
docker start open-webui dsh >> "$log" 2>&1
sudo -n systemctl start agent-harness-worker >> "$log" 2>&1
echo "$(date +%T) worker: $(systemctl is-active agent-harness-worker)" >> "$log"
[ -f "$R/dienststand-$map-na.txt" ] || sh "$R/dienststand.sh" "$R/dienststand-$map-na.txt"
echo "$(date +%T) vangnet klaar" >> "$log"
