# Praktijkproef IDEA-258 — deel 1: hostkant, LAN-grens, Mac-context (T-53)

**Datum:** 14-10-2026. **Uitvoerder:** mac:claude in opdracht van JP ("voer sprint uit"); root-regels door JP met `sudo` (`ssh -t`).
**Host:** `max2`, Ubuntu 26.04.1 LTS, systemd 259, Docker 29.9.0, runc 1.5.2, containerd 2.4.1, rootlesskit 3.2. **Bundel:** PR 34, branch `feat/dev-docker-host`.
Ruwe uitvoer staat in `evidence/dev-docker/raw/` (bestandsnamen hieronder). Dit bestand bevat geen wachtwoord; de URL-vorm in deze repo is altijd `…:***@…`.

## Afwijkingen tijdens deze run (details in PR 34)

| # | Wat | Gevolg |
|---|---|---|
| 7 | De gepinde digest `215ae4d4…` was de **arm64**-manifest; amd64 = `sha256:cd4ccfdaf62cbfeb5c6ee19ef0dd663406d4ed740c320b324d016a90e85385b3` | `compose.yml` en `images.txt` pinnen amd64 |
| 11 | **ufw is op max2 inactief** (`Status: inactive`, `INPUT`-policy `ACCEPT`; `raw/baseline-root.log`), terwijl spec en plan "actief, default-deny" aannamen (ISS-17) | JP-besluit A: de keten `dev-docker-in` is de enige LAN-grens; geen ufw-regel |
| 12 | Preflight vroeg `DelegateControllers` van de template `user@.service`; dat werkt niet (`raw/preflight.log` van de eerste run was daardoor rood) | instantie `user@<uid>.service` gebruikt |
| 13 | **Rootless containers starten niet**: runc 1.5.2 leest `OwnerUID=` uit `busctl --user status`, systemd 259 print die regel niet meer; runc kiest dan de systeem-bus ("Access denied … interactive authentication"). Gemeten: zelfs `docker run alpine:3` faalde (`raw/install-user-run1.txt`) | `busctl`-shim voor `docker.service` van devdock (`host/busctl-shim`); daarna werkt de systemd-cgroupdriver en geldt `--memory` per container |

## 1. Baseline en sampler (spec §9 stap 1)

- Productie-engine vóór: `raw/baseline-prod-before.txt` (ps, 21 regels), `raw/baseline-prod-before-2.txt` (images, `df`, `MemAvailable`).
- `ufw status verbose`, `ufw status numbered` en `iptables-save -t filter` als root: `raw/baseline-root.log` — `Status: inactive`, `:INPUT ACCEPT`.
- Sampler gestart als janpeter (`nohup bash ~/sampler.sh`, pid 1741022) om 14:30Z; ALARM-watcher op de Mac (`~/dev-docker-alarm.log`).

## 2. Gate en bootstrap (spec §9 stap 2)

- Invoer: `--floor-gib 12.0 --series '21.53:evidence/dev-docker/2026-10-12-p6-memavailable-max2.csv, 2026-10-12T10:46Z..2026-10-13T12:46Z, ~60 s-resolutie'`.
  Uitkomst: `X_eff=12.0 budget_gib=8 marge_gib=1.53`, `OK invoer en budget`.
- Eerste preflight (16:31): `PREFLIGHT ROOD (2)` — delegatie (afwijking 12) en ufw (afwijking 11); niets gewijzigd (`raw/preflight.log` is door de latere run overschreven; de rode uitkomst staat in ISS-17 en de PR).
- Tweede preflight (16:53): `PREFLIGHT GROEN` (`raw/preflight.log`).
- `bootstrap.sh` echt (`raw/bootstrap-1.log`): 15 × `CHANGED` (pakketten `uidmap slirp4netns`, gebruiker `devdock` uid 1001, subid `devdock:200000:65536`, authorized_keys, slice-drop-in, firewallscript en units, linger).
- Tweede run (`raw/bootstrap-2.log`): `0 × CHANGED`, `GEEN WIJZIGINGEN (uid=1001 MemoryMax=8589934592)`.
- Slice: `MemoryMax=8589934592`, `MemorySwapMax=0`, `CPUQuotaPerSecUSec=8s`, `TasksMax=4096`; `memory.max` = `8589934592` (`raw/proof-2.log`).

