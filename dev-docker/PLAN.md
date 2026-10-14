# Dev-Docker op max2 voor de Mac (IDEA-258) — implementatieplan

> **Voor agentische uitvoerders:** dit plan wordt na dubbel GO en JP-akkoord gematerialiseerd als Scrum4Me-taken (sprint → PBI → story → taken). Elke taak hieronder is zelfstandig uitvoerbaar; de taak-ID's uit de ceremonie komen in het reviewrecord. Uitvoering alleen op opdracht van JP.

**Status:** concept, revisie 2 (14-10-2026, na reviewronde 1). **Auteur:** mac:claude (Claude Fable 5.1) in opdracht van JP.
**Spec:** `dev-docker/SPEC.md` revisie 11 (dubbel GO op revisie 9; JP-besluit §12 op 14-10-2026; revisie 11 = hostadres-correctie, zie "Afwijkingen van de spec"). **Grill:** ProductDoc `GRILLS/idea-258-grill`. **Reviewrecords:** `docs/reviews/2026-10-14-idea-258-dev-docker-spec-review-record.md` (spec) en `docs/reviews/2026-10-14-idea-258-dev-docker-plan-review-record.md` (dit plan). **Herkomst:** de headroombronnen van spec §8 (caps, R17, U4-record in de `scrum4me-server`-repo) en PR 32 zijn in de spec-loop gepind en geverifieerd; in deze repo staan alleen de P6-CSV en de sampler (`evidence/dev-docker/`). Voor dit plan zijn de spec, het JP-besluit en de hieronder genoemde metingen de gezaghebbende invoer.

**Doel:** één bestaande PostgreSQL-integratietest (`npm test` van de s4m-queue-repo) slaagt vanaf de Mac tegen een database op `max2`, aangemaakt via de skill `max2-docker`, met Docker Desktop afgesloten; niets op de productie-engine is aangeraakt.

**Architectuur:** aparte rootless Docker-engine onder `devdock` op max2 (user-slice met `MemoryMax` 8 GiB), bereikbaar via `docker --context max2-dev` (SSH); één vaste `dev-postgres` gebonden aan `192.168.0.158:55432`, met een eigen `INPUT`-keten als LAN-grens; databases per taak via de skill; wekelijkse leeftijdsgebaseerde prune. Spec §3.

**Tech stack:** Docker CE 29.9 rootless (rootlesskit 3.2, slirp4netns), systemd 259 (user-units, slice-drop-in), iptables/ufw, PostgreSQL 17.11 (`pgvector/pgvector:pg17`), bash 5.3 (gemeten op max2 én op de Mac via Homebrew: `/opt/homebrew/bin/bash`, dat met `#!/usr/bin/env bash` wint omdat `/opt/homebrew/bin` vóór `/bin` staat), `jq` en `perl` (gemeten aanwezig op beide), Node 26 + vitest (s4m-queue-tests), Homebrew-Docker-CLI op de Mac. **Niet aanwezig op de Mac:** GNU `timeout`.

## Globale beperkingen (uit de spec en CLAUDE.md; gelden voor elke taak)

- **Geen secrets in Git, evidence of Scrum4Me.** Postgres-wachtwoorden ontstaan op max2 (`openssl rand -hex 24`), leven alleen in `/home/devdock/dev-docker/.env` (0600) en de container-env; nooit op de Mac-schijf, nooit in transcripten of bewijsbestanden; agents gebruiken nooit `db url --reveal`, `docker … inspect dev-postgres` of `exec … printenv` (spec §6.1, §7). **Enige uitzondering:** de helper zelf leest `DEV_PASSWORD` via `docker exec dev-postgres printenv DEV_PASSWORD` in procesgeheugen (spec §6.2), en de secretscan van taak 4 stap 7 gebruikt dezelfde route één keer, met `grep -qF` en een leegte-controle, zonder de waarde te printen. Vóór elke commit: `git grep -nE 'postgres(ql)?://dev:[^*]' -- . ':!*.md'` moet leeg zijn, en het bewijsbestand bevat `dev:` alleen gevolgd door `***`.
- **Forge is Forgejo.** Push alleen naar `origin`; PR's via de Forgejo-API/`tea`/compare-URL, nooit `gh pr create`. Niet deployen via Forgejo Actions (CLAUDE.md).
- **Productie-engine onaangeraakt.** Geen `docker`-opdracht onder janpeter op max2 behalve de read-only baseline (spec §8 "Baseline"). Nooit de runnercaps verlagen; waiver D7 wordt niet gewijzigd.
- **Headroom (JP-besluit 14-10-2026):** `--floor-gib 12.0`, `X_eff = 12,0 GiB`, budget `min(8, 21,53 − 12,0)` → **8 GiB**; stopregel: één 5 s-steekproef `MemAvailable < 12,0 GiB` (= 12 582 912 kB) → `systemctl --user stop docker` als devdock, budget verlagen volgens spec §8.2 en melden; `< 10,8 GiB` is bovendien de U4-rode lijn van de pool. **Live bewaakt** tijdens de uitrol en de testrun (taak 2 stap 1, taak 4 stap 3), niet alleen achteraf.
- **LAN-grens:** poort 55432 alleen via `enp4s0` vanaf `192.168.0.0/24`; de sprong naar `dev-docker-in` staat op `INPUT`-positie 1 (spec §4.4). Nooit een regel zonder matchcriteria of `-j RETURN` in `INPUT`.
- **Beweer niets dat je niet hebt gemeten:** elk "werkt" in het bewijs komt met de opdracht en de uitvoer; een geslaagde `docker info` alleen haalt de acceptatie niet (spec §9).
- **Idempotent:** `bootstrap.sh`, `install-user.sh`, het firewallscript en de helper mogen herhaald draaien zonder een correcte toestand te wijzigen (spec §4).
- **Geen terugval en geen instelbare doelen:** de helper kent één context (`max2-dev`) en één databasehost (`192.168.0.158`), beide hard in het script; geen omgevingsvariabele kan ze verzetten (spec §5.3, §6.1).
- **Hoofdstop na materialisatie:** dit plan autoriseert geen uitvoering.

## Afwijkingen van de spec (gemeten tijdens het plannen, 14-10-2026)

