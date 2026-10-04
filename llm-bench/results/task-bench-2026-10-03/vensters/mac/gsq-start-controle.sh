#!/bin/bash
# M7 Taak 10, op max2: de controles vóór het nachtvenster, dan de dienststand vooraf. Exit 0 = mag starten.
R=/home/janpeter/m7-runs/task-bench-2026-10-03
fail() { echo "controle faalt: $*"; exit 1; }
[ ! -e "$R/gsq" ] && [ ! -e "$R/gsq.sid" ] || fail "gsq of gsq.sid bestaat al"
tmux has-session -t "=m7-gsq" 2>/dev/null && fail "tmux-sessie m7-gsq bestaat al"
python3 - <<'PY' || fail "taakconfig wijkt af van worker.json"
import json, sys
a = json.load(open("/etc/agent-harness/worker.json"))["task"]
b = json.load(open("/home/janpeter/Development/max2-m7/llm-bench/task_bench/task-config.json"))
sys.exit(0 if a == b else 1)
PY
ollama list | awk '{print $1}' | grep -qx 'qwen3.8-gsq-rco:27b-iq3_s-text' || fail "gsq-model ontbreekt in ollama list"
[ "$(docker ps -aq --filter name=^harness- | wc -l)" = 0 ] || fail "er zijn al harness-containers"
[ "$(git -C /home/janpeter/Development/agent-harness-m7 rev-parse HEAD)" = 24aa096ee5f9c01384426bb8357817de67eddf55 ] || fail "bench-clone niet op 24aa096"
[ "$(git -C /home/janpeter/Development/max2-m7 rev-parse HEAD)" = cb99e3db1952ab877367371671125448f0f77a5b ] || fail "max2-clone niet op cb99e3d"
sh "$R/dienststand.sh" "$R/dienststand-gsq-voor.txt" || fail "dienststand"
echo "controles ok; worker $(systemctl is-active agent-harness-worker)"