## 3. Engine (spec §9 stap 3)

- Alias `max2-dev` in `~/.ssh/config` (`HostName max2`, `User devdock`, `ConnectTimeout 5`, `ServerAliveInterval 15`, `ServerAliveCountMax 2`, `BatchMode yes`): `ssh max2-dev id` → `uid=1001(devdock) gid=1001(devdock) groups=1001(devdock)`.
- `rsync -a --delete dev-docker/host/ max2-dev:dev-docker-src/` en `install-user.sh`: run 1 stopte bij het starten van `dev-postgres.service` (afwijking 13, `raw/install-user-run1.txt`); run 2 slaagde (`raw/install-user-run2.txt`): `OK per-container geheugenlimiet werkt (memory.max=67108864)`, `dev-postgres: Up 6 seconds (healthy)`; run 3 (`raw/install-user-run3.txt`): `GEEN WIJZIGINGEN`.
- Units (devdock): `docker` active, `dev-postgres.service` `active (exited)`, `dev-docker-prune.timer` active (volgende run zondag 2026-10-18 04:30).
- Bind (spec §4.4, NO-GO-voorwaarde): `ss -ltn | grep 55432` → alleen `192.168.0.158:55432`; `docker ps` → `dev-postgres Up … (healthy) 192.168.0.158:55432->5432/tcp`. De builtin-poortdriver bindt dus op het LAN-adres.
- `prune.sh --dry-run` via SSH: exit 0, duur onder 1 s (`raw/prune-dry-run-max2.txt`); het pgvector-image `cd4ccfdaf62c` staat als `in gebruik`, de vier andere standaardimages als `standaardimage (images.txt)`; niets van de productie-engine genoemd. De deadline van 120 s in de helper is ruim.

## 4. LAN-grens en herstelproef (spec §9 stap 3, acceptatie 6)

Eén root-sessie: `proof-checks.sh --uid 1001 --wait-listener 200`, daarna `recovery-test.sh`, daarna `proof-checks.sh --uid 1001`.

| Moment | SUMMARY |
|---|---|
| vóór de herstelproef (`raw/proof-1.log`) | `jump_first=yes chain=ok jumps=1 testrule=0 listener=lan-only nc_ts=1 nc_lan=1 tick=skipped` |
| ná de herstelproef (`raw/proof-2.log`) | `jump_first=yes chain=ok jumps=1 testrule=0 listener=lan-only nc_ts=1 nc_lan=1 tick=skipped` |

- Eerste `-A`-regel van `INPUT`: `-A INPUT -m comment --comment dev-docker -j dev-docker-in`. Keten `dev-docker-in`: de twee DROP-regels (`! -i enp4s0` en `! -s 192.168.0.0/24 -i enp4s0`, beide `--ctstate NEW`, tcp/55432) gevolgd door `-j RETURN`.
- Herstelproef (`raw/recovery.log`): eerste regel na het invoegen van de testregel = `-A INPUT -s 192.0.2.254/32 -m comment --comment dd-recovery-test -j DROP` (sprong verplaatst); na `systemctl start dev-docker-firewall.service` weer `-A INPUT -m comment --comment dev-docker -j dev-docker-in`; telling `1`; journal: `dev-docker-firewall[…]: sprong naar dev-docker-in hersteld op INPUT-positie 1`. Geen `dd-recovery-test`-restant (`testrule=0`).
- `ss -tn 'sport = :55432'` na herstel: geen verbindingen. `nc -z -w2` vanaf max2 naar `100.102.8.64` en naar `192.168.0.158`: beide `rc=1` (geweigerd; de tweede bewijst dat de keten vuurt). De verbinding vanaf de Mac volgt in T-55.
- Geheugen: `memory.events` van de slice `max 0`, `oom_kill 0`; `memory.peak` 1,57 GB (indicatie, bevat page cache). `iptables-save -t filter` als momentopname in `raw/proof-1.log` en `raw/proof-2.log`. In beide logs is het journalblok van de dsh-/owui-firewallunits (elke minuut een run, ruim 23.000 regels) ingekort tot de eerste en laatste 100 regels; alle dev-docker-regels staan er volledig in. `proof-checks.sh` begrenst dit blok voortaan zelf.

## 5. Mac-context (spec §9 stap 4)

