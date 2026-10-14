#!/usr/bin/env bash
# proof-checks.sh — root, read-only (IDEA-258, spec §4.4/§9). Alle sudo-leescontroles in één run.
#   sudo bash proof-checks.sh --uid <uid> [--wait-listener <sec>] [--wait-tick <sec>]
# BEWUST zonder `set -e` (enige uitzondering op de regel): elk blok eindigt met `|| true`, `grep -c` zonder treffer telt als 0,
# elke nc-status wordt eerst in een variabele gevangen. Uitvoer: stdout én een bestand in de root-eigen map /var/tmp/dd-proof/.
# Afsluiting: SUMMARY aan het bestand, chmod 0644, op stdout `OUT=<pad>` en als laatste de SUMMARY-regel.
# Exit 0 alleen als alles klopt en geen gevraagde wachtoptie op timeout eindigde; anders exit 1.
set -u

UIDARG=""; WAIT_L=0; WAIT_T=0
while [ $# -gt 0 ]; do
  case "$1" in
    --uid) UIDARG=${2-}; shift 2;;
    --wait-listener) WAIT_L=${2-}; shift 2;;
    --wait-tick) WAIT_T=${2-}; shift 2;;
    *) echo "gebruik: proof-checks.sh --uid <uid> [--wait-listener <sec>] [--wait-tick <sec>]" >&2; exit 2;;
  esac
done
[[ $UIDARG =~ ^[0-9]+$ ]] || { echo "FOUT: --uid <uid> is verplicht (numeriek)" >&2; exit 2; }
[[ $WAIT_L =~ ^[0-9]+$ ]] && [[ $WAIT_T =~ ^[0-9]+$ ]] || { echo "FOUT: wachttijden moeten numeriek zijn" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "FOUT: root vereist" >&2; exit 1; }

# Uitvoermap: eerst aanmaken zonder iets bestaands aan te raken, dan controleren, dan pas schrijven. /var/tmp is sticky maar
# wereld-schrijfbaar: devdock zou de map of een symlink vooraf kunnen aanmaken. Geen install -d/chown/chmod op een bestaand pad
# (die volgen een symlink): mkdir zonder -p faalt met EEXIST en wijzigt niets.
DIR=/var/tmp/dd-proof
mkdir -m 0755 "$DIR" 2>/dev/null || true
if [ -L "$DIR" ] || [ ! -d "$DIR" ] || [ "$(stat -c %u "$DIR")" != 0 ] || [ "$(stat -c %a "$DIR")" != 755 ]; then
  echo "FOUT-proofdir: $DIR is geen door root aangemaakte gewone map met mode 755; niets gewijzigd" >&2; exit 1
fi
out=$(mktemp "$DIR/proof-XXXXXX") || { echo "FOUT-mktemp" >&2; exit 1; }

emit()  { printf '%s\n' "$*" | tee -a "$out"; }
block() { local name=$1; shift; emit "## $name"; { "$@" 2>&1 || true; } | tee -a "$out"; }

R1=(-p tcp --dport 55432 -m conntrack --ctstate NEW ! -i enp4s0 -j DROP)
R2=(-i enp4s0 -p tcp --dport 55432 -m conntrack --ctstate NEW ! -s 192.168.0.0/24 -j DROP)
chain_ok() {                                                # dezelfde eis als dev-docker-firewall.sh
  local c
  iptables -C dev-docker-in "${R1[@]}" 2>/dev/null && iptables -C dev-docker-in "${R2[@]}" 2>/dev/null \
    && iptables -C dev-docker-in -j RETURN 2>/dev/null \
    && c=$(iptables -S dev-docker-in) && [ "$(grep -c '^-A ' <<<"$c")" -eq 3 ] \
    && [ "$(awk '$1 == "-A" {last=$0} END {print last}' <<<"$c")" = "-A dev-docker-in -j RETURN" ]
}
listener_state() {                                          # none | lan-only | other
  local l
  l=$(ss -ltn 2>/dev/null | awk '$4 ~ /:55432$/ {print $4}')
  if [ -z "$l" ]; then echo none; return; fi
  if [ "$(grep -vc '^192\.168\.0\.158:55432$' <<<"$l")" = 0 ]; then echo lan-only; else echo other; fi
}
nc_rc() {                                                   # 0 | 1 | FOUT (uitvoeringsfout van nc zelf)
  local rc
  command -v nc >/dev/null 2>&1 || { echo FOUT; return; }
  nc -z -w2 "$1" 55432 >/dev/null 2>&1; rc=$?
  case $rc in 0|1) echo "$rc";; *) echo FOUT;; esac
}
# Alle 'Finished'-tijdstempels (short-iso-precise) van een unit in deze boot; ook een gefaalde run telt als afgerond.
# Matcht op unitnaam én op Description (afhankelijk van StatusUnitFormat logt systemd de naam of de beschrijving).
unit_runs() {
  local u=$1 d
  d=$(systemctl show "$u.service" -p Description --value 2>/dev/null)
  journalctl -b -u "$u.service" -o short-iso-precise --no-pager 2>/dev/null \
    | awk -v u="$u" -v d="$d" '(index($0, "Finished ") && (index($0, u ".service") || (d != "" && index($0, "Finished " d)))) || index($0, u ".service: Failed with result") {print $1}'
}

