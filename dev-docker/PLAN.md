# Dev-Docker op max2 voor de Mac (IDEA-258) — implementatieplan

> **Voor agentische uitvoerders:** dit plan wordt na dubbel GO en JP-akkoord gematerialiseerd als Scrum4Me-taken (sprint → PBI → story → taken). Elke taak hieronder is zelfstandig uitvoerbaar; de taak-ID's uit de ceremonie komen in het reviewrecord. Uitvoering alleen op opdracht van JP.

**Status:** concept, revisie 1 (14-10-2026). **Auteur:** mac:claude (Claude Fable 5.1) in opdracht van JP.
**Spec:** `dev-docker/SPEC.md` revisie 11 (dubbel GO op revisie 9; JP-besluit §12 op 14-10-2026; revisie 11 = hostadres-correctie, zie "Afwijkingen van de spec"). **Grill:** ProductDoc `GRILLS/idea-258-grill`. **Reviewrecords:** `docs/reviews/2026-10-14-idea-258-dev-docker-spec-review-record.md` (spec) en `docs/reviews/2026-10-14-idea-258-dev-docker-plan-review-record.md` (dit plan).

**Doel:** één bestaande PostgreSQL-integratietest (`npm test` van de s4m-queue-repo) slaagt vanaf de Mac tegen een database op `max2`, aangemaakt via de skill `max2-docker`, met Docker Desktop afgesloten; niets op de productie-engine is aangeraakt.

**Architectuur:** aparte rootless Docker-engine onder `devdock` op max2 (user-slice met `MemoryMax` 8 GiB), bereikbaar via `docker --context max2-dev` (SSH); één vaste `dev-postgres` gebonden aan `192.168.0.158:55432`, met een eigen `INPUT`-keten als LAN-grens; databases per taak via de skill; wekelijkse leeftijdsgebaseerde prune. Spec §3.

**Tech stack:** Docker CE 29.9 rootless (rootlesskit 3.2, slirp4netns), systemd 259 (user-units, slice-drop-in), iptables/ufw, PostgreSQL 17.11 (`pgvector/pgvector:pg17`), bash, Node 26 + vitest (s4m-queue-tests), Homebrew-Docker-CLI op de Mac.

## Globale beperkingen (uit de spec en CLAUDE.md; gelden voor elke taak)

- **Geen secrets in Git, evidence of Scrum4Me.** Postgres-wachtwoorden ontstaan op max2 (`openssl rand -hex 24`), leven alleen in `/home/devdock/dev-docker/.env` (0600) en de container-env; nooit op de Mac-schijf, nooit in transcripten of bewijsbestanden; agents gebruiken nooit `db url --reveal`, `docker … inspect dev-postgres` of `exec … printenv` (spec §6.1, §7). Vóór elke commit: `git grep -nE 'postgres(ql)?://dev:[^*]' -- . ':!*.md'` moet leeg zijn, en het bewijsbestand bevat `dev:` alleen gevolgd door `***`.
- **Forge is Forgejo.** Push alleen naar `origin`; PR's via de Forgejo-API/`tea`/compare-URL, nooit `gh pr create`. Niet deployen via Forgejo Actions (CLAUDE.md).
- **Productie-engine onaangeraakt.** Geen `docker`-opdracht onder janpeter op max2 behalve de read-only baseline (spec §8 "Baseline"). Nooit de runnercaps verlagen; waiver D7 wordt niet gewijzigd.
- **Headroom (JP-besluit 14-10-2026):** `--floor-gib 12.0`, `X_eff = 12,0 GiB`, budget `min(8, 21,53 − 12,0)` → **8 GiB**; stopregel: één 5 s-steekproef `MemAvailable < 12,0 GiB` → `systemctl --user stop docker` als devdock en melden; `< 10,8 GiB` is bovendien de U4-rode lijn van de pool (spec §8.2).
- **LAN-grens:** poort 55432 alleen via `enp4s0` vanaf `192.168.0.0/24`; de sprong naar `dev-docker-in` staat op `INPUT`-positie 1 (spec §4.4). Nooit een regel zonder matchcriteria of `-j RETURN` in `INPUT`.
- **Beweer niets dat je niet hebt gemeten:** elk "werkt" in het bewijs komt met de opdracht en de uitvoer; een geslaagde `docker info` alleen haalt de acceptatie niet (spec §9).
- **Idempotent:** `bootstrap.sh`, `install-user.sh`, het firewallscript en de helper mogen herhaald draaien zonder een correcte toestand te wijzigen (spec §4).
- **Hoofdstop na materialisatie:** dit plan autoriseert geen uitvoering.

## Afwijkingen van de spec (gemeten tijdens het plannen, 14-10-2026)

