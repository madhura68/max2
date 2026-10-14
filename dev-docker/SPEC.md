# Spec — Dev-Docker op max2 voor de Mac (IDEA-258)

**Status:** concept ter review. **Datum:** 14-10-2026. **Auteur:** max2:claude (Claude Fable 5.1) in opdracht van JP.
**Bron:** grill IDEA-258 (Scrum4Me ProductDoc `GRILLS/idea-258-grill`, revisie `cmv7rt021000fyl174lrf4iyu`, sha256 `4c8c691a…0de3312`) en het onderzoeksrapport in PR 32 (`docs/reports/2026-10-14-codex-docker/`).
**Scope van dit document:** het volledige ontwerp plus de precieze inhoud van het eerste increment. Plan en taken volgen apart; dit document autoriseert geen uitvoering.

---

## 1. Doel

Claude en Codex op de Mac gebruiken Docker op `max2` zoals ze nu Docker Desktop gebruiken, maar zonder Docker Desktop. Er staat standaard één PostgreSQL klaar waarin elke taak in één opdracht een eigen database krijgt. Opruimen gebeurt wekelijks en automatisch. Productie op `max2` kan vanaf de Mac niet per ongeluk worden geraakt.

**Resultaat na het eerste increment:** een bestaande PostgreSQL-integratietest slaagt vanaf de Mac tegen een database op `max2`, aangemaakt via de skill, met Docker Desktop afgesloten. Niets op de productie-engine is aangeraakt.

## 2. Scope

### In scope (eerste increment)

1. Hostkant op `max2`: gebruiker `devdock`, rootless Docker-engine, capaciteitsplafond, firewallregel, `dev-postgres`, registertabel, prune-timer, standaardimages.
2. Mac-kant: SSH-alias, Docker-context `max2-dev`, fasering van de standaardcontext.
3. Skill `max2-docker` met helperscript, in de s4m-queue-repo, gesymlinkt voor Claude én Codex.
4. Praktijkproef met bewijsbestand in deze repo.

### Buiten scope

- Migratie van projectscripts (When2Watch `test:db:up`, Media-Organizer host-allowlist): per product, daarna.
- Ops-dashboard-paneel: eigen idee op het Ops-dashboard-product.
- Werken buiten het thuisnetwerk (Tailscale op de Mac).
- GPU-toegang vanuit de dev-engine.
- Een remote Codex-project op `max2` (route 2 uit PR 32).

## 3. Architectuur

```
Mac (één macOS-gebruiker; Claude en Codex delen hem)
│
│  docker --context max2-dev …          SSH, sleutel van janpetervisser
├──────────────────────────────────────▶ max2: devdock (rootless dockerd, user-slice met plafond)
│                                         ├─ dev-postgres  (pgvector/pgvector:pg17, 192.168.0.158:55432)
│                                         │    └─ devmeta.databases  (register: naam, aanmaakdatum, keep)
│                                         ├─ wegwerpcontainers  (label dev.owner=mac)
│                                         └─ dev-docker-prune.timer  (zondag 04:30, leeftijdsgebaseerd)
│
│  DATABASE_URL=postgresql://dev:…@max2:55432/<project>_<taak>
└──────────────────────────────────────▶ dev-postgres, rechtstreeks over het LAN (ufw-regel)

max2: productie-engine (rootful, /var/run/docker.sock) — onaangeraakt.
Uitrol van producten blijft `ssh max2 docker …` onder janpeter.
```

**Kernkeuzes** (uit de grill): aparte rootless engine; Docker-API over SSH; databaseverkeer direct over het LAN; één vaste Postgres met database per taak; wekelijks leeftijdsgebaseerd opruimen met opt-out; hard plafond op de user-slice.

## 4. Hostkant `max2`

Alle bestanden onder `dev-docker/host/` in deze repo. Bootstrap is idempotent: opnieuw draaien verandert niets aan een correct ingerichte host.

### 4.1 Gebruiker `devdock`

| Eigenschap | Waarde |
|---|---|
| Naam | `devdock` |
| Shell | `/bin/bash` |
| Groepen | alleen de eigen groep; **niet** `docker`, **niet** `sudo` |
| subuid/subgid | `devdock:200000:65536` (janpeter heeft `100000:65536`; geen overlap) |
| Linger | `loginctl enable-linger devdock` (engine en timer draaien zonder login) |
| SSH | `~/.ssh/authorized_keys` met de bestaande publieke sleutel van de Mac; zelfde beperking als nu: geen wachtwoordlogin |
| Home | `/home/devdock` |

