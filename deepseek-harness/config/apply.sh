#!/usr/bin/env bash
# Copy the profile patch into the running dsh container's data volume (read on the next request).
set -euo pipefail
docker exec -i -u dsh dsh sh -c 'cat > /data/profiles/web/cordis.patch.yml' < "$(dirname "$0")/cordis.patch.yml"
docker exec dsh head -3 /data/profiles/web/cordis.patch.yml