1. **Hostadres in de DB-URL (spec §6.2 rev. 10 zei `@max2:55432`).** Op de Mac lost `max2` op naar `max2.tailc720d5.ts.net` = `100.102.8.64` (Tailscale, `dscacheutil -q host -a name max2`). Verkeer naar dat adres komt op max2 binnen via `tailscale0` en wordt door de `! -i enp4s0`-regel gedropt. De helper gebruikt daarom **`PGHOST=192.168.0.158`** (statisch LAN-adres van max2; de Mac zit op `192.168.0.50`/`en0`, route direct). De SSH-route (`docker --context max2-dev`, alias `max2-dev` → `HostName max2`) blijft via Tailscale lopen; dat is correct, want SSH valt niet onder de keten. Spec revisie 11 corrigeert §6.2.
2. **Testkeuze voor de proef (spec §9 "Keuze van de test"):** `npm test` van **s4m-queue** (`~/Development/s4m-queue`, vitest, 30+ testbestanden). Criterium uit de spec: accepteert een URL-variabele (`S4M_TEST_DATABASE_URL`, `test/helpers/db.ts:55`) en kent geen host-allowlist (geen loopback-check in `test/`; `dispatch-config.test.ts:42` test alleen URL-parsing). Bonus: de skill woont in dezelfde repo. Gemeten: `process.loadEnvFile()` in `test/setup.ts` overschrijft een al gezette variabele **niet**, dus een lokale `.env` met een loopback-URL wint niet van de omgeving die `db run` zet. Nodig: de rol `dev` heeft `CREATEDB` (spec §4.5), want `test/bootstrap-controller-test-db.test.ts` maakt een database `s4m_queue_bootstrap_<hex>` aan; de prune registreert een eventueel restant als `prune:first-seen`.
3. **Image-digest (spec §4.5, §12):** `docker buildx imagetools inspect pgvector/pgvector:pg17` op de Mac (14-10-2026) → `linux/amd64` = `sha256:215ae4d47393a980e9ef7ff7760f7dad53ec3e84bceb9fbd45cef34e50b5ba0f`. Taak 1 pint die; de uitvoerder herhaalt de meting op de dag van uitvoering en noteert een afwijking.

## Reviewfocus (faalpaden die de spec impliceert; elk heeft een test in de genoemde taak)

1. **Komma-decimaal of lege `--floor-gib`** → exit 2 vóór enige mutatie, met de punt-hint (taak 1, `bootstrap.sh --check-args`).
2. **Volume zonder parseerbare `CreatedAt`** → overgeslagen en gerapporteerd, nooit "oud" (taak 1, `prune.sh --selftest`).
3. **Wachtwoord met URL-tekens** (`/`, `+`, `=`, `:`, `@`) → percent-encoded in de URL en in de uitvoer gemaskeerd (taak 4, vitest met `docker`-stub).
4. **Databasenaam op de denylist of buiten de regex** (`postgres`, `pg_foo`, hoofdletters, 64 tekens) → exit 2 zonder `docker`-aanroep (taak 4).
5. **max2 onbereikbaar** → `db run` exit 3 binnen een vaste time-out, zonder lokale terugval (taak 4; stub-`docker` die `exit 1` geeft).

---

## Bestanden en verantwoordelijkheden

```
max2-repo (deze repo)
  dev-docker/host/bootstrap.sh              root; preflight+gate, pakketten, devdock, subid, slice, firewall-units, linger, ufw   (taak 1)
  dev-docker/host/dev-docker-firewall.sh    root; keten dev-docker-in + sprong op INPUT-positie 1, muteert alleen bij afwijking  (taak 1)
  dev-docker/host/recovery-test.sh          root; afgedwongen verplaatsing + herstelcontrole, EXIT-trap                           (taak 1)
  dev-docker/host/install-user.sh           devdock; rootless engine, context, .env, compose, units, images                       (taak 1)
  dev-docker/host/compose.yml, init/01-roles.sh, init/02-devmeta.sql, prune.sh, pull-images.sh, images.txt                        (taak 1)
  dev-docker/host/systemd/{dev-postgres.service, dev-docker-firewall.service, dev-docker-firewall.timer,
                            dev-docker-prune.service, dev-docker-prune.timer, 50-dev-docker.conf}                                  (taak 1)
  dev-docker/README.md                      bediening in 30 regels                                                                 (taak 1)
  evidence/dev-docker/pgvector-pg17-entrypoint.md   regels 260–290 van docker-entrypoint.sh uit het gepinde image                 (taak 1)
  evidence/dev-docker/2026-MM-DD-praktijkproef.md   bewijs §9                                                                      (taak 2, 5, 6, 7)
s4m-queue-repo
  .claude/skills/max2-docker/SKILL.md       werkwijze voor Claude en Codex                                                         (taak 4)
  scripts/max2-docker                       bash-helper (status, db create|run|url|drop|list|keep, cleanup --dry-run, images)      (taak 4)
  test/max2-docker.test.ts                  vitest met docker-stub op PATH                                                         (taak 4)
Mac (niet in git)
  ~/.ssh/config alias max2-dev; docker context max2-dev; symlinks ~/.claude/skills/max2-docker en ~/.codex/skills/max2-docker;
  ~/.docker/config.json (fase 3)                                                                                                    (taak 2, 3, 4, 7)
```