`bootstrap.sh` (root via `sudo`, uitgevoerd door janpeter) maakt de gebruiker, de subid-ranges, linger, de slice-drop-in en de ufw-regel. Het script weigert te draaien als een bestaand object afwijkt van de verwachte waarde en meldt wat afwijkt, in plaats van het te overschrijven.

### 4.2 Rootless engine

- Installatie als `devdock`: `dockerd-rootless-setuptool.sh install` (pakketten `docker-ce-rootless-extras` en `rootlesskit` staan al op max2, Docker 29.9.0).
- Socket: `/run/user/<uid>/docker.sock`. De setuptool maakt context `rootless`; `install-user.sh` zet `docker context use rootless` voor devdock. Dit is nodig omdat de Docker-SSH-route (`docker system dial-stdio`) in een niet-interactieve shell draait waar `DOCKER_HOST` uit een profiel niet geladen wordt.
- Systemd user unit `docker.service` enabled; data-root blijft standaard `~/.local/share/docker`.
- Poortdriver: `builtin` (standaard). Poorten < 1024 zijn niet nodig (`ip_unprivileged_port_start=1024`).
- Geen `daemon.json`-aanpassingen in het eerste increment.

### 4.3 Capaciteitsplafond

Drop-in `/etc/systemd/system/user-<uid>.slice.d/50-dev-docker.conf` (uid van devdock wordt door bootstrap ingevuld):

```ini
[Slice]
MemoryMax=8G
MemorySwapMax=0
CPUQuota=800%
TasksMax=4096
```

Alles van devdock (rootless dockerd, alle containers, de timer) valt onder deze slice. Richtwaarden; aanpasbaar zonder ontwerpwijziging. cgroup v2 met `cpu memory pids` gedelegeerd is op max2 aanwezig, zodat ook per-container `--memory`/`--cpus` werkt.

### 4.4 Netwerk en firewall

- ufw is actief op max2. Rootless publiceert poorten via rootlesskit in de host-netwerknamespace en valt daarmee **wel** onder ufw (anders dan de rootful engine).
- Regel: `ufw allow from 192.168.0.0/24 to any port 55432 proto tcp comment 'dev-postgres (IDEA-258)'`.
- Publicatie: `192.168.0.158:55432:5432`. Lukt binden op een specifiek adres niet met de builtin-driver, dan `0.0.0.0:55432:5432` met de ufw-regel als grens. Dit wordt in de proef vastgesteld en in het bewijsbestand vastgelegd.
- Geen Tailscale-publicatie in het eerste increment.

### 4.5 dev-postgres

Compose-stack in `/home/devdock/dev-docker/` (bron: `dev-docker/host/compose.yml`):

| Onderdeel | Waarde |
|---|---|
| Image | `pgvector/pgvector:pg17`, gepind op amd64-digest in `compose.yml` |
| Container | `dev-postgres`, `restart: unless-stopped`, label `dev.role=postgres` |
| Poort | `192.168.0.158:55432:5432` (zie 4.4) |
| Volume | named volume `dev-postgres-data` |
| Env | `POSTGRES_USER=dev`, `POSTGRES_DB=postgres`, `POSTGRES_PASSWORD` uit `/home/devdock/dev-docker/.env` (0600) |
| Resources | `mem_limit: 2g`, `shm_size: 256m` |
| Healthcheck | `pg_isready -U dev` |
| Init | `init/01-devmeta.sql` maakt schema `devmeta` en de registertabel |

Het wachtwoord wordt door `install-user.sh` gegenereerd (`openssl rand -base64 24`) en alleen in `.env` geschreven. Het staat nooit in deze repo, nooit in de s4m-queue-repo en wordt op de Mac niet op schijf gezet.

### 4.6 Registertabel

```sql
CREATE SCHEMA IF NOT EXISTS devmeta;
CREATE TABLE IF NOT EXISTS devmeta.databases (
  name        text PRIMARY KEY,
  created_at  timestamptz NOT NULL DEFAULT now(),
  created_by  text NOT NULL,          -- 'mac:claude' | 'mac:codex' | 'mac:jp' | 'prune:first-seen'
  keep        boolean NOT NULL DEFAULT false,
  note        text
);
```

