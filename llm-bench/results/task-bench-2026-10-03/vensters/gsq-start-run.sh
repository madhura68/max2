#!/bin/bash
# M7 Taak 10, op max2, na een schone M4-stop: containers stoppen volgens de dienststand, dan run, nazorg en vangnet in tmux.
R=/home/janpeter/m7-runs/task-bench-2026-10-03; voor=$R/dienststand-gsq-voor.txt
containers=$(awk '/^## containers/{f=1;next} /^## /{f=0} f && NF' "$voor")
for c in $containers; do
  if [ "$c" = tei-gpu ]; then docker compose -f /srv/apps/tei/docker-compose.yml stop; else docker stop "$c"; fi
done
echo "worker: $(systemctl is-active agent-harness-worker)"
if sid=$(tmux new-session -d -P -F '#{pane_pid}' -s m7-gsq "sh $R/gsq.sh") && [ -n "$sid" ]; then
  echo "$sid" > "$R/gsq.sid"; echo "run gestart: sid=$sid $(date -u +%T)Z"
else
  echo "start mislukt: er draait niets, terug naar de dienststand vooraf"
  for c in $containers; do
    if [ "$c" = tei-gpu ]; then docker compose -f /srv/apps/tei/docker-compose.yml start; else docker start "$c"; fi
  done
  sudo -n systemctl start agent-harness-worker; echo "worker: $(systemctl is-active agent-harness-worker); JP"; exit 1
fi
tmux new-session -d -s m7-gsq-nazorg "bash $R/gsq-nazorg.sh" && echo "nazorg gestart"
tmux new-session -d -s m7-gsq-vangnet "bash $R/gsq-vangnet.sh" && echo "vangnet gestart"