**Branches en PR's.** Hostkant en bewijs: branch `feat/dev-docker-host` in de max2-repo, PR op Forgejo (PR 33 bevat alleen de docs en kan eerder mergen; anders branch vanaf de docs-branch en later rebasen). Skill: branch `feat/max2-docker-skill` in de s4m-queue-repo, eigen PR. Volgorde: taak 1 → 2 → 3 → 4 → 5 → 6 → 7; taak 4 kan parallel aan 2–3 (eigen repo), maar de proef (5) wacht op 2, 3 en 4.

**Uitvoering met `sudo`.** `bootstrap.sh`, `recovery-test.sh` en de reboot vragen het wachtwoord van janpeter via `ssh -t`. Dat kan niet vanuit de niet-interactieve Bash-tool; de agent zet de opdracht klaar in de Terminal-panel (`run_in_terminal`) en JP typt het wachtwoord, of JP voert de regel zelf uit. Het script zelf logt niets van stdin.

---

### Taak 1 — Host-bundel schrijven en statisch verifiëren (max2-repo)

**Files:** create alle `dev-docker/host/*` uit de tabel, `dev-docker/README.md`, `evidence/dev-docker/pgvector-pg17-entrypoint.md`. Test: `bash -n`, `shellcheck -S warning`, `bootstrap.sh --check-args`, `prune.sh --selftest`, `docker compose config`.

**Interfaces.** Produceert: `bootstrap.sh --pubkey-file <pad> --floor-gib <X> --series '<GiB>:<bron>' [--preflight-only] [--check-args]` (exit 0 ok, 2 invoer, 3 preflight rood; `--preflight-only` muteert niets); `install-user.sh` (geen argumenten; idempotent; maakt `.env` alleen als die ontbreekt); `dev-docker-firewall.sh` (geen argumenten; spec §4.4 letterlijk); `recovery-test.sh` (spec §4.4 letterlijk); `prune.sh [--dry-run] [--selftest]` met `last-run.json` `{ran_at, dry_run, steps:[{name, candidates:[…], kept:[{id, reason}], errors:[…]}], disk_avail_bytes}`; `compose.yml` met `image: pgvector/pgvector:pg17@sha256:215ae4d4…ba0f`, poort `192.168.0.158:55432:5432`, env uit `.env` (`POSTGRES_PASSWORD`, `DEV_PASSWORD`), labels en volume `dev-postgres-data` (spec §4.5); `init/01-roles.sh` maakt rol `dev` (`LOGIN CREATEDB PASSWORD '$DEV_PASSWORD'`), `CREATE EXTENSION vector` in `template1`, herschrijft `pg_hba.conf` (reject `postgres` over TCP, loopback `scram-sha-256`, `local all all trust`); `init/02-devmeta.sql` = spec §4.6 letterlijk. Consumeert: niets.

