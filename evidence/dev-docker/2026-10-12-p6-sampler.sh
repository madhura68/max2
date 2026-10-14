#!/usr/bin/env bash
# M52-P6: read-only 26h budget sampler (N=2). Changes nothing on the host. Afgeleid van ~/m52-u2/sampler.sh.
D="$HOME/m52-p6"; DUR=93600
exec 9>"$D/sampler.lock"; flock -n 9 || { echo "sampler already running"; exit 0; }
echo $$ > "$D/sampler.pid"
start=$(date +%s); end=$((start+DUR)); date -u -d @$start +%FT%TZ > "$D/start.utc"; date -u -d @$end +%FT%TZ > "$D/end.utc"
DR=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null); DR=${DR:-/var/lib/docker}
echo "ts,load1,load5,load15,cpu_busy_pct,mem_avail_kb,swap_used_kb,gpu_util_pct,gpu_mem_mib,df_root_used_pct,df_docker_used_pct" > "$D/metrics.csv"
while [ "$(date +%s)" -lt "$end" ]; do
  ts=$(date -u +%FT%TZ)
  read -r l1 l5 l15 _ < /proc/loadavg
  ma=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
  su=$(awk '/SwapTotal/{t=$2}/SwapFree/{f=$2}END{print t-f}' /proc/meminfo)
  busy=$(vmstat 1 5 | tail -1 | awk '{print 100-$15}')
  gpu=$(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
  d1=$(df --output=pcent / | tail -1 | tr -d ' %'); d2=$(df --output=pcent "$DR" 2>/dev/null | tail -1 | tr -d ' %')
  echo "$ts,$l1,$l5,$l15,$busy,$ma,$su,${gpu:-,},$d1,$d2" >> "$D/metrics.csv"
  sleep 55
done
date -u +%FT%TZ > "$D/done.utc"; rm -f "$D/sampler.pid"
