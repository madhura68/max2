# pgvector/pgvector:pg17 — entrypoint-fragment (IDEA-258, plan taak 1 stap 4)

**Datum:** 2026-10-14 (Mac, Docker Desktop-engine; alleen het image is opgehaald, er is niets op max2 aangeraakt).
**Image:** `pgvector/pgvector:pg17@sha256:cd4ccfdaf62cbfeb5c6ee19ef0dd663406d4ed740c320b324d016a90e85385b3` — `linux/amd64`, PostgreSQL 17.11 (Debian 17.11-1.pgdg12+2), `uname -m` in de container: `x86_64`.

**Afwijking 7 op het plan (digest):** het plan noemt `sha256:215ae4d47393a980e9ef7ff7760f7dad53ec3e84bceb9fbd45cef34e50b5ba0f` als amd64-digest. Gemeten op de uitvoerdag (`docker buildx imagetools inspect pgvector/pgvector:pg17 --raw | jq -c '.manifests[] | {digest, platform}'`) is dat de **linux/arm64**-manifest; de **linux/amd64**-manifest is `sha256:cd4ccfdaf62cbfeb5c6ee19ef0dd663406d4ed740c320b324d016a90e85385b3`. max2 is x86_64, dus `compose.yml` en `images.txt` pinnen de amd64-digest. De digest van de tag-index (`sha256:ac08538c…a75d` op de uitvoerdag) is bewust niet gepind: die verandert bij elke herpublicatie van de tag.

```
docker run --rm --platform linux/amd64 --entrypoint sed pgvector/pgvector:pg17@sha256:cd4ccfdaf62cbfeb5c6ee19ef0dd663406d4ed740c320b324d016a90e85385b3 -n 260,290p /usr/local/bin/docker-entrypoint.sh
```

Uitvoer, met regelnummers toegevoegd (regels 260–290 van `/usr/local/bin/docker-entrypoint.sh`):

```
260			}; then
261				OLD_DATABASES+=( '/var/lib/postgresql/data (unused mount/volume)' )
262			fi
263		fi
264	}
265	
266	# append POSTGRES_HOST_AUTH_METHOD to pg_hba.conf for "host" connections
267	# all arguments will be passed along as arguments to `postgres` for getting the value of 'password_encryption'
268	pg_setup_hba_conf() {
269		# default authentication method is md5 on versions before 14
270		# https://www.postgresql.org/about/news/postgresql-14-released-2318/
271		if [ "$1" = 'postgres' ]; then
272			shift
273		fi
274		local auth
275		# check the default/configured encryption and use that as the auth method
276		auth="$(postgres -C password_encryption "$@")"
277		: "${POSTGRES_HOST_AUTH_METHOD:=$auth}"
278		{
279			printf '\n'
280			if [ 'trust' = "$POSTGRES_HOST_AUTH_METHOD" ]; then
281				printf '# warning trust is enabled for all connections\n'
282				printf '# see https://www.postgresql.org/docs/17/auth-trust.html\n'
283			fi
284			printf 'host all all all %s\n' "$POSTGRES_HOST_AUTH_METHOD"
285		} >> "$PGDATA/pg_hba.conf"
286	}
287	
288	# start socket-only postgresql server for setting up or running scripts
289	# all arguments will be passed along as arguments to `postgres` (via pg_ctl)
290	docker_temp_server_start() {
```

**Waarneming (bevestigt spec §4.5):** `pg_setup_hba_conf` begint op regel 268; de regel `host all all all %s` (de `printf` met `$POSTGRES_HOST_AUTH_METHOD`) staat op regel 284, dus binnen 266–285. Volgorde in `_main` (gemeten met `grep -n`): `docker_init_database_dir` → `pg_setup_hba_conf` (regel 355) → `docker_temp_server_start` (360) → `docker_setup_db` (362) → `docker_process_init_files /docker-entrypoint-initdb.d/*` (363) → `docker_temp_server_stop` (365). Een init-script dat uitvoerbaar is (`-x`) wordt als proces uitgevoerd, een niet-uitvoerbaar `*.sh` wordt gesourced (regels 180–190); `init/01-roles.sh` is daarom 0755.

**Lokale praktijkproef van de init-scripts (Mac, Docker Desktop, wegwerpcontainer met testwachtwoorden, 14-10-2026):** actief `pg_hba.conf` na de init: `host all postgres all reject`, `local all all trust`, beide loopback-regels `scram-sha-256`, replicatie-loopback `scram-sha-256`, `host all all all scram-sha-256`. Rol `dev`: `LOGIN`, `CREATEDB`, geen superuser; `vector` staat in `template1` en dus in een nieuwe database. Over TCP: fout wachtwoord → `password authentication failed`; leeg wachtwoord → `no password supplied`; `postgres` met het juiste wachtwoord → `pg_hba.conf rejects connection`; `dev` met het juiste wachtwoord maakt een database en ziet `vector`; `dev` kan geen rol met superuser maken. De testwachtwoorden stonden niet in de containerlogs. Dit bewijst het init-pad van het gepinde image, niet het gedrag op max2.