**Stappen.**
1. Schrijf de bestanden volgens spec §4.1–§4.9; de twee shell-blokken uit §4.4 worden letterlijk overgenomen (`chain_ok`, `case`-sprongherstel, TEST-NET-1-testregel met `trap … EXIT`). Units: `dev-docker-firewall.service` (`Type=oneshot`, géén `RemainAfterExit`, `After=network-pre.target docker.service ufw.service tailscaled.service`, `Before=user@__UID__.service`, `WantedBy=multi-user.target`), `.timer` (`AccuracySec=1s`, `OnBootSec=2min`, `OnUnitActiveSec=1min`), `dev-postgres.service` (user; `Type=oneshot`, `RemainAfterExit=yes`, `ExecStartPre` wacht ≤ 180 s op `ip -4 -o addr show enp4s0 | grep -q '192.168.0.158/'`, `ExecStart=docker compose up -d`), prune-timer `OnCalendar=Sun *-*-* 04:30:00`, `Persistent=true`; `50-dev-docker.conf` met `__MEMORYMAX__`-placeholder. `bootstrap.sh` vult `__UID__`/`__MEMORYMAX__` met `sed` bij installatie.
2. Argument- en gate-logica van `bootstrap.sh` staan in functies die ook op de Mac draaien: `--check-args` valideert `--floor-gib`/`--series` (regex `^[0-9]+(\.[0-9]+)?$`), berekent `X_eff`, budget en marge en print ze zonder iets anders te doen. Test op de Mac: `bash dev-docker/host/bootstrap.sh --check-args --floor-gib 12.0 --series '21.53:p6'` → `X_eff=12.0 budget_gib=8 marge_gib=1.53`, exit 0; `--floor-gib 12,0` → exit 2 met "gebruik een punt als decimaalteken"; `--floor-gib 20` met dezelfde reeks → exit 2 (budget 1,5 < 2 GiB); zonder `--series` → exit 2.
3. `prune.sh --selftest` voert de kandidaatberekening uit op ingebouwde fixtures (JSON-regels zoals `docker … --format` ze geeft): een volume zonder `CreatedAt` → `kept` met reden `geen CreatedAt`; een image-ID in gebruik → `in gebruik`; een image ouder dan 168 h en nergens in gebruik → kandidaat; een database `pg_catalog`/`postgres` → `denylist`; alles zonder `docker` aan te roepen. Exit 0 = alle fixtures zoals verwacht.
4. Pin het image: `docker buildx imagetools inspect pgvector/pgvector:pg17` → amd64-digest in `compose.yml` en `images.txt`; `docker run --rm --platform linux/amd64 --entrypoint sed pgvector/pgvector:pg17@sha256:215ae4d4… -n 260,290p /usr/local/bin/docker-entrypoint.sh` → `evidence/dev-docker/pgvector-pg17-entrypoint.md` (met datum en digest). Verwacht: de `host all all all $POSTGRES_HOST_AUTH_METHOD`-regel tussen regel 266 en 285.
5. Verificatie: `for f in dev-docker/host/*.sh; do bash -n "$f"; done && shellcheck -S warning dev-docker/host/*.sh dev-docker/host/init/01-roles.sh` schoon; `docker compose -f dev-docker/host/compose.yml --env-file <(printf 'POSTGRES_PASSWORD=x\nDEV_PASSWORD=y\n') config` toont poort `192.168.0.158:55432->5432` en de digest; secretscan uit de globale beperkingen leeg.
6. Commit per laag (firewall, bootstrap, engine/compose, prune, docs) op `feat/dev-docker-host`; push; PR op Forgejo met de verificatie-uitvoer in de beschrijving.

**Acceptatie.** Alle verificaties uit stap 2, 3 en 5 slagen en staan in de PR; geen placeholder (`TODO`, `<…>`) buiten `__UID__`/`__MEMORYMAX__`; `git grep -n 'ensure()' dev-docker/` is leeg (het positieblinde patroon is bewust niet overgenomen).

### Taak 2 — Hostkant uitrollen op max2 en de LAN-grens bewijzen (spec §9 stap 1–3)

**Files:** modify Mac `~/.ssh/config` (alias `max2-dev`: `HostName max2`, `User devdock`, `IdentityFile` = die van alias `max2`); create `evidence/dev-docker/2026-MM-DD-praktijkproef.md` (deel 1); max2: alles wat `bootstrap.sh`/`install-user.sh` aanmaken.

**Interfaces.** Consumeert taak 1. Produceert: draaiende rootless engine onder devdock met `dev-postgres` gezond op `192.168.0.158:55432`; sprong naar `dev-docker-in` op positie 1; bewijsbestand deel 1 (baseline, gate, firewall, bind).