De helper registreert elke database die hij aanmaakt. De prune registreert databases die buiten de helper om zijn gemaakt met `created_by='prune:first-seen'` en de datum van de eerste waarneming; ze krijgen zo dezelfde 14-daagse klok. Systeemdatabases (`postgres`, `template0`, `template1`) staan nooit in het register en worden nooit verwijderd.

### 4.7 Prune-timer

Systemd user units van devdock: `dev-docker-prune.service` + `dev-docker-prune.timer` (`OnCalendar=Sun *-*-* 04:30:00`, `Persistent=true`). Script `prune.sh` met `--dry-run`. Volgorde:

1. **Wegwerpcontainers:** alle containers behalve `dev-postgres`, zonder label `dev.keep=true`, met `Created` ouder dan 7 dagen: stop + verwijder.
2. **Volumes:** dangling volumes behalve `dev-postgres-data`: verwijder. (Docker bewaart geen aanmaakdatum per volume; een volume dat nog aan een container hangt blijft.)
3. **Databases:** registerrijen met `keep=false` en `created_at < now() - interval '14 days'`: actieve verbindingen beëindigen, `DROP DATABASE`, rij verwijderen. Onbekende databases eerst registreren (4.6), nooit direct droppen.
4. **Images en buildcache:** `docker system prune -af` (het image van `dev-postgres` is in gebruik en blijft).
5. **Standaardimages:** `pull-images.sh` opnieuw (4.8).
6. **Verslag:** journal plus `/home/devdock/dev-docker/prune.log` en `last-run.json` (tijdstip, aantallen, fouten). `max2-docker status` toont de laatste run.

`--dry-run` toont elke kandidaat zonder iets te wijzigen; dat is wat `max2-docker cleanup --dry-run` op de Mac aanroept.

### 4.8 Standaardimages

`images.txt`: `pgvector/pgvector:pg17`, `node:24-bookworm-slim`, `node:22-bookworm-slim`, `debian:bookworm-slim`, `alpine:3`. `pull-images.sh` pullt ze voor `linux/amd64` en faalt luid bij een pull-fout. Niet standaard: `ubuntu:24.04`, `docker:cli`.

### 4.9 Bestanden in deze repo

```
dev-docker/
  SPEC.md                  dit document
  README.md                korte bediening (volgt met de implementatie)
  host/
    bootstrap.sh           root: gebruiker, subid, linger, slice-drop-in, ufw-regel
    install-user.sh        devdock: rootless engine, context, compose, timer, images
    compose.yml            dev-postgres
    init/01-devmeta.sql    registertabel
    prune.sh               opruimen, met --dry-run
    pull-images.sh / images.txt
    systemd/dev-docker-prune.service, dev-docker-prune.timer
    systemd/50-dev-docker.conf   slice-drop-in (sjabloon)
evidence/dev-docker/       bewijs van de praktijkproef en latere metingen
```

Plaatsing volgt de bestaande repo-conventie (`deepseek-harness/`, `open-webui/`: componentmap met `host/`); de grill noemde `hosts/max2/dev-docker/`, maar `hosts/max2/` is in `CLAUDE.md` gereserveerd voor de runner-overlay.

## 5. Mac-kant

### 5.1 SSH en Docker-context

- `~/.ssh/config`: alias `max2-dev` met `HostName max2`, `User devdock`, dezelfde `IdentityFile` als de bestaande `max2`-alias.
- `docker context create max2-dev --docker host=ssh://max2-dev`.
- Bewijs: `docker --context max2-dev info --format '{{.Name}} {{.SecurityOptions}}'` toont `max2` en `name=rootless`.

### 5.2 Fasering van de standaardcontext en Docker Desktop

| Fase | Wanneer | Wat |
|---|---|---|
| 1 | Nu | Alles via `--context max2-dev`; Desktop draait nog |
| 2 | Direct na geslaagde proef | `docker context use max2-dev`; Desktop afsluiten en uit "Start bij inloggen" |
| 3 | 14 dagen zonder terugval | `pg_dumpall` van `local-postgres` naar `max2:/home/devdock/dev-docker/backups/` (30 dagen bewaren); Docker Desktop en zijn data verwijderen |
| 4 | Direct na 3 | Homebrew: `docker`, `docker-compose`, `docker-buildx`, `docker-credential-helper`; `~/.docker/config.json`: `credsStore: osxkeychain`, `cliPluginsExtraDirs` naar de Homebrew-plugins; registry-login opnieuw controleren |

