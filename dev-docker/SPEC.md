# Spec — Dev-Docker op max2 voor de Mac (IDEA-258)

**Status:** concept, revisie 8 (na reviewronde 7). **Datum:** 14-10-2026. **Auteur:** max2:claude (Claude Fable 5.1) in opdracht van JP.
**Bron:** grill IDEA-258 (Scrum4Me ProductDoc `GRILLS/idea-258-grill`, revisie `cmv7rt021000fyl174lrf4iyu`) en het onderzoeksrapport in PR 32 (`docs/reports/2026-10-14-codex-docker/`). Reviewrecord: `docs/reviews/2026-10-14-idea-258-dev-docker-spec-review-record.md`.
**Scope van dit document:** het volledige ontwerp plus de precieze inhoud van het eerste increment. Plan en taken volgen apart; dit document autoriseert geen uitvoering.

---

## 1. Doel

Claude en Codex op de Mac gebruiken Docker op `max2` zoals ze nu Docker Desktop gebruiken, maar zonder Docker Desktop. Er staat standaard één PostgreSQL klaar waarin elke taak in één opdracht een eigen database krijgt. Opruimen gebeurt wekelijks en automatisch. Productie op `max2` kan vanaf de Mac niet per ongeluk worden geraakt.

**Resultaat na het eerste increment:** een bestaande PostgreSQL-integratietest slaagt vanaf de Mac tegen een database op `max2`, aangemaakt via de skill, met Docker Desktop afgesloten. Niets op de productie-engine is aangeraakt.

## 2. Scope

### In scope (eerste increment)

1. Hostkant op `max2`: gebruiker `devdock`, rootless Docker-engine, capaciteitsplafond met headroomgate, firewallregel, `dev-postgres`, registertabel, prune-timer, standaardimages.
2. Mac-kant: SSH-alias, Docker-context `max2-dev`, fasering van de standaardcontext en van Docker Desktop.
3. Skill `max2-docker` met helperscript, in de s4m-queue-repo, gesymlinkt voor Claude én Codex.
4. Praktijkproef met bewijsbestand in deze repo.

### Buiten scope

- Migratie van projectscripts (When2Watch `test:db:up`, Media-Organizer host-allowlist): per product, daarna.
- Ops-dashboard-paneel: eigen idee op het Ops-dashboard-product.
- Werken buiten het thuisnetwerk (Tailscale op de Mac).
- GPU-toegang vanuit de dev-engine.
- Een remote Codex-project op `max2` (route 2 uit PR 32).
- Rollen of wachtwoorden per database: één dev-rol voor alle databases (zie §7, restrisico).

## 3. Architectuur

```
Mac (één macOS-gebruiker; Claude en Codex delen hem)
│
│  docker --context max2-dev …          SSH, sleutel van janpetervisser
├──────────────────────────────────────▶ max2: devdock (rootless dockerd, user-slice met plafond)
│                                         ├─ dev-postgres  (pgvector/pgvector:pg17, gebonden aan 192.168.0.158:55432; ufw als tweede grens)
│                                         │    └─ devmeta.databases  (register: naam, aanmaakdatum, keep)
│                                         ├─ wegwerpcontainers  (label dev.owner=mac)
│                                         └─ dev-docker-prune.timer  (zondag 04:30, leeftijdsgebaseerd)
│
│  max2-docker db run <naam> -- <testcommando>   (DATABASE_URL en PG*-variabelen alleen in de omgeving van het kindproces)
└──────────────────────────────────────▶ dev-postgres, rechtstreeks over het LAN (ufw-regel)

max2: productie-engine (rootful, /var/run/docker.sock) — onaangeraakt.
Uitrol van producten blijft `ssh max2 docker …` onder janpeter.
```

**Kernkeuzes** (uit de grill): aparte rootless engine; Docker-API over SSH; databaseverkeer direct over het LAN; één vaste Postgres met database per taak; wekelijks leeftijdsgebaseerd opruimen met opt-out; hard plafond op de user-slice.

## 4. Hostkant `max2`

Alle bestanden onder `dev-docker/host/` in deze repo. De uitrol gaat vanaf de Mac over SSH (CLAUDE.md: "Uitrol gaat handmatig of via SSH vanaf mac"): `bootstrap.sh` als root via janpeter (bestand eerst kopiëren, dan met tty uitvoeren, §4.1), daarna `install-user.sh` als devdock via een echte SSH-login (§4.2). Bronbestanden en de compose-map blijven op max2 gescheiden: bronnen in `~/dev-docker-src/` (per `rsync --delete` gesynchroniseerd), de draaiende stack in `~/dev-docker/`. Beide scripts zijn idempotent: opnieuw draaien verandert niets aan een correct ingerichte host en weigert bij afwijkingen in plaats van te overschrijven.

### 4.1 Gebruiker `devdock` en bootstrap (root)

| Eigenschap | Waarde |
|---|---|
| Naam | `devdock` |
| Shell | `/bin/bash` |
| Groepen | alleen de eigen groep; **niet** `docker`, **niet** `sudo` |
| subuid/subgid | `devdock:200000:65536` (janpeter heeft `100000:65536`; geen overlap) |
| Linger | `loginctl enable-linger devdock` (engine en timer draaien zonder login) |
| SSH | `~/.ssh/authorized_keys` met de bestaande publieke sleutel van de Mac; wachtwoordlogin blijft uit |
| Home | `/home/devdock` |

`bootstrap.sh` en de publieke sleutel worden als bestanden gekopieerd en het script wordt met een tty uitgevoerd, zodat `sudo` om het wachtwoord van janpeter kan vragen en argumenten en stdin niet door elkaar lopen. De remote opdracht is één gequoteerde string, omdat `ssh` de argumenten samenvoegt en de remote shell ze opnieuw splitst:

```sh
KEY=$(ssh -G max2 | awk '/^identityfile /{print $2; exit}'); KEY=${KEY/#\~/$HOME}   # ssh -G geeft de tilde onverwerkt terug
test -r "$KEY.pub" || { echo "geen publieke sleutel naast $KEY"; exit 1; }   # de sleutel waarmee de max2-alias nu inlogt
scp -r dev-docker/host/bootstrap.sh dev-docker/host/dev-docker-firewall.sh dev-docker/host/systemd "$KEY.pub" max2:/tmp/
ssh -t max2 "sudo bash /tmp/bootstrap.sh --pubkey-file '/tmp/$(basename "$KEY").pub' --floor-gib <X> \
  --series '21.53:evidence/dev-docker/2026-10-12-p6-memavailable-max2.csv, 2026-10-12T10:46Z..2026-10-13T12:46Z, ~60 s-resolutie'"
```