1. **Hostadres in de DB-URL (spec §6.2 rev. 10 zei `@max2:55432`; de grill noemt in besluit 3 en de doelarchitectuur ook nog `@max2`).** Op de Mac lost `max2` op naar `max2.tailc720d5.ts.net` = `100.102.8.64` (Tailscale, `dscacheutil -q host -a name max2`). Verkeer naar dat adres komt op max2 binnen via `tailscale0` en wordt door de `! -i enp4s0`-regel gedropt. De helper gebruikt daarom **`PGHOST=192.168.0.158`** (statisch LAN-adres van max2; de Mac zit op `192.168.0.50`/`en0`, route direct). De SSH-route (`docker --context max2-dev`, alias `max2-dev` → `HostName max2`) blijft via Tailscale lopen; dat is correct, want SSH valt niet onder de keten. Spec revisie 11 corrigeert §6.2. **Gevolg dat de spec niet noemt:** buiten het thuis-LAN (spec §2 sluit dat uit) werkt de SSH-route wel en het DB-pad niet. De helper vangt dat op: `db run` test eerst het TCP-pad naar `192.168.0.158:55432` met een deadline en stopt met exit 3 en de melding "LAN-pad naar dev-postgres niet bereikbaar; alleen op 192.168.0.0/24" (taak 3); SKILL.md noemt dit in één zin.
2. **Testkeuze voor de proef (spec §9 "Keuze van de test"):** `npm test` van **s4m-queue** (`~/Development/s4m-queue`, vitest, 67 testbestanden waarvan 37 `setupTestDb` of `S4M_TEST_DATABASE_URL` gebruiken; "DB-afhankelijk" = precies die 37). Criterium uit de spec: accepteert een URL-variabele (`S4M_TEST_DATABASE_URL`, `test/helpers/db.ts:55`) en kent geen host-allowlist (geen loopback-check in `test/`; `dispatch-config.test.ts:42` test alleen URL-parsing). Gemeten: `process.loadEnvFile()` in `test/setup.ts` overschrijft een al gezette variabele **niet**; de migraties `001`–`005` en de ppe-fixtures bevatten geen `CREATE EXTENSION`, `CREATE ROLE` of iets anders dat een superuser vereist, dus de rol `dev` (eigenaar van de database, `CREATEDB`) volstaat; `test/bootstrap-controller-test-db.test.ts` maakt een database `s4m_queue_bootstrap_<hex>` aan (naam kan binnen de helper-regex vallen, zie taak 4 stap 5).
3. **Image-digest (spec §4.5, §12):** `docker buildx imagetools inspect pgvector/pgvector:pg17` op de Mac (14-10-2026) → `linux/amd64` = `sha256:215ae4d47393a980e9ef7ff7760f7dad53ec3e84bceb9fbd45cef34e50b5ba0f`. Taak 1 pint die; de uitvoerder herhaalt de meting op de dag van uitvoering en noteert een afwijking.

## Reviewfocus (faalpaden die de spec impliceert; elk heeft een test in de genoemde taak)

1. **Komma-decimaal of lege `--floor-gib`** → exit 2 vóór enige mutatie, met de punt-hint; **budget onder 2 GiB** → exit 3 (gate) vóór enige mutatie (taak 1, `bootstrap.sh --check-args`).
2. **Volume zonder parseerbare `CreatedAt`** → overgeslagen en gerapporteerd, nooit "oud"; **schijf < 20 % vrij** → waarschuwing (taak 1, `prune.sh --selftest`).
3. **Wachtwoord met URL-tekens** (`/`, `+`, `=`, `:`, `@`) → percent-encoded in de URL; **ruwe én encoded vorm** gemaskeerd in stdout en stderr; nergens in argv van enig proces (taak 3, vitest met `docker`-stub en `ps -Ao args`).
4. **Databasenaam op de denylist of buiten de regex** (`postgres`, `pg_foo`, hoofdletters, 64 tekens) → exit 2 zonder `docker`-aanroep (taak 3).
5. **max2 onbereikbaar of LAN-pad dicht** → exit 3 binnen de deadline, transportkinderen opgeruimd, geen lokale terugval (taak 3; stub-modi `unreachable` en `hang`; TCP-check via `--lib`).

---

## Bestanden en verantwoordelijkheden

```
max2-repo (deze repo)
  dev-docker/host/bootstrap.sh              root; preflight+gate, pakketten, devdock, subid, slice, firewall-units, linger, ufw   (taak 1)
  dev-docker/host/dev-docker-firewall.sh    root; keten dev-docker-in + sprong op INPUT-positie 1, muteert alleen bij afwijking  (taak 1)
  dev-docker/host/recovery-test.sh          root; afgedwongen verplaatsing + herstelcontrole, EXIT-trap                           (taak 1)
  dev-docker/host/proof-checks.sh           root; alle sudo-leescontroles van §4.4/§9 in één run, uitvoer naar één bestand      (taak 1)
  dev-docker/host/install-user.sh           devdock; rootless engine, context, .env, compose, units, images                       (taak 1)
  dev-docker/host/compose.yml, init/01-roles.sh, init/02-devmeta.sql, prune.sh, pull-images.sh, images.txt                        (taak 1)
  dev-docker/host/systemd/{dev-postgres.service, dev-docker-firewall.service, dev-docker-firewall.timer,
                            dev-docker-prune.service, dev-docker-prune.timer, 50-dev-docker.conf}                                  (taak 1)
  dev-docker/README.md                      bediening in 30 regels + rollback (spec §10 letterlijk)                                (taak 1)
  evidence/dev-docker/pgvector-pg17-entrypoint.md   regels 260–290 van docker-entrypoint.sh uit het gepinde image                 (taak 1)
  evidence/dev-docker/2026-MM-DD-praktijkproef.md   bewijs §9                                                                      (taak 2, 4, 5, 6)
s4m-queue-repo
  .claude/skills/max2-docker/SKILL.md       werkwijze voor Claude en Codex                                                         (taak 3)
  scripts/max2-docker                       bash-helper (status, db create|run|url|drop|list|keep, cleanup --dry-run, images)      (taak 3)
  test/max2-docker.test.ts                  vitest met docker-stub op PATH                                                         (taak 3)
  test/fixtures/max2-docker/docker          stub                                                                                   (taak 3)
Mac (niet in git)
  ~/.ssh/config alias max2-dev (ConnectTimeout 5, ServerAliveInterval 15); docker context max2-dev;
  symlinks ~/.claude/skills/max2-docker, ~/.codex/skills/max2-docker en ~/bin/max2-docker; ~/.docker/config.json (fase 3)         (taak 2, 3, 6)
```

