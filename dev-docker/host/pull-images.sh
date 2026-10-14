#!/usr/bin/env bash
# pull-images.sh — devdock (IDEA-258, spec §4.8). Pullt de standaardimages uit images.txt voor linux/amd64
# en faalt luid bij de eerste pull-fout (geen stille gedeeltelijke set).
set -euo pipefail
dir=$(cd "$(dirname "$0")" && pwd)
[ -r "$dir/images.txt" ] || { echo "FOUT: $dir/images.txt ontbreekt" >&2; exit 1; }
n=0
while IFS= read -r img; do
  [ -n "$img" ] || continue
  echo "pull $img"
  docker pull --platform linux/amd64 "$img" >/dev/null || { echo "FOUT: pull mislukt: $img" >&2; exit 1; }
  n=$(( n + 1 ))
done <"$dir/images.txt"
echo "images gepulld: $n"
