# Gedeeld door nazorg en vangnet (gesourced door bash). Herstelt precies één keer (mkdir is atomair), na de M7-eindvoorwaarde,
# naar de dienststand van vooraf (dienststand-gsq-voor.txt): alleen de containers die toen draaiden, TEI via compose, de worker
# alleen als hij active was.
R=/home/janpeter/m7-runs/task-bench-2026-10-03; map=gsq
leeft() {   # 0 = er leeft nog iets van de run; 1 = klaar; elke andere uitkomst: stop, JP
  sid=$(cat "$R/$map.sid" 2>/dev/null); [ -n "$sid" ] || { echo "$(date +%T) lege sid: JP" >> "$log"; exit 1; }
  tmux has-session -t "=m7-$map" 2>/dev/null && return 0
  pgrep -s "$sid" >/dev/null; rc=$?
  [ $rc -eq 0 ] && return 0
  [ $rc -eq 1 ] && return 1
  echo "$(date +%T) pgrep exit $rc: niets hersteld, JP" >> "$log"; exit 1
}
herstel() {
  mkdir "$R/$map-herstel.lock" 2>/dev/null || { echo "$(date +%T) herstel al gedaan of bezig" >> "$log"; return 0; }
  n=$(docker ps -aq --filter name=^harness- | wc -l)
  [ "$n" = 0 ] || { echo "$(date +%T) nog $n harness-containers: niet hersteld, worker blijft gestopt, JP" >> "$log"; exit 1; }
  voor="$R/dienststand-$map-voor.txt"
  for c in $(awk '/^## containers/{f=1;next} /^## /{f=0} f && NF' "$voor"); do
    if [ "$c" = tei-gpu ]; then docker compose -f /srv/apps/tei/docker-compose.yml start >> "$log" 2>&1
    else docker start "$c" >> "$log" 2>&1; fi
  done
  if [ "$(awk '/^## agent-harness-worker/{getline; print; exit}' "$voor")" = active ]; then
    sudo -n systemctl start agent-harness-worker >> "$log" 2>&1
  fi
  sleep 3
  echo "$(date +%T) worker: $(systemctl is-active agent-harness-worker)" >> "$log"
  sh "$R/dienststand.sh" "$R/dienststand-$map-na.txt"
  if diff <(sed -n 1,6p "$voor") <(sed -n 1,6p "$R/dienststand-$map-na.txt") >/dev/null 2>&1; then
    echo "$(date +%T) dienstregels gelijk aan vooraf" >> "$log"
  else
    echo "$(date +%T) dienstregels wijken af van vooraf: JP" >> "$log"
  fi
}
