#!/usr/bin/env bash
# bootstrap.sh — root op max2 (IDEA-258, spec §4.1). Per scp naar ~/dd-run/ en `ssh -t … sudo bash …`.
#   bootstrap.sh --pubkey-file <pad> --floor-gib <X> --series '<GiB>:<bron>' [--series …] [--preflight-only] [--check-args]
# Exit 0 = ok, 2 = ongeldige invoer, 3 = preflight/gate rood, 1 = andere fout (bv. geen root, apt faalt).
#   --check-args      alleen invoervalidatie en budgetberekening (draait ook op de Mac, geen root nodig)
#   --preflight-only  alle read-only controles op max2, muteert niets
# Uitvoer: X_eff=<GiB> budget_gib=<n> marge_gib=<n>, per controle OK / ROOD <reden>, per mutatie CHANGED / SAME.
# Idempotent: een tweede run op een correct ingerichte host wijzigt niets (alleen SAME-regels).
set -euo pipefail

bad() { echo "FOUT: $*" >&2; exit 2; }
HINT="gebruik een punt als decimaalteken (12.0, niet 12,0)"

PUBKEY=""; FLOOR=""; SERIES=(); PREFLIGHT_ONLY=0; CHECK_ARGS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --pubkey-file) [ $# -ge 2 ] || bad "--pubkey-file mist een waarde"; PUBKEY=$2; shift 2;;
    --floor-gib)   [ $# -ge 2 ] || bad "--floor-gib mist een waarde: $HINT"; FLOOR=$2; shift 2;;
    --series)      [ $# -ge 2 ] || bad "--series mist een waarde"; SERIES+=("$2"); shift 2;;
    --preflight-only) PREFLIGHT_ONLY=1; shift;;
    --check-args)  CHECK_ARGS=1; shift;;
    *) bad "onbekende optie: $1";;
  esac
done

# --- invoervalidatie (vóór iedere mutatie) -----------------------------------------------------------------
NUM='^[0-9]+(\.[0-9]+)?$'
[ -n "$FLOOR" ] || bad "--floor-gib is verplicht: $HINT"
[[ $FLOOR =~ $NUM ]] || bad "ongeldige --floor-gib '$FLOOR': $HINT"
[ "${#SERIES[@]}" -gt 0 ] || bad "--series '<GiB>:<bron>' is verplicht (minstens één reeks van ≥ 24 uur)"