Een terugval in fase 2 of 3 (iets heeft Desktop toch nodig) wordt in `evidence/dev-docker/` genoteerd en pauzeert de volgende fase.

### 5.3 Gedrag bij onbereikbaar max2

Is `max2` onbereikbaar, dan stopt de opdracht met een duidelijke fout. Er is **geen** automatische terugval naar een lokale engine; dat zou de migratie oncontroleerbaar maken (PR 32, §6).

## 6. Skill `max2-docker`

Bron: `.claude/skills/max2-docker/` in de s4m-queue-repo, gesymlinkt naar `~/.claude/skills/max2-docker` en `~/.codex/skills/max2-docker` (zelfde patroon als `s4m-queue`). Codex deelt de macOS-gebruiker, SSH-sleutel en Docker-config; aparte configuratie is niet nodig. Dat Codex vanuit zijn shell `docker -H ssh://…` kan uitvoeren is in PR 32 bewezen.

### 6.1 SKILL.md (inhoud op hoofdlijnen)

- **Wanneer:** elke keer dat een sessie op de Mac een container, image-build of testdatabase nodig heeft.
- **Regels:** altijd de dev-engine (`max2-dev`); nooit `ssh max2 docker …` onder janpeter voor dev-werk; databasenaam `<project>_<taak>`; wegwerpcontainers met label `dev.owner=mac` en een unieke naam met taakcode; `dev.keep=true` of `db keep` alleen met reden; aan het einde van een taak de eigen database droppen tenzij `keep`; de URL alleen aan het testproces doorgeven, niet in bestanden of logs schrijven.
- **Commando's:** zie 6.2, met voorbeelden voor `DATABASE_URL` in een testrun.
- **Fouten:** onbereikbaar max2 → stoppen (5.3); naam al in gebruik → bestaande URL hergebruiken, geen nieuwe container.

### 6.2 Helperscript `scripts/max2-docker` (bash)

| Commando | Gedrag |
|---|---|
| `status` | Engine-info (`max2`, rootless), `dev-postgres`-health, aantal databases en containers, laatste prune-run uit `last-run.json` |
| `db create <naam> [--keep] [--by <adres>] [--note <tekst>]` | Valideert `^[a-z][a-z0-9_]{2,62}$`; maakt de database als hij niet bestaat; registreert in `devmeta.databases`; print `DATABASE_URL=postgresql://dev:<pw>@max2:55432/<naam>` op stdout. Idempotent: bestaat de naam al, dan dezelfde URL |
| `db url <naam>` | Alleen de URL |
| `db drop <naam>` | Beëindigt verbindingen, dropt de database, verwijdert de registerrij; weigert systeemdatabases |
| `db list` | Naam, aanmaakdatum, `created_by`, `keep`, leeftijd |
| `db keep <naam> on\|off` | Zet de opt-out |
| `cleanup --dry-run` | Draait `prune.sh --dry-run` op max2 via SSH en toont de kandidaten |
| `images` | Standaardimages en hun aanwezigheid |

Implementatiekeuzes: alle databaseacties lopen via `docker --context max2-dev exec -i dev-postgres psql …` (geen `psql` op de Mac vereist); het wachtwoord komt uit `docker … exec dev-postgres printenv POSTGRES_PASSWORD` en blijft in procesgeheugen; `--by` default `mac:${MAX2_DOCKER_AGENT:-unknown}` (Claude en Codex zetten de variabele in de skill-instructie); exitcodes: 0 ok, 2 invoerfout, 3 max2 onbereikbaar, 4 dev-postgres niet gezond.

## 7. Beveiliging

- **Scheiding:** devdock heeft geen sudo, geen toegang tot `/var/run/docker.sock`, geen hostpaden buiten zijn home. Een `docker rm` vanaf de Mac kan alleen dev-resources raken.
- **Secrets:** Postgres-wachtwoord alleen in `/home/devdock/dev-docker/.env` (0600) en in de container-env. Niet in Git, niet op de Mac-schijf, niet in Scrum4Me-issues.
- **Bereik:** Postgres is bereikbaar voor het LAN-subnet; het wachtwoord is de grens. Dev-data bevat per afspraak geen productiegegevens.
- **SSH:** bestaande sleutel; wachtwoordlogin blijft uit.

## 8. Capaciteit en de runnerpool