**Branches en PR's.** Hostkant en bewijs: branch `feat/dev-docker-host` in de max2-repo, PR op Forgejo die pas **na taak 6** ter review gaat (eerdere taken pushen naar dezelfde branch; de PR-beschrijving wordt per taak aangevuld; reparaties tijdens de uitrol zijn gewone commits op die branch). PR 33 bevat alleen de docs en kan eerder mergen; anders branch vanaf de docs-branch en later rebasen. Skill: branch `feat/max2-docker-skill` in de s4m-queue-repo, eigen PR; taak 4 draait vanaf die branch (schone worktree) of na JP's merge. Volgorde: taak 1 → 2 → 3 → 4 → 5 → 6; taak 3 kan parallel aan taak 2 (eigen repo), maar taak 4 wacht op 2 en 3.

**Uitvoering met `sudo`.** Elke `ssh -t` start een nieuwe tty, dus elk root-commando vraagt het wachtwoord van janpeter; een niet-interactieve agent kan dat niet. Daarom zijn alle root-handelingen per taak gebundeld in één script (`bootstrap.sh`, `recovery-test.sh`, `proof-checks.sh`, en in taak 5 één regel voor de user-manager-herstart en één voor de reboot). De agent zet de opdracht klaar in de Terminal-panel (`run_in_terminal`) en JP typt het wachtwoord, of JP voert de regel zelf uit. `proof-checks.sh` schrijft zijn uitvoer naar `/tmp/dev-docker-proof-<UTC-stamp>.txt` (0644) dat de agent daarna zonder sudo met `scp` ophaalt. De scripts loggen niets van stdin.

---

### Taak 1 — Host-bundel schrijven en statisch verifiëren (max2-repo)

**Files:** create alle `dev-docker/host/*` uit de tabel, `dev-docker/README.md`, `evidence/dev-docker/pgvector-pg17-entrypoint.md`. Test: `bash -n`, `shellcheck -S warning`, `bootstrap.sh --check-args`, `prune.sh --selftest`, `docker compose config`.

**Interfaces.** Produceert:
- `bootstrap.sh --pubkey-file <pad> --floor-gib <X> --series '<GiB>:<bron>' [--preflight-only] [--check-args]`. Exit 0 ok; **2 = ongeldige invoer** (ontbrekende of niet-numerieke `--floor-gib`/`--series`, komma-decimaal → melding "gebruik een punt als decimaalteken"); **3 = preflight/gate rood** (budget onder 2 GiB, AppArmor-profiel ontbreekt, delegatie ontbreekt, ufw niet default-deny, subuid-range bezet, bestaande afwijkende `devdock`). `--check-args` doet alleen de invoervalidatie en de budgetberekening (draait ook op de Mac); `--preflight-only` doet alle read-only controles op max2 en muteert niets. Uitvoer van beide: `X_eff=<GiB> budget_gib=<n> marge_gib=<n>` plus per controle `OK`/`ROOD <reden>`.
- `install-user.sh` (geen argumenten; idempotent; maakt `.env` alleen als die ontbreekt).
- `dev-docker-firewall.sh` en `recovery-test.sh`: spec §4.4 letterlijk.
- `proof-checks.sh` (root, read-only): print achtereenvolgens `ufw status verbose`, `ufw status numbered`, `iptables-save -t filter`, `iptables -S INPUT | awk '$1 == "-A" {print; exit}'`, `iptables -S dev-docker-in`, `iptables -S INPUT | grep -c -- '-j dev-docker-in'`, `iptables -S INPUT | grep -c dd-recovery-test`, `ss -ltn | grep 55432`, `ss -tn 'sport = :55432'`, `nc -z -w2 100.102.8.64 55432; echo "nc-ts rc=$?"`, `nc -z -w2 192.168.0.158 55432; echo "nc-lan rc=$?"`, `journalctl -t dev-docker-firewall -b --no-pager -o short-iso`, `journalctl -b -u dsh-firewall.service -u owui-firewall.service -u dev-docker-firewall.service -o short-iso --no-pager`, `systemctl show user-<uid>.slice -p MemoryMax -p MemorySwapMax -p CPUQuotaPerSecUSec -p TasksMax`, `cat /sys/fs/cgroup/user.slice/user-<uid>.slice/memory.max` en `memory.peak`, `docker ps -a --no-trunc --format '{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.CreatedAt}}'` en `docker images --digests --format '{{.ID}}\t{{.Repository}}:{{.Tag}}\t{{.Digest}}'` (productie-engine, read-only), `df -B1 /var/lib/docker /home`; elk blok met kop `## <naam>`; alles naar `/tmp/dev-docker-proof-<UTC-stamp>.txt` én stdout. Argument `--uid <uid>`.
- `prune.sh [--dry-run] [--selftest]` met `last-run.json` `{ran_at, dry_run, steps:[{name, candidates:[…], kept:[{id, reason}], errors:[…]}], disk:{total_bytes, avail_bytes, avail_pct, warn_below_pct:20, warning:bool}}`, geschreven met `jq -n` (gemeten aanwezig op max2); `prune.sh` print bij `avail_pct < 20` de regel `WAARSCHUWING: <pct> % vrij op /var/lib/docker (grens 20 %)` (spec §7).
- `compose.yml` met `image: pgvector/pgvector:pg17@sha256:215ae4d4…ba0f`, poort `192.168.0.158:55432:5432`, env uit `.env` (`POSTGRES_PASSWORD`, `DEV_PASSWORD`), labels en volume `dev-postgres-data` (spec §4.5); `init/01-roles.sh` maakt rol `dev` (`LOGIN CREATEDB PASSWORD '$DEV_PASSWORD'`), `CREATE EXTENSION vector` in `template1`, herschrijft `pg_hba.conf` (reject `postgres` over TCP, loopback `scram-sha-256`, `local all all trust`); `init/02-devmeta.sql` = spec §4.6 letterlijk.
Consumeert: niets.

