#!/usr/bin/env bash
# Offline test for crashloop-watch.sh: fake docker + captured mail, no network.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
t="$(mktemp -d)"; trap 'rm -rf "$t"' EXIT
fail() { echo "FAIL: $*"; exit 1; }

# Fake docker reads "$t/containers": name status restarts health
cat > "$t/docker" <<'EOF'
#!/usr/bin/env bash
db="$(dirname "$0")/containers"
case "$1" in
  ps) awk '$2=="running"||$2=="restarting"{print $1}' "$db" ;;
  inspect) awk -v n="${@: -1}" '$1==n{printf "%s\t%s\t%s\n",$2,$3,($4=="-"?"":$4)}' "$db" ;;
esac
EOF
chmod +x "$t/docker"
cat > "$t/mail" <<EOF
#!/usr/bin/env bash
cat >> "$t/mails"; echo "---END---" >> "$t/mails"
EOF
chmod +x "$t/mail"

run() {
  : > "$t/mails"
  STATE_DIR="$t/state" CONFIG=/dev/null MAIL_TO=test@example DOCKER="$t/docker" \
    MAIL_CMD="$t/mail" HOST_LABEL=test NOW_OVERRIDE= bash "$here/crashloop-watch.sh" >/dev/null
}
mails() { grep -c -- '---END---' "$t/mails" || true; }

# 1. baseline: healthy fleet, parked stack exited -> no mail
printf '%s\n' "worker running 0 healthy" "parked exited 0 -" > "$t/containers"
run; [ "$(mails)" = 0 ] || fail "baseline should not mail"

# 2. crash loop -> one alarm mail naming the worker, not the parked container
printf '%s\n' "worker restarting 40 -" "parked exited 0 -" > "$t/containers"
run; [ "$(mails)" = 1 ] || fail "loop should mail once"
grep -q 'CRASHLOOP' "$t/mails" && grep -q 'worker: status=restarting' "$t/mails" || fail "alarm content"
grep -q parked "$t/mails" && fail "parked container must be ignored"

# 3. still looping within REMIND_S -> no duplicate mail
printf '%s\n' "worker restarting 80 -" > "$t/containers"
run; [ "$(mails)" = 0 ] || fail "no duplicate within remind window"

# 4. recovered -> recovery mail
printf '%s\n' "worker running 80 healthy" > "$t/containers"
run; [ "$(mails)" = 1 ] && grep -q 'recovered' "$t/mails" || fail "recovery mail"

# 5. restart jump while running (between checks) -> alarm
printf '%s\n' "worker running 84 healthy" > "$t/containers"
run; grep -q '+4 restarts' "$t/mails" || fail "restart jump alarm"

# 6. unhealthy -> alarm (after recovery of #5 first)
printf '%s\n' "worker running 84 healthy" > "$t/containers"; run
printf '%s\n' "worker running 84 unhealthy" > "$t/containers"
run; grep -q 'health=unhealthy' "$t/mails" || fail "unhealthy alarm"

# 7. recreated container (count reset) with small count -> no alarm
printf '%s\n' "worker running 84 healthy" > "$t/containers"; run
printf '%s\n' "worker running 1 healthy" > "$t/containers"
run; grep -q CRASHLOOP "$t/mails" && fail "recreate with 1 restart must not alarm"

echo "PASS: 7 scenarios"
