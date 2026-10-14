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