**Stappen.**
1. Schrijf de bestanden volgens spec §4.1–§4.9; de twee shell-blokken uit §4.4 worden letterlijk overgenomen (`chain_ok`, `case`-sprongherstel, TEST-NET-1-testregel met `trap … EXIT`). Units: `dev-docker-firewall.service` (`Type=oneshot`, géén `RemainAfterExit`, `After=network-pre.target docker.service ufw.service tailscaled.service`, `Before=user@__UID__.service`, `WantedBy=multi-user.target`), `.timer` (`AccuracySec=1s`, `OnBootSec=2min`, `OnUnitActiveSec=1min`), `dev-postgres.service` (user; `Type=oneshot`, `RemainAfterExit=yes`, `ExecStartPre` wacht ≤ 180 s op `ip -4 -o addr show enp4s0 | grep -q '192.168.0.158/'`, `ExecStart=docker compose up -d`), prune-timer `OnCalendar=Sun *-*-* 04:30:00`, `Persistent=true`; `50-dev-docker.conf` met `__MEMORYMAX__`-placeholder. `bootstrap.sh` vult `__UID__`/`__MEMORYMAX__` met `sed` bij installatie. Alle scripts `#!/usr/bin/env bash`, `set -euo pipefail`; geen bash-4-exclusieve constructies zijn nodig, maar bash ≥ 4 is op beide hosts gemeten (5.3).
2. Test `--check-args` op de Mac: `bash dev-docker/host/bootstrap.sh --check-args --floor-gib 12.0 --series '21.53:p6'` → `X_eff=12.0 budget_gib=8 marge_gib=1.53`, exit 0; `--floor-gib 12,0` → exit 2 met "gebruik een punt als decimaalteken"; zonder `--series` → exit 2; `--floor-gib 20 --series '21.53:p6'` → `budget_gib=1.5`, melding "budget onder 2 GiB", **exit 3**; `--floor-gib 10 --series '21.53:p6'` → `X_eff=10.8` (ondergrens), budget 8.
3. `prune.sh --selftest` voert de kandidaatberekening uit op ingebouwde fixtures (JSON-regels zoals `docker … --format` ze geeft): een volume zonder `CreatedAt` → `kept` met reden `geen CreatedAt`; een image-ID in gebruik → `in gebruik`; een image ouder dan 168 h en nergens in gebruik → kandidaat; een database `pg_catalog`/`postgres` → `denylist`; een `disk`-fixture met 15 % vrij → `warning:true` en de WAARSCHUWING-regel; alles zonder `docker` aan te roepen. Exit 0 = alle fixtures zoals verwacht.
4. Pin het image: `docker buildx imagetools inspect pgvector/pgvector:pg17` → amd64-digest in `compose.yml` en `images.txt`; `docker run --rm --platform linux/amd64 --entrypoint sed pgvector/pgvector:pg17@sha256:215ae4d4… -n 260,290p /usr/local/bin/docker-entrypoint.sh` → `evidence/dev-docker/pgvector-pg17-entrypoint.md` (met datum en digest). Verwacht: de `host all all all $POSTGRES_HOST_AUTH_METHOD`-regel tussen regel 266 en 285.
5. Verificatie: `for f in dev-docker/host/*.sh; do bash -n "$f"; done && shellcheck -S warning dev-docker/host/*.sh dev-docker/host/init/01-roles.sh` schoon; `docker compose -f dev-docker/host/compose.yml --env-file <(printf 'POSTGRES_PASSWORD=x\nDEV_PASSWORD=y\n') config` toont poort `192.168.0.158:55432->5432` en de digest; secretscan uit de globale beperkingen leeg.
6. Commit per laag (firewall, bootstrap, engine/compose, prune, proof-checks, docs) op `feat/dev-docker-host`; push; PR op Forgejo aanmaken met de verificatie-uitvoer in de beschrijving (review pas na taak 6).

**Acceptatie.** Alle verificaties uit stap 2, 3 en 5 slagen en staan in de PR; geen placeholder (`TODO`, `<…>`) buiten `__UID__`/`__MEMORYMAX__`; `git grep -n 'ensure()' -- dev-docker/host` is leeg (het positieblinde patroon is bewust niet overgenomen).

### Taak 2 — Hostkant uitrollen op max2, LAN-grens bewijzen, Mac-context (spec §9 stap 1–4)

**Files:** modify Mac `~/.ssh/config` (alias `max2-dev`: `HostName max2`, `User devdock`, `IdentityFile` = die van alias `max2`, `ConnectTimeout 5`, `ServerAliveInterval 15`); Mac `docker context create max2-dev --docker host=ssh://max2-dev`; create `evidence/dev-docker/2026-MM-DD-praktijkproef.md` (deel 1); max2: alles wat `bootstrap.sh`/`install-user.sh` aanmaken.

**Interfaces.** Consumeert taak 1. Produceert: draaiende rootless engine onder devdock met `dev-postgres` gezond op `192.168.0.158:55432`; sprong naar `dev-docker-in` op positie 1; context `max2-dev`; bewijsbestand deel 1 (baseline, gate, firewall, bind, context).