# decimaal (punt) → micro-GiB (1e-6); mode up = naar boven afronden (conservatief voor de vloer), down = naar beneden
to_micro() {
  local v=$1 mode=$2 int frac="" rest="" n
  int=${v%%.*}
  [[ $v == *.* ]] && frac=${v#*.}
  rest=${frac:6}; frac=${frac:0:6}
  while [ "${#frac}" -lt 6 ]; do frac="${frac}0"; done
  n=$(( 10#$int * 1000000 + 10#$frac ))
  if [ "$mode" = up ] && [[ $rest =~ [1-9] ]]; then n=$(( n + 1 )); fi
  echo "$n"
}
# micro-GiB → tekst; $2 = minimaal aantal decimalen (1 → "12.0", 0 → "8")
fmt() {
  local n=$1 min=$2 neg="" fs
  if [ "$n" -lt 0 ]; then neg=-; n=$(( -n )); fi
  fs=$(printf '%06d' $(( n % 1000000 )))
  while [[ $fs == *0 ]]; do fs=${fs%0}; done
  [ "$min" -ge 1 ] && [ -z "$fs" ] && fs=0
  if [ -n "$fs" ]; then echo "$neg$(( n / 1000000 )).$fs"; else echo "$neg$(( n / 1000000 ))"; fi
}

SERIES_MICRO=(); SERIES_SRC=()
for s in "${SERIES[@]}"; do
  [[ $s == *:* ]] || bad "ongeldige --series '$s': verwacht <GiB>:<bron> ($HINT)"
  g=${s%%:*}; src=${s#*:}                       # splitsen op de eerste dubbele punt; de bron is vrije tekst
  [[ $g =~ $NUM ]] || bad "ongeldige --series '$s': GiB-waarde '$g' is geen decimaal getal: $HINT"
  [ -n "${src//[[:space:]]/}" ] || bad "ongeldige --series '$s': de bron ontbreekt"
  SERIES_MICRO+=("$(to_micro "$g" down)"); SERIES_SRC+=("$g: $src")
done

FLOOR_MIN=10800000                               # U4-rode lijn 10,8 GiB: ondergrens van elke keuze (spec §8.2)
x=$(to_micro "$FLOOR" up)
x_eff=$(( x > FLOOR_MIN ? x : FLOOR_MIN ))
lowest=${SERIES_MICRO[0]}
for v in "${SERIES_MICRO[@]}"; do [ "$v" -lt "$lowest" ] && lowest=$v; done
raw=$(( lowest - x_eff )); [ "$raw" -lt 0 ] && raw=0
cap=8000000; b=$(( raw < cap ? raw : cap ))
budget=$(( b / 500000 * 500000 ))                # afgerond omlaag op 0,5 GiB, nooit omhoog
marge=$(( lowest - x_eff - budget ))

echo "X_eff=$(fmt "$x_eff" 1) budget_gib=$(fmt "$budget" 0) marge_gib=$(fmt "$marge" 0)"
for s in "${SERIES_SRC[@]}"; do echo "SERIE $s"; done
if [ "$budget" -lt 2000000 ]; then
  echo "ROOD budget onder 2 GiB: laagste MemAvailable $(fmt "$lowest" 0) GiB min X_eff $(fmt "$x_eff" 1) GiB; geen caps verlagen, dit is een NO-GO (CLAUDE.md)"
  exit 3
fi
echo "OK invoer en budget"
[ "$CHECK_ARGS" = 1 ] && exit 0

# --- vanaf hier root op max2 ---------------------------------------------------------------------------------
[ "$(id -u)" = 0 ] || { echo "FOUT: root vereist (sudo bash …)" >&2; exit 1; }
if [ "$PREFLIGHT_ONLY" = 0 ]; then
  [ -n "$PUBKEY" ] || bad "--pubkey-file is verplicht"
fi
if [ -n "$PUBKEY" ]; then
  [ -r "$PUBKEY" ] || bad "pubkey-bestand niet leesbaar: $PUBKEY"
  grep -q 'PRIVATE KEY' "$PUBKEY" && bad "dit lijkt een private sleutel; geef het .pub-bestand"
  [ "$(grep -c . "$PUBKEY")" = 1 ] || bad "pubkey-bestand moet precies één regel bevatten"
  grep -qE '^(ssh-(ed25519|rsa)|ecdsa-sha2-nistp[0-9]+|sk-[a-z0-9@.-]+) ' "$PUBKEY" || bad "pubkey-bestand heeft geen herkenbaar publiek-sleutelformaat"
fi
SRC=$(cd "$(dirname "$0")" && pwd)
UID_DD=""; if getent passwd devdock >/dev/null; then UID_DD=$(id -u devdock); fi

reds=0
ok()   { echo "OK $*"; }
rood() { echo "ROOD $*"; reds=$(( reds + 1 )); }

# --- 1. preflight (read-only, faalt vóór iedere mutatie) ---------------------------------------------------
[ "$(uname -m)" = x86_64 ] && ok "architectuur x86_64 (image-digest is linux/amd64)" || rood "architectuur $(uname -m): de gepinde image-digest is linux/amd64"

ur=$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null || echo absent)
if [ "$ur" = 1 ] && [ ! -e /etc/apparmor.d/rootlesskit ]; then
  rood "AppArmor: apparmor_restrict_unprivileged_userns=1 en /etc/apparmor.d/rootlesskit ontbreekt"
else
  ok "AppArmor (apparmor_restrict_unprivileged_userns=$ur, profiel $([ -e /etc/apparmor.d/rootlesskit ] && echo aanwezig || echo n.v.t.))"
fi

dpkg -s docker-ce-rootless-extras >/dev/null 2>&1 && ok "docker-ce-rootless-extras geïnstalleerd" || rood "docker-ce-rootless-extras ontbreekt"

if [ "$(stat -fc %T /sys/fs/cgroup 2>/dev/null)" = cgroup2fs ]; then
  # `systemctl show user@.service` (template) werkt niet ("neither a valid invocation ID nor unit name", gemeten op max2): vraag een instantie.
  dc=""
  for u in ${UID_DD:+"$UID_DD"} ${SUDO_UID:+"$SUDO_UID"} 1000; do
    dc=$(systemctl show "user@$u.service" -p DelegateControllers --value 2>/dev/null || true)
    [ -n "$dc" ] && break
  done
  miss=""; for c in cpu memory pids; do [[ " $dc " == *" $c "* ]] || miss+=" $c"; done
  [ -z "$miss" ] && ok "cgroup v2, DelegateControllers van user@<uid>.service: $dc" || rood "DelegateControllers van user@<uid>.service mist:$miss (heeft: ${dc:-leeg})"
else
  rood "cgroup v2 niet actief"
fi

us=$(ufw status verbose 2>/dev/null || true)
if grep -q '^Status: active' <<<"$us" && grep -q 'Default: deny (incoming)' <<<"$us"; then ok "ufw actief, Default: deny (incoming)"; else rood "ufw niet actief of niet default-deny voor incoming"; fi

sd=$(sshd -T 2>/dev/null || true)
if [ -z "$sd" ]; then
  rood "sshd -T gaf geen uitvoer"
elif grep -qiE '^(allowusers|allowgroups) ' <<<"$sd"; then
  rood "sshd heeft AllowUsers/AllowGroups: controleer dat devdock niet wordt uitgesloten"
else
  ok "sshd zonder AllowUsers/AllowGroups"
fi

# subuid/subgid: 200000:65536 vrij voor devdock en zonder overlap met andere gebruikers
for f in /etc/subuid /etc/subgid; do
  if awk -F: '$1 != "devdock" && $2 < 265536 && ($2 + $3) > 200000 {bad=1} END {exit !bad}' "$f" 2>/dev/null; then
    rood "$f: een andere gebruiker overlapt 200000:65536"
  else
    ok "$f: 200000:65536 vrij van overlap"
  fi
done
if [ -n "$UID_DD" ]; then
  dd_line=$(getent passwd devdock)
  [ "$(cut -d: -f6,7 <<<"$dd_line")" = /home/devdock:/bin/bash ] && ok "bestaande devdock: home en shell kloppen" || rood "bestaande devdock heeft afwijkende home/shell: $(cut -d: -f6,7 <<<"$dd_line")"
  [ "$(id -nG devdock)" = devdock ] && ok "bestaande devdock zit alleen in de eigen groep" || rood "bestaande devdock zit in extra groepen: $(id -nG devdock)"
else
  ok "gebruiker devdock bestaat nog niet"
fi

echo "## iptables-save -t filter (momentopname voor het bewijsbestand)"
iptables-save -t filter || rood "iptables-save -t filter mislukt"

if [ "$reds" -gt 0 ]; then echo "PREFLIGHT ROOD ($reds)"; exit 3; fi
echo "PREFLIGHT GROEN"
[ "$PREFLIGHT_ONLY" = 1 ] && exit 0

# --- mutaties: elke stap meldt CHANGED of SAME --------------------------------------------------------------
changes=0
changed() { echo "CHANGED $*"; changes=$(( changes + 1 )); }
same()    { echo "SAME $*"; }

# put <bronbestand> <doel> <mode>: schrijft alleen als de inhoud afwijkt
put() {
  if [ -f "$2" ] && [ ! -L "$2" ] && cmp -s "$1" "$2" && [ "$(stat -c %a "$2")" = "$3" ]; then same "$2"; else install -m "$3" -o root -g root "$1" "$2"; changed "$2"; fi
}
tmpd=$(mktemp -d); trap 'rm -rf "$tmpd"' EXIT

# 2. pakketten
need=""; for p in uidmap slirp4netns; do dpkg -s "$p" >/dev/null 2>&1 || need+=" $p"; done
if [ -n "$need" ]; then
  export DEBIAN_FRONTEND=noninteractive
  # shellcheck disable=SC2086  # bewust woordsplitsing over de lijst met pakketnamen
  apt-get install -y $need </dev/null
  changed "pakketten:$need"
else
  same "pakketten uidmap slirp4netns"
fi

# 3. gebruiker, subid-ranges, authorized_keys
if [ -z "$UID_DD" ]; then
  useradd --create-home --home-dir /home/devdock --shell /bin/bash --user-group devdock
  UID_DD=$(id -u devdock); changed "gebruiker devdock (uid $UID_DD)"
else
  same "gebruiker devdock (uid $UID_DD)"
fi
for kind in uid gid; do
  f=/etc/sub$kind
  if [ "$(grep -c '^devdock:' "$f")" = 1 ] && grep -qx 'devdock:200000:65536' "$f"; then
    same "$f devdock:200000:65536"
  else
    while IFS=: read -r _ st ct; do usermod "--del-sub${kind}s" "$st-$(( st + ct - 1 ))" devdock; done < <(grep '^devdock:' "$f" || true)
    usermod "--add-sub${kind}s" 200000-265535 devdock
    changed "$f devdock:200000:65536"
  fi
done
sshdir=/home/devdock/.ssh
if [ -e "$sshdir" ] && { [ -L "$sshdir" ] || [ ! -d "$sshdir" ]; }; then echo "FOUT: $sshdir is geen gewone map" >&2; exit 1; fi
if [ ! -d "$sshdir" ]; then mkdir -m 0700 "$sshdir"; chown devdock:devdock "$sshdir"; changed "$sshdir"; else same "$sshdir"; fi
ak=$sshdir/authorized_keys
if [ -L "$ak" ]; then echo "FOUT: $ak is een symlink" >&2; exit 1; fi
if [ -f "$ak" ] && grep -qxFf "$PUBKEY" "$ak"; then
  same "authorized_keys bevat de sleutel"
else
  cat "$PUBKEY" >>"$ak"; chown devdock:devdock "$ak"; chmod 0600 "$ak"; changed "authorized_keys + sleutel"
fi

# 4. slice-drop-in, firewallscript en -units; pas daarna linger
membytes=$(( budget / 500000 * 536870912 ))
dropdir=/etc/systemd/system/user-$UID_DD.slice.d
mkdir -p "$dropdir"
sed "s/__MEMORYMAX__/$membytes/" "$SRC/systemd/50-dev-docker.conf" >"$tmpd/50.conf"
sed "s/__UID__/$UID_DD/g" "$SRC/systemd/dev-docker-firewall.service" >"$tmpd/fw.service"
chg_before=$changes
put "$tmpd/50.conf" "$dropdir/50-dev-docker.conf" 644
put "$SRC/dev-docker-firewall.sh" /usr/local/sbin/dev-docker-firewall.sh 755
put "$tmpd/fw.service" /etc/systemd/system/dev-docker-firewall.service 644
put "$SRC/systemd/dev-docker-firewall.timer" /etc/systemd/system/dev-docker-firewall.timer 644
[ "$changes" -gt "$chg_before" ] && systemctl daemon-reload
for u in dev-docker-firewall.timer dev-docker-firewall.service; do
  if ! systemctl is-enabled --quiet "$u" 2>/dev/null; then systemctl enable "$u" >/dev/null 2>&1; changed "enable $u"; else same "enable $u"; fi
done
if ! systemctl is-active --quiet dev-docker-firewall.timer; then systemctl start dev-docker-firewall.timer; changed "start dev-docker-firewall.timer"; else same "dev-docker-firewall.timer actief"; fi
inp=$(iptables -S INPUT)                         # eerst vangen, dan lezen: geen SIGPIPE onder pipefail
first=$(awk '$1 == "-A" {print; exit}' <<<"$inp")
if [ "$changes" -gt "$chg_before" ] || [[ $first != *" -j dev-docker-in" ]]; then
  systemctl start dev-docker-firewall.service; changed "dev-docker-firewall.service gestart"
else
  same "sprong staat op INPUT-positie 1"
fi
if [ ! -e /var/lib/systemd/linger/devdock ]; then loginctl enable-linger devdock; changed "linger devdock"; else same "linger devdock"; fi
systemctl show "user-$UID_DD.slice" -p MemoryMax -p MemorySwapMax -p CPUQuotaPerSecUSec -p TasksMax
[ -r "/sys/fs/cgroup/user.slice/user-$UID_DD.slice/memory.max" ] && echo "memory.max=$(cat "/sys/fs/cgroup/user.slice/user-$UID_DD.slice/memory.max")" || echo "memory.max: slice nog niet actief"

# 5. ufw-regel
if ufw status | grep -q '55432/tcp.*ALLOW.*192\.168\.0\.0/24'; then
  same "ufw-regel 55432/tcp vanaf 192.168.0.0/24"
else
  ufw allow from 192.168.0.0/24 to any port 55432 proto tcp comment 'dev-postgres (IDEA-258)'
  changed "ufw-regel 55432/tcp vanaf 192.168.0.0/24"
fi

if [ "$changes" = 0 ]; then echo "GEEN WIJZIGINGEN (uid=$UID_DD MemoryMax=$membytes)"; else echo "KLAAR: $changes wijziging(en) (uid=$UID_DD MemoryMax=$membytes)"; fi