# --- wachten op de listener (vóór het meten) ---------------------------------------------------------------------
listener_timeout=0
if [ "$WAIT_L" -gt 0 ]; then
  end=$(( $(date +%s) + WAIT_L ))
  while [ "$(listener_state)" = none ]; do
    if [ "$(date +%s)" -ge "$end" ]; then listener_timeout=1; break; fi
    sleep 2
  done
fi

# --- wachten op de eerste timer-tick ná de boot-runs van dsh/owui ------------------------------------------------
tick=skipped
if [ "$WAIT_T" -gt 0 ]; then
  active=()
  for u in dsh-firewall owui-firewall; do systemctl is-active --quiet "$u.timer" 2>/dev/null && active+=("$u"); done
  if [ "${#active[@]}" -eq 0 ]; then
    tick=n/a-dsh
  else
    end=$(( $(date +%s) + WAIT_T )); ref=""; tick=pending
    for u in "${active[@]}"; do                              # per unit de EERSTE run in deze boot; de referentie is de latere van die twee
      ts=""
      while [ -z "$ts" ]; do
        ts=$(unit_runs "$u" | head -n 1)
        [ -n "$ts" ] && break
        if [ "$(date +%s)" -ge "$end" ]; then tick=timeout; break; fi
        sleep 3
      done
      [ "$tick" = timeout ] && break
      if [ -z "$ref" ] || [[ $ts > $ref ]]; then ref=$ts; fi
    done
    if [ "$tick" != timeout ]; then
      tick=timeout
      while :; do
        if [ -n "$(unit_runs dev-docker-firewall | awk -v r="$ref" '$1 > r {print; exit}')" ]; then tick=ok; break; fi
        if [ "$(date +%s)" -ge "$end" ]; then break; fi
        sleep 3
      done
    fi
  fi
fi

# --- metingen ---------------------------------------------------------------------------------------------------
block "ufw status verbose" ufw status verbose
block "ufw status numbered" ufw status numbered
block "iptables-save -t filter" iptables-save -t filter
inp=$(iptables -S INPUT 2>&1)
first=$(awk '$1 == "-A" {print; exit}' <<<"$inp")
emit "## INPUT: eerste -A-regel"; emit "$first"
block "iptables -S dev-docker-in" iptables -S dev-docker-in
jumps=$(grep -c -- '-j dev-docker-in' <<<"$inp" || true)
emit "## INPUT: aantal sprongen naar dev-docker-in"; emit "$jumps"
testrule=$(grep -c dd-recovery-test <<<"$inp" || true)
emit "## INPUT: aantal dd-recovery-test-regels"; emit "$testrule"
ss_l=$(ss -ltn 2>&1 | grep 55432 || true)
emit "## ss -ltn | grep 55432"; emit "$ss_l"
block "ss -tn 'sport = :55432'" ss -tn 'sport = :55432'
nc_ts=$(nc_rc 100.102.8.64); nc_lan=$(nc_rc 192.168.0.158)
emit "## nc"
if [ "$nc_ts" = FOUT ]; then emit "nc-ts FOUT"; else emit "nc-ts rc=$nc_ts"; fi
if [ "$nc_lan" = FOUT ]; then emit "nc-lan FOUT"; else emit "nc-lan rc=$nc_lan"; fi
block "journalctl -t dev-docker-firewall -b" journalctl -t dev-docker-firewall -b --no-pager -o short-iso
block "journalctl dsh/owui/dev-docker firewall units -b" journalctl -b -u dsh-firewall.service -u owui-firewall.service -u dev-docker-firewall.service -o short-iso --no-pager
block "systemctl show user-$UIDARG.slice" systemctl show "user-$UIDARG.slice" -p MemoryMax -p MemorySwapMax -p CPUQuotaPerSecUSec -p TasksMax
cg=/sys/fs/cgroup/user.slice/user-$UIDARG.slice
for f in memory.max memory.peak memory.events; do block "$cg/$f" cat "$cg/$f"; done
emit "## $cg/memory.stat (anon)"; emit "$(grep '^anon ' "$cg/memory.stat" 2>&1 || true)"
block "docker ps -a (productie-engine)" env -u DOCKER_HOST docker ps -a --no-trunc --format '{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.CreatedAt}}'
block "docker images (productie-engine)" env -u DOCKER_HOST docker images --digests --format '{{.ID}}\t{{.Repository}}:{{.Tag}}\t{{.Digest}}'
block "df -B1 /var/lib/docker /home" df -B1 /var/lib/docker /home

# --- samenvatting ------------------------------------------------------------------------------------------------
jf=no; [[ $first == *" -j dev-docker-in" ]] && jf=yes
chain=bad; chain_ok && chain=ok
listener=$(listener_state); [ "$listener_timeout" = 1 ] && listener=timeout
summary="SUMMARY jump_first=$jf chain=$chain jumps=$jumps testrule=$testrule listener=$listener nc_ts=$nc_ts nc_lan=$nc_lan tick=$tick"
echo "$summary" >>"$out"
chmod 0644 "$out"
echo "OUT=$out"
echo "$summary"
if [ "$jf" = yes ] && [ "$chain" = ok ] && [ "$jumps" = 1 ] && [ "$testrule" = 0 ] && [ "$listener" = lan-only ] \
   && [ "$nc_ts" = 1 ] && [ "$nc_lan" = 1 ] && { [ "$tick" = ok ] || [ "$tick" = n/a-dsh ] || [ "$tick" = skipped ]; }; then
  exit 0
fi
exit 1