**Stappen.**
1. Baseline en sampler op max2 (spec §8/§9 stap 1): `proof-checks.sh --uid 0` is nog niet bruikbaar (devdock bestaat niet), dus baseline als janpeter zonder sudo: de twee `docker`-opdrachten van de productie-engine en `df -B1 /var/lib/docker /home` → in het bewijs; `sudo ufw status verbose`, `sudo ufw status numbered` en `sudo iptables-save -t filter` in één `ssh -t`-sessie door JP (uitvoer naar `/tmp/dev-docker-baseline.txt`, daarna `scp`). Sampler starten (`nohup`): `while :; do d=$(date -u +%FT%TZ); m=$(awk '/MemAvailable/{print $2}' /proc/meminfo); a=$(df -B1 --output=avail /var/lib/docker | tail -1); echo "$d $m $a"; [ "$m" -lt 12582912 ] && echo "$d ALARM MemAvailable=$m kB < 12582912"; sleep 5; done >> ~/dev-docker-proef-sampler.log 2>&1 &`. **Bewaking:** in een tweede terminal `ssh max2 tail -f ~/dev-docker-proef-sampler.log | grep --line-buffered ALARM` gedurende stap 3–4 en tijdens taak 4 stap 3; bij een ALARM: `ssh max2-dev systemctl --user stop docker`, JP melden, budget verlagen (spec §8.2) en de stap herhalen.
2. Preflight zonder mutatie: `scp -r dev-docker/host/bootstrap.sh dev-docker/host/dev-docker-firewall.sh dev-docker/host/systemd "$KEY.pub" max2:/tmp/` (KEY per spec §4.1) en `ssh -t max2 "sudo bash /tmp/bootstrap.sh --preflight-only --pubkey-file '/tmp/<key>.pub' --floor-gib 12.0 --series '21.53:evidence/dev-docker/2026-10-12-p6-memavailable-max2.csv, 2026-10-12T10:46Z..2026-10-13T12:46Z, ~60 s-resolutie'"` → exit 0, uitvoer (gate groen: budget 8 GiB; AppArmor-profiel; delegatie; ufw default deny; subuid vrij) in het bewijs. Exit 3 → stoppen en JP melden; niets is gewijzigd.
3. Bootstrap echt: zelfde opdracht zonder `--preflight-only`. Tweede run van bootstrap → geen wijzigingen (idempotentie, uitvoer in het bewijs). Lees het sampler-minimum tot nu toe: `awk '$2<m||!m{m=$2;t=$1} END{print t, m}' ~/dev-docker-proef-sampler.log`.
4. Alias `max2-dev` op de Mac (met `ConnectTimeout 5`, `ServerAliveInterval 15`); `ssh max2-dev id` → `uid=<uid>(devdock)`; `rsync -a --delete dev-docker/host/ max2-dev:dev-docker-src/ && ssh max2-dev bash dev-docker-src/install-user.sh`. Controle: `ssh max2-dev 'systemctl --user status docker dev-postgres.service dev-docker-prune.timer --no-pager'` (docker `active (running)`, dev-postgres `active (exited)`, timer `active (waiting)`); `ssh max2-dev 'docker ps --filter name=dev-postgres --format "{{.Status}}"'` → bevat `(healthy)`. Sampler-minimum opnieuw lezen.
5. Bind-bewijs: `dev-postgres.service` doet de bind; slaagt die niet (`docker compose ps` toont geen `healthy`, `journalctl --user -u dev-postgres.service` toont `bind: cannot assign requested address`), dan is dat de NO-GO uit spec §4.4 → stoppen, JP melden, geen `0.0.0.0`.
6. LAN-grens en herstelproef in één root-sessie: `scp dev-docker/host/recovery-test.sh dev-docker/host/proof-checks.sh max2:/tmp/ && ssh -t max2 'sudo bash /tmp/proof-checks.sh --uid <uid> && sudo bash /tmp/recovery-test.sh && sudo bash /tmp/proof-checks.sh --uid <uid>'`; daarna `scp max2:/tmp/dev-docker-proof-*.txt evidence/dev-docker/raw/`. Verwacht in beide proof-bestanden: eerste `-A`-regel = sprong; keten R1, R2, RETURN; sprongtelling 1; `dd-recovery-test`-telling 0; `ss -ltn` alleen `192.168.0.158:55432`; `nc-ts rc=1` en `nc-lan rc=1`; slice `MemoryMax=8589934592`, `MemorySwapMax=0`, `CPUQuotaPerSecUSec=8s`, `TasksMax=4096`, `memory.max` `8589934592`; en in de recovery-uitvoer: testregel eerst, daarna sprong, telling 1, journalmelding.
7. Mac-context (spec §5.1, §9 stap 4): `docker context create max2-dev --docker host=ssh://max2-dev`; `docker --context max2-dev info --format '{{.Name}} {{.SecurityOptions}}'` → `max2` en `name=rootless`; `docker --context max2-dev ps --filter name=dev-postgres --format '{{.Status}}'` → `(healthy)`; `docker context ls` toont `desktop-linux` nog als standaard (fase 1).
8. Bewijs deel 1 schrijven (opdrachten, uitvoer, uid, budget, sampler-minimum per stap); secretscan; commit op `feat/dev-docker-host`; push.

**Acceptatie.** Spec §9-acceptatie regel 1, 5 en 6 (context; slice-limieten; sprong op 1 met keteninhoud; geen testregel-restant; `ss`; beide `nc` geweigerd) staan met uitvoer in het bewijs; de tweede bootstrap-run wijzigt niets; geen ALARM-regel in de sampler; geen secret in het bewijs.

### Taak 3 — Skill `max2-docker` met helper en tests (s4m-queue-repo)

**Files:** create `.claude/skills/max2-docker/SKILL.md`, `scripts/max2-docker` (bash, `chmod 755`), `test/max2-docker.test.ts`, `test/fixtures/max2-docker/docker` (stub); modify `README.md` (sectie "max2-docker"); Mac: symlinks `~/.claude/skills/max2-docker` en `~/.codex/skills/max2-docker` → `~/Development/s4m-queue/.claude/skills/max2-docker`, en `~/bin/max2-docker` → `~/Development/s4m-queue/scripts/max2-docker` (niet in git; gedocumenteerd in SKILL.md; SKILL.md noemt het absolute pad als `~/bin` niet op het PATH staat).

**Interfaces.** Consumeert: context `max2-dev` (taak 2), container `dev-postgres` met rol `dev` en register `devmeta.databases` (taak 1/2). Produceert: `scripts/max2-docker <commando>` met exact de tabel uit spec §6.2; omgevingsvariabelen van `db run`: `DATABASE_URL=postgresql://dev:<pw-percent-encoded>@192.168.0.158:55432/<naam>`, `PGHOST=192.168.0.158`, `PGPORT=55432`, `PGUSER=dev`, `PGDATABASE=<naam>`, `PGPASSWORD=<pw>`, `PGCONNECT_TIMEOUT=5`; exitcodes 0/2/3/4/kind; `MAX2_DOCKER_AGENT` voor `--by`; **geen andere omgevingsvariabelen** (context en host staan hard in het script). `scripts/max2-docker --lib` definieert alleen de functies (voor tests) en voert niets uit.

**Docker-aanroepen van de helper (allemaal via `docker --context max2-dev`, allemaal onder de deadline):** gezondheid `ps --filter name=dev-postgres --format '{{.Status}}'` (bevat `(healthy)`; nooit `inspect`); wachtwoord `exec dev-postgres printenv DEV_PASSWORD` (in een variabele, nooit in argv); beheer `exec -i dev-postgres psql -U postgres -v ON_ERROR_STOP=1 -Atq` met SQL op **stdin**; `cleanup --dry-run` en `status` gebruiken `ssh max2-dev dev-docker/prune.sh --dry-run` resp. `ssh max2-dev cat dev-docker/last-run.json` (geprint via `jq`, gemeten aanwezig op de Mac).