De runnerpool rekent met een headroomgate op de laagste `MemAvailable` onder eigen productielast (migratieontwerp §7.8, `scrum4me-server`-repo). Daarom:

1. Vóór bootstrap: `MemAvailable` en `docker system df` van de productie-engine vastleggen in `evidence/dev-docker/`.
2. Na bootstrap en na de proef: opnieuw meten, met `systemd-cgtop` voor de devdock-slice.
3. Het plafond (8 GiB) blijft binnen de huidige vrije ruimte (ca. 24 GiB). Zakt de gate onder de §7.8-drempel, dan is dat een NO-GO voor fase 2 en wordt het plafond verlaagd, niet de gate.

## 9. Praktijkproef (eerste increment)

**Keuze van de test:** een bestaande integratietest die al een `DATABASE_URL`-variabele accepteert (usage-ledger/M48 of QR-login, zie PR 32 §4). Welke precies wordt in het plan vastgelegd met repo, branch en commando.

**Stappen**

1. Baseline: `docker ps -a` en `docker images` van de productie-engine (`ssh max2 docker …`), `MemAvailable`, `ufw status numbered`.
2. `bootstrap.sh` (root) en `install-user.sh` (devdock) uitvoeren; `systemctl --user status docker` en de timer controleren.
3. Mac: alias, context, `docker --context max2-dev info`.
4. `max2-docker db create <project>_proef` → URL; `psql`-identiteitscheck via `docker exec` (`select current_database(), inet_server_addr()`).
5. Testrun met die URL vanaf de Mac; Docker Desktop **afgesloten** vóór de run.
6. Codex: één `max2-docker db list` vanuit een Codex-sessie.
7. `max2-docker cleanup --dry-run`; daarna `db drop`.
8. Baseline opnieuw: productie-engine ongewijzigd (zelfde container-ID's en image-ID's).
9. Bewijsbestand `evidence/dev-docker/2026-MM-DD-praktijkproef.md`: commando's, uitvoer (zonder wachtwoord), container-/database-identiteit, testuitslag, baselinevergelijking, metingen uit §8.

**Acceptatie** (alle punten):

- `docker --context max2-dev info` geeft `max2` en `name=rootless`.
- `db create` levert een werkende URL; de test slaagt vanaf de Mac met Desktop afgesloten.
- Geen productiecontainer of -image is gewijzigd (baseline vóór/na identiek).
- `cleanup --dry-run` toont de proefdatabase als niet-kandidaat (jonger dan 14 dagen) en niets van productie.
- Codex heeft de skill één keer succesvol aangeroepen.
- De metingen uit §8 zijn vastgelegd en de gate is niet gezakt.

Een geslaagde `docker info` alleen haalt deze acceptatie niet.

## 10. Rollback

Volledig omkeerbaar zonder productie te raken: `systemctl --user disable --now` van engine en timer als devdock, `loginctl disable-linger devdock`, ufw-regel verwijderen, slice-drop-in verwijderen, gebruiker en home verwijderen (`userdel -r`), op de Mac de context en de alias verwijderen. Docker Desktop wordt pas in fase 3 verwijderd, dus tot dan is terugvallen een kwestie van `docker context use desktop-linux`.

## 11. Te verifiëren in de proef (uit de grill)

| # | Punt | Hoe |
|---|---|---|
| 1 | ufw laat 55432 vanaf het LAN door en verder niets nieuws | `ufw status numbered` vóór/na; verbinding vanaf de Mac |
| 2 | Rootless kan op `192.168.0.158` binden | compose up; anders terugval naar `0.0.0.0` (4.4) |
| 3 | Docker-over-SSH vindt de rootless socket zonder login-shell | `docker --context max2-dev info` |
| 4 | Slice-plafond omvat dockerd en containers | `systemd-cgtop`, `systemctl status user-<uid>.slice` |
| 5 | Mac-CLI zonder Desktop | fase 4, pas na 14 dagen |
| 6 | Headroomgate niet gezakt | §8 |
| 7 | Geen secrets in Git | `git grep` op wachtwoordpatronen vóór elke commit |

## 12. Open punten

- Exacte test en repo voor de praktijkproef (plan).
- Of `MemoryMax=8G` ruim genoeg is voor één Node-testrun plus Postgres; eerste meting in de proef.
- Beheer van de s4m-queue-repo: de skill komt daar in een eigen PR; volgorde: hostkant eerst, skill daarna, proef als laatste.
