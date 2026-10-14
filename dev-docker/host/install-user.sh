#!/usr/bin/env bash
# install-user.sh — als devdock, via een echte SSH-login (spec §4.2). Niet via sudo -u of su: daar ontbreken de
# sessie en de D-Bus en faalt dockerd-rootless-setuptool.sh.
#   rsync -a --delete dev-docker/host/ max2-dev:dev-docker-src/ && ssh max2-dev bash dev-docker-src/install-user.sh
# Geen argumenten. Idempotent: een bestaand .env en een bestaand volume blijven ongemoeid; per stap CHANGED of SAME.
set -euo pipefail

SRC=$(cd "$(dirname "$0")" && pwd)             # ~/dev-docker-src (bronnen); de draaiende stack staat in ~/dev-docker
DST=$HOME/dev-docker
UNITS=$HOME/.config/systemd/user
[ "$(id -un)" = devdock ] || { echo "FOUT: alleen als devdock (echte SSH-login)" >&2; exit 1; }
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
if [ ! -S "$XDG_RUNTIME_DIR/bus" ]; then
  echo "FOUT: geen user-manager/D-Bus op $XDG_RUNTIME_DIR; vereist een echte SSH-login en linger (bootstrap.sh)" >&2; exit 1
fi
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}

changes=0
changed() { echo "CHANGED $*"; changes=$(( changes + 1 )); }
same()    { echo "SAME $*"; }
# put <bron> <doel> <mode>: schrijft alleen als de inhoud of de mode afwijkt
put() {
  if [ -f "$2" ] && [ ! -L "$2" ] && cmp -s "$1" "$2" && [ "$(stat -c %a "$2")" = "$3" ]; then same "$2"; else install -m "$3" "$1" "$2"; changed "$2"; return 0; fi
}

# 1. rootless engine
if [ -S "$XDG_RUNTIME_DIR/docker.sock" ] && systemctl --user is-active --quiet docker; then
  same "rootless docker.service actief"
else
  command -v dockerd-rootless-setuptool.sh >/dev/null || { echo "FOUT: dockerd-rootless-setuptool.sh ontbreekt (docker-ce-rootless-extras)" >&2; exit 1; }
  dockerd-rootless-setuptool.sh install
  changed "rootless engine geïnstalleerd"
fi
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
# De Docker-SSH-route (`docker system dial-stdio`) draait in een niet-interactieve shell zonder profiel: de context
# staat in ~/.docker/config.json en werkt daar wel, DOCKER_HOST uit een profiel niet.
# Met DOCKER_HOST gezet meldt de CLI altijd context "default": de controle draait daarom zonder die variabele.
if [ "$(env -u DOCKER_HOST docker context show 2>/dev/null)" = rootless ]; then same "docker context rootless is standaard"; else docker context use rootless >/dev/null; changed "docker context use rootless"; fi

# 2. mappen en bestanden uit ~/dev-docker-src
mkdir -p "$DST/init" "$DST/backups" "$UNITS"
compose_changed=0
cmp -s "$SRC/compose.yml" "$DST/compose.yml" 2>/dev/null || compose_changed=1
put "$SRC/compose.yml" "$DST/compose.yml" 644
put "$SRC/init/01-roles.sh" "$DST/init/01-roles.sh" 755      # uitvoerbaar: de entrypoint voert het uit in plaats van het te sourcen
put "$SRC/init/02-devmeta.sql" "$DST/init/02-devmeta.sql" 644
put "$SRC/prune.sh" "$DST/prune.sh" 755
put "$SRC/pull-images.sh" "$DST/pull-images.sh" 755
put "$SRC/images.txt" "$DST/images.txt" 644
for u in dev-postgres.service dev-docker-prune.service dev-docker-prune.timer; do put "$SRC/systemd/$u" "$UNITS/$u" 644; done

# 3. .env alleen als hij ontbreekt; de waarden worden nooit getoond
if [ ! -e "$DST/.env" ]; then
  ( umask 077; { printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 24)"; printf 'DEV_PASSWORD=%s\n' "$(openssl rand -hex 24)"; } >"$DST/.env" )
  changed "$DST/.env aangemaakt (0600, waarden niet getoond)"
else
  [ "$(stat -c %a "$DST/.env")" = 600 ] || { chmod 0600 "$DST/.env"; changed ".env naar 0600"; }
  grep -q '^POSTGRES_PASSWORD=.' "$DST/.env" && grep -q '^DEV_PASSWORD=.' "$DST/.env" || { echo "FOUT: .env mist POSTGRES_PASSWORD of DEV_PASSWORD" >&2; exit 1; }
  same "$DST/.env bestaat (ongemoeid)"
fi

# 4. standaardimages vóór de eerste compose up (de unit heeft maar 180 s startruimte)
bash "$DST/pull-images.sh"

# 5. units en start
systemctl --user daemon-reload
for u in dev-postgres.service dev-docker-prune.timer; do
  if systemctl --user is-enabled --quiet "$u" 2>/dev/null; then same "enable $u"; else systemctl --user enable "$u" >/dev/null 2>&1; changed "enable $u"; fi
done
if ! systemctl --user is-active --quiet dev-postgres.service; then
  systemctl --user start dev-postgres.service; changed "start dev-postgres.service"
elif [ "$compose_changed" = 1 ]; then
  systemctl --user restart dev-postgres.service; changed "restart dev-postgres.service (compose.yml gewijzigd)"
else
  same "dev-postgres.service actief"
fi
systemctl --user is-active --quiet dev-docker-prune.timer || { systemctl --user start dev-docker-prune.timer; changed "start dev-docker-prune.timer"; }

# 6. wachten op healthy (max. 120 s)
st=""
for _ in $(seq 1 60); do
  st=$(docker ps --filter name=dev-postgres --format '{{.Status}}')
  [[ $st == *"(healthy)"* ]] && break
  sleep 2
done
echo "dev-postgres: ${st:-niet gevonden}"
[[ $st == *"(healthy)"* ]] || { echo "FOUT: dev-postgres is niet healthy; journalctl --user -u dev-postgres.service" >&2; exit 1; }
if [ "$changes" = 0 ]; then echo "GEEN WIJZIGINGEN"; else echo "KLAAR: $changes wijziging(en)"; fi
