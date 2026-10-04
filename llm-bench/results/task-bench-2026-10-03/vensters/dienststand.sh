#!/bin/sh
# Dienststand op max2 (Vensterprocedure M6). Gebruik: sh dienststand.sh <uitvoerbestand>
{
  echo "## agent-harness-worker"; systemctl is-active agent-harness-worker
  echo "## containers (tei-gpu, open-webui, dsh)"; docker ps --format '{{.Names}}' | grep -E '^(tei-gpu|open-webui|dsh)$' | sort
  echo "## gpu"; nvidia-smi --query-gpu=memory.used,memory.total --format=csv
  echo "## api/ps"; curl -s 127.0.0.1:11434/api/ps; echo
} > "$1"