**Deadline (macOS heeft geen `timeout`):** functie `with_deadline <sec> <cmd…>`: start het commando op de achtergrond, een killer-subshell (`sleep <sec>; kill -TERM <pid>; sleep 1; kill -KILL <pid>`) ernaast, `wait` op het commando, killer beëindigen; exit 124 bij time-out. Elke `docker`/`ssh`-transportaanroep loopt eronder met 15 s; **niet** het kindproces van `db run`. Classificatie exit 3: deadline (124) óf stderr met `ssh: connect to host|Connection timed out|Cannot connect to the Docker daemon|error during connect`; andere docker-fouten → exit 4 (dev-postgres niet gezond/beheerfout) met de stderr-regel. Vóór het kind test `db run` het LAN-pad: `tcp_open 192.168.0.158 55432` (bash `/dev/tcp` in een subshell onder `with_deadline 3`) → bij falen exit 3 met "LAN-pad naar dev-postgres niet bereikbaar; alleen op 192.168.0.0/24".

**Maskering (bash 5.3; geen secret in argv, beide vormen, beide streams, exitcode behouden):**
```sh
mask() { MASK_RAW="$pw" MASK_ENC="$pw_enc" perl -pe 's/\Q$ENV{MASK_RAW}\E/***/g; s/\Q$ENV{MASK_ENC}\E/***/g'; }
t=$(mktemp -d); mkfifo "$t/out" "$t/err"
mask <"$t/out" & p1=$!; mask <"$t/err" >&2 & p2=$!
"$@" >"$t/out" 2>"$t/err"; rc=$?
wait "$p1" "$p2"; rm -rf "$t"; exit "$rc"
```
`perl` is gemeten aanwezig op de Mac; `\Q…\E` neutraliseert metatekens; de geheimen bereiken `perl` via de omgeving, niet via argv; `--no-redact` slaat de `mask`-stap over.

**Stappen.**
1. Test eerst (vitest, `execFile` op `scripts/max2-docker` met `PATH=test/fixtures/max2-docker:$PATH`; de stub-`docker` leest `MAX2_DOCKER_STUB_MODE` (`ok` | `unreachable` | `hang` | `unhealthy`), levert het stub-wachtwoord uit `MAX2_DOCKER_STUB_PASSWORD`, logt elke aanroep (argv én stdin) naar `$MAX2_DOCKER_STUB_LOG`; de stub-`ssh` in dezelfde map beantwoordt `cat dev-docker/last-run.json` en `prune.sh --dry-run` met fixtures):
   (a) `db create Bad-Name`, `db create postgres`, `db drop pg_x`, naam van 64 tekens → exit 2, stub-log leeg;
   (b) `db create proj_taak` (modus `ok`) → exit 0, stdout bevat `postgresql://dev:***@192.168.0.158:55432/proj_taak`; stub-log bevat één `ps --filter name=dev-postgres`, één `exec dev-postgres printenv DEV_PASSWORD`, één `exec -i dev-postgres psql …` met op stdin `format('CREATE DATABASE %I OWNER dev', …) \gexec` en één met `INSERT INTO devmeta.databases … ON CONFLICT (name) DO NOTHING`;
   (c) stub-wachtwoord `a/b+c=d:e@f`; `db run proj_taak -- sh -c 'printf "%s\n%s\n" "$DATABASE_URL" "$PGPASSWORD" | tee "$OUT"'` (met `OUT` een tempbestand) → exit 0; stdout van de helper toont `postgresql://dev:***@192.168.0.158:55432/proj_taak` en `***`; het tempbestand (ongemaskeerd, door het kind geschreven) bevat `dev:a%2Fb%2Bc%3Dd%3Ae%40f@192.168.0.158` en de ruwe waarde; `sh -c 'exit 7'` → 7;
   (d) modus `unreachable` (stub: `ssh: connect to host max2 port 22: Operation timed out` op stderr, exit 255) → `status` en `db run` exit 3; modus `hang` (stub slaapt 60 s) → exit 3 binnen 17 s, en `pgrep -f 'fixtures/max2-docker/docker'` is daarna leeg; `tcp_open 127.0.0.1 1` via `bash -c 'source scripts/max2-docker --lib; tcp_open 127.0.0.1 1'` → exit ≠ 0 binnen 4 s;
   (e) modus `unhealthy` (`ps` zonder `(healthy)`) → `db create` exit 4;
   (f) `db run proj_taak -- sh -c 'echo "$PGPASSWORD" >&2'` → `***` op stderr van de helper, stdout leeg;
   (g) tijdens `db run proj_taak -- sleep 2`: `ps -Ao args` bevat nergens `postgresql://`, de ruwe of de encoded stub-waarde (de test scant na 0,5 s en nogmaals na 1,5 s).