```
$ docker context create max2-dev --docker host=ssh://max2-dev
$ docker --context max2-dev info --format '{{.Name}} {{.SecurityOptions}}'
max2 [name=seccomp,profile=builtin name=rootless name=cgroupns]
$ docker --context max2-dev ps --filter name=dev-postgres --format '{{.Names}} {{.Status}} {{.Ports}}'
dev-postgres Up 14 seconds (healthy) 192.168.0.158:55432->5432/tcp
$ docker context ls     # default, desktop-linux (huidig, fase 1), max2-dev
```

## 6. Headroom en baseline productie (spec §8)

- Sampler (5 s, `~/dev-docker-proef-sampler.log`, 387 regels t/m 15:02Z): **minimum `MemAvailable` 23 460 492 kB = 22,37 GiB** (14:45:51Z), dus ≥ `X_eff` 12,0 GiB en ≥ 10,8 GiB; **0 ALARM-regels**. De testrun (T-55) en de sampler-stop volgen later; dit is het minimum tot en met de uitrol.
- Productie-engine na: `raw/baseline-prod-after.txt`, `raw/baseline-prod-after-2.txt`. De image-lijst is identiek (51 regels, gesorteerd diff leeg). Het enige verschil in `docker ps -a` zijn twee wegwerp-jobcontainers van de runners (`forgejo-runner-03-runner-run-…`, `forgejo-runner-runner-run-…`), verklaard door de CI-runs van PR 42 in deze periode. Vrije schijf: 624 781 553 664 → 622 969 860 096 bytes (−1,8 GB, de images en data van devdock).

## Acceptatie T-53

| Punt | Stand |
|---|---|
| Spec §9 acceptatie 1 (context: `max2` en `name=rootless`) | ja, §5 |
| Spec §9 acceptatie 5 (slice-limieten effectief) | ja, §2 en §4 |
| Spec §9 acceptatie 6 (sprong op 1, keten R1/R2/RETURN, geen testregel-restant, `ss`, beide `nc` geweigerd; vóór en na herstelproef) | ja, §4; vóór/na user-manager-herstart en reboot volgt in T-56 |
| Tweede bootstrap-run wijzigt niets | ja, §2 |
| Geen ALARM in de sampler | ja, §6 |
| Geen secret in het bewijs | `secretscan.sh` volledig vóór de commit van dit bestand |

# Deel 2 — praktijkproef T-55 (14-10-2026)

Aanroeppad: `max2-docker` (s4m-queue PR 42, `~/.local/bin/max2-docker`), `MAX2_DOCKER_AGENT=claude`. Databasenaam `s4mqueue_proef`.

## 7. Identiteit, argv-hygiëne, negatieve authenticatie (spec §9 stap 5–6, §11 rij 10)

Bron: `raw/t55-identiteit-argv-auth.txt`.

- `db create` gaf een gemaskeerde URL (`postgresql://dev:***@192.168.0.158:55432/s4mqueue_proef`); `db list` toont de rij met de aanvrager `mac:claude`.
- Identiteit: `s4mqueue_proef|dev|172.18.0.2|5432` (database, rol, containeradres, containerpoort).
- `client_addr` zoals gemeten: **172.18.0.1**, niet het LAN-adres van de Mac (`ipconfig getifaddr en0` = 192.168.0.50). Dat is het gateway-adres van het containernetwerk, vermoedelijk door de poortdoorgifte van de rootless engine (de oorzaak is niet apart gemeten). Zolang dat zo is, zien de bronadres-regels in `pg_hba.conf` geen LAN-adressen en kunnen ze LAN-clients niet onderscheiden. De LAN-grens ligt daarom, zoals ontworpen, in de keten `dev-docker-in` (§4.4) en niet in `pg_hba.conf`.
- Argv-hygiëne: 11 momentopnamen van de nakomelingen van de lopende `db run … pg_sleep(3)`, in 8 daarvan was `psql` zichtbaar, **0 TREFFER** op een URL-patroon met gebruikersnaam en wachtwoord.
- Negatief (met `PGPASSFILE=/dev/null`, `-w`): verkeerd wachtwoord → `password authentication failed for user "dev"`; leeg wachtwoord → `no password supplied`; rol `postgres` over TCP → `pg_hba.conf rejects connection for host "172.18.0.1", user "postgres"`.

