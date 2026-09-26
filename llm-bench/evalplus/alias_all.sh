#!/usr/bin/env bash
# Name-corrected MBPP+ for every model directory of a run (see alias_fix.py). Offline.
#   ./alias_all.sh /var/tmp/llm-bench/evalplus-<datum>
set -euo pipefail
cd "$(dirname "$0")"
out=$(realpath "$1")
img=llm-bench-evalplus:0.3.1
docker build -q -t "$img" . >/dev/null
for d in "$out"/*/; do
  m=$(basename "$d")
  [ -f "$d/mbpp.raw-sanitized.jsonl" ] || continue
  docker run --rm --network none -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$out:/work" -w /work "$img" sh -c \
    "python /opt/alias_fix.py $m && rm -f $m/mbpp.aliased_eval_results.json \
     && evalplus.evaluate --dataset mbpp --samples $m/mbpp.aliased.jsonl --i-just-wanna-run > $m/mbpp.aliased.eval.log 2>&1"
  echo "$m done"
done