Staan er meerdere `IdentityFile`-regels of is de sleutel alleen in de agent, dan geeft JP het pad expliciet. `--floor-gib <X>` is verplicht (geen standaardwaarde; X is JP's besluit, §8.2/§12) en wordt met `--series` in het bewijsbestand vastgelegd. Validatie vóór iedere mutatie: `--floor-gib` en de GiB-waarden van `--series` zijn eindige decimale getallen met punt (`^[0-9]+(\.[0-9]+)?$`), de effectieve vloer is `X_eff = max(X, 10.8)` in GiB (de U4-rode lijn kan niet onderschreden worden, §8.2); ongeldige invoer is exit 2 zonder wijziging, met de melding "gebruik een punt als decimaalteken" (JP schrijft in proza `12,0`; de opdrachtregel wil `12.0`). `--series <GiB>:<bron>` is herhaalbaar en wordt op de **eerste** dubbele punt gesplitst; de bron is vrije tekst. Alleen reeksen van ≥ 24 uur tellen (§8); de stap-A-momentopname van 19,59 GiB is géén reeks en wordt niet meegegeven. Bij meerdere reeksen neemt het script de laagste waarde. Het zet `DEBIAN_FRONTEND=noninteractive` en voert `apt-get` met `</dev/null` uit. Volgorde:

1. **Preflight (read-only, faalt vóór iedere mutatie):** headroomgate en budget uit §8 (weigert zonder invoer en bij een budget onder 2 GiB); `kernel.apparmor_restrict_unprivileged_userns` en aanwezigheid van `/etc/apparmor.d/rootlesskit`; `dpkg -s docker-ce-rootless-extras`; cgroup v2 met `cpu memory pids` in `DelegateControllers` van `user@.service`; ufw actief met `Default: deny (incoming)`; `iptables-save -t filter` (als root) gaat als momentopname in het bewijsbestand. De LAN-grens wordt **niet** afgeleid uit een semantische doorloop van de bestaande ketens (Tailscale draait in netfilter-modus 2 en zet standaard `-i tailscale0 -j ACCEPT` in `ts-input`; de host heeft eigen INPUT-regels buiten ufw, zie `deepseek-harness/host/dsh-firewall.sh` en `open-webui/host/owui-firewall.sh`), maar afgedwongen door twee eigen DROP-regels **bovenaan** `INPUT` (§4.4), zodat de rest van de policy er niet toe doet; `sshd -T` zonder `AllowUsers`/`AllowGroups` die devdock zouden uitsluiten (gemeten: alleen `PasswordAuthentication no`); subuid-range `200000:65536` vrij; geen bestaande gebruiker `devdock` met afwijkende instellingen.
2. **Pakketten:** `apt-get install -y uidmap slirp4netns` (gemeten 14-10-2026: beide ontbreken op max2; `dockerd-rootless-setuptool.sh check --force` eist `uidmap`; rootlesskit heeft `slirp4netns` of `pasta` nodig voor netwerk).
3. Gebruiker en subid-ranges; `authorized_keys` uit `--pubkey-file` (het script leest nooit een private sleutel).
4. Slice-drop-in (§4.3) met de uit de gate berekende `MemoryMax`; firewallscript naar `/usr/local/sbin/dev-docker-firewall.sh` en de units `dev-docker-firewall.service`/`.timer` (met ingevulde uid) naar `/etc/systemd/system/`; `systemctl daemon-reload`; `systemctl enable --now dev-docker-firewall.timer dev-docker-firewall.service`; **daarna pas** `loginctl enable-linger devdock`, zodat `user@<uid>.service` meteen onder het plafond start. Controle: `systemctl show user-<uid>.slice -p MemoryMax -p MemorySwapMax -p CPUQuotaPerSecUSec -p TasksMax` en, zodra de user-manager draait, `cat /sys/fs/cgroup/user.slice/user-<uid>.slice/memory.max`.
5. ufw-regel (§4.4).

Gemeten voorwaarden op max2 (14-10-2026): `kernel.apparmor_restrict_unprivileged_userns=1`, maar `/etc/apparmor.d/rootlesskit` bestaat (profiel voor `/usr/bin/rootlesskit` met `userns`, `flags=(unconfined)`), dus rootlesskit mag user-namespaces maken; `rootlesskit 3.2.0`; `docker-ce-rootless-extras 5:29.9.0`; `user@.service`: `Delegate=yes`, `DelegateControllers=cpu memory pids`; `uidmap`, `slirp4netns`, `passt` niet geïnstalleerd, wel beschikbaar in apt.

### 4.2 Rootless engine (`install-user.sh`, als devdock)

- **Uitvoering:** vanaf de Mac, als echte SSH-login zodat pam_systemd een gebruikerssessie met `XDG_RUNTIME_DIR=/run/user/<uid>`, D-Bus en de user-manager start. Eerst de alias `max2-dev` (§5.1), dan: `rsync -a --delete dev-docker/host/ max2-dev:dev-docker-src/ && ssh max2-dev bash dev-docker-src/install-user.sh`. `rsync --delete` is idempotent en voorkomt dat een tweede run een oude kopie uitvoert; het script kopieert `compose.yml`, `init/`, `prune.sh`, `pull-images.sh`, `images.txt` en de units van `~/dev-docker-src/` naar `~/dev-docker/` en de systemd-map. Niet via `sudo -u devdock` of `su`: daar ontbreken de sessie en de bus en faalt de setuptool. devdock kan de checkout van janpeter niet lezen; de bestanden komen dus per `rsync` mee.
- **Installatie:** `dockerd-rootless-setuptool.sh install` (vereist `uidmap` en `slirp4netns` uit §4.1 stap 2). Socket `/run/user/<uid>/docker.sock`; systemd user unit `docker.service` enabled; data-root standaard `~/.local/share/docker`.
- **Context:** de setuptool maakt context `rootless`; het script zet `docker context use rootless` voor devdock. Dit is nodig omdat de Docker-SSH-route (`docker system dial-stdio`) in een niet-interactieve shell draait waar `DOCKER_HOST` uit een profiel niet geladen wordt; de context staat in `~/.docker/config.json` en werkt daar wel.
- **CLI-plugins:** compose en buildx staan hostbreed in `/usr/libexec/docker/cli-plugins` (gemeten) en zijn voor devdock beschikbaar.
- Poortdriver `builtin` (standaard); netwerkdriver `slirp4netns`. Poorten < 1024 zijn niet nodig (`ip_unprivileged_port_start=1024`). Geen `daemon.json`-aanpassingen in het eerste increment.
- Daarna: compose en de user-unit `dev-postgres.service` (§4.5), timer (§4.7), images (§4.8). `install-user.sh` maakt `.env` alleen aan als hij ontbreekt; een bestaand `.env` en een bestaand volume blijven ongemoeid (init-scripts draaien alleen op een leeg volume, §4.5).

### 4.3 Capaciteitsplafond

Drop-in `/etc/systemd/system/user-<uid>.slice.d/50-dev-docker.conf` (uid en `MemoryMax` worden door bootstrap ingevuld):

```ini
[Slice]
MemoryMax=<budget uit §8, maximaal 8G>
MemorySwapMax=0
CPUQuota=800%
TasksMax=4096
```

Alles van devdock (`user@<uid>.service` met rootless dockerd, alle containers, de timer) valt onder deze slice. `MemoryMax` is een plafond op het worstgeval, geen reservering en geen gemeten verbruik. cgroup v2 met gedelegeerde `cpu memory pids` is gemeten, zodat ook per-container `--memory`/`--cpus` werkt. Deze slice staat los van de runnercaps; "Caps zijn gelijk op beide hosts" (CLAUDE.md) gaat over de runner en wordt niet geraakt.

### 4.4 Netwerk en firewall

- ufw is actief op max2. Rootless publiceert poorten via rootlesskit in de host-netwerknamespace en valt daarmee **wel** onder ufw (anders dan de rootful engine, die zijn eigen DOCKER-keten gebruikt).
- Regel: `ufw allow from 192.168.0.0/24 to any port 55432 proto tcp comment 'dev-postgres (IDEA-258)'`.
- Publicatie: **gebonden aan het LAN-adres**, `192.168.0.158:55432:5432`. Gemeten: `enp4s0` heeft `192.168.0.158/24` statisch (`ipv4.method: manual`, `valid_lft forever`); Tailscale is `100.102.8.64/32` op `tailscale0`. Een socket op het LAN-adres luistert niet op andere **bestemmings**adressen (`ss -ltn` toont alleen `192.168.0.158:55432`), maar de bind zegt niets over de **ingress**: onder het weak-host-model levert Linux een pakket naar `192.168.0.158:55432` ook af als het via `tailscale0` of een bridge binnenkomt, en Tailscales `ts-input` accepteert alles op `tailscale0`. De bind is dus geen netwerkgrens.
- **De grens is een eigen keten `dev-docker-in` met één sprong op positie 1 van `INPUT`**, geïnstalleerd en elke minuut opnieuw verzekerd door `dev-docker-firewall.sh` (root; `/usr/local/sbin/`; bash met `set -euo pipefail` zoals `dsh-firewall.sh`, maar **positiebewust**: `iptables -C` zegt alleen dat een regel ergens bestaat, niet waar). Het script raakt de keten alleen aan als die ontbreekt of afwijkt, en herstelt per tick uitsluitend de positie van de eigen sprong:

  ```sh
  R1=(-p tcp --dport 55432 -m conntrack --ctstate NEW ! -i enp4s0 -j DROP)              # elke andere ingress: tailscale0, bridges, lo
  R2=(-i enp4s0 -p tcp --dport 55432 -m conntrack --ctstate NEW ! -s 192.168.0.0/24 -j DROP)
  chain_ok() {
    iptables -C dev-docker-in "${R1[@]}" 2>/dev/null && iptables -C dev-docker-in "${R2[@]}" 2>/dev/null \
      && iptables -C dev-docker-in -j RETURN 2>/dev/null \
      && c=$(iptables -S dev-docker-in) && [ "$(grep -c '^-A ' <<<"$c")" -eq 3 ] \
      && [ "$(awk '$1 == "-A" {print; exit}' <<<"$c")" != "-A dev-docker-in -j RETURN" ]
  }
  if ! chain_ok; then                                   # alleen bij eerste installatie of na manipulatie
    iptables -N dev-docker-in 2>/dev/null || true
    iptables -F dev-docker-in
    iptables -A dev-docker-in "${R1[@]}"; iptables -A dev-docker-in "${R2[@]}"; iptables -A dev-docker-in -j RETURN
    logger -t dev-docker-firewall "keten dev-docker-in opnieuw opgebouwd"
  fi
  inp=$(iptables -S INPUT)                              # eerst vangen, dan lezen: geen SIGPIPE onder pipefail
  first=$(awk '$1 == "-A" {print; exit}' <<<"$inp")
  case "$first" in
    *" -j dev-docker-in") ;;                            # onafhankelijk van hoe iptables -S het comment serialiseert
    *) while iptables -D INPUT -m comment --comment dev-docker -j dev-docker-in 2>/dev/null; do :; done   # alleen de eigen sprong
       iptables -I INPUT 1 -m comment --comment dev-docker -j dev-docker-in
       logger -t dev-docker-firewall "sprong naar dev-docker-in hersteld op INPUT-positie 1";;
  esac
  ```

  Een normale tick muteert niets. De keten wordt alleen herbouwd als ze ontbreekt (bij de eerste installatie bestaat de sprong nog niet, dus zonder venster) of afwijkt (na manipulatie; dan is er een venster van enkele milliseconden tussen `-F` en de drie `-A`'s, dat de proef niet hoeft te meten). De `-D`-lus eindigt bij de eerste mislukte `-D`; met `set -e` is een `while`-conditie daarvan uitgezonderd. Andermans regels worden nooit verwijderd of verplaatst. De proef legt de werkelijke eerste `-A`-regel vast; de `case`-vergelijking op `-j dev-docker-in` is onafhankelijk van de serialisatie van het comment. `--ctstate NEW` voorkomt dat antwoordverkeer van een uitgaande verbinding met toevallig bronpoort 55432 (ephemeral bereik 32768–60999) wordt gedropt. Alleen tcp/55432 dat via `enp4s0` vanaf `192.168.0.0/24` binnenkomt bereikt de rest van de policy, waar de ufw-regel het toelaat.
- **Units** (root, `/etc/systemd/system/`, bootstrap vult `<uid>` in): `dev-docker-firewall.service` (`Type=oneshot`, `After=network-pre.target docker.service ufw.service tailscaled.service`, `Before=user@<uid>.service` zodat de sprong er is vóór de listener, `WantedBy=multi-user.target`) en `dev-docker-firewall.timer` (`AccuracySec=1s`, `OnBootSec=2min`, `OnUnitActiveSec=1min`, `WantedBy=timers.target`). **Boot-race, gemeten in de boom:** `dsh-firewall.service` en `owui-firewall.service` hebben geen `[Install]` en zitten niet in de boot-transactie; ze draaien alleen via hun timers (`OnBootSec=30s`, standaard `AccuracySec=1min`, daarna elke 2 min) en voegen na een reboot, als hun regels nog ontbreken, op positie 1 in — dus **boven** de sprong die `dev-docker-firewall.service` vroeg in de boot plaatste. Een `After=` op die units zou niets ordenen. Daarom de eerste tick op 2 min na boot (na hun 30–90 s), die de sprong terugzet. **Begrensd gat (geaccepteerd):** na iedere boot is de sprong ≈ 30–120 s verplaatst terwijl dev-postgres al luistert; tussen ticks kan een `ufw reload`, een hernieuwde `ts-input` of een Caddy-IP-wissel van `dsh-firewall` hem opnieuw verplaatsen voor nominaal ≤ 1 min plus uitvoeringstijd (`AccuracySec=1s`; de werkelijke hersteltijd wordt in de proef uit de journal gemeten). In zo'n venster beslist op het `tailscale0`-pad `ts-input` (accept), niet ufw: dáár is scram-sha-256 de enige bescherming; op `enp4s0` blijft ufw gelden. Een verbinding die in het venster is toegelaten blijft na herstel bestaan (de DROP-regels matchen alleen `NEW`); de proef legt daarom na herstel `ss -tn 'sport = :55432'` vast.
- **Controle** (preflight ná installatie, in de proef en na iedere herstart): `iptables -S INPUT | awk '$1 == "-A" {print; exit}'` → de sprong naar `dev-docker-in`; `iptables -S dev-docker-in` → precies de twee DROP-regels en `RETURN`; `nc -z -w2 100.102.8.64 55432` vanaf max2 faalt (geen listener én DROP), `nc -z -w2 192.168.0.158 55432` vanaf max2 zelf faalt ook (ingress `lo`, de `! -i enp4s0`-regel: bewijst dat de keten vuurt), terwijl dezelfde verbinding vanaf de Mac slaagt. Herstelproef (de verplaatsing moet expliciet worden afgedwongen: `dsh-firewall.sh` voegt via `ensure` alleen ontbrekende regels in en is in de stabiele toestand een no-op voor de `INPUT`-volgorde): als root `iptables -I INPUT 1 -m comment --comment dd-recovery-test -j RETURN`; de eerste `-A`-regel is nu de testregel; `systemctl start dev-docker-firewall.service`; de eerste `-A`-regel is weer de sprong, `iptables -S INPUT | grep -c -- '-j dev-docker-in'` → `1`, en de journal toont de herstelmelding; daarna `iptables -D INPUT -m comment --comment dd-recovery-test -j RETURN`. Een tailnet-peer-test is niet nodig: de `! -i enp4s0`-regel dropt `tailscale0` ongeacht bron of routering.
- Boot-race (listener): een user-unit kan niet na `network-online.target` worden geordend, en een bind op een nog niet geconfigureerd adres laat de container bij daemon-herstel gestopt achter. Daarom start de stack niet via de restart-policy alleen maar via de user-unit `dev-postgres.service` (§4.5), die eerst op het adres wacht en dan `docker compose up -d` doet.
- Dit sluit aan bij grill-besluit 3 (direct bereikbaar over het LAN, geen tunnel). **Geen `0.0.0.0`-terugval in dit increment:** lukt binden op het LAN-adres met de builtin-portdriver aantoonbaar niet, dan stopt de proef als NO-GO en beslist JP (een wildcard-bind zou een negatieve controle vanaf een externe niet-LAN-peer vereisen, die deze proef niet heeft).
- Geen Tailscale-publicatie in het eerste increment.

### 4.5 dev-postgres

Compose-stack in `/home/devdock/dev-docker/` (bron: `dev-docker/host/compose.yml`):

| Onderdeel | Waarde |
|---|---|
| Image | `pgvector/pgvector:pg17@sha256:<amd64-digest>`; dezelfde digest-referentie staat in `images.txt`, zodat prune stap 5 nooit een tweede, ongebruikt image pullt (gemeten: PostgreSQL 17.11) |
| Container | `dev-postgres`, `restart: unless-stopped`, labels `dev.role=postgres`, `dev.keep=true`; compose-netwerk met label `dev.keep=true` |
| Poort | `192.168.0.158:55432:5432` (zie 4.4) |
| Volume | named volume `dev-postgres-data`, label `dev.keep=true` |
| Env | `POSTGRES_USER=postgres` (superuser, alleen binnen de container gebruikt), `POSTGRES_PASSWORD` en `DEV_PASSWORD` uit `/home/devdock/dev-docker/.env` (0600) |
| Resources | `mem_limit: 2g`, `shm_size: 256m` |
| Healthcheck | `pg_isready -h 127.0.0.1 -p 5432 -U dev -d postgres` (over TCP: het tijdelijke initdb-proces luistert alleen op de unix-socket en zou anders al "gereed" melden vóór rol `dev` bestaat) |
| Start | user-unit `dev-postgres.service`: `Type=oneshot`, `RemainAfterExit=yes`, `Wants=docker.service`, `After=docker.service`, `WorkingDirectory=/home/devdock/dev-docker`, `ExecStartPre` wacht (max. `TimeoutStartSec=180`) tot `ip -4 -o addr show enp4s0` het adres `192.168.0.158/` toont, `ExecStart=docker compose up -d`, `Restart=on-failure`, `WantedBy=default.target`; geslaagd = `active (exited)`. Compose zelf `restart: unless-stopped` als tweede laag: faalt de bind bij daemon-herstel, dan blijft de container gestopt en start de unit hem alsnog |
| Init | `init/01-roles.sh` maakt de clientrol `dev` (`LOGIN CREATEDB`, géén superuser, wachtwoord `DEV_PASSWORD`), `CREATE EXTENSION vector` in `template1` (zodat elke nieuwe database pgvector heeft zonder superuser) en herschrijft `pg_hba.conf` (gemeten in de image: de entrypoint voegt `host all all all <POSTGRES_HOST_AUTH_METHOD>` toe, regels 266–285; initdb zet de loopback-regels `127.0.0.1/32` en `::1/128` op `@authmethodhost@`, standaard `trust`): bovenaan `host all postgres all reject` (eerste match wint; de superuser kan alleen via de unix-socket, dus `docker exec`, inloggen) en de loopback-regels van `trust` naar `scram-sha-256`, zodat ook een verbinding die de rootless-poortdriver als loopback presenteert een wachtwoord vereist; `local all all trust` blijft voor `docker exec`; geen reload nodig: de init-scripts draaien tegen de tijdelijke server (alleen unix-socket) en de definitieve start leest het gewijzigde bestand; `init/02-devmeta.sql` maakt schema `devmeta` en de registertabel in database `postgres` |

De init-scripts in `docker-entrypoint-initdb.d` draaien **alleen bij een leeg volume**; een wachtwoordwijziging daarna vraagt `ALTER ROLE dev PASSWORD …` als `postgres` én een nieuwe `.env`, nooit alleen een van beide. Beide wachtwoorden worden door `install-user.sh` gegenereerd met `openssl rand -hex 24` (48 tekens `[0-9a-f]`, URL-veilig; base64 zou `/`, `+` en `=` kunnen bevatten en de URL breken) en alleen in `.env` geschreven. Ze staan nooit in deze repo, nooit in de s4m-queue-repo en komen op de Mac niet op schijf (§6.2, §7). Clients (de Mac, de tests) gebruiken uitsluitend de rol `dev`; beheer (databases aanmaken en droppen, het register) loopt via `docker exec … psql -U postgres` binnen de container, zodat het superuser-wachtwoord de container nooit verlaat. De helper percent-encodeert het wachtwoord in de URL toch, zodat een latere wijziging van de generator niets breekt.

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

De helper registreert elke database die hij aanmaakt; bij een herhaalde `db create` van een bestaande, al geregistreerde naam blijven `created_at` en `keep` ongewijzigd. `CREATE DATABASE` en `DROP DATABASE` kunnen niet in een functie, `DO`-blok of transactie draaien; de helper en de prune gebruiken daarom losse psql-statements met `\gexec`, bijvoorbeeld `SELECT format('CREATE DATABASE %I OWNER dev', :'n') \gexec`, en registreren in een tweede statement. Slaagt de create maar faalt de registratie, dan registreert de eerstvolgende prune de database als `prune:first-seen`; dat is aanvaardbaar. De prune registreert databases die buiten de helper om zijn gemaakt met `created_by='prune:first-seen'` en de datum van de eerste waarneming; ze krijgen zo dezelfde 14-daagse klok. **Denylist** (helper én prune, nooit registreren, nooit droppen): `postgres`, `template0`, `template1` en alles dat met `pg_` begint.

### 4.7 Prune-timer

Systemd user units van devdock: `dev-docker-prune.service` + `dev-docker-prune.timer` (`OnCalendar=Sun *-*-* 04:30:00`, `Persistent=true`). Script `prune.sh` met `--dry-run`. **Containers verdwijnen uitsluitend in stap 1; er is geen `docker system prune`**, want die verwijdert álle gestopte containers ongeacht label of leeftijd, zou een gestopte `dev-postgres` meenemen en kent geen dry-run. Volgorde:

0. **Wacht:** `dev-postgres` moet bestaan en draaien. Zo niet, dan meldt het script dat (exit ≠ 0, `last-run.json`), voert alleen stap 1 uit en **stopt daarna**: geen volumes, databases, images, netwerken of backups. Zo kan `network prune` het compose-netwerk van een gestopte dev-postgres niet wegnemen en `image prune` niet het image van een ontbrekende. Het script verwijdert `dev-postgres`, zijn netwerk en `dev-postgres-data` onder geen enkele voorwaarde (naam én label `dev.keep=true`).
1. **Wegwerpcontainers:** alle containers behalve `dev-postgres`, zonder label `dev.keep=true`, met `Created` ouder dan 7 dagen: stop + `docker rm`.
2. **Volumes:** dangling volumes zonder label `dev.keep=true`, met `CreatedAt` ouder dan 7 dagen (gemeten: `docker volume inspect` geeft `CreatedAt`, bv. `2026-09-27T13:01:26+02:00`), behalve `dev-postgres-data`: `docker volume rm`. Een volume zonder parseerbare `CreatedAt` wordt overgeslagen en gerapporteerd, nooit als "oud" behandeld.
3. **Databases:** registerrijen met `keep=false` en `created_at < now() - interval '14 days'`, niet op de denylist: `DROP DATABASE IF EXISTS %I WITH (FORCE)` via `\gexec` (PostgreSQL ≥ 13; beëindigt verbindingen atomair), daarna de rij verwijderen. Onbekende databases buiten de denylist worden eerst geregistreerd (`prune:first-seen`), nooit direct gedropt.
4. **Images, buildcache, netwerken.** Images: het script berekent de kandidaten zelf en verwijdert op ID, zodat dry-run en echte run hetzelfde pad delen: de set image-ID's in gebruik is `docker inspect --format '{{.Image}}' $(docker ps -aq)` (alleen als `docker ps -aq` niet leeg is; `docker ps --format '{{.ImageID}}'` bestaat niet in Docker 29.9, gemeten); de set beschermde ID's is `docker image inspect --format '{{.Id}}' <ref>` voor elke regel van `images.txt` die lokaal aanwezig is (een digest-referentie staat in `image ls` als `<none>`-tag, dus vergelijking op naam werkt niet; afwezige referenties worden gerapporteerd, niet gepulld); kandidaat is elk image-ID uit `docker image ls --no-trunc --format '{{.ID}}\t{{.Repository}}:{{.Tag}}\t{{.CreatedAt}}'` dat in geen van beide sets zit en ouder is dan 168 h (`CreatedAt` is de bouwdatum, dus standaardimages zouden anders wekelijks worden verwijderd en in stap 5 opnieuw gepuld); verwijdering met `docker rmi <id>` (ongetagde images vallen onder dezelfde berekening; er is géén aparte `docker image prune`, die zou jonge ongetagde images buiten de leeftijdsregel om verwijderen). Buildcache: `docker builder prune -af --filter until=168h`; de dry-run toont hiervoor alleen de omvang uit `docker buildx du` als **schatting**. Netwerken: `docker network prune -f --filter 'label!=dev.keep=true'`; dry-run = netwerken zonder endpoint en zonder het label. Het image van `dev-postgres` is aan een bestaande container gekoppeld én staat in `images.txt` en blijft; het compose-netwerk draagt `dev.keep=true`.
5. **Standaardimages:** `pull-images.sh` opnieuw (§4.8).
6. **Backups:** bestanden in `/home/devdock/dev-docker/backups/` ouder dan 30 dagen verwijderen (§5.2 fase 4).
7. **Verslag:** journal plus `/home/devdock/dev-docker/prune.log` en `last-run.json` (tijdstip, per stap de kandidaten, de bewaarde items met reden, fouten). `max2-docker status` toont de laatste run.

`--dry-run` gebruikt dezelfde kandidaatberekening als de echte run (voor de buildcache een schatting) en schrijft niets: geen verwijdering, geen registerrij ("zou registreren"). De uitvoer bevat per stap de **kandidaten** én de **bewaarde items met reden** (`jonger dan 7 dagen` voor containers en volumes, `jonger dan 14 dagen` voor databases, `dev.keep`, `denylist`, `geen CreatedAt`, `in gebruik`). Dat is wat `max2-docker cleanup --dry-run` op de Mac aanroept.

### 4.8 Standaardimages

`images.txt`: `pgvector/pgvector:pg17@sha256:<dezelfde digest als compose.yml>`, `node:24-bookworm-slim`, `node:22-bookworm-slim`, `debian:bookworm-slim`, `alpine:3`. `pull-images.sh` pullt ze voor `linux/amd64` en faalt luid bij een pull-fout. Niet standaard: `ubuntu:24.04`, `docker:cli`.

### 4.9 Bestanden in deze repo

```
dev-docker/
  SPEC.md                  dit document
  README.md                korte bediening (volgt met de implementatie)
  host/
    bootstrap.sh           root (per scp + ssh -t): preflight + gate, pakketten, gebruiker, subid, slice-drop-in, linger, ufw-regel, firewall-unit
    dev-docker-firewall.sh root (/usr/local/sbin): keten dev-docker-in + sprong op INPUT-positie 1 (§4.4), positiebewust, muteert alleen bij afwijking
    install-user.sh        devdock via SSH-login: rootless engine, context, compose, timer, images
    compose.yml            dev-postgres
    init/01-roles.sh       clientrol dev (CREATEDB) en pgvector in template1
    init/02-devmeta.sql    registertabel
    prune.sh               opruimen, met --dry-run
    pull-images.sh / images.txt
    systemd/dev-postgres.service      wacht op het LAN-adres, dan compose up
    systemd/dev-docker-firewall.service, dev-docker-firewall.timer   root-units voor het firewallscript
    systemd/dev-docker-prune.service, dev-docker-prune.timer
    systemd/50-dev-docker.conf   slice-drop-in (sjabloon)
evidence/dev-docker/       bewijs van de praktijkproef en latere metingen
```

Plaatsing volgt de bestaande repo-conventie (`deepseek-harness/`, `open-webui/`: componentmap met `host/`); de grill noemde `hosts/max2/dev-docker/`, maar `hosts/max2/` is in `CLAUDE.md` gereserveerd voor de runner-overlay. `.gitignore` sluit `.env` en `.env.*` al uit.

## 5. Mac-kant

### 5.1 SSH en Docker-context

- `~/.ssh/config`: alias `max2-dev` met `HostName max2`, `User devdock`, dezelfde `IdentityFile` als de bestaande `max2`-alias.
- `docker context create max2-dev --docker host=ssh://max2-dev`.
- Bewijs: `docker --context max2-dev info --format '{{.Name}} {{.SecurityOptions}}'` toont `max2` en `name=rootless`.

### 5.2 Fasering van de standaardcontext en Docker Desktop

Gemeten op de Mac (14-10-2026): `docker` is `/Applications/Docker.app/Contents/Resources/bin/docker` (symlink in `/usr/local/bin`), `credsStore: desktop`, `currentContext: desktop-linux`; `/opt/homebrew/bin` staat in `PATH` vóór `/usr/local/bin`; Homebrew 7.0.9 biedt `docker` 29.9.0, `docker-compose` 5.6.0, `docker-buildx` 0.38.0 en `docker-credential-helper` 0.9.10, geen daarvan geïnstalleerd.

| Fase | Wanneer | Wat |
|---|---|---|
| 1 | Nu | Alles via `--context max2-dev`; Desktop draait nog |
| 2 | Direct na geslaagde proef | `docker context use max2-dev`; Desktop afsluiten en uit "Start bij inloggen" |
| 3 | Direct na fase 2, Desktop nog geïnstalleerd maar afgesloten | Homebrew: `docker`, `docker-compose`, `docker-buildx`, `docker-credential-helper`; `~/.docker/config.json`: `credsStore: osxkeychain`, `cliPluginsExtraDirs: ["/opt/homebrew/lib/docker/cli-plugins"]`. Omdat `/opt/homebrew/bin` vóór `/usr/local/bin` staat, wint de Homebrew-`docker` meteen. Controle met Desktop afgesloten: `docker --context max2-dev info`, `docker compose version`, `docker buildx version`, registry-login via de keychain zonder credentials te tonen. Faalt iets, dan is `docker context use desktop-linux` plus Desktop starten de terugval |
| 4 | 14 dagen na fase 3 zonder terugval | Desktop éénmalig starten voor `pg_dumpall` van `local-postgres` met expliciet `--context desktop-linux` (de standaardcontext is dan `max2-dev`), dump naar `max2-dev:dev-docker/backups/` (30 dagen bewaard door prune stap 6); daarna Docker Desktop en zijn data verwijderen, inclusief de `/usr/local/bin`-symlinks, de hangende symlinks in `~/.docker/cli-plugins`, de context `desktop-linux` en `credsStore: desktop`; tot slot de controles van fase 3 nog één keer draaien |

Een terugval in fase 2 of 3 (iets heeft Desktop toch nodig) wordt in `evidence/dev-docker/` genoteerd en pauzeert de volgende fase. Pas na fase 4 is er geen lokale engine meer.

### 5.3 Gedrag bij onbereikbaar max2

Is `max2` onbereikbaar, dan stopt de opdracht met een duidelijke fout (exit 3). Er is **geen** automatische terugval naar een lokale engine; dat zou de migratie oncontroleerbaar maken (PR 32, §6).

## 6. Skill `max2-docker`

Bron: `.claude/skills/max2-docker/` in de s4m-queue-repo, gesymlinkt naar `~/.claude/skills/max2-docker` en `~/.codex/skills/max2-docker` (zelfde patroon als `s4m-queue`). Codex deelt de macOS-gebruiker, SSH-sleutel en Docker-config; aparte configuratie is niet nodig. Dat Codex vanuit zijn shell `docker -H ssh://…` kan uitvoeren is in PR 32 bewezen.

### 6.1 SKILL.md (inhoud op hoofdlijnen)

- **Wanneer:** elke keer dat een sessie op de Mac een container, image-build of testdatabase nodig heeft.
- **Regels:** altijd de dev-engine (`max2-dev`); nooit `ssh max2 docker …` onder janpeter voor dev-werk; databasenaam `<project>_<taak>`; wegwerpcontainers met label `dev.owner=mac` en een unieke naam met taakcode; `dev.keep=true` of `db keep` alleen met reden; aan het einde van een taak de eigen database droppen tenzij `keep`; **geen Mac-bind-mounts** (`-v /Users/…`): een remote engine lost het pad op max2 op; gebruik named volumes, `docker cp` of een buildcontext (PR 32 §3).
- **Wachtwoord nooit in beeld:** tests draaien via `max2-docker db run <naam> -- <commando>`; het commando gebruikt de omgevingsvariabelen (`DATABASE_URL`, of `PGHOST`/`PGPORT`/`PGUSER`/`PGDATABASE`/`PGPASSWORD` voor libpq-tools) en krijgt de URL **nooit als argument**: `psql -Atc '…'` in plaats van `psql "$DATABASE_URL"`, want `"$DATABASE_URL"` wordt door de aanroepende shell geëxpandeerd vóór `db run` iets zet, en een URL in argv is zichtbaar in `ps`. De agent gebruikt nooit `db url --reveal`, `docker … inspect dev-postgres` of `exec … printenv`, en zet de URL niet in bestanden, logs of het bewijsbestand. Dit is een regel voor agents, geen afgedwongen grens: wie de SSH-sleutel heeft kan het wachtwoord opvragen (§7). Transcripten van Claude en Codex worden op de Mac opgeslagen; alles wat een tool print staat daarmee op schijf. `db run` maskeert het wachtwoord daarom in de uitvoer van het kindproces; vóór de proef wordt van het gekozen testcommando gecontroleerd of het zijn configuratie of verbindingsfouten met URL print.
- **Commando's:** zie 6.2, met voorbeelden voor een testrun.
- **Fouten:** onbereikbaar max2 → stoppen (§5.3); naam al in gebruik → bestaande database hergebruiken (idempotent), geen nieuwe container.

### 6.2 Helperscript `scripts/max2-docker` (bash)

| Commando | Gedrag |
|---|---|
| `status` | Engine-info (`max2`, rootless), `dev-postgres`-health, aantal databases en containers, laatste prune-run uit `last-run.json` |
| `db create <naam> [--keep] [--by <adres>] [--note <tekst>]` | Valideert naam (zie onder); maakt de database als hij niet bestaat; registreert in `devmeta.databases` (bestaande rij blijft ongewijzigd); print de **gemaskeerde** URL `postgresql://dev:***@max2:55432/<naam>`. Idempotent |
| `db run <naam> [--no-redact] -- <commando…>` | Zet `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE` en `PGPASSWORD` alleen in de omgeving van het kindproces, zet `/opt/homebrew/opt/libpq/bin` vooraan in `PATH` als die map bestaat (libpq is keg-only en staat niet op het pad, gemeten) en voert het commando uit (`set +x`, geen shell-tracing); stdout en stderr van het kind gaan door een filter dat het wachtwoord door `***` vervangt (uit te zetten met `--no-redact`, niet voor agents); exitcode van het kind blijft behouden. Dit is de enige route waarlangs tests het wachtwoord krijgen |
| `db url <naam> [--reveal]` | Gemaskeerde URL; met `--reveal` de echte, uitsluitend voor handmatig gebruik door JP |
| `db drop <naam>` | `DROP DATABASE IF EXISTS %I WITH (FORCE)` via `\gexec`, registerrij weg; weigert de denylist |
| `db list` | Naam, aanmaakdatum, `created_by`, `keep`, leeftijd |
| `db keep <naam> on\|off` | Zet de opt-out; weigert de denylist |
| `cleanup --dry-run` | Draait `prune.sh --dry-run` op max2 via SSH en toont kandidaten én bewaarde items met reden |
| `images` | Standaardimages en hun aanwezigheid |

**Naamvalidatie** (`db create`, `db keep`, `db drop`): `^[a-z][a-z0-9]{1,30}_[a-z0-9_]{1,31}$` (project en taak gescheiden door een underscore, totaal ≤ 63) én niet op de denylist van §4.6; anders exit 2.

Implementatiekeuzes: alle beheeracties lopen via `docker --context max2-dev exec -i dev-postgres psql -U postgres …` (voor beheer is geen `psql` op de Mac vereist; alleen de identiteitscheck van de proef gebruikt de Mac-`psql` via `db run`; identifiers via `format('%I')` met `\gexec`, §4.6); het clientwachtwoord komt uit `docker … exec dev-postgres printenv DEV_PASSWORD`, wordt percent-encoded in de URL gezet en blijft in procesgeheugen; de URL luidt `postgresql://dev:<pw>@max2:55432/<naam>`; `--by` default `mac:${MAX2_DOCKER_AGENT:-unknown}` (Claude en Codex zetten de variabele in de skill-instructie); exitcodes: 0 ok, 2 invoerfout, 3 max2 onbereikbaar, 4 dev-postgres niet gezond, anders de exitcode van het kindproces bij `db run`.

## 7. Beveiliging

- **Scheiding:** devdock heeft geen sudo, geen toegang tot `/var/run/docker.sock`, geen hostpaden buiten zijn home. Een `docker rm` vanaf de Mac kan alleen dev-resources raken.
- **Secrets:** beide Postgres-wachtwoorden alleen in `/home/devdock/dev-docker/.env` (0600) en in de container-env; het superuser-wachtwoord verlaat de container niet en `pg_hba.conf` weigert `postgres` over het netwerk (§4.5). Niet in Git, niet op de Mac-schijf, niet in Scrum4Me-issues. De helper toont het clientwachtwoord alleen op `--reveal`; agents gebruiken `db run`. Dit is bescherming door instructie: elke sessie met de SSH-sleutel kan het wachtwoord via `docker exec` opvragen, en een kindproces kan zijn configuratie printen (door `db run` gemaskeerd) of door een ander proces van dezelfde Mac-gebruiker worden geïnspecteerd.
- **Bereik:** Postgres is bereikbaar voor het LAN-subnet; het wachtwoord is de grens. Dev-data bevat per afspraak geen productiegegevens.
- **Restrisico (geaccepteerd):** één clientrol `dev` (`CREATEDB`, geen superuser) met één wachtwoord voor alle databases, bereikbaar op het LAN. Compromittering raakt alle dev-databases en geeft toegang tot wat de rol binnen de container kan, niet tot de host of de productie-engine; rollen per database zijn buiten scope (§2).
- **SSH:** bestaande sleutel; wachtwoordlogin blijft uit.
- **Restrisico schijf (geaccepteerd):** de dev-engine deelt het bestandssysteem met de productie-engine (gemeten 14-10-2026: `df -h` op max2 toont één volume `/dev/mapper/ubuntu--vg-ubuntu--lv` van 914 GB voor `/` én `/var/lib/docker`, 578 GB vrij; de P6-reeks bevestigt `df_root_used_pct` = `df_docker_used_pct`). Het slice-plafond begrenst geen schijf; een weggelopen build of database kan het volume vullen vóór de wekelijkse prune. `max2-docker status` en `prune.sh` tonen de vrije ruimte en waarschuwen onder 20 % (dezelfde grens als §7.8); de proef meet de vrije ruimte vóór en na (§9). Een quotum is buiten scope.

## 8. Capaciteit: headroomgate en budget

### 8.1 Wat §7.8 nu voor max2 betekent

De runnerpool-regel staat in het migratieontwerp (`scrum4me-server`-repo, `docs/forgejo-runner-pool/migratieontwerp.md`), oorspronkelijk per stack (§7.8) en sinds **delta R17 host-breed**: de som van de geheugenlimieten over **alle** runnerstacks van een host mag ten hoogste 50 % van de laagste gemeten `MemAvailable` van die host zijn. Stand van zaken, uit de gepinde bronnen:

| Grootheid | Waarde | Bron |
|---|---|---|
| Caps per stack (runner + DinD) | 1 GiB + 5 GiB = 6,0 GiB; live gemeten op max2 per stack `Memory=5368709120` voor de DinD | `evidence/stap-a/caps.md`; `docker inspect` 14-10-2026 |
| Stacks op max2 | **N = 2** (`forgejo-runner` en `forgejo-runner-03`, beide met DinD) | `docker ps` 14-10-2026; U4-record |
| Caps-som host-breed (R17) | **12,0 GiB** | R17 §7.8 |
| Laagste `MemAvailable` onder N = 2-productielast | **21,53 GiB** (22 576 424 kB om 2026-10-12T12:28:21Z; 1584 samples, 2026-10-12 10:46Z – 2026-10-13 12:46Z, resolutie ≈ 60 s) | `evidence/dev-docker/2026-10-12-p6-memavailable-max2.csv` (kopie van `max2:~/m52-p6/metrics.csv`); U2 (24 h, 1405 samples) gaf 21,67 GiB |
| 50 %-budget | 10,77 GiB (P6) / 10,83 GiB (U2) | berekend |
| Oordeel §7.8 host-breed | **ROOD**: 12,0 GiB > 10,77 GiB (55,7 %, berekend op het P6-minimum); R17-rekenvoorbeeld op de stap-A-momentopname: 9,79 GiB / 61 %; U4 op U2: 10,83 GiB; CPU: 25 vCPU > 14 (R17) | berekend; R17 §7.8; U4-record regel 25 |
| Besluit JP | **D7, 11-10-2026: waiver van §7.8 voor max2 op beide assen** (record-and-proceed; `preflight.sh` blijft eerlijk rood); P5 acceptatie co-locatierisico | U4-record (`evidence/n-stacks/2026-10-12-uitrol-stack-03.md`) |
| Operationele rode lijn onder de waiver (P6-drempel, U4) | `MemAvailable` **< 10,8 GiB in één steekproef** → rood; plus mediane wachttijd > 440 s of host-OOM/throttling | U4-record regel 115 |
| Historische N = 1-lijn | caps-som 6,0 GiB → rood onder 12,0 GiB `MemAvailable` | `caps.md` (vóór R17; alleen ter context) |

De eerdere revisies van deze spec gebruikten de N = 1-lijn (12,0 GiB) als "de gate"; dat was onjuist: de host is met twee stacks al rood onder de host-brede regel en draait onder waiver D7. De dev-engine komt dus bovenop een gewaiverde situatie. Daarom is de vraag aan JP niet "past 8 GiB onder de gate" maar: **mag er dev-last bij op een host waarvan de runnergate onder waiver staat, en welke operationele vloer geldt dan?** (§12).

### 8.2 Voorstel van deze spec (afgeleide regel, geen §7.8)

De dev-slice is geen runnercap en telt in de §7.8-som niet mee (letterlijk optellen zou 12 + 8 = 20 GiB tegen 10,77 GiB geven en is niet de bedoeling van de regel). Deze spec stelt een eigen **operationele vloer X** voor: `MemAvailable` op max2 blijft ook met de dev-engine op haar plafond boven X. Voorgesteld **X = 12,0 GiB**: strenger dan de U4-rode lijn van 10,8 GiB (die blijft onverkort gelden) en gelijk aan de historische N = 1-lijn, zodat de dev-engine de gewaiverde situatie niet verder verslechtert dan de pool ooit groen was. JP kiest X (§12); de budgetregel hieronder is parametrisch.

**Budgetregel:** met de effectieve vloer `X_eff = max(X, 10.8)` in GiB (de U4-rode lijn van 10,8 GiB is de ondergrens van elke keuze): `MemoryMax = min(8 GiB, laagste_MemAvailable − X_eff)`, afgerond omlaag op 0,5 GiB. Komt het afgeronde budget onder 2 GiB, dan **weigert** `bootstrap.sh` vóór iedere mutatie; het budget wordt nooit omhoog afgerond. Met de P6-reeks en X = 12,0: `21,53 − 12,0 = 9,53` → **8 GiB**, marge 1,53 GiB (met X = 10,8: 10,73 → 8 GiB, marge 2,73). `MemoryMax` is een plafond op het worstgeval, geen gemeten verbruik: dev-postgres idle en één testrun blijven daar naar verwachting ver onder, en dat wordt in de proef gemeten.

**Invoer:** uitsluitend reeksen van ≥ 24 uur aaneengesloten met de huidige productielast (N = 2) en een werkdag erin; de P6-reeks (26 h, ≈ 60 s-resolutie: `vmstat 1 5` + `sleep 55`) voldoet. Een momentopname zoals stap A (19,59 GiB, zonder video-editor-stack) is geen reeks en telt niet mee. Waarde, bronpad, meetperiode en resolutie zijn `--series`-argumenten van `bootstrap.sh` (§4.1) en komen in het bewijsbestand; zonder invoer weigert de preflight. De ≈ 60 s-resolutie van P6 kan korte dips missen; de proefsampler meet daarom iedere 5 s.

**Meten tijdens de proef:** een aparte lichte lus (`while :; do date -u +%FT%TZ; grep MemAvailable /proc/meminfo; df -B1 --output=avail /var/lib/docker; sleep 5; done`, dus zonder de blokkerende `vmstat 1 5` van de P6-sampler, die met `sleep 4` ≈ 8 s zou geven) draait vanaf vóór `bootstrap.sh` tot na de testrun; de werkelijke tijdsverschillen tussen samples komen in het bewijsbestand; de testrun is de representatieve dev-belasting. **Stopregel:** één steekproef onder `X_eff` → `systemctl --user stop docker` als devdock, budget verlagen volgens de regel (met dezelfde weigering onder 2 GiB), proef opnieuw. Een steekproef onder 10,8 GiB is bovendien de U4-rode lijn van de pool en wordt als zodanig aan JP gemeld. Nooit de runnercaps verlagen (CLAUDE.md: "Haalt deze host de headroomgate niet, dan is dat een NO-GO en geen reden om de caps te verlagen"); de waiver D7 wordt door deze spec niet gewijzigd.

**Baseline productie-engine:** `docker ps -a --no-trunc --format '{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.CreatedAt}}'` en `docker images --digests --format '{{.ID}}\t{{.Repository}}:{{.Tag}}\t{{.Digest}}'` van de productie-engine (geen statusvelden, die verschillen altijd) vóór en na de proef, met de tijdstempels van eventuele legitieme uitrollen in die periode (uit het Scrum4Me-/Forgejo-spoor); verschillen die daaruit verklaarbaar zijn, tellen niet als afwijking. De reboot-test (§9) valt buiten deze vergelijking en wordt als eigen gebeurtenis gelogd.

## 9. Praktijkproef (eerste increment)

**Keuze van de test:** een bestaande integratietest die al een `DATABASE_URL`-variabele accepteert (usage-ledger/M48 of QR-login, zie PR 32 §4) **en** een niet-loopback host zonder host-allowlist toestaat (Media-Organizer valt daarmee af voor de proef). Welke precies wordt in het plan vastgelegd met repo, branch en commando.

**Stappen**

1. Baseline (§8): productie-engine, sampler (5 s) starten, vrije schijfruimte (`df -B1 /var/lib/docker /home`), `ufw status verbose` (default deny incoming), `ufw status numbered` en `iptables-save -t filter` (§4.1 stap 1).
2. `bootstrap.sh` (root, per scp en `ssh -t`, §4.1) met de `--series`-invoer; controle van de slice-limieten (§4.1 stap 4); `ufw status numbered` opnieuw.
3. Mac: alias `max2-dev` in `~/.ssh/config` (§5.1); daarna `rsync` en `install-user.sh` via `ssh max2-dev` (§4.2); `systemctl --user status docker dev-postgres.service` (`active (exited)`) en de timer controleren; `cat /sys/fs/cgroup/user.slice/user-<uid>.slice/memory.max`; op max2 `iptables -S INPUT | awk '$1 == "-A" {print; exit}'` → de sprong naar `dev-docker-in`, `iptables -S dev-docker-in` → de twee DROP-regels en `RETURN`, de herstelproef uit §4.4, `ss -ltn | grep 55432` → alleen `192.168.0.158:55432`, `nc -z -w2 100.102.8.64 55432` én `nc -z -w2 192.168.0.158 55432` vanaf max2 → beide geweigerd (§4.4).
4. Mac: Docker-context aanmaken en `docker --context max2-dev info` (§5.1).
5. `max2-docker db create <project>_proef`; identiteitscheck **over het LAN-pad** vanaf de Mac, zonder URL in argv: `max2-docker db run <project>_proef -- psql -Atc 'select current_database(), current_user, inet_server_addr(), inet_server_port()'` (libpq staat op de Mac in `/opt/homebrew/opt/libpq/bin`; `psql` leest `PGHOST` enz. uit de omgeving die `db run` zet) → `<project>_proef`, `dev`, het containeradres, `5432`; daarnaast `select client_addr from pg_stat_activity where pid = pg_backend_pid()` in het bewijsbestand, en twee negatieve controles vanaf de Mac: dezelfde `psql` met een fout wachtwoord en met `PGPASSWORD` leeg → geweigerd; `psql -U postgres` over TCP → geweigerd door `pg_hba` (§4.5).
6. Testrun: `max2-docker db run <project>_proef -- <testcommando>`; Docker Desktop **afgesloten** vóór de run; vooraf is gecontroleerd dat het testcommando zijn URL niet print (§6.1).
7. Codex: één `max2-docker db list` vanuit een Codex-sessie.
8. `max2-docker cleanup --dry-run`; daarna `db drop`.
9. Baseline opnieuw (§8), vrije schijfruimte opnieuw; sampler stoppen; laagste waarde noteren.
10. Herstarttest zonder productie te raken: als root `systemctl stop user@<uid>.service && systemctl start user@<uid>.service` → `dev-postgres.service` doorloopt zijn wacht- en startpad en dev-postgres komt terug. Daarna de echte reboot-test, **na** de baseline en als aparte, gelogde gebeurtenis (herstart alle productiecontainers): `sudo reboot` van max2 op een door JP gekozen rustig moment; daarna `max2-docker status` → dev-postgres draait zonder handmatige `compose up` en `ss -ltn` toont opnieuw alleen het LAN-adres. De positiecontrole pas **na de eerste timer-tick** (`journalctl -b -u dev-docker-firewall.service` toont een run ná de boot-runs van `dsh-firewall`/`owui-firewall`, of `systemctl start dev-docker-firewall.service`): de sprong staat op positie 1; de journal-tijdstempels van `dsh-firewall`, `owui-firewall`, `dev-docker-firewall` en `dev-postgres` (listener) komen in het bewijs, zodat het werkelijke boot-venster van §4.4 gemeten is en niet beweerd.
11. Bewijsbestand `evidence/dev-docker/2026-MM-DD-praktijkproef.md`: commando's, uitvoer (gemaskeerde URL's), database-identiteit, testuitslag, baselinevergelijking, gate-invoer en -uitkomst, sampler-minimum.

**Acceptatie** (alle punten):

- `docker --context max2-dev info` geeft `max2` en `name=rootless`.
- `db create` levert een registerrij en een gemaskeerde URL; de identiteitscheck en de test slagen via `db run` vanaf de Mac met Desktop afgesloten.
- Geen productiecontainer of -image is gewijzigd (baseline vóór/na identiek, of verklaard uit gelogde uitrollen).
- `db list` toont de proefdatabase; `cleanup --dry-run` noemt haar bij de bewaarde items met reden `jonger dan 14 dagen` en noemt niets van de productie-engine.
- De slice-limieten staan effectief (`memory.max` van `user-<uid>.slice` = budget).
- De sprong naar `dev-docker-in` is de eerste regel van `INPUT` en de keten bevat precies de twee DROP-regels; dat geldt vóór én na de herstelproef (met afgedwongen verplaatsing), de user-manager-herstart en de reboot-test (na de eerste tick, met het gemeten boot-venster in het bewijs); `ss -tn 'sport = :55432'` na herstel toont alleen LAN-bronnen; poort 55432 luistert uitsluitend op `192.168.0.158` (`ss -ltn`); de lokale verbindingen via `100.102.8.64` en via `192.168.0.158` vanaf max2 worden geweigerd (de tweede bewijst dat de keten vuurt), de verbinding vanaf de Mac slaagt; `iptables-save -t filter` staat als momentopname in het bewijsbestand.
- Verkeerd of leeg wachtwoord wordt geweigerd; `postgres` over TCP wordt geweigerd; `client_addr` is vastgelegd.
- dev-postgres komt na de reboot-test vanzelf terug (aparte acceptatieregel, los van de baselinevergelijking).
- Codex heeft de skill één keer succesvol aangeroepen.
- De `--series`-invoer, X, `X_eff`, het budget en het sampler-minimum staan vast; geen steekproef onder `X_eff`; vrije schijfruimte vóór en na vastgelegd.
- Het bewijsbestand bevat geen wachtwoord: `grep -F` op de letterlijke waarde (op dat moment via `docker exec` opgehaald en niet opgeslagen) en op `dev:` dat niet door `***` wordt gevolgd; een los hex-patroon is onbruikbaar omdat de image-digests in de baseline ook hex zijn.

Een geslaagde `docker info` alleen haalt deze acceptatie niet.

## 10. Rollback

Volledig omkeerbaar zonder productie te raken, in deze volgorde: als devdock `docker compose down` in `~/dev-docker` en `systemctl --user disable --now dev-postgres.service dev-docker-prune.timer docker`; als root `loginctl disable-linger devdock`, `loginctl terminate-user devdock` (of `systemctl stop user@<uid>.service`; `userdel` weigert anders vanwege lopende processen), ufw-regel verwijderen (`ufw delete` op het regelnummer of de comment), `systemctl disable --now dev-docker-firewall.timer dev-docker-firewall.service`, de sprong verwijderen (`iptables -D INPUT -m comment --comment dev-docker -j dev-docker-in`, herhalen tot `-D` faalt: na de herstelproef kunnen er tijdelijk twee hebben bestaan en `-X` weigert op een keten die nog in gebruik is), de keten legen en verwijderen (`iptables -F dev-docker-in && iptables -X dev-docker-in`), de unitbestanden en `/usr/local/sbin/dev-docker-firewall.sh` verwijderen, `userdel -r devdock`, subid-regels verwijderen, en **daarna pas** de slice-drop-in verwijderen plus één afsluitende `daemon-reload`. De pakketten `uidmap` en `slirp4netns` blijven staan (onschadelijk; vermelden in het bewijs). Op de Mac de context en de alias verwijderen. Docker Desktop wordt pas in fase 4 verwijderd; tot dan is terugvallen `docker context use desktop-linux` plus Desktop starten.

## 11. Te verifiëren in de proef

| # | Punt | Hoe |
|---|---|---|
| 1 | 55432 is alleen vanaf het LAN bereikbaar, ook na herstart en na andermans INPUT-invoegingen | sprong naar `dev-docker-in` op positie 1 (vóór/na herstelproef met afgedwongen verplaatsing, user-manager-herstart, reboot na eerste tick); keteninhoud; gemeten boot-venster en hersteltijd uit de journal; `ss -ltn` toont alleen `192.168.0.158:55432`; `nc` vanaf max2 via beide adressen geweigerd; verbinding vanaf de Mac via `db run`; wachtwoordloos en `postgres` over TCP geweigerd |
| 2 | Rootless bindt op `192.168.0.158` en dev-postgres komt na een herstart vanzelf terug (wachtende user-unit) | `compose up` via `dev-postgres.service`; user-manager-herstart en reboot-test §9 stap 10; faalt de bind, dan NO-GO (§4.4) |
| 3 | Docker-over-SSH vindt de rootless socket zonder login-shell | `docker --context max2-dev info` |
| 4 | Slice-plafond is effectief en omvat dockerd en containers | `systemctl show user-<uid>.slice -p MemoryMax …`, `cat …/user-<uid>.slice/memory.max`, `systemd-cgtop` tijdens de testrun |
| 5 | Mac-CLI zonder Desktop | fase 3: Homebrew-CLI, compose, buildx en keychain-helper met Desktop afgesloten |
| 6 | Headroom | §8: `--series`-invoer, X (JP), budget, sampler-minimum ≥ X en ≥ 10,8 GiB; vrije schijfruimte |
| 7 | Geen secrets in Git of bewijs | `git grep` op wachtwoordpatronen vóór elke commit; `grep` op het bewijsbestand |
| 8 | Rootless-preflight | `bootstrap.sh` stap 1: AppArmor-profiel, `uidmap`, `slirp4netns`, delegatie |
| 9 | Prune-dry-run | toont kandidaten én bewaarde items; registerstand voor en na identiek |
| 10 | `db run` lekt het wachtwoord niet | `ps` tijdens de identiteitscheck toont geen URL in argv; kind-uitvoer bevat `***` |

## 12. Open punten

- Exacte test en repo voor de praktijkproef (plan), met het selectiecriterium uit §9.
- Of de rootlesskit-builtin-portdriver op `192.168.0.158` bindt (verwacht wel; anders NO-GO van de proef, §4.4).
- Voor het plan: de image-digest van `pgvector/pgvector:pg17` vastpinnen en het entrypoint-fragment (regels 266–285) als bewijs bijvoegen; gemeten op max2: systemd 259 (`Restart=` op `Type=oneshot` is toegestaan sinds 244), Tailscale netfilter-modus 2.
- Of 8 GiB ruim genoeg is voor één Node-testrun plus Postgres; eerste meting in de proef (§8).
- Beheer van de s4m-queue-repo: de skill komt daar in een eigen PR; volgorde: hostkant eerst, skill daarna, proef als laatste.
- **Besluit JP (gate-eigenaar), op de juiste premisse (§8.1):** (a) mag er dev-last bij op max2 terwijl de runnergate host-breed rood is onder waiver D7; (b) welke operationele vloer X geldt (voorstel 12,0 GiB; de U4-lijn van 10,8 GiB blijft hoe dan ook gelden); (c) bevestiging dat de dev-slice niet in de §7.8-capsom meetelt. Zonder (a) en (b) start de proef niet.
