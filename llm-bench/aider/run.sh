#!/usr/bin/env bash
# Aider polyglot benchmark against local Ollama models (PBI-1, ST-002 T-6/T-7).
#   ./run.sh <exercises-name> <model> [model...]
# <exercises-name> is a directory under $RUNS (e.g. polyglot-subset30, own-tasks).
# Runs on the sandbox network from ./network.sh (Ollama reachable, nothing else).
# Thinking off, num_ctx 32768, diff edit format, 2 tries, 1 thread.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
RUNS=${RUNS:-/var/tmp/llm-bench/aider-runs}
AIDER_SRC=${AIDER_SRC:-/var/tmp/llm-bench/aider}   # Aider-AI/aider checkout the image was built from
IMG=aider-benchmark:5dc9490-warm
NET=llm-bench-internal
EDIT_FORMAT=${EDIT_FORMAT:-diff}
NUM_CTX=${NUM_CTX:-32768}
ex=$1; shift
gw=$(docker network inspect $NET -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}')
[ -d "$RUNS/$ex" ] || { echo "missing $RUNS/$ex" >&2; exit 1; }

for model in "$@"; do
  tag=$(echo "$model" | tr '/:' '__')
  cfg="$RUNS/settings-$tag.yml"
  cat > "$cfg" <<YAML
- name: ollama_chat/$model
  edit_format: $EDIT_FORMAT
  use_temperature: 0
  extra_params:
    num_ctx: $NUM_CTX
    think: false
YAML
  echo "== $model $ex $(date +%T)"
  docker run --rm --network $NET --memory=12g --memory-swap=12g \
    -v "$AIDER_SRC:/aider" -v "$RUNS:/benchmarks" \
    -e AIDER_DOCKER=1 -e AIDER_BENCHMARK_DIR=/benchmarks -e OLLAMA_API_BASE="http://$gw:11434" \
    "$IMG" python3 benchmark/benchmark.py "$ex--$tag" --new \
      --model "ollama_chat/$model" --edit-format "$EDIT_FORMAT" \
      --read-model-settings "/benchmarks/settings-$tag.yml" \
      --exercises-dir "$ex" --threads 1 --tries 2 \
    > "$RUNS/$ex--$tag.log" 2>&1 || echo "!! benchmark exited non-zero for $model (see $RUNS/$ex--$tag.log)"
  latest=$(ls -td "$RUNS"/*--"$ex--$tag" | head -1)
  docker run --rm --network none -v "$AIDER_SRC:/aider" -v "$RUNS:/benchmarks" -e AIDER_DOCKER=1 \
    -e AIDER_BENCHMARK_DIR=/benchmarks "$IMG" python3 benchmark/benchmark.py --stats "/benchmarks/$(basename "$latest")" \
    2>/dev/null | tee "$RUNS/$ex--$tag.stats.txt" | grep -E 'pass_rate|well_formed|test_cases|seconds_per_case|error_outputs|num_malformed|exhausted' || true
done
echo "== done $(date +%T)"