2. Helper schrijven tot de tests slagen: identifiers via `format('%I')` en `\gexec`; percent-encoding met een bash-lus over de bytes (`printf '%%%02X'`), geen `python`-afhankelijkheid; denylist en regex uit spec §6.2; `/opt/homebrew/opt/libpq/bin` vooraan in `PATH` als die bestaat; `set +x` en geen `-x` ergens.
3. `SKILL.md` volgens spec §6.1 (wanneer, regels, wachtwoord nooit in beeld, commando's met één voorbeeld per commando, fouten) plus: de regel voor tests met een andere variabelenaam — `max2-docker db run <naam> -- sh -c 'S4M_TEST_DATABASE_URL=$DATABASE_URL npm test'` (enkele quotes: de kind-shell expandeert, de aanroeper niet); één zin "werkt alleen op het thuis-LAN; daarbuiten stopt `db run` met exit 3"; het aanroeppad (`~/bin/max2-docker` of het absolute pad).
4. `npm run typecheck && npm test -- test/max2-docker.test.ts` groen; `shellcheck -S warning scripts/max2-docker test/fixtures/max2-docker/docker` schoon; symlinks aanmaken en `ls -l ~/.claude/skills/max2-docker ~/.codex/skills/max2-docker ~/bin/max2-docker` in de PR-beschrijving.
5. Commit op `feat/max2-docker-skill`; push; PR op Forgejo (s4m-queue, product `cmptif5j9001o4y7rqgxgnn0r`).

**Acceptatie.** Alle tests uit stap 1 bestaan en slagen; spec §11 rij 10 is door (c), (f) en (g) gedekt; `grep -nE 'desktop-linux|unix://|MAX2_DOCKER_(CONTEXT|PGHOST)' scripts/max2-docker` is leeg.

### Taak 4 — Praktijkproef: database, identiteit, testrun, Codex, dry-run (spec §9 stap 5–9)

**Files:** bewijsbestand (deel 2); geen code. Draait vanaf `~/Development/s4m-queue` op branch `feat/max2-docker-skill` (schone worktree, `git status --porcelain` leeg) of op `main` na JP's merge.

**Interfaces.** Consumeert taak 2 en 3. Produceert: bewijs van spec §9-acceptatie regels 2, 3, 4, 7, 9, 10 (deels), 11.

**Stappen.**
1. `export MAX2_DOCKER_AGENT=claude; max2-docker db create s4mqueue_proef --note 'IDEA-258 praktijkproef'` → gemaskeerde URL; `max2-docker db list` toont de rij. Sampler-bewaking uit taak 2 stap 1 draait opnieuw mee.
2. Identiteit over het LAN-pad: `max2-docker db run s4mqueue_proef -- psql -Atc 'select current_database(), current_user, inet_server_addr(), inet_server_port()'` → `s4mqueue_proef|dev|<containeradres>|5432`; `… -- psql -Atc 'select client_addr from pg_stat_activity where pid = pg_backend_pid()'` → de waarde **zoals gemeten** in het bewijs, naast `ipconfig getifaddr en0` van dat moment; geen claim over wat het "moet" zijn (de rootless-poortdriver kan de bron vertalen, spec §4.5); het LAN-pad is bewezen door taak 2 stap 6 plus deze geslaagde verbinding. Negatief, met `export PATH=/opt/homebrew/opt/libpq/bin:$PATH` en `PGPASSFILE=/dev/null`: `PGPASSWORD=fout psql -h 192.168.0.158 -p 55432 -U dev -d s4mqueue_proef -c 'select 1'` → `password authentication failed`; `PGPASSWORD= psql …` → geweigerd; `psql -h 192.168.0.158 -p 55432 -U postgres -d postgres -c 'select 1'` → `pg_hba.conf rejects connection`.
3. Docker Desktop afsluiten (`osascript -e 'quit app "Docker"'`; `pgrep -x Docker` leeg, in het bewijs). Testrun: `max2-docker db run s4mqueue_proef -- sh -c 'S4M_TEST_DATABASE_URL=$DATABASE_URL npm test'` → vitest-samenvatting in het bewijs; tijdens de run op max2 `ssh max2-dev 'systemd-cgtop -b -n 3 user.slice/user-<uid>.slice'` (als devdock; valt terug op `cat /sys/fs/cgroup/user.slice/user-<uid>.slice/memory.peak` ná de run, ook in `proof-checks.sh`) → piekgebruik in het bewijs (spec §12: is 8 GiB genoeg). Vooraf gecontroleerd dat `test/helpers/db.ts` bij een fout geen URL print (regel 56 print alleen de melding) en dat `db run` hoe dan ook maskeert. **Slagingsregel:** alle 37 DB-afhankelijke testbestanden slagen en geen enkele test faalt op verbinding, rechten of host; een test die om een andere reden faalt (bv. `PLAN_A_DB_WORKTREE` niet gezet) wordt met naam en reden genoteerd en telt niet mee, mits dezelfde test ook tegen de lokale Desktop-Postgres faalt (één controle-run vóór stap 3, met Desktop nog aan, van alleen dat bestand).
4. Codex: één `max2-docker db list` vanuit een Codex-sessie (JP start die); uitvoer in het bewijs.
5. Registerstand vóór: `max2-docker db list` → in het bewijs. `max2-docker cleanup --dry-run` → `s4mqueue_proef` bij de bewaarde items met `jonger dan 14 dagen`; eventuele `s4m_queue_bootstrap_<hex>`-restanten als "zou registreren (prune:first-seen)"; niets van de productie-engine. Registerstand ná: `db list` identiek (spec §11 rij 9). Daarna `max2-docker db drop s4mqueue_proef`; restanten per naam tegen de regex toetsen (`s4m_queue_bootstrap_<12 hex>` = `s4m` + `_` + 23 tekens → valt binnen de regex) en met `db drop` verwijderen; alleen een door de helper geweigerde naam gaat via `docker --context max2-dev exec -i dev-postgres psql -U postgres` met `\gexec`, gelogd met reden; `db list` leeg.
6. Baseline opnieuw (de twee `docker`-opdrachten en `df`, identiek aan taak 2 stap 1; diff leeg of verklaard uit gelogde uitrollen); sampler stoppen; minimum en tijdstip (`awk` uit taak 2 stap 3) in het bewijs; geen ALARM-regel.
7. Bewijs deel 2; secretscan: `grep -nE 'dev:[^*]' evidence/dev-docker/2026-*-praktijkproef.md` leeg, en `pw=$(docker --context max2-dev exec dev-postgres printenv DEV_PASSWORD); [ -n "$pw" ] && grep -qF -- "$pw" evidence/dev-docker/*.md && echo LEK || echo schoon; unset pw` (de enige toegestane `printenv`-aanroep buiten de helper; print nooit de waarde); commit; push.

**Acceptatie.** Spec §9-acceptatie regels 2, 3, 4, 7, 9, 10, 11 met uitvoer in het bewijs; Desktop was aantoonbaar afgesloten tijdens stap 3; piekgebruik van de slice is genoteerd.

### Taak 5 — Herstart- en reboottest (spec §9 stap 10)

**Files:** bewijsbestand (deel 3).

**Interfaces.** Consumeert taak 2–4. Produceert: bewijs van spec §9-acceptatie regels 6 (na herstart en reboot) en 8.

**Stappen.**
1. User-manager-herstart (één root-regel door JP): `ssh -t max2 'sudo systemctl stop user@<uid>.service && sudo systemctl start user@<uid>.service && sudo bash /tmp/proof-checks.sh --uid <uid>'`; daarna `ssh max2-dev 'systemctl --user status dev-postgres.service --no-pager; journalctl --user -u dev-postgres.service -n 20 --no-pager'` → `active (exited)` met het wachtpad; `docker --context max2-dev ps --filter name=dev-postgres --format '{{.Status}}'` → `(healthy)`; proof-bestand: sprong eerst, keten R1/R2/RETURN, sprongtelling 1, `dd-recovery-test` 0, `ss -ltn` alleen LAN-adres, `ss -tn 'sport = :55432'` alleen LAN-bronnen.
2. Reboot op een door JP gekozen rustig moment, als aparte gelogde gebeurtenis: `ssh -t max2 'sudo reboot'`; na terugkomst wachten tot `journalctl -b -u dev-docker-firewall.service` (via `proof-checks.sh`) een run toont **ná** de boot-runs van `dsh-firewall.service`/`owui-firewall.service` (anders `ssh -t max2 'sudo systemctl start dev-docker-firewall.service'`), dan `ssh -t max2 'sudo bash /tmp/proof-checks.sh --uid <uid>'` → zelfde vier controles als stap 1, plus de journal-tijdstempels (dsh/owui-insert, dev-docker-herstelmelding, dev-postgres-listener uit `journalctl --user -u dev-postgres.service -b -o short-iso`) → het gemeten boot-venster in seconden in het bewijs; `max2-docker status` → dev-postgres draait zonder handmatige `compose up`.
3. Productiecontainers na de reboot: `docker ps` (janpeter, read-only) toont dezelfde containers `Up` als de baseline; afwijkingen melden als issue op product max2 (fingerprint `max2:<component>:not-up-after-reboot`).
4. Bewijs deel 3; commit; push.

**Acceptatie.** Spec §9-acceptatie regels 6 en 8 met uitvoer; het boot-venster is een gemeten getal, geen schatting.

### Taak 6 — Mac fase 2 en 3: standaardcontext en Homebrew-CLI (spec §5.2)

**Files:** Mac `docker context use max2-dev`; Homebrew `docker docker-compose docker-buildx docker-credential-helper`; `~/.docker/config.json` (`credsStore: osxkeychain`, `cliPluginsExtraDirs: ["/opt/homebrew/lib/docker/cli-plugins"]`); bewijsbestand (deel 4); PR-beschrijving `feat/dev-docker-host` afronden.

**Interfaces.** Consumeert taak 4 en 5 (geslaagde proef). Produceert: Mac werkt zonder Desktop; terugvalrecept gedocumenteerd; PR ter review.

**Stappen.**
1. Fase 2: `docker context use max2-dev`; Desktop afsluiten en uit "Start bij inloggen" (Systeeminstellingen → Algemeen → Inloggen); `docker info --format '{{.Name}}'` → `max2`.
2. Fase 3: `brew install docker docker-compose docker-buildx docker-credential-helper`; `~/.docker/config.json` aanpassen (back-up eerst: `cp ~/.docker/config.json ~/.docker/config.json.bak-$(date +%F)`); controle met Desktop afgesloten: `which docker` → `/opt/homebrew/bin/docker`, `docker info`, `docker compose version`, `docker buildx version`, `docker login git.jp-visser.nl` via de keychain zonder credentials te tonen (`docker-credential-osxkeychain list` toont alleen registry-URL's).
3. Terugval beschreven in het bewijs: `docker context use desktop-linux` + Desktop starten. Fase 4 (Desktop verwijderen) is tijdgebonden (14 dagen zonder terugval) en komt als aparte taak in een volgende sprint, met de `pg_dumpall` van `local-postgres` naar `max2-dev:dev-docker/backups/`.
4. Bewijs deel 4; commit; push; PR-beschrijving van `feat/dev-docker-host` afronden (verwijzing naar het bewijsbestand en de vier delen) en ter review aan JP geven.

**Acceptatie.** Spec §11 rij 5; `docker context ls` toont `max2-dev` als standaard; Desktop niet actief tijdens de controles; PR ter review.

---

## Daarna (buiten dit increment; geen taken)

- Fase 4: Desktop en data verwijderen na 14 dagen zonder terugval (spec §5.2).
- Migratie van projectscripts (When2Watch `test:db:up`, Media-Organizer-allowlist, scrum4me-mcp `TEST_DATABASE_URL`): per product, met de skill als standaard.
- Ops-dashboard-paneel (eigen idee), Tailscale-publicatie, GPU-toegang, rollen per database (spec §2).

## Zelfcontrole van dit plan tegen de spec

- §4.1–§4.9 → taak 1 (bestanden), taak 2 (uitrol en controles via `proof-checks.sh`). §4.4-herstelproef → taak 2 stap 6; §4.4-controles na herstart/reboot → taak 5 stap 1 en 2. §4.7 prune → taak 1 stap 3 (selftest) en taak 4 stap 5 (dry-run op de host, registerstand vóór/ná).
- §5.1 → taak 2 stap 4 (alias) en stap 7 (context). §5.2 fase 1–3 → taak 2 stap 7 en taak 6; fase 4 → "Daarna". §5.3 → taak 3 (deadline, exit 3, geen terugval; tests (d)).
- §6 → taak 3 (helper, SKILL.md, symlinks, tests). §6.2-hostadres → afwijking 1.
- §7 → globale beperkingen; taak 1 (schijfwaarschuwing < 20 % in `prune.sh`/`last-run.json`, `status` toont ze); taak 3 (maskering); taak 4 stap 7 (secretscan). §8 → globale beperkingen (JP-besluit), taak 2 stap 1–4 (gate, sampler met ALARM en live bewaking), taak 4 stap 3 en 6 (bewaking, minimum).
- §9 stap 1–11 → taak 2 (1–4), 4 (5–9), 5 (10), 2/4/5/6 (11). §10 rollback → `dev-docker/README.md` (taak 1) neemt §10 letterlijk over; geen aparte taak.
- §11 rijen 1–10 → 1: taak 2/5; 2: taak 2/5; 3: taak 2 stap 7; 4: taak 2 stap 6 en taak 4 stap 3 (`systemd-cgtop`/`memory.peak`); 5: taak 6; 6: taak 2/4; 7: elke taak; 8: taak 2 stap 2; 9: taak 4 stap 5; 10: taak 3 (c)/(f)/(g) en taak 4.
- §12 open punten: test → afwijking 2; bind → taak 2 stap 5; digest/entrypoint → afwijking 3 en taak 1 stap 4; 8 GiB genoeg → taak 4 stap 3; s4m-queue-PR → taak 3; JP-besluit → genomen.
