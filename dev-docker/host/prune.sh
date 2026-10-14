#!/usr/bin/env bash
# prune.sh — devdock (IDEA-258, spec §4.7). Leeftijdsgebaseerd opruimen van de dev-engine.
#   prune.sh [--dry-run] [--selftest]
# Geen `docker system prune`: die verwijdert álle gestopte containers ongeacht label of leeftijd. Containers verdwijnen
# uitsluitend in stap 1. Het script verwijdert dev-postgres, zijn netwerk en dev-postgres-data onder geen enkele voorwaarde.
# --dry-run gebruikt dezelfde kandidaatberekening, schrijft niets en print het JSON-object naar stdout.
# --selftest draait de kandidaatberekening op ingebouwde fixtures zonder docker aan te roepen.
# Een echte run schrijft ~/dev-docker/last-run.json (jq -n) en prune.log. Exit 0 = geen fouten, 1 = fouten of dev-postgres uit.
set -euo pipefail

DRY=0; SELFTEST=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1;;
    --selftest) SELFTEST=1;;
    *) echo "gebruik: prune.sh [--dry-run] [--selftest]" >&2; exit 2;;
  esac
done

DD=$(cd "$(dirname "$0")" && pwd)
DAY=86400

# Formats met $'…\t…': `docker volume|network inspect` leest een letterlijke \t niet als tab (gemeten tegen een echte engine).
# Kandidaatberekening in perl: BSD date kent geen -d en jq's fromdateiso8601 weigert +02:00 en "… +0200 CEST";
# perl (core Time::Local) draait identiek op max2 en op de Mac. Invoer: TSV op stdin. Uitvoer per regel:
#   C<TAB>label<TAB>actie-id      kandidaat
#   K<TAB>label<TAB>reden         bewaard, met reden
read -r -d '' CLASSIFY <<'PERL' || true
use strict; use warnings; use Time::Local qw(timegm);
my ($mode, $now, @files) = @ARGV; my $DAY = 86400;
sub epoch {
  my ($s) = @_;
  return undef unless defined $s;
  return undef unless $s =~ /^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:\.\d+)?\s*(Z|[+-]\d\d:?\d\d)?/;
  my ($y, $mo, $d, $h, $mi, $se, $tz) = ($1, $2, $3, $4, $5, $6, $7);
  return undef if $y < 1971;                                    # Go-nultijd 0001-01-01 en soortgelijke waarden
  my $e = eval { timegm($se, $mi, $h, $d, $mo - 1, $y) };
  return undef unless defined $e;
  if (defined $tz && $tz ne 'Z') { $tz =~ /^([+-])(\d\d):?(\d\d)$/; my $o = $2 * 3600 + $3 * 60; $e -= ($1 eq '+' ? $o : -$o); }
  return $e;
}
sub readset { my %s; for my $f (@_) { open(my $h, '<', $f) or next; while (<$h>) { chomp; $s{$_} = 1 if length } close $h } return \%s; }
my $inuse = readset($files[0] // '/dev/null'); my $prot = readset($files[1] // '/dev/null');
my %img; my @order;
sub aged {                                                      # bewaard-reden of undef (= oud genoeg)
  my ($created, $days, $label) = @_;
  my $e = epoch($created);
  return 'geen CreatedAt' unless defined $e;
  return "jonger dan $label dagen" if $now - $e < $days * $DAY;
  return undef;
}
while (my $l = <STDIN>) {
  chomp $l; next unless length $l;
  my @f = split /\t/, $l, -1;
  if ($mode eq 'containers' || $mode eq 'volumes') {
    my ($id, $name, $keep, $created) = $mode eq 'containers' ? @f[0, 1, 2, 3] : ($f[0], $f[0], $f[1], $f[2]);
    my $r;
    if ($name eq 'dev-postgres' || $name eq 'dev-postgres-data') { $r = (defined $keep && $keep eq 'true') ? 'dev.keep' : 'beschermd'; }
    elsif (defined $keep && $keep eq 'true') { $r = 'dev.keep'; }
    else { $r = aged($created, 7, 7); }
    print defined $r ? "K\t$name\t$r\n" : "C\t$name\t$name\n";
  } elsif ($mode eq 'images') {
    my ($id, $tag, $created) = @f[0, 1, 2];
    push @order, $id unless $img{$id};
    $img{$id}{tags} .= ($img{$id}{tags} ? ',' : '') . $tag; $img{$id}{created} //= $created;
  } elsif ($mode eq 'dbs') {
    my ($name, $created, $keep) = @f[0, 1, 2];
    my $r;
    if ($name =~ /^(postgres|template0|template1)$/ || $name =~ /^pg_/) { $r = 'denylist'; }
    elsif (defined $keep && $keep =~ /^(t|true)$/) { $r = 'dev.keep'; }
    elsif (!defined $created || $created !~ /^\d+$/) { $r = 'geen CreatedAt'; }
    elsif ($now - $created < 14 * $DAY) { $r = 'jonger dan 14 dagen'; }
    print defined $r ? "K\t$name\t$r\n" : "C\t$name\t$name\n";
  } elsif ($mode eq 'unknown') {
    my $name = $f[0];
    if ($name =~ /^(postgres|template0|template1)$/ || $name =~ /^pg_/) { print "K\t$name\tdenylist\n"; }
    else { print "K\t$name\tonbekend: wordt geregistreerd als prune:first-seen\n"; }
  } elsif ($mode eq 'networks') {
    my ($name, $n, $keep) = @f[0, 1, 2];
    if ($name =~ /^(bridge|host|none)$/) { print "K\t$name\tstandaardnetwerk\n"; }
    elsif (defined $keep && $keep eq 'true') { print "K\t$name\tdev.keep\n"; }
    elsif ($n > 0) { print "K\t$name\tin gebruik\n"; }
    else { print "C\t$name\t$name\n"; }
  }
}
for my $id (@order) {
  my $short = $id; $short =~ s/^sha256://; $short = substr($short, 0, 12);
  my $label = "$short $img{$id}{tags}";
  my $r;
  if ($inuse->{$id}) { $r = 'in gebruik'; }
  elsif ($prot->{$id}) { $r = 'standaardimage (images.txt)'; }
  else { $r = aged($img{$id}{created}, 7, 7); }
  print defined $r ? "K\t$label\t$r\n" : "C\t$label\t$id\n";
}
PERL

classify() { perl -e "$CLASSIFY" -- "$@"; }               # classify <mode> <now> [inuse-bestand protected-bestand]

# step_json <naam> <classificatie-bestand> <fouten-bestand>
step_json() {
  jq -Rn --arg name "$1" --rawfile errs "$3" '
    [inputs | split("\t")] as $r
    | {name: $name,
       candidates: [$r[] | select(.[0] == "C") | .[1]],
       kept: [$r[] | select(.[0] == "K") | {id: .[1], reason: .[2]}],
       errors: ($errs | split("\n") | map(select(length > 0)))}' <"$2"
}
# disk_json <totaal-bytes> <beschikbaar-bytes>
disk_json() {
  jq -n --argjson t "$1" --argjson a "$2" '
    {total_bytes: $t, avail_bytes: $a, avail_pct: (if $t > 0 then (($a * 1000 / $t) | floor / 10) else 0 end), warn_below_pct: 20}
    | .warning = (.avail_pct < .warn_below_pct)'
}
disk_warn_line() {                                          # print de WAARSCHUWING-regel als het disk-object dat vraagt
  local w pct
  w=$(jq -r '.warning' <<<"$1"); pct=$(jq -r '.avail_pct' <<<"$1")
  [ "$w" = true ] && printf 'WAARSCHUWING: %s %% vrij op /var/lib/docker (grens 20 %%)\n' "$pct"
  return 0
}

# ----------------------------------------------------------------------------------------------------------------
if [ "$SELFTEST" = 1 ]; then
  t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
  docker() { : >"$t/docker-aangeroepen"; echo "selftest: onverwachte docker-aanroep: $*" >&2; return 99; }
  NOW=$(perl -MTime::Local -e 'print timegm(0,0,12,14,9,2026)')
  fails=0; n=0
  expect() {                                                # expect <naam> <verwacht-bestand> <werkelijk-bestand>
    n=$(( n + 1 ))
    if diff <(sort "$2") <(sort "$3") >"$t/diff"; then echo "OK   $1"; else echo "FOUT $1"; cat "$t/diff"; fails=$(( fails + 1 )); fi
  }
  d20=$(( NOW - 20 * DAY )); d02=$(( NOW - 2 * DAY )); d30=$(( NOW - 30 * DAY ))

  printf '%s\t%s\t%s\t%s\n' c1 dev-postgres true '2026-01-01 00:00:00 +0000 UTC' c2 old-run '' '2026-10-01 10:00:00 +0200 CEST' \
    c3 new-run '' '2026-10-13 10:00:00 +0200 CEST' c4 kept-run true '2026-09-01 00:00:00 +0000 UTC' c5 nodate '' '' \
    c6 zero '' '0001-01-01 00:00:00 +0000 UTC' | classify containers "$NOW" | cut -f1,2,3 >"$t/got"
  printf 'K\tdev-postgres\tdev.keep\nC\told-run\told-run\nK\tnew-run\tjonger dan 7 dagen\nK\tkept-run\tdev.keep\nK\tnodate\tgeen CreatedAt\nK\tzero\tgeen CreatedAt\n' >"$t/exp"
  expect containers "$t/exp" "$t/got"

  printf '%s\t%s\t%s\n' v-nocreated '' '' v-old '' '2026-09-27T13:01:26+02:00' v-new '' '2026-10-13T13:01:26+02:00' \
    v-keep true '2026-09-01T00:00:00Z' v-novalue '<no value>' '<no value>' dev-postgres-data '' '2026-01-01T00:00:00Z' | classify volumes "$NOW" >"$t/got"
  printf 'K\tv-nocreated\tgeen CreatedAt\nC\tv-old\tv-old\nK\tv-new\tjonger dan 7 dagen\nK\tv-keep\tdev.keep\nK\tv-novalue\tgeen CreatedAt\nK\tdev-postgres-data\tbeschermd\n' >"$t/exp"
  expect volumes "$t/exp" "$t/got"

  printf 'sha256:aaa111111111111\n' >"$t/inuse"; printf 'sha256:ccc333333333333\n' >"$t/prot"
  printf '%s\t%s\t%s\n' sha256:aaa111111111111 inuse:1 '2026-01-01 00:00:00 +0000 UTC' sha256:bbb222222222222 old:1 '2026-08-01 00:00:00 +0000 UTC' \
    sha256:ccc333333333333 std:1 '2026-01-01 00:00:00 +0000 UTC' sha256:ddd444444444444 fresh:1 '2026-10-14 08:00:00 +0200 CEST' \
    sha256:eee555555555555 '<none>:<none>' '2026-07-01 00:00:00 +0000 UTC' sha256:bbb222222222222 old:2 '2026-08-01 00:00:00 +0000 UTC' \
    | classify images "$NOW" "$t/inuse" "$t/prot" >"$t/got"
  printf 'K\taaa111111111 inuse:1\tin gebruik\nC\tbbb222222222 old:1,old:2\tsha256:bbb222222222222\nK\tccc333333333 std:1\tstandaardimage (images.txt)\nK\tddd444444444 fresh:1\tjonger dan 7 dagen\nC\teee555555555 <none>:<none>\tsha256:eee555555555555\n' >"$t/exp"
  expect images "$t/exp" "$t/got"

  printf '%s\t%s\t%s\n' postgres 0 f pg_catalog 0 f proj_old "$d20" f proj_new "$d02" f proj_keep "$d30" t template0 0 f | classify dbs "$NOW" | cut -f1,2,3 >"$t/got"
  printf 'K\tpostgres\tdenylist\nK\tpg_catalog\tdenylist\nC\tproj_old\tproj_old\nK\tproj_new\tjonger dan 14 dagen\nK\tproj_keep\tdev.keep\nK\ttemplate0\tdenylist\n' >"$t/exp"
  expect databases "$t/exp" "$t/got"

  printf 'stray_db\npostgres\npg_foo\n' | classify unknown "$NOW" >"$t/got"
  printf 'K\tstray_db\tonbekend: wordt geregistreerd als prune:first-seen\nK\tpostgres\tdenylist\nK\tpg_foo\tdenylist\n' >"$t/exp"
  expect onbekende-databases "$t/exp" "$t/got"

  printf '%s\t%s\t%s\n' bridge 0 '' dev-docker_default 1 true old_net 0 '' busy_net 2 '' | classify networks "$NOW" >"$t/got"
  printf 'K\tbridge\tstandaardnetwerk\nK\tdev-docker_default\tdev.keep\nC\told_net\told_net\nK\tbusy_net\tin gebruik\n' >"$t/exp"
  expect netwerken "$t/exp" "$t/got"

  dj=$(disk_json 100 15); { echo "$dj" | jq -r '"warning=\(.warning) pct=\(.avail_pct)"'; disk_warn_line "$dj"; } >"$t/got"
  printf 'warning=true pct=15\nWAARSCHUWING: 15 %% vrij op /var/lib/docker (grens 20 %%)\n' >"$t/exp"
  expect schijf-15-procent "$t/exp" "$t/got"
  dj=$(disk_json 100 50); { echo "$dj" | jq -r '"warning=\(.warning) pct=\(.avail_pct)"'; disk_warn_line "$dj"; } >"$t/got"
  printf 'warning=false pct=50\n' >"$t/exp"
  expect schijf-50-procent "$t/exp" "$t/got"

  printf 'C\ta\ta\nK\tb\tin gebruik\n' >"$t/cl"; : >"$t/er"
  step_json test "$t/cl" "$t/er" | jq -c '[.name, .candidates, .kept[0].reason, .errors]' >"$t/got"
  printf '["test",["a"],"in gebruik",[]]\n' >"$t/exp"
  expect json-stap "$t/exp" "$t/got"

  n=$(( n + 1 ))
  if [ -e "$t/docker-aangeroepen" ]; then echo "FOUT geen docker-aanroep: docker is aangeroepen"; fails=$(( fails + 1 )); else echo "OK   geen docker-aanroep"; fi
  [ "$fails" = 0 ] && { echo "selftest: $n controles OK"; exit 0; }
  echo "selftest: $fails van $n controles FOUT"; exit 1
fi

# ----------------------------------------------------------------------------------------------------------------
export DOCKER_HOST=${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
NOW=$(date +%s); RAN_AT=$(date -u +%FT%TZ)
STEPS="$work/steps"; : >"$STEPS"; ANY_ERR=0
pg() { docker exec -i dev-postgres psql -U postgres -v ON_ERROR_STOP=1 -Atq "$@"; }
say() { echo "== $*"; }

# finish <naam>: voegt een stap toe aan het verslag uit $work/cl (classificatie) en $work/er (fouten)
finish() {
  step_json "$1" "$work/cl" "$work/er" | jq -c . >>"$STEPS"
  [ -s "$work/er" ] && ANY_ERR=1
  say "$1: $(grep -c '^C' "$work/cl" || true) kandidaat/kandidaten, $(grep -c '^K' "$work/cl" || true) bewaard"
  grep -E '^[CK]' "$work/cl" | awk -F'\t' '$1=="C"{print "   kandidaat: " $2} $1=="K"{print "   bewaard:   " $2 "  (" $3 ")"}' || true
  [ -s "$work/er" ] && sed 's/^/   FOUT: /' "$work/er"
  : >"$work/cl"; : >"$work/er"
}
err() { echo "$*" >>"$work/er"; }
: >"$work/cl"; : >"$work/er"

# 0. dev-postgres moet draaien; anders alleen stap 1
PG_UP=1
if [ -z "$(docker ps --filter name='^dev-postgres$' --filter status=running --format '{{.Names}}')" ]; then
  PG_UP=0; err "dev-postgres draait niet of bestaat niet: alleen stap 1 wordt uitgevoerd"; ANY_ERR=1
fi
[ "$PG_UP" = 1 ] && printf 'K\tdev-postgres\tdraait\n' >"$work/cl"
finish dev-postgres

# 1. wegwerpcontainers
docker ps -a --no-trunc --format $'{{.ID}}\t{{.Names}}\t{{.Label "dev.keep"}}\t{{.CreatedAt}}' | classify containers "$NOW" >"$work/cl"
if [ "$DRY" = 0 ]; then
  while IFS=$'\t' read -r kind _ target; do
    [ "$kind" = C ] || continue
    { docker stop -t 10 "$target" >/dev/null 2>&1 || true; docker rm "$target" >/dev/null 2>&1; } || err "container $target niet verwijderd"
  done <"$work/cl"
fi
finish containers

if [ "$PG_UP" = 1 ]; then
  # 2. volumes (dangling)
  vols=$(docker volume ls -q -f dangling=true)
  if [ -n "$vols" ]; then
    # shellcheck disable=SC2086  # bewust: één argument per volumenaam
    docker volume inspect --format $'{{.Name}}\t{{index .Labels "dev.keep"}}\t{{.CreatedAt}}' $vols | classify volumes "$NOW" >"$work/cl"
  fi
  if [ "$DRY" = 0 ]; then
    while IFS=$'\t' read -r kind _ target; do
      [ "$kind" = C ] || continue
      docker volume rm "$target" >/dev/null 2>&1 || err "volume $target niet verwijderd"
    done <"$work/cl"
  fi
  finish volumes

  # 3. databases (register + onbekende)
  pg -F $'\t' -c "SELECT name, extract(epoch from created_at)::bigint, keep FROM devmeta.databases" | classify dbs "$NOW" >"$work/cl" || err "register niet te lezen"
  pg -c "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname NOT IN (SELECT name FROM devmeta.databases)" | classify unknown "$NOW" >>"$work/cl" || err "pg_database niet te lezen"
  if [ "$DRY" = 0 ]; then
    while IFS=$'\t' read -r kind label target; do
      if [ "$kind" = C ]; then
        printf '%s\n' "SELECT format('DROP DATABASE IF EXISTS %I WITH (FORCE)', :'n') \\gexec" | pg -v n="$target" >/dev/null || err "database $target niet gedropt"
        printf '%s\n' "DELETE FROM devmeta.databases WHERE name = :'n'" | pg -v n="$target" >/dev/null || err "registerrij $target niet verwijderd"
      elif [ "$kind" = K ] && [ "$target" = "onbekend: wordt geregistreerd als prune:first-seen" ]; then
        printf '%s\n' "INSERT INTO devmeta.databases (name, created_by) VALUES (:'n', 'prune:first-seen') ON CONFLICT (name) DO NOTHING" | pg -v n="$label" >/dev/null || err "database $label niet geregistreerd"
      fi
    done <"$work/cl"
  fi
  finish databases

  # 4. images, buildcache, netwerken
  ids=$(docker ps -aq)
  : >"$work/inuse"; : >"$work/prot"
  # shellcheck disable=SC2086
  [ -n "$ids" ] && docker inspect --format '{{.Image}}' $ids >"$work/inuse"
  missing=""
  while IFS= read -r ref; do
    [ -n "$ref" ] || continue
    docker image inspect --format '{{.Id}}' "$ref" >>"$work/prot" 2>/dev/null || missing+=" $ref"
    # Containerd-image-store (Docker 29): de tag verwijst naar de index-manifest, de digest-referentie naar de platform-manifest;
    # `image ls` toont ze als twee ID's. Beide beschermen, anders wordt de index als "ongebruikt" kandidaat (gemeten op de Mac).
    [[ $ref == *@* ]] && { docker image inspect --format '{{.Id}}' "${ref%@*}" >>"$work/prot" 2>/dev/null || true; }
  done <"$DD/images.txt"
  [ -n "$missing" ] && echo "   niet lokaal aanwezig (niet gepulld):$missing"
  docker image ls --no-trunc --format $'{{.ID}}\t{{.Repository}}:{{.Tag}}\t{{.CreatedAt}}' | classify images "$NOW" "$work/inuse" "$work/prot" >"$work/cl"
  if [ "$DRY" = 0 ]; then
    while IFS=$'\t' read -r kind _ target; do
      [ "$kind" = C ] || continue
      docker rmi "$target" >/dev/null 2>&1 || err "image $target niet verwijderd"
    done <"$work/cl"
  fi
  finish images

  if [ "$DRY" = 1 ]; then
    est=$(docker buildx du 2>/dev/null | tail -n1 || true)
    printf 'C\tbuildcache ouder dan 168h (schatting: %s)\tbuildcache\n' "${est:-onbekend}" >"$work/cl"
  else
    docker builder prune -af --filter until=168h >/dev/null 2>&1 || err "builder prune mislukt"
    printf 'K\tbuildcache\topgeruimd: alles ouder dan 168h\n' >"$work/cl"
  fi
  finish buildcache

  netids=$(docker network ls -q)
  # shellcheck disable=SC2086
  docker network inspect --format $'{{.Name}}\t{{len .Containers}}\t{{index .Labels "dev.keep"}}' $netids | classify networks "$NOW" >"$work/cl"
  [ "$DRY" = 0 ] && { docker network prune -f --filter 'label!=dev.keep=true' >/dev/null 2>&1 || err "network prune mislukt"; }
  finish netwerken

  # 5. standaardimages
  if [ "$DRY" = 1 ]; then
    for r in $missing; do printf 'C\t%s\tpull\n' "$r"; done >"$work/cl"
  else
    bash "$DD/pull-images.sh" >/dev/null 2>"$work/pull.err" || err "pull-images.sh: $(tail -n1 "$work/pull.err")"
    printf 'K\tstandaardimages\tgepulld\n' >"$work/cl"
  fi
  finish standaardimages

  # 6. backups ouder dan 30 dagen
  if [ -d "$DD/backups" ]; then
    while IFS= read -r f; do printf 'C\t%s\t%s\n' "$f" "$f"; done < <(find "$DD/backups" -type f -mtime +30 -print) >"$work/cl"
    if [ "$DRY" = 0 ]; then
      while IFS=$'\t' read -r kind _ target; do
        [ "$kind" = C ] || continue
        rm -f -- "$target" || err "backup $target niet verwijderd"
      done <"$work/cl"
    fi
  fi
  finish backups
fi

# 7. verslag
if size_avail=$(df -B1 --output=size,avail /var/lib/docker 2>/dev/null | tail -n1) && [ -n "$size_avail" ]; then
  read -r size avail <<<"$size_avail"; DISK=$(disk_json "$size" "$avail")
else
  DISK=$(jq -n '{total_bytes: null, avail_bytes: null, avail_pct: null, warn_below_pct: 20, warning: null}')
  echo "FOUT: df op /var/lib/docker mislukt"; ANY_ERR=1
fi
disk_warn_line "$DISK"
REPORT=$(jq -s --arg ran_at "$RAN_AT" --argjson disk "$DISK" --argjson dry "$([ "$DRY" = 1 ] && echo true || echo false)" '{ran_at: $ran_at, dry_run: $dry, steps: ., disk: $disk}' "$STEPS")
if [ "$DRY" = 1 ]; then
  echo "--- verslag (dry-run: niets geschreven, geen registerrij, niets verwijderd)"; echo "$REPORT"
else
  jq -n --argjson r "$REPORT" '$r | del(.dry_run)' >"$DD/last-run.json"
  { echo "$RAN_AT prune klaar: fouten=$ANY_ERR"; } >>"$DD/prune.log"
  echo "verslag: $DD/last-run.json"
fi
exit "$ANY_ERR"