## 8. Basislijn, Docker Desktop uit, testrun (spec §9 stap 7, §11 rij 7)

- Basislijn met Desktop aan (`raw/t55-baseline-npm-test.txt`, repo `~/Development/s4m-queue`, `main`, lokale `.env`): eerste poging 36 bestanden rood omdat de lokale test-database op `127.0.0.1:5433` niet draaide (afwijking 14: container `local-postgres-postgres-1` gestart en na de basislijn weer gestopt). Tweede poging: **63 bestanden groen, 4 rood** (462 tests groen, 18 overgeslagen). De vier rode zijn `test/ppe/{bootstrap-registry,controller-store,run-ledger,takeover}.test.ts`, alle met `PPE_CONTROLLER_DATABASE_URL_MISSING`: de variabele staat niet in de lokale omgeving. Dat is de basislijn en staat los van Docker.
- Docker Desktop afsluiten, vier controles in `raw/t55-desktop.txt`: vóór 11 processen en `docker --context desktop-linux info` slaagt (`docker-desktop`); na `osascript -e 'quit app "Docker"'` liepen app en backend nog (afwijking 15); na `tell application "Docker Desktop" to quit` blijft alleen het door launchd beheerde root-hulpproces `com.docker.vmnetd` over (geen app, geen VM) en faalt `info` met "failed to connect to the docker API".
- Testrun tegen max2 (`max2-docker db run s4mqueue_proef -- sh -c 'S4M_TEST_DATABASE_URL=$DATABASE_URL npm test'`, Desktop uit), twee keer (`raw/t55-testrun-1.log`, `raw/t55-testrun-2.log`): **62 bestanden groen, 5 rood**, 457 tests groen, 23 overgeslagen, 6,4 s. Rood: de vier `test/ppe`-bestanden uit de basislijn én **`test/work-item-permissions.test.ts`**: `permission denied to create role` bij `CREATE ROLE … NOLOGIN` (regel 44). De rol `dev` is `LOGIN CREATEDB` (spec §4.6) en mag geen rollen maken. Beide runs gaven hetzelfde resultaat.
- **Gevolg voor de acceptatie:** de slagingsregel "niets faalt op verbinding, rechten of host" is niet gehaald. Eén bestand faalt op rechten en niet in de basislijn. Het besluit ligt bij JP, zie "Besluit JP" onderaan.
- Slice (`user-1001.slice`, `raw/t55-cgtop.txt`, `systemd-cgtop` als janpeter want `devdock` krijgt "Failed to determine supported controllers"): geheugen tijdens de run 1,4–1,5 GB, 127–141 taken. `memory.peak` vóór 1 590 194 176, ná run 1 1 680 224 256, ná run 2 1 735 147 520 (limiet 8 589 934 592); `memory.events` `max 0`, `oom 0`, `oom_kill 0`; `anon` 110 534 656 → 123 772 928 → 130 363 392 bytes.

## 9. Register, opruiming, basislijn productie, sampler (spec §9 stap 9–10, §11 rij 9)

Bron: `raw/t55-cleanup-drop.txt`, `raw/baseline-prod-after-t55*.txt`, `raw/t55-sampler.txt`.

- `db list` vóór en na `cleanup --dry-run`: dezelfde rij (alleen de looptijd telt door), `s4mqueue_proef` bewaard als "jonger dan 14 dagen", `postgres` op de denylist, niets van de productie-engine; `dev-postgres` en het netwerk `dev-docker_default` bewaard (`dev.keep`), de volumestap meldt 0 kandidaten en `dev-postgres-data` bestaat nog. Het verslag meldt `dry_run: true`, schijf 63,5 % vrij.
- Afwijking 16: de dry-run noemde de buildcache altijd als kandidaat met afgekapte schatting ("Total:"). `prune.sh` leest nu `docker builder du` en meldt een lege buildcache niet meer; selftest 10 van 10 en een dry-run op max2 bevestigen het.
- `db drop s4mqueue_proef` → `db list` leeg; volgens `db list` en de dry-run bleven er geen `s4m_queue_bootstrap_*`-databases achter.
- Productie-engine na de proef (`baseline-prod-after-t55.txt`, `-2.txt`): de image-lijst is identiek aan de eerdere meting (gesorteerd diff leeg). Verschil in `docker ps -a` alleen de twee wegwerp-jobcontainers van de runners.
- Sampler gestopt na 541 regels (14:30:27Z t/m 15:15:37Z): **minimum `MemAvailable` 23 460 492 kB = 22,37 GiB** (14:45:51Z), **0 ALARM-regels**.

