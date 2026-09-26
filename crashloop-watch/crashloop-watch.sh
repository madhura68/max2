#!/usr/bin/env bash
# crashloop-watch — mail within minutes when a container crash-loops (ISS-11).
#
# The daily health report caught the 2026-09-21 worker loop, but only once a
# day: the fleet was down ~2.5 days. This runs every 10 min and mails when a
# container is restarting, its RestartCount jumped, or it is unhealthy.
# One mail per incident (reminder every REMIND_S), plus a mail on recovery.
# Stopped containers are ignored on purpose (parked stacks, one-shots).
#
# Env (all optional): STATE_DIR, CONFIG (MAIL_FROM/MAIL_TO), THRESHOLD,
# REMIND_S, HOST_LABEL, DOCKER (binary, for tests), MAIL_CMD (for tests).
set -euo pipefail

STATE_DIR="${STATE_DIR:-$HOME/.local/state/crashloop-watch}"
CONFIG="${CONFIG:-/opt/server-health/conf/config.env}"
THRESHOLD="${THRESHOLD:-3}"          # restarts since the previous run
REMIND_S="${REMIND_S:-21600}"        # re-mail a persisting incident every 6 h
HOST_LABEL="${HOST_LABEL:-$(hostname)}"
DOCKER="${DOCKER:-docker}"
MAIL_CMD="${MAIL_CMD:-msmtp --read-recipients}"

# shellcheck disable=SC1090
[ -r "$CONFIG" ] && . "$CONFIG"
MAIL_FROM="${MAIL_FROM:-crashloop-watch@$HOST_LABEL}"
: "${MAIL_TO:?MAIL_TO missing (set it in $CONFIG)}"

mkdir -p "$STATE_DIR"
STATE="$STATE_DIR/state.tsv"         # name <TAB> restarts <TAB> alarmed_at (0 = ok)
touch "$STATE"
NOW="$(date +%s)"
NEW="$(mktemp)"
trap 'rm -f "$NEW"' EXIT

declare -A prev_restarts prev_alarm
while IFS=$'\t' read -r n r a; do
  [ -n "$n" ] || continue
  prev_restarts[$n]=$r; prev_alarm[$n]=$a
done < "$STATE"

alarms=() recovered=()
while read -r name; do
  [ -n "$name" ] || continue
  IFS=$'\t' read -r status restarts health < <(
    "$DOCKER" inspect -f '{{.State.Status}}{{"\t"}}{{.RestartCount}}{{"\t"}}{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$name" 2>/dev/null
  ) || continue
  last="${prev_restarts[$name]:-$restarts}"
  delta=$(( restarts - last ))
  (( delta < 0 )) && delta=$restarts   # container recreated: count restarts since then

  reason=""
  if [ "$status" = restarting ]; then reason="status=restarting"
  elif (( delta >= THRESHOLD )); then reason="+$delta restarts since last check"
  elif [ "$health" = unhealthy ]; then reason="health=unhealthy"
  fi

  alarmed="${prev_alarm[$name]:-0}"
  if [ -n "$reason" ]; then
    if (( alarmed == 0 || NOW - alarmed >= REMIND_S )); then
      alarms+=("$name: $reason (RestartCount=$restarts, status=$status)")
      alarmed=$NOW
    fi
  elif (( alarmed != 0 )); then
    recovered+=("$name: ok again (status=$status${health:+, health=$health}, RestartCount=$restarts)")
    alarmed=0
  fi
  printf '%s\t%s\t%s\n' "$name" "$restarts" "$alarmed" >> "$NEW"
done < <("$DOCKER" ps -a --filter status=running --filter status=restarting --format '{{.Names}}')

mv "$NEW" "$STATE"
trap - EXIT

send() {  # subject, lines...
  local subject="$1"; shift
  {
    echo "From: $MAIL_FROM"
    echo "To: $MAIL_TO"
    echo "Subject: $subject"
    echo "Content-Type: text/plain; charset=UTF-8"
    echo
    printf '%s\n' "$@"
    echo
    echo "-- crashloop-watch on $HOST_LABEL; logs: docker logs <name>, journalctl -u crashloop-watch"
  } | $MAIL_CMD
}

if (( ${#alarms[@]} )); then
  printf 'ALARM %s\n' "${alarms[@]}"
  send "[$HOST_LABEL] CRASHLOOP: ${#alarms[@]} container(s)" "${alarms[@]}"
fi
if (( ${#recovered[@]} )); then
  printf 'RECOVERED %s\n' "${recovered[@]}"
  send "[$HOST_LABEL] crashloop recovered: ${#recovered[@]} container(s)" "${recovered[@]}"
fi
exit 0
