#!/usr/bin/env bash
# init/01-roles.sh — draait alleen bij een leeg volume (docker-entrypoint-initdb.d), uitvoerbaar gemaakt zodat de
# entrypoint het als proces uitvoert en niet sourced (anders lekt `set -euo pipefail` in de entrypoint).
# Volgorde in de entrypoint (gepind image, evidence/dev-docker/pgvector-pg17-entrypoint.md): initdb → pg_setup_hba_conf
# (voegt `host all all all <methode>` toe) → tijdelijke server (alleen unix-socket) → dit script → stop → definitieve start.
# Daarom is een reload niet nodig: de definitieve server leest het herschreven pg_hba.conf.
set -euo pipefail
[ -n "${DEV_PASSWORD:-}" ] || { echo "FOUT: DEV_PASSWORD ontbreekt of is leeg" >&2; exit 1; }
psql=(psql -v ON_ERROR_STOP=1 --no-psqlrc --username "$POSTGRES_USER")

# Clientrol: geen superuser. Het wachtwoord gaat via \getenv naar psql, nooit via argv.
"${psql[@]}" --dbname postgres <<'SQL'
\getenv dev_pw DEV_PASSWORD
CREATE ROLE dev LOGIN CREATEDB PASSWORD :'dev_pw';
SQL

# pgvector in template1: elke nieuwe database krijgt de extensie zonder superuser.
"${psql[@]}" --dbname template1 -c 'CREATE EXTENSION IF NOT EXISTS vector'

# pg_hba.conf: postgres nooit over TCP (eerste match wint; docker exec gebruikt de unix-socket met `local … trust`),
# loopback van trust naar scram-sha-256 (ook een verbinding die de poortdriver als loopback presenteert vraagt een wachtwoord).
hba=$PGDATA/pg_hba.conf
tmp=$(mktemp)
{
  echo 'host all postgres all reject'
  sed -E 's#^(host[[:space:]].*(127\.0\.0\.1/32|::1/128)[[:space:]]+)trust[[:space:]]*$#\1scram-sha-256#' "$hba"
} >"$tmp"
cat "$tmp" >"$hba"                              # behoud eigenaar en mode van pg_hba.conf
rm -f "$tmp"

if ! grep -qx 'host all postgres all reject' "$hba"; then echo "FOUT: reject-regel ontbreekt in pg_hba.conf" >&2; exit 1; fi
if grep -qE '^host[[:space:]].*(127\.0\.0\.1/32|::1/128)[[:space:]]+trust' "$hba"; then echo "FOUT: loopback staat nog op trust" >&2; exit 1; fi
if ! grep -qE '^local[[:space:]]+all[[:space:]]+all[[:space:]]+trust' "$hba"; then echo "FOUT: local all all trust ontbreekt" >&2; exit 1; fi
echo "01-roles.sh: rol dev, vector in template1 en pg_hba.conf gereed"