**Stappen.**
1. Baseline en sampler op max2 (spec §8/§9 stap 1): `docker ps -a --no-trunc --format '{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.CreatedAt}}'` en `docker images --digests --format …` van de productie-engine → in het bewijs; `df -B1 /var/lib/docker /home`; `sudo ufw status verbose` en `sudo ufw status numbered`; `sudo iptables-save -t filter` als momentopname; sampler starten in een `tmux`/`nohup`-lus: `while :; do date -u +%FT%TZ; grep MemAvailable /proc/meminfo; df -B1 --output=avail /var/lib/docker | tail -1; sleep 5; done >> ~/dev-docker-proef-sampler.log`.
2. Preflight zonder mutatie: `scp -r dev-docker/host/bootstrap.sh dev-docker/host/dev-docker-firewall.sh dev-docker/host/systemd "$KEY.pub" max2:/tmp/` (KEY per spec §4.1) en `ssh -t max2 "sudo bash /tmp/bootstrap.sh --preflight-only --pubkey-file '/tmp/<key>.pub' --floor-gib 12.0 --series '21.53:evidence/dev-docker/2026-10-12-p6-memavailable-max2.csv, 2026-10-12T10:46Z..2026-10-13T12:46Z, ~60 s-resolutie'"` → exit 0, uitvoer (gate groen: budget 8 GiB; AppArmor-profiel; delegatie; ufw default deny; subuid vrij) in het bewijs. Rood → stoppen en JP melden; niets is gewijzigd.
3. Bootstrap echt: zelfde opdracht zonder `--preflight-only`. Controle: `systemctl show user-<uid>.slice -p MemoryMax -p MemorySwapMax -p CPUQuotaPerSecUSec -p TasksMax` (verwacht `MemoryMax=8589934592`, `MemorySwapMax=0`, `CPUQuotaPerSecUSec=8s`, `TasksMax=4096`), `sudo iptables -S INPUT | awk '$1 == "-A" {print; exit}'` → sprong, `sudo iptables -S dev-docker-in` → R1, R2, RETURN; `sudo ufw status numbered` opnieuw. Tweede run van bootstrap → geen wijzigingen (idempotentie, uitvoer in het bewijs).
4. Alias `max2-dev` op de Mac; `ssh max2-dev id` → `uid=<uid>(devdock)`; `rsync -a --delete dev-docker/host/ max2-dev:dev-docker-src/ && ssh max2-dev bash dev-docker-src/install-user.sh`. Controle: `ssh max2-dev 'systemctl --user status docker dev-postgres.service dev-docker-prune.timer --no-pager'` (docker `active (running)`, dev-postgres `active (exited)`, timer `active (waiting)`), `cat /sys/fs/cgroup/user.slice/user-<uid>.slice/memory.max` → `8589934592`.
5. Bind-bewijs vóór de echte stack is niet nodig: `dev-postgres.service` doet de bind; slaagt die niet (`docker compose ps` toont geen `healthy`, journal toont `bind: cannot assign requested address`), dan is dat de NO-GO uit spec §4.4 → stoppen, JP melden, geen `0.0.0.0`.
6. LAN-grens (spec §4.4 "Controle"): `ss -ltn | grep 55432` → alleen `192.168.0.158:55432`; `nc -z -w2 100.102.8.64 55432` en `nc -z -w2 192.168.0.158 55432` vanaf max2 → beide exit 1; `scp dev-docker/host/recovery-test.sh max2:/tmp/ && ssh -t max2 'sudo bash /tmp/recovery-test.sh'` → eerste `-A`-regel testregel, daarna sprong, telling 1, journalmelding; `sudo iptables -S INPUT | grep -c dd-recovery-test` → 0.
7. Bewijs deel 1 schrijven (opdrachten, uitvoer, uid, budget, sampler-start); secretscan; commit op `feat/dev-docker-host`; push.

**Acceptatie.** Spec §9-acceptatie regel 5 en 6 (slice-limieten; sprong op 1 met keteninhoud; geen testregel-restant; `ss`; beide `nc` geweigerd) staan met uitvoer in het bewijs; de tweede bootstrap-run wijzigt niets; geen secret in het bewijs.

### Taak 3 — Mac-kant fase 1: Docker-context (spec §5.1, §9 stap 4)

**Files:** Mac `docker context create max2-dev --docker host=ssh://max2-dev`; bewijsbestand (aanvulling).

**Interfaces.** Consumeert taak 2 (alias, engine). Produceert: context `max2-dev`.

**Stappen.** `docker context create max2-dev --docker host=ssh://max2-dev`; `docker --context max2-dev info --format '{{.Name}} {{.SecurityOptions}}'` → `max2` en `name=rootless`; `docker --context max2-dev ps` toont `dev-postgres` `healthy`; `docker context ls` toont `desktop-linux` nog als standaard (fase 1). Uitvoer in het bewijs; commit.

**Acceptatie.** Spec §9-acceptatie regel 1.

### Taak 4 — Skill `max2-docker` met helper en tests (s4m-queue-repo)

**Files:** create `.claude/skills/max2-docker/SKILL.md`, `scripts/max2-docker` (bash, `chmod 755`), `test/max2-docker.test.ts`, `test/fixtures/max2-docker/docker` (stub); modify `README.md` (sectie "max2-docker"); Mac: symlinks `~/.claude/skills/max2-docker` en `~/.codex/skills/max2-docker` → `~/Development/s4m-queue/.claude/skills/max2-docker` (niet in git; gedocumenteerd in SKILL.md).

**Interfaces.** Consumeert: context `max2-dev` (taak 3), container `dev-postgres` met rol `dev` en register `devmeta.databases` (taak 1/2). Produceert: `scripts/max2-docker <commando>` met exact de tabel uit spec §6.2; omgevingsvariabelen van `db run`: `DATABASE_URL=postgresql://dev:<pw-percent-encoded>@192.168.0.158:55432/<naam>`, `PGHOST=192.168.0.158`, `PGPORT=55432`, `PGUSER=dev`, `PGDATABASE=<naam>`, `PGPASSWORD=<pw>`; exitcodes 0/2/3/4/kind; `MAX2_DOCKER_AGENT` voor `--by`; `MAX2_DOCKER_CONTEXT` (default `max2-dev`) en `MAX2_DOCKER_PGHOST` (default `192.168.0.158`) als overrides, zodat tests een stub kunnen gebruiken.

