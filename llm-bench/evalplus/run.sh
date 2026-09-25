#!/usr/bin/env bash
# EvalPlus HumanEval+ and MBPP+ for Ollama models (PBI-1, ST-002 T-5).
#   ./run.sh <outdir> <model> [model...]
# Generation runs with --network host (HTTP to Ollama on loopback only, no code execution);
# sanitize + evaluate execute model code and run with --network none.
set -euo pipefail
cd "$(dirname "$0")"
out=$(realpath -m "$1"); shift
img=llm-bench-evalplus:0.3.1
docker build -q -t "$img" . >/dev/null
mkdir -p "$out"
run() { docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$out:/work" "$@"; }

for model in "$@"; do
  dir=$(echo "$model" | tr '/:' '__')
  for ds in humaneval mbpp; do
    echo "== $model $ds gen $(date +%T)"
    run --network host "$img" python /opt/gen.py --model "$model" --dataset "$ds" --out "/work/$dir"
    echo "== $model $ds eval $(date +%T)"
    run --network none "$img" sh -c "evalplus.sanitize --samples $dir/$ds.raw.jsonl >/dev/null 2>&1 \
      && evalplus.evaluate --dataset $ds --samples $dir/$ds.raw-sanitized.jsonl --i-just-wanna-run \
         > $dir/$ds.eval.log 2>&1" || echo "!! $model $ds evaluation failed, see $dir/$ds.eval.log"
    grep -E -A1 "^$ds|^pass@1" "$out/$dir/$ds.eval.log" | tee "$out/$dir/$ds.score.txt" || true
  done
done
echo "== done $(date +%T)"