## Besluit JP en herhaling na `CREATEROLE` (14-10-2026)

JP koos voor `CREATEROLE` aan `dev` (via de vraag in de sessie). Doorgevoerd: `init/01-roles.sh` (`CREATE ROLE dev LOGIN CREATEDB CREATEROLE`), spec revisie 12 (§4.5, §4.9 en §7, niet opnieuw gereviewd) en op de draaiende instantie eenmalig `ALTER ROLE dev CREATEROLE` via de beheerroute (`docker --context max2-dev exec -i dev-postgres psql -U postgres`), omdat init-scripts alleen bij de eerste initialisatie draaien. Daarna `pg_roles`: `dev|rolsuper f|createdb t|createrole t|replication f|bypassrls f|login t`.

**Gemeten grenzen van de rol** (`raw/t55-rolecheck.txt`, als `dev` in `s4mqueue_proef`, PostgreSQL 17):

| Poging | Uitkomst |
|---|---|
| `CREATE ROLE … NOLOGIN` | slaagt |
| rol met `SUPERUSER`, `BYPASSRLS` of `REPLICATION` aanmaken | geweigerd (alleen rollen met dat attribuut mogen dat) |
| eigen rol lid maken van `pg_read_all_data` | geweigerd (ADMIN-optie op die rol ontbreekt) |
| `ALTER ROLE postgres PASSWORD …` | geweigerd (alleen een superuser wijzigt een superuser) |
| rol `postgres` lid maken van een door `dev` gemaakte rol | **slaagt**; verwachtte ik niet, het geeft `dev` zelf geen extra rechten |
| opruimen van de proefrol | slaagt, geen `zz_probe*` over |

## 10. Herhaalde testrun na `CREATEROLE` (spec §9 stap 7)

Zelfde opdracht, Desktop uit, nieuwe database `s4mqueue_proef` (`raw/t55-testrun-3.log`): **63 bestanden groen, 4 rood**, 462 tests groen, 18 overgeslagen, 6,5 s. Dat is gelijk aan de basislijn met Desktop aan: dezelfde vier `test/ppe`-bestanden rood met `PPE_CONTROLLER_DATABASE_URL_MISSING`, geen `permission denied`. `test/work-item-permissions.test.ts` slaagt nu.

- Slice (`raw/t55-cgtop-3.txt`): geheugen 1,5 GB, 139–154 taken. `memory.peak` ongewijzigd 1 735 147 520 (limiet 8 589 934 592), `memory.events` `max 0`, `oom 0`, `oom_kill 0`, `anon` 140 832 768 bytes.
- Opruiming (`raw/t55-cleanup-drop-3.txt`): dry-run laat `s4mqueue_proef` bewaren (jonger dan 14 dagen) en de buildcache als 0 kandidaten zien; `db drop`, daarna `db list` leeg. Op de instantie bestaan alleen de rollen `dev` en `postgres` en de database `postgres`: geen resten van de testrun.

## Acceptatie T-55 (stand)

| Punt | Stand |
|---|---|
| Spec §9 identiteit, negatieve authenticatie, argv-hygiëne | ja, §7 |
| Desktop aantoonbaar dicht tijdens de testrun | ja, §8 |
| Testrun: alle DB-afhankelijke bestanden slagen, geen verschil met de basislijn | ja, §10 (na besluit `CREATEROLE`; de eerste run faalde op één bestand, §8) |
| `memory.events` `max 0` en `oom_kill 0`, piek genoteerd | ja, §8 en §10 |
| Codex-sessie: één `db list` | ja: JP draaide `max2-docker db list` vanuit een Codex-sessie, exitcode 0, lege lijst (de proefdatabase was al verwijderd). Door JP gemeld, niet door mij gemeten; de skill staat via een symlink in `~/.codex/skills/` |
| `cleanup --dry-run` en register ongewijzigd | ja, §9 en §10 |
| `db drop`, basislijn productie gelijk, sampler zonder ALARM | ja, §9 |