**Stappen.**
1. Test eerst (vitest, `execFile` op `scripts/max2-docker` met `PATH=test/fixtures/max2-docker:$PATH`; de stub-`docker` leest `MAX2_DOCKER_STUB_MODE`): (a) `db create Bad-Name` → exit 2, stdout leeg, stub niet aangeroepen (de stub schrijft elke aanroep naar `$MAX2_DOCKER_STUB_LOG`); idem `db create postgres`, `db drop pg_x`, naam van 64 tekens; (b) `db create proj_taak` met stub-modus `ok` → exit 0, stdout bevat `postgresql://dev:***@192.168.0.158:55432/proj_taak`, stub-log bevat één `exec -i dev-postgres psql -U postgres` met `format('CREATE DATABASE %I OWNER dev', …) \gexec` en één `INSERT INTO devmeta.databases … ON CONFLICT (name) DO NOTHING`; (c) `db run proj_taak -- sh -c 'echo "$DATABASE_URL"; echo "$PGPASSWORD"'` met stub-wachtwoord `a/b+c=d:e@f` → exit 0, stdout toont twee keer `***`, nooit het wachtwoord, en `DATABASE_URL` is `…dev:a%2Fb%2Bc%3Dd%3Ae%40f@192.168.0.158…` (gecontroleerd door de kind-uitvoer vóór maskering in een bestand te schrijven dat de test leest); exitcode van het kind blijft (`sh -c 'exit 7'` → 7); (d) stub-modus `unreachable` (`exit 1` met "ssh: connect to host") → `status` en `db run` exit 3 binnen 10 s; (e) stub-modus `unhealthy` → `db create` exit 4; (f) `db run` toont `***` ook in stderr van het kind; (g) `ps`-controle: tijdens `db run … -- sleep 1` bevat `ps -o args` van het kind geen `postgresql://`.
2. Helper schrijven tot de tests slagen: beheer via `docker --context "$MAX2_DOCKER_CONTEXT" exec -i dev-postgres psql -U postgres -v ON_ERROR_STOP=1 -Atq`, identifiers via `format('%I')`, `\gexec`; wachtwoord via `docker … exec dev-postgres printenv DEV_PASSWORD` in een variabele (nooit in argv, nooit `set -x`); percent-encoding met `printf`/`od` (geen `python`-afhankelijkheid); maskering via `sed "s|$(escape "$pw")|***|g"` op stdout én stderr (`2>&1 | sed` met `set -o pipefail` en behoud van de kind-exitcode via `PIPESTATUS`); `/opt/homebrew/opt/libpq/bin` vooraan in `PATH` als die bestaat; denylist en regex uit spec §6.2; `cleanup --dry-run` = `ssh max2-dev dev-docker/prune.sh --dry-run`; `status` leest `ssh max2-dev cat dev-docker/last-run.json`.
3. `SKILL.md` volgens spec §6.1 (wanneer, regels, wachtwoord nooit in beeld, commando's met één voorbeeld per commando, fouten) plus de regel voor tests die een andere variabelenaam willen: `max2-docker db run <naam> -- sh -c 'S4M_TEST_DATABASE_URL=$DATABASE_URL npm test'` (enkele quotes: de kind-shell expandeert, de aanroeper niet).
4. `npm run typecheck && npm test -- test/max2-docker.test.ts` groen; `shellcheck -S warning scripts/max2-docker` schoon; symlinks aanmaken en `ls -l ~/.claude/skills/max2-docker ~/.codex/skills/max2-docker` in de PR-beschrijving.
5. Commit op `feat/max2-docker-skill`; push; PR op Forgejo (s4m-queue, product `cmptif5j9001o4y7rqgxgnn0r`).

**Acceptatie.** Alle tests uit stap 1 bestaan en slagen; spec §11 rij 10 (geen URL in argv; `***` in kind-uitvoer) is door test (c) en (g) gedekt; de helper bevat geen fallback naar een lokale engine (`grep -n 'desktop-linux\|unix://' scripts/max2-docker` leeg).

### Taak 5 — Praktijkproef: database, identiteit, testrun, Codex, dry-run (spec §9 stap 5–9)

**Files:** bewijsbestand (deel 2); geen code.

**Interfaces.** Consumeert taak 2, 3, 4. Produceert: bewijs van spec §9-acceptatie regels 2, 3, 4, 7, 9, 10 (deels), 11.

**Stappen.**
1. `export MAX2_DOCKER_AGENT=claude; max2-docker db create s4mqueue_proef --note 'IDEA-258 praktijkproef'` → gemaskeerde URL; `max2-docker db list` toont de rij.
2. Identiteit over het LAN-pad: `max2-docker db run s4mqueue_proef -- psql -Atc 'select current_database(), current_user, inet_server_addr(), inet_server_port()'` → `s4mqueue_proef|dev|<containeradres>|5432`; `… -- psql -Atc 'select client_addr from pg_stat_activity where pid = pg_backend_pid()'` → `192.168.0.50` (de Mac op het LAN; bewijst het `enp4s0`-pad). Negatief: `PGPASSWORD=fout psql -h 192.168.0.158 -p 55432 -U dev -d s4mqueue_proef -c 'select 1'` → `password authentication failed`; met `PGPASSWORD=` leeg → geweigerd; `psql -h 192.168.0.158 -p 55432 -U postgres -d postgres -c 'select 1'` → `pg_hba.conf rejects connection`.
3. Docker Desktop afsluiten (`osascript -e 'quit app "Docker"'`, `pgrep -x Docker` leeg). Testrun: `cd ~/Development/s4m-queue && git status --porcelain` leeg (schone main), dan `max2-docker db run s4mqueue_proef -- sh -c 'S4M_TEST_DATABASE_URL=$DATABASE_URL npm test'` → vitest-samenvatting (aantal bestanden/tests geslaagd) in het bewijs; vooraf gecontroleerd dat `test/helpers/db.ts` bij een fout geen URL print (regel 56 print alleen de melding; `pg`-fouten bevatten geen wachtwoord) en dat `db run` hoe dan ook maskeert. Een test die faalt om een reden buiten deze proef (bv. een ontbrekende `PLAN_A_DB_WORKTREE`) wordt met naam en reden genoteerd; de proef slaagt als de DB-afhankelijke tests slagen en geen enkele faalt op verbinding, rechten of host.
4. Codex: één `max2-docker db list` vanuit een Codex-sessie (JP start die); uitvoer als screenshot of plakwerk in het bewijs.
5. `max2-docker cleanup --dry-run` → `s4mqueue_proef` bij de bewaarde items met `jonger dan 14 dagen`; eventuele `s4m_queue_bootstrap_*`-restanten als "zou registreren (prune:first-seen)"; niets van de productie-engine. Daarna `max2-docker db drop s4mqueue_proef` en `db list` leeg; restant-databases van de test met `db drop` opruimen (ze voldoen aan de regex niet; drop via `docker --context max2-dev exec -i dev-postgres psql -U postgres` met `\gexec`, gelogd).
6. Baseline opnieuw (identiek aan stap 1 van taak 2, diff leeg of verklaard uit gelogde uitrollen); `df` opnieuw; sampler stoppen; `sort -k2 -n` op de `MemAvailable`-regels → minimum en tijdstip in het bewijs; minimum ≥ 12 582 912 kB (12,0 GiB).
7. Bewijs deel 2; secretscan (`grep -nE 'dev:[^*]' evidence/dev-docker/2026-*-praktijkproef.md` leeg; `grep -F "$(…)"` met het op dat moment via `docker exec` gelezen wachtwoord, niet opgeslagen); commit; push.

**Acceptatie.** Spec §9-acceptatie regels 2, 3, 4, 7, 9, 10, 11 met uitvoer in het bewijs; Desktop was aantoonbaar afgesloten tijdens stap 3 (`pgrep` in het bewijs).

### Taak 6 — Herstart- en reboottest (spec §9 stap 10)

**Files:** bewijsbestand (deel 3).

**Interfaces.** Consumeert taak 2–5. Produceert: bewijs van spec §9-acceptatie regels 6 (na herstart/reboot) en 8.

**Stappen.**
1. User-manager-herstart: `ssh -t max2 'sudo systemctl stop user@<uid>.service && sudo systemctl start user@<uid>.service'`; daarna `ssh max2-dev 'systemctl --user status dev-postgres.service --no-pager'` → `active (exited)` met het wachtpad in de journal (`journalctl --user -u dev-postgres.service -n 20`); `docker --context max2-dev ps` → `healthy`; `ss -ltn | grep 55432` → alleen het LAN-adres.
2. Reboot op een door JP gekozen rustig moment, als aparte gelogde gebeurtenis: `ssh -t max2 'sudo reboot'`; na terugkomst `max2-docker status` → dev-postgres draait; `ss -ltn`; positiecontrole pas na de eerste timer-tick: `sudo journalctl -b -u dev-docker-firewall.service --no-pager` toont een run ná de boot-runs van `dsh-firewall.service`/`owui-firewall.service` (`sudo journalctl -b -u dsh-firewall.service -u owui-firewall.service -u dev-docker-firewall.service -o short-iso --no-pager` in het bewijs, plus `journalctl --user -u dev-postgres.service -b -o short-iso` voor het listener-moment); `sudo iptables -S INPUT | awk '$1 == "-A" {print; exit}'` → sprong; `sudo journalctl -t dev-docker-firewall -b --no-pager` → de herstelmelding met tijdstempel; het gemeten boot-venster (dsh/owui-insert → herstel) in seconden in het bewijs; `ss -tn 'sport = :55432'` → alleen LAN-bronnen.
3. Productiecontainers na de reboot: `docker ps` (janpeter) toont dezelfde containers als de baseline `Up`; afwijkingen melden als issue op product max2 (fingerprint `max2:<component>:not-up-after-reboot`).
4. Bewijs deel 3; commit; push; PR `feat/dev-docker-host` klaar voor JP's review.

**Acceptatie.** Spec §9-acceptatie regels 6 en 8 met uitvoer; het boot-venster is een gemeten getal, geen schatting.

### Taak 7 — Mac fase 2 en 3: standaardcontext en Homebrew-CLI (spec §5.2)

**Files:** Mac `docker context use max2-dev`; Homebrew `docker docker-compose docker-buildx docker-credential-helper`; `~/.docker/config.json` (`credsStore: osxkeychain`, `cliPluginsExtraDirs: ["/opt/homebrew/lib/docker/cli-plugins"]`); bewijsbestand (deel 4).

**Interfaces.** Consumeert taak 5 en 6 (geslaagde proef). Produceert: Mac werkt zonder Desktop; terugvalrecept gedocumenteerd.

**Stappen.**
1. Fase 2: `docker context use max2-dev`; Desktop afsluiten en uit "Start bij inloggen" (Systeeminstellingen → Algemeen → Inloggen); `docker info --format '{{.Name}}'` → `max2`.
2. Fase 3: `brew install docker docker-compose docker-buildx docker-credential-helper`; `~/.docker/config.json` aanpassen (back-up eerst: `cp ~/.docker/config.json ~/.docker/config.json.bak-$(date +%F)`); controle met Desktop afgesloten: `which docker` → `/opt/homebrew/bin/docker`, `docker info`, `docker compose version`, `docker buildx version`, `docker login` tegen `git.jp-visser.nl` via de keychain zonder credentials te tonen (`docker-credential-osxkeychain list` toont alleen registry-URL's).
3. Terugval beschreven in het bewijs: `docker context use desktop-linux` + Desktop starten. Fase 4 (Desktop verwijderen) is tijdgebonden (14 dagen zonder terugval) en komt als aparte taak in een volgende sprint, met de `pg_dumpall` van `local-postgres` naar `max2-dev:dev-docker/backups/`.
4. Bewijs deel 4; commit; push.

**Acceptatie.** Spec §11 rij 5; `docker context ls` toont `max2-dev` als standaard; Desktop niet actief tijdens de controles.

---

## Daarna (buiten dit increment; geen taken)

- Fase 4: Desktop en data verwijderen na 14 dagen zonder terugval (spec §5.2).
- Migratie van projectscripts (When2Watch `test:db:up`, Media-Organizer-allowlist, scrum4me-mcp `TEST_DATABASE_URL`): per product, met de skill als standaard.
- Ops-dashboard-paneel (eigen idee), Tailscale-publicatie, GPU-toegang, rollen per database (spec §2).

## Zelfcontrole van dit plan tegen de spec

- §4.1–§4.9 → taak 1 (bestanden), taak 2 (uitrol en controles). §4.4-herstelproef → taak 2 stap 6 en taak 6 stap 2. §4.7 prune → taak 1 stap 3 (selftest) en taak 5 stap 5 (dry-run op de host).
- §5.1 → taak 2 stap 4 (alias) en taak 3 (context). §5.2 fase 1–3 → taak 3 en 7; fase 4 → "Daarna". §5.3 → taak 4 test (d).
- §6 → taak 4 (helper, SKILL.md, symlinks, tests). §6.2-hostadres → afwijking 1.
- §7 → globale beperkingen, taak 4 (maskering), taak 5 stap 7 (secretscan). §8 → globale beperkingen (JP-besluit), taak 2 stap 1–2 (gate, sampler), taak 5 stap 6 (minimum).
- §9 stap 1–11 → taak 2 (1–3), 3 (4), 5 (5–9), 6 (10), 2/5/6/7 (11). §10 rollback → `dev-docker/README.md` (taak 1) neemt §10 letterlijk over; geen aparte taak.
- §11 rijen 1–10 → 1: taak 2/6; 2: taak 2/6; 3: taak 3; 4: taak 2 (+ `systemd-cgtop` tijdens taak 5 stap 3); 5: taak 7; 6: taak 2/5; 7: elke taak; 8: taak 2 stap 2; 9: taak 5 stap 5; 10: taak 4 (c)/(g) en taak 5.
- §12 open punten: test → afwijking 2; bind → taak 2 stap 5; digest/entrypoint → afwijking 3 en taak 1 stap 4; 8 GiB genoeg → taak 5 stap 3 met `systemd-cgtop`; s4m-queue-PR → taak 4; JP-besluit → genomen.
