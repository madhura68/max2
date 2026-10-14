# Codex en Docker op de Mac — onderzoek en migratieadvies

**Peildatum:** 14-10-2026 08:38 CEST. **Status:** onderzoek afgerond; migratie niet uitgevoerd.

## Conclusie

Codex gebruikt Docker op deze Mac hoofdzakelijk als leverancier van PostgreSQL-testdatabases. De agent voert via zijn lokale shell Docker-opdrachten en scripts uit; Docker Desktop levert de Linux-engine. Tests, Next.js en de agent zelf lopen daarmee niet automatisch in Docker.

In de 20 onderzochte hoofdchats is in **6 lokale Docker-runtimeactiviteit** aangetoond. Een zevende gebruikt Docker op een server. Bij de overige 13 is geen Docker-uitvoering gevonden. Onderliggende subagents zijn aan hun hoofdchat toegerekend. Docker Desktop werd onder meer via `open -a Docker` gestart en eenmaal via de UI geïnspecteerd bij een storing. Er is geen bewijs dat deze chats `docker sandbox` of een Docker-MCP gebruiken als algemene Codex-uitvoeromgeving; de actuele Codex-configuratie bevat geen MCP-startcommando dat Docker start.

**Aanbevolen eerste route:** Codex en de werkbestanden op de Mac houden; testcontainers en imagebuilds via SSH op max2 uitvoeren. De Docker-API-verbinding is al read-only bewezen. Voor databases die door lokale tests worden gebruikt is daarnaast een SSH-poorttunnel nodig. Voor zwaardere Linux-projecten is een volledig remote Codex-project op max2 een tweede optie.

## Afbakening en betrouwbaarheid

- Selectie: de 20 laatst bijgewerkte hoofdchats op basis van `state_5.sqlite.threads.updated_at`, exclusief deze onderzoekschat. Subagents tellen niet als zelfstandige sessies. Gearchiveerde hoofdchats mochten meedoen; geen daarvan viel in de uiteindelijke selectie.
- De laatste activiteit van de geselecteerde chats ligt tussen 3 en 14 oktober 2026. Hun volledige bewaarde historie is onderzocht; de oudste geselecteerde chat begon al op 23 september. Dit is dus geen selectie van uitsluitend opdrachten van de laatste twintig dagen, en ook niet van de twintig laatst aangemaakte chats.
- Bronnen: lokale Codex-historie, actuele Docker-inventaris, read-only SSH-inspectie van max2 en officiële OpenAI-/Docker-documentatie.
- Automatische doorzoeking van **22.221 historie-items en 6.413 commandExecution-items**, verspreid over 20 hoofdchats plus 70 onderliggende agentchats. De 6.413 command-items zijn qua aantal per chat vergeleken met de oorspronkelijke `item_completed/CommandExecution`-events in alle 90 rolloutbestanden: geen verschillen. Relevante opdrachten, aanmaakresultaten en vervolgreadbacks zijn inhoudelijk bekeken. De aantallen zoekhits zijn niet gebruikt als aantallen containerstarts.
- Een Docker-vermelding in een plan, bestandsnaam of testcode geldt niet als uitvoering. Een mislukte `docker run` door een naamconflict geldt niet als nieuwe container. Ook is shell-exit 0 na een afsluitende `tail` op zichzelf geen bewijs van een geslaagde test.
- Docker bewaart geen volledige makerhistorie. Aanwezigheid van een image bewijst niet dat Codex die in deze twintig sessies bouwde. `CreatedAt` van een gedownload image is de bouwtijd van dat image, niet de downloadtijd op deze Mac.
- Verwijderde proefcontainers staan niet meer in `docker ps -a`; ze zijn daarom uit de sessiehistorie gereconstrueerd. Enkele mislukte/herhaalde probes logden geen blijvend herleidbare containernaam. De lijst is een bewezen minimum, geen exact lifetime-totaal.

## De twintig sessies

Titels hieronder zijn de namen uit de app. Tijden zijn Europe/Amsterdam; de volledige UUID staat in de bronnenbijlage.

| Nr. | Laatst bijgewerkt | Chat | Doel | Docker-gebruik |
|---|---|---|---|---|
| 1 | 14-10 02:35 | Codex usage vastleggen | Usage-overzicht en Codex-usage/afleverproeven | Mac: usage-v1 PG17 en tijdelijke handler/crashproeven. Ook beheer op scrum4me-srv. |
| 2 | 13-10 23:50 | Haal MODS-context op | T-49 foregroundproef, context ophalen | Geen Docker-uitvoering gevonden. |
| 3 | 13-10 23:46 | Rond foregroundproef beurt 2 af | T-49 tweede antwoordbeurt | Geen Docker-uitvoering gevonden. |
| 4 | 13-10 23:03 | Voer T-47 annuleringstest uit | T-47 annuleringstest | Geen Docker-uitvoering gevonden. |
| 5 | 13-10 22:48 | Haal MODS-context op | T-47 context-/bronproef | Geen Docker-uitvoering gevonden. |
| 6 | 13-10 02:03 | Inventariseer de repository | my-mods inventarisatie en begrensde T-30-test | Geen Docker-uitvoering gevonden. |
| 7 | 12-10 22:43 | Codex usage — read-only bronproef | Eén read-only get_context-bronproef | Geen Docker-uitvoering gevonden. |
| 8 | 12-10 20:01 | Usage-ledger 4 codex | M48 usage-ledger, leeskant en kostenoverzichten | Mac: m48-i2-insights-test, PostgreSQL-integratietests; daarna verwijderd. |
| 9 | 08-10 16:34 | Voer When2Watch-sprint uit | When2Watch IDEA-241, Engels, afspraakmodel en tijdzones | Mac: bestaande w2w-test-pg hergebruikt. max2: releasebuilds, migratie en appuitrol. |
| 10 | 08-10 13:09 | When2Watch V2 | When2Watch V2/IDEA-241 verkennen | Geen Docker-uitvoering gevonden. |
| 11 | 07-10 21:09 | Werk IDEA-216 When2Watch uit | When2Watch IDEA-216 ontwikkelen; later IDEA-219 uitwerken | max2: appimages bouwen en webcontainer uitrollen. Geen lokale Docker-creatie aangetoond in deze chat. |
| 12 | 07-10 20:22 | Laat Codex de volgende stap noemen | Globale instructie over resultaat en volgende stap | Geen Docker-uitvoering gevonden. |
| 13 | 07-10 04:08 | Onderzoek geldigheidsduur QR-login | QR-login met gekozen sessieduur | Mac: qr-login-sprint-pg en qr-login-release-pg voor database-/releasecontroles. |
| 14 | 07-10 02:51 | Pak reviewverzoek op | Media-Organizer, gepinde plan-/deltareview | Compose-bestand gelezen; geen Docker-runtimeactie gevonden. |
| 15 | 06-10 22:21 | Verwijder folders direct met rm | Media-Organizer, recursief verwijderen | Mac: media-recursive-t237-postgres voor DB-tests. max2: tijdelijke Linux/NFS-proefcontainers. |
| 16 | 06-10 20:56 | Onderzoek optionele PPE-parameters | MCP, optionele PPE-statusparameters | Geen Docker-uitvoering gevonden. |
| 17 | 04-10 21:25 | Start queue monitor | Queue-monitor en reviewwerk | Geen Docker-uitvoering gevonden. |
| 18 | 04-10 14:28 | Review M42-vis-design-migratie | M42 UI-/DataTable-migratie en praktijkproef | Mac: bestaande local-postgres-postgres-1 gebruikt; Docker-storing onderzocht. Ook serveruitrol via scrum4me-srv. |
| 19 | 03-10 15:33 | Vervang GitHub-verwijzingen in CLAU | inspannings-monitor, Forgejo-verwijzingen | Geen Docker-uitvoering gevonden. |
| 20 | 03-10 11:37 | Onderzoek Superpowers-updates | Superpowers-installatie en updates onderzoeken | Geen Docker-uitvoering gevonden. |

## Containers die aantoonbaar lokaal zijn gemaakt of gebruikt

### Aanmaak in de onderzochte sessies

| Container | Image | Doel en bewijs | Huidige toestand |
|---|---|---|---|
| `usage-v1-t197-pg17` | `postgres:17` | Chat 1, subagent: usagepagina, echte DB-tests en preview; named volume `usage-v1-t197-pg17-data`; poort 55497 | Aanwezig, gestopt |
| `m48-i2-insights-test` | `postgres:17-alpine` | Chat 8: M48-leeskant/integratietests, poort 55439; aanmaak retourneerde container-ID | Stop en verwijdering in historie; nu afwezig |
| `qr-login-sprint-pg` | `postgres:17` | Chat 13: QR-login-/sessieduurtests, poort 55436 | Aanwezig, gestopt |
| `qr-login-release-pg` | `postgres:17` | Chat 13: aparte release-/verificatie-DB, poort 55437 | Aanwezig, gestopt |
| `media-recursive-t237-postgres` | PG17-image `67f41722b7a8…` | Chat 15: databasebootstrap en suite voor recursief verwijderen; dynamische loopbackpoort 52565 | Aanwezig, gestopt |
| `codex-pilot-gate-0797c8d4ebf6` | Gepind PG17.9-image `2a0d0fe14825…` | Chat 1: echte usage-handler tegen wegwerp-PG; 15 tests geslaagd volgens toenmalig proefresultaat | Cleanup bevestigd; nu afwezig |
| `codex-auto-delivery-bd8da8343829` | Hetzelfde PG17.9-image | Chat 1/subagent: usage-aflevering en herstel na verloren resultaat | Cleanup bevestigd; nu afwezig |
| `codex-auto-delivery-200d7666d702` | Hetzelfde PG17.9-image | Herhaalde aflever-/crashproef | Cleanup bevestigd; nu afwezig |
| `codex-auto-delivery-0cc3d60684d2` | Hetzelfde PG17.9-image | Verse proef na harnessreparatie op 14 oktober; 1 handler-/PG-test geslaagd | Cleanup bevestigd; nu afwezig |

Dit zijn **minstens negen met naam onderbouwde lokaal aangemaakte containers**. Daarnaast tonen de logs geslaagde containerstarts bij mislukte tussenruns van de auto-delivery-proef; de bewaarde uitvoer levert niet voor elke tussenrun een naam. Die starts zijn niet als extra benoemde containers verzonnen.

### Bestaande containers die opnieuw werden gebruikt

- **`w2w-test-pg` / `postgres:17`:** gemaakt op 25 september, hergebruikt in chat 9 voor When2Watch-tests. `npm run test:db:up` faalde eerst door een bestaande naam; daarna werd de bestaande container gestart. Die fout heeft geen nieuwe container gemaakt.
- **`local-postgres-postgres-1` / `postgres:17`:** gebruikt in chat 18 voor de M42-browser-/UI-proef, via `127.0.0.1:5433`. Aanmaak van deze Compose-stack is niet aan de twintig geselecteerde chats toegeschreven. De lokale Docker-storing blokkeerde de database en daarmee de praktijkproef.
- **`m41-t1972-pg`:** verscheen in chat 18 alleen in de inventaris van tegelijk actieve containers. Dat bewijst aanwezigheid op dat moment, geen aanmaak of gebruik door die chat. Nu niet meer aanwezig.

### Alle huidige Mac-containers

De inventaris bevat **8 containers, waarvan 0 draaiend**. Alle acht zijn PostgreSQL-containers. Bij geen van deze acht staat AutoRemove aan.

| Naam | Container-ID, kort | Gemaakt op, lokaal | Image | Status | Koppeling aan selectie |
|---|---|---|---|---|---|
| `usage-v1-t197-pg17` | `d23e12cea071` | 2026-10-07 | `postgres:17` | exited, exit 255 | Chat 1: aangemaakt |
| `media-recursive-t237-postgres` | `a29c54d1b0c1` | 2026-10-06 | `67f41722b7a8` | exited, exit 0 | Chat 15: aangemaakt |
| `qr-login-release-pg` | `ba27755286a8` | 2026-10-06 | `postgres:17` | exited, exit 255 | Chat 13: aangemaakt |
| `qr-login-sprint-pg` | `94f80aa9a952` | 2026-10-06 | `postgres:17` | exited, exit 255 | Chat 13: aangemaakt |
| `codex-modelregistry-pg-20261001` | `7b6502f473cf` | 2026-10-01 | `postgres:17` | exited, exit 0 | Geen aanmaakbewijs binnen selectie |
| `scrum4us-t549-postgres` | `111edf4e5910` | 2026-09-30 | `pgvector/pgvector:pg17` | exited, exit 0 | Geen aanmaakbewijs binnen selectie |
| `local-postgres-postgres-1` | `168f3de0e0d0` | 2026-09-28 | `postgres:17` | exited, exit 0 | Chat 18: bestaande DB gebruikt |
| `w2w-test-pg` | `a055bed71000` | 2026-09-25 | `postgres:17` | exited, exit 0 | Chat 9: bestaande DB gebruikt |

`codex-modelregistry-pg-20261001` en `scrum4us-t549-postgres` passen op naam bij eerder testwerk, maar de naam alleen bewijst hun opdracht of maker niet. De data-inhoud van deze databases is niet gelezen.

## Images op de Mac

Voor de onderbouwde lokale aanmaak hierboven zijn **bestaande PostgreSQL-images** gebruikt: `postgres:17`, `postgres:17-alpine` en de pin behorend bij `postgres:17.9`. Er is in de onderzochte historie geen positieve bouwuitkomst gevonden waarmee de onderstaande zelf benoemde Mac-app-/runnerimages aan deze twintig chats kunnen worden toegeschreven. Dat sluit gebruik door andere Codex-sessies, Claude, CI of handmatig werk niet uit.

De actuele volledige inventaris bevat **23 image-ID's** (`docker image ls -a`), inclusief één ongetagd image dat door `scrum4us-t549-postgres` wordt gebruikt.

| Image/ref | ID, kort | Door Docker getoonde grootte | Betekenis/herkomstgrens |
|---|---|---|---|
| `s4m-model-claude-probe:test` | `d91024f0aa40` | 2GB | Runner-/egress-testimage volgens naam; maker en opdracht niet bewezen in selectie |
| `s4m-model-codex:u7-smoke` | `7e157a7f99d0` | 2.2GB | Runner-/egress-testimage volgens naam; maker en opdracht niet bewezen in selectie |
| `s4m-model-codex-probe:test` | `a7ef7bccde62` | 2.2GB | Runner-/egress-testimage volgens naam; maker en opdracht niet bewezen in selectie |
| `s4m-dispatch-egress:test` | `da7ec3aa4461` | 1.65GB | Runner-/egress-testimage volgens naam; maker en opdracht niet bewezen in selectie |
| `s4m-dispatch-egress:u7-smoke` | `2c397f2f33be` | 1.65GB | Runner-/egress-testimage volgens naam; maker en opdracht niet bewezen in selectie |
| `postgres:16` | `ca0bd484cb98` | 663MB | Aanwezig basis-/databaseimage; pull/maker niet bewezen in selectie |
| `pgvector/pgvector:pg17` | `ac08538c6f8b` | 656MB | Aanwezig basis-/databaseimage; pull/maker niet bewezen in selectie |
| `codex-modelregistry-workers:test` | `e472e27aa75d` | 454MB | Projectspecifiek image; bouw niet bewezen in selectie |
| `media-organizer-metadata-base:20260922` | `01c0f92057a4` | 915MB | Projectspecifiek image; bouw niet bewezen in selectie |
| `node:24-bookworm-slim` | `0e0ff40c39bc` | 351MB | Aanwezig basis-/databaseimage; pull/maker niet bewezen in selectie |
| `debian:bookworm-slim` | `3783cc01769c` | 138MB | Aanwezig basis-/databaseimage; pull/maker niet bewezen in selectie |
| `debian:bookworm` | `f37a335e82bc` | 207MB | Aanwezig basis-/databaseimage; pull/maker niet bewezen in selectie |
| `docker:dind` | `3f3c01aaaebf` | 480MB | Aanwezig basis-/databaseimage; pull/maker niet bewezen in selectie |
| `postgres:17-alpine` | `b0f9560a2de0` | 415MB | Aantoonbaar lokaal gebruikt in selectie; geen nieuwe lokale imagebuild |
| `docker:cli` | `018edbc908e0` | 224MB | Aanwezig basis-/databaseimage; pull/maker niet bewezen in selectie |
| `alpine:3` | `294b683cb724` | 13.6MB | Aanwezig basis-/databaseimage; pull/maker niet bewezen in selectie |
| `scrum4me-workers:idea-214-task8` | `04e29de8ee58` | 451MB | Projectspecifiek image; bouw niet bewezen in selectie |
| `ubuntu:24.04` | `008173c23f95` | 141MB | Aanwezig basis-/databaseimage; pull/maker niet bewezen in selectie |
| `node:24.19.0-bookworm` | `4196d66a565c` | 1.63GB | Aanwezig basis-/databaseimage; pull/maker niet bewezen in selectie |
| `postgres:17` | `67f41722b7a8` | 667MB | Aantoonbaar lokaal gebruikt in selectie; geen nieuwe lokale imagebuild |
| `<none>:<none>` | `cf134a767f47` | 646MB | Oud PostgreSQL-image van bestaande Scrum4Us-testcontainer; ongetagd |
| `postgres:<none>` | `347bc4e64006` | 666MB | Aanwezig basis-/databaseimage; pull/maker niet bewezen in selectie |
| `postgres:17.9` | `2a0d0fe14825` | 666MB | Aantoonbaar lokaal gebruikt in selectie; geen nieuwe lokale imagebuild |

De vijf s4m-runner-/egressimages dragen een bouwtijd op 12 oktober. Die datum bewijst geen Codex-toeschrijving. Hun precieze bouwdoel verdient een apart brononderzoek als ze ook moeten worden behouden of gemigreerd.

`docker system df` rapporteerde: images **8,715 GB**, volumes **82 / 6,766 GB**, buildcache **4,053 GB**. Slechts acht volumes zijn aan de huidige containers gekoppeld. Deze opslagcategorieën mogen niet zonder meer worden opgeteld als gegarandeerd vrij te maken schijfruimte. Gestopt of reclaimable betekent ook niet dat de inhoud waardeloos is.

## Docker-werk dat al buiten de Mac plaatsvond

- **When2Watch:** chat 11 bouwde en deployde releases op max2 via SSH. Succesvolle bouwuitvoer noemt onder meer `when2watch:dfc39bb`, `:4a50e76`, `:93bbaed`, `:4379141`, `:2153d94`, `:b31af05`, `:c04812c`, `:d13cad0`, `:e864397` en `:fb7a690`. Chat 9 bouwde `when2watch:c35cd1a` en `when2watch-tools:c35cd1a`, draaide een migratie en verving de webcontainer. Dit zijn remote builds; ze staan niet in de Mac-image-inventaris. De genoemde tags zijn concrete historische voorbeelden, geen volledige releasecatalogus.
- **When2Watch-containers op max2:** `when2watch-web-1`, `when2watch-db-1`, tijdelijke Compose-migratiecontainers en benoemde readbacks `w2w-idea241-readback-c35` en `w2w-idea241-postsync-readback`. Historisch gemaakte/readback-containers zijn niet noodzakelijk nog aanwezig. Live staat de webcontainer inmiddels op `when2watch:3c7b9ec`; `:c35cd1a` is dus geen claim over de actuele release.
- **Media-Organizer:** chat 15 gebruikte op max2 `media-recursive-t237-inspect`, `media-recursive-t237-rm-version`, `media-recursive-t237-probe` en `media-recursive-t237-qualification-inspect`, met `--rm` en een bestaand gepind appimage. Doel: echt Linux-/NFS-gedrag onderzoeken. Deze proeven horen bij het doelplatform; een lokale Mac-test zou dat gedrag niet vervangen.
- **Scrum4Me-server:** chats 1 en 18 bevatten bestaande-containerinspecties/DB-readbacks en builds of uitrol op `scrum4me-srv`, onder meer `scrum4me-mcp-http` en Workers. Ook dit is geen gebruik van de lokale Docker-engine.

## Wat op max2 al werkt

| Onderdeel | Actueel vastgesteld |
|---|---|
| SSH | Bestaande alias `max2`, gebruiker `janpeter`, BatchMode werkt zonder nieuwe sleutels of host-key-acceptatie |
| Docker-toegang | Gebruiker heeft toegang tot de bestaande engine; lid van docker-groep |
| Engine | Docker 29.9.0, Linux/amd64, Docker-root `/var/lib/docker` |
| Compose / Buildx | Compose v5.6.0, Buildx v0.38.0 |
| Codex | `/usr/bin/codex`, CLI 0.154.0 aanwezig; login/configuratie voor een nieuw remote project niet gevalideerd |
| Capaciteit, momentopname | 28 CPU's volgens Docker; circa 30 GiB RAM, 24 GiB beschikbaar; circa 582 GB vrije schijf op het Docker-filesysteem |
| Bestaande workloads | Onder meer When2Watch, Media-Organizer, Ops-dashboard, Caddy, agentworkers en Forgejo-runners |

De volgende **read-only proef is echt uitgevoerd en geslaagd**:

```sh
docker -H ssh://max2 info --format 'name={{.Name}} architecture={{.Architecture}} cpus={{.NCPU}} memory={{.MemTotal}} root={{.DockerRootDir}}'
```

Resultaat: `name=max2 architecture=x86_64 cpus=28 memory=32821678080 root=/var/lib/docker`.

Dit bewijst verbinding en Docker-API-toegang vanuit de huidige Codex-shell. Het bewijst nog geen containerstart, build, testpoorttunnel, lokale browsertest of werking met Docker Desktop afgesloten.

## Benodigde aanpassingen

### 1. Expliciete remote Docker-keuze

Maak bij uitvoering een context voor het gekozen ontwikkelendpoint. Een context kan via SSH met een remote engine werken; daarvoor is geen nieuwe publiek bereikbare Docker-API nodig. [Docker: SSH-toegang](https://docs.docker.com/engine/security/protect-access/)

Voorbeeld voor **de al bereikbare bestaande engine**; deze configuratie is nog niet aangemaakt:

```sh
docker context create max2-codex --docker host=ssh://max2
docker --context max2-codex info
```

Gebruik eerst expliciet `--context max2-codex` in de betrokken opdrachten. Bestaande `--host unix:///…` en `--context desktop-linux` moeten afzonderlijk worden verwijderd/geparametriseerd; een contextwissel neemt die expliciete keuzes niet weg. [Docker-contexten](https://docs.docker.com/engine/manage-resources/contexts/)

De contextnaam is alleen een routeringsnaam. Hij maakt geen aparte Docker-engine en beperkt geen rechten. Omdat de bestaande max2-engine ook productie bedient, zijn er twee concrete mogelijkheden: een afgebakende pilot op die engine met uitsluitend eigen testresources, of een aparte ontwikkelengine onder een afzonderlijke gebruiker. Voor structurele scheiding heeft die tweede optie mijn voorkeur; rootless Docker kan daemon en containers zonder host-root laten draaien, maar vereist een eigen compatibiliteitsproef voor deze workloads. [Docker rootless](https://docs.docker.com/engine/security/rootless/)

### 2. Testdatabases bereikbaar maken vanaf de Mac

Een met `-p 127.0.0.1:55497:5432` gepubliceerde remote containerpoort luistert op **max2**. De Docker-SSH-verbinding tunnelt geen PostgreSQL- of webverkeer mee. Houd de service aan remote loopback gebonden en gebruik een aparte SSH-forward naar een gecontroleerde vrije Mac-poort. [Docker-poortpublicatie](https://docs.docker.com/engine/network/port-publishing/)

```sh
# Illustratie nadat de remote testcontainer en beide vrije poorten zijn gecontroleerd:
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30   -L 127.0.0.1:55497:127.0.0.1:55497 max2
```

De test krijgt dan bijvoorbeeld `DATABASE_URL` of `USAGE_TEST_DATABASE_URL` naar `127.0.0.1:55497`. Gebruik echte host/DB-/eigenaarschapscontrole voordat migraties of destructive fixtures draaien. Alleen het woord localhost bewijst niet dat de database een testdatabase is. Deze route laat de bestaande localhost-allowlist van Media-Organizer intact. De tunnel moet door de uitvoerprocedure worden geopend, bewaakt en gesloten.

### 3. Mac-paden en bind mounts vervangen

Concrete voorbeelden zijn de secretfile `/tmp/usage-v1-t197.hC4FPg/pg-password` en de initdirectory van `local-postgres`. Een remote bind mount wordt op de daemonhost opgelost; een `/Users/janpetervisser/…`-pad op de Mac wordt niet automatisch naar max2 gekopieerd. Gebruik remote voorbereid materiaal, `docker cp`, een named volume of een buildcontext. Tijdelijke credentials moeten alleen op het gekozen doel terechtkomen. [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)

Voor imagebuilds kunnen lokale bestanden als buildcontext naar de builder worden gestuurd; beoordeel daarbij `.dockerignore` en welke bestanden daadwerkelijk meegaan. Voor bestandsintensieve runtimetests is een remote checkout vaak eenvoudiger. [Docker buildcontext](https://docs.docker.com/build/concepts/context/)

### 4. De concrete proefscripts aanpassen

Historisch bewezen vindplaatsen uit chat 1:

- `docs/reports/codex-pilot-handler-2026-10-13/run-probe.py`: expliciete context `desktop-linux`, PG17.9-pin en dynamische loopbackpoort.
- `docs/reports/codex-pilot-handler-2026-10-13/auto-delivery-probe.py`: expliciete `--host unix:///Users/janpetervisser/.docker/run/docker.sock`, lokale PG17.9-pin en een gesanitiseerde HOME.
- When2Watch `package.json`, script `test:db:up`: vaste naam `w2w-test-pg` en poort 55432; bestaand naamconflict is daadwerkelijk opgetreden.
- Media-Organizer `scripts/test-db-bootstrap.ts`: beperkte database-/hostallowlist; de testomgeving moet daar inhoudelijk aan blijven voldoen.
- Ad-hoc DB-opdrachten voor QR-login/M48 en de `local-postgres`-Compose-stack: expliciete remote bediening, unieke namen en bijbehorende tunnelconfiguratie.

Dit zijn migratievindplaatsen uit de logs, geen in dit onderzoek gewijzigde of opnieuw gekwalificeerde repositorybestanden. Bij uitvoering eerst de actuele branch/bronpin en repo-instructies lezen.

Maak Docker-endpoint, testpoort en imagepin expliciete invoer. Houd Docker-/SSH-orchestratie buiten de subprocessen die HOME en credentials bewust afschermen; geef die tests alleen hun begrensde test-DB-URL. Een globale `DOCKER_CONTEXT`-instelling is hiervoor onvoldoende. Voeg per run een unieke containernaam en eigenaarslabel toe; leg container-ID en aangemaakte volumes vast. Cleanup raakt alleen die vastgelegde resources. Dit voorkomt de bewezen When2Watch-naamconflicten en achtergebleven testvolumes; namen/labels vormen op zichzelf geen autorisatiegrens.

### 5. Architectuur en imagepins

De Mac draait Linux/arm64-images; max2 is Linux/amd64. Controleer voor de gebruikte PostgreSQL-versies de amd64-variant en pin die verifieerbaar. Controleer of een bestaande digest een manifestlijst of een platformspecifiek image aanwijst; neem een lokale image-ID met `--pull=never` niet blind over. Bouw projectspecifieke images op max2 of als bewuste multi-platformbuild. [Docker multi-platform](https://docs.docker.com/build/building/multi-platform/)

Verhuis voor reproduceerbare testdatabases liever de definitie en fixtures dan oude containerschijven. Onderzoek en backup waardevolle ontwikkeldata, met name `local-postgres-data`, voordat iets wordt verwijderd. Voor te behouden PostgreSQL-data hoort een logische dump/restore met controle bij de uitvoering. Er is nu geen data gekopieerd of gewist.

### 6. Codex-instructies en lokale hulpmiddelen

Leg na akkoord in de toepasselijke Codex-/repo-instructies vast: gekozen endpoint, testresourceprefix/labels, poortprocedure, eigenaarschapscontrole, en gedrag bij onbereikbaar max2. Voor deze workloads moet een onbereikbaar endpoint de proef stoppen; automatische terugval naar Docker Desktop maakt de migratie oncontroleerbaar. Bestaande afzonderlijke productieopdrachten blijven een expliciete andere context.

Op deze Mac is `/usr/local/bin/docker` een verwijzing naar `/Applications/Docker.app/Contents/Resources/bin/docker`. Ook Compose en Buildx verwijzen naar Docker.app. De Docker-config gebruikt `credsStore: desktop`. Voor volledig verwijderen van Docker Desktop moeten een zelfstandige Docker-CLI, Compose, Buildx en een passende credential-helper beschikbaar zijn. Op macOS ondersteunt Docker onder meer `osxkeychain`. Controleer registrytoegang zonder credentials te tonen. [Docker credential stores](https://docs.docker.com/reference/cli/docker/login/)

Stop Docker Desktop pas na de eerste geslaagde remote proef. Verwijder de app en lokale data pas na een geslaagde proef met Desktop afgesloten én een besluit over de te behouden volumes. De huidige aantallen bewijzen niet dat alle 82 volumes weggegooid kunnen worden.

## Alternatief: het hele Linux-project via Codex op max2

OpenAI documenteert remote projecten via SSH: hostalias toevoegen, Codex op de host beschikbaar en geauthenticeerd maken, vervolgens de SSH-host en projectmap via Settings → Connections kiezen. Shell en bestanden van zo'n project zitten dan op max2. In deze onderzoekschat is alleen de lokale host aangesloten; het beschikbaar zijn van `/usr/bin/codex` bewijst nog geen complete remote-projectconfiguratie. [OpenAI: SSH-host verbinden](https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host)

| Route | Effect | Werk dat nodig is |
|---|---|---|
| Codex op Mac, Docker op max2 — eerste aanbeveling | Docker-VM en containerbelasting verhuizen; lokale Node/Next-tests blijven lokaal | Context, tunnels, mount-/pin-/scriptcorrecties |
| Codex-project en Docker op max2 | Ook Linux-builds/tests en repo-I/O verhuizen | Remote checkout, login, tools, MCP, skills, repo-instructies en secrets per host configureren; UI/browserbereik testen |

Voor die tweede route moeten Mac-specifieke paden worden aangepast en eventuele Scrum4Me-identiteiten de gekozen host correct weergeven. Neem authbestanden of complete configuraties niet ongemerkt over. Xcode, iOS-simulator en andere Mac-specifieke verificatie blijven op de Mac. Een Codex-container bouwen is voor geen van beide routes een vereiste.

## Voorgesteld eerste increment

**Doel:** één bestaande PostgreSQL-integratietest vanaf de Mac laten slagen tegen een uitsluitend daarvoor aangemaakte databasecontainer op max2, met Docker Desktop afgesloten. Dat toetst meteen de belangrijkste werkelijke gebruiksvorm.

**Keuze vooraf door JP:** beperkte pilot op de al bereikbare max2-engine, of eerst een afzonderlijke ontwikkelengine. De eerste route is de kleinste proef; de tweede beperkt structureel de toegang tot productieresources.

**Bestanden/interfaces:** Docker-contextconfiguratie, een kleine taakgebonden start/stop-/tunnelprocedure, gekozen bestaande testcommand/DB-URL en een bewijsbestand in de betreffende repo. Nog geen generiek testplatform of migratie van alle projecten.

**Uitvoering na akkoord:**

1. Verifieer het gekozen endpoint en leg de baseline van bestaande containers vast. Kies één afgebakende bestaande test en de bijbehorende productcontext/bronpin.
2. Maak één gelabelde PG-testcontainer met een gecontroleerde amd64-imagepin, eigen DB, begrensde resources en loopbackpoort op max2. Maak geen verbinding met bestaande productie-DB's.
3. Open de tunnel, bewijs de identiteit van de nieuwe testdatabase en voer de bestaande gekozen integratietest uit vanaf de Mac.
4. Herhaal de relevante verbinding/test met Docker Desktop afgesloten. Verifieer dat de gebruikte CLI/plugins nog werken en dat een nieuwe Codex-shell dezelfde route kan gebruiken.
5. Sluit de tunnel en verwijder uitsluitend de eigen tijdelijke container/volume(s); vergelijk de bestaande-containerbaseline. Bewaar opdracht, host, imagepin, container-ID, testuitslag en cleanupbewijs.

**Acceptatie:** test slaagt; Docker geeft host `max2` terug; PostgreSQL-identiteit hoort bij de nieuwe proef; geen Mac-container is gestart; geen productieresource is gewijzigd; cleanup is bewezen; de procedure werkt met Desktop uit. Een succesvolle `docker info` alleen haalt deze acceptatie niet.

**Daarna op hoofdlijnen:** dezelfde werkwijze toepassen op my-mods/usage, QR-login, M48, When2Watch en Media-Organizer; een remote imagebuild kwalificeren; beslissen over behoud van lokale data; pas dan Docker Desktop verwijderen. Per product gelden de bestaande Scrum4Me-plan-/uitvoergrenzen.

## Bronnen en controleerbaar bewijs

### Lokale bronnen

- Hoofdchatselectie: `/Users/janpetervisser/.codex/state_5.sqlite`, read-only geopend.
- Uitvoeringshistorie: `/Users/janpetervisser/.codex/thread_history_1.sqlite`, read-only; vergeleken met oorspronkelijke rollouts.
- Live Mac: `docker version`, `context ls`, `buildx ls`, `ps -a`, beperkte `inspect`, `image ls -a`, `image inspect`, `system df`; inspectie van CLI-symlinks en alleen relevante niet-geheime Docker-/Codex-configvelden.
- Live max2: bestaande SSH-route met BatchMode/StrictHostKeyChecking; `hostname`, `uname -m`, `id`, versies, `docker ps -a`, `free -h`, `df -h`; aansluitend de geslaagde Docker-over-SSH-read-only proef.
- `docker-inventaris-2026-10-14.json` naast dit rapport bevat de geschoonde container-/image-inventaris met volledige IDs. Geen container-env, wachtwoorden of Codex-authbestanden zijn daarin opgenomen.

### Selectie en historische referenties

`ordinal` hieronder verwijst naar `thread_items.rollout_ordinal`; dit is geen broncoderegelnummer. Alle testresultaten in deze paragraaf zijn historisch bewijs en zijn voor dit onderzoek niet opnieuw uitgevoerd.

| Bewijs | Chat/agent | Ordinal / toelichting |
|---|---|---|
| Usage-PG aangemaakt, ready | `01a11559-bba6-77e2-8f2d-27b6b0a5bd49` | 313, `docker run`, `PG17_READY`; hoort bij hoofdchat 1 |
| M48-PG aangemaakt | Hoofdchat 8 | 3998, container-ID `969fe18b5829…` |
| M48 cleanup | Hoofdchat 8 | 4686, stop/rm-resultaat en huidige afwezigheid |
| QR-PG's aangemaakt | Hoofdchat 13 | 403 en 936, exacte IDs komen overeen met live inventaris |
| Media-PG aangemaakt | Hoofdchat 15 | 744, ID `a29c54d1b0c1…`, poort 52565 |
| Usage-handlerproef | Hoofdchat 1 | 9747 uitvoering; 9756 evidence-readback met containernaam/ID en verwijdering |
| Auto-delivery tussenruns | `01a13790-a0b3-7481-aa4a-8e62ecba716a` | 171 mislukte creatie; 191/203 wel container gestart maar proef mislukt; 214 geslaagde run; 252 naam/readback |
| Auto-delivery definitieve proef | `01a137cd-e5bd-7a53-8292-2af68fcc3e77` | 105 uitvoering, 116 readback: `codex-auto-delivery-0cc3d60684d2` en cleanup |
| Mac-socket expliciet gemaakt | `01a13790-a0b3-7481-aa4a-8e62ecba716a` | 191; fout door gesanitiseerde HOME opgelost met vaste Unix-socket |

1. **Codex usage vastleggen** — `01a1142e-7e7c-78f0-9500-bdf800a887e2`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/07/rollout-2026-10-07T04-25-53-01a1142e-7e7c-78f0-9500-bdf800a887e2.jsonl`

2. **Haal MODS-context op** — `01a13737-746b-71b1-ae90-b7f66c92ea02`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/13/rollout-2026-10-13T23-42-23-01a13737-746b-71b1-ae90-b7f66c92ea02.jsonl`

3. **Rond foregroundproef beurt 2 af** — `01a1373b-6c17-7fe2-9608-1e3658b92966`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/13/rollout-2026-10-13T23-46-43-01a1373b-6c17-7fe2-9608-1e3658b92966.jsonl`

4. **Voer T-47 annuleringstest uit** — `01a13713-a026-7bf1-90d9-34bfe5f1b940`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/13/rollout-2026-10-13T23-03-15-01a13713-a026-7bf1-90d9-34bfe5f1b940.jsonl`

5. **Haal MODS-context op** — `01a13700-683a-7741-8955-7ea2dae129bd`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/13/rollout-2026-10-13T22-42-16-01a13700-683a-7741-8955-7ea2dae129bd.jsonl`

6. **Inventariseer de repository** — `01a13280-3bca-7d03-9850-9db54e8eac65`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/13/rollout-2026-10-13T01-43-47-01a13280-3bca-7d03-9850-9db54e8eac65.jsonl`

7. **Codex usage — read-only bronproef** — `01a131da-82c0-7ca2-ba45-53d835e79b5c`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/12/rollout-2026-10-12T22-42-46-01a131da-82c0-7ca2-ba45-53d835e79b5c.jsonl`

8. **Usage-ledger 4 codex** — `01a1162a-70ff-7930-b16e-8c99dbd844e5`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/07/rollout-2026-10-07T13-40-42-01a1162a-70ff-7930-b16e-8c99dbd844e5.jsonl`

9. **Voer When2Watch-sprint uit** — `01a11b31-86cd-7293-b557-50fe9e541f63`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/08/rollout-2026-10-08T13-06-33-01a11b31-86cd-7293-b557-50fe9e541f63.jsonl`

10. **When2Watch V2** — `01a1179c-e081-76b1-9d18-76874f80074e`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/07/rollout-2026-10-07T20-25-19-01a1179c-e081-76b1-9d18-76874f80074e.jsonl`

11. **Werk IDEA-216 When2Watch uit** — `01a0ce4f-4b85-7fc0-a63d-0df577fe5931`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/09/23/rollout-2026-09-23T14-48-18-01a0ce4f-4b85-7fc0-a63d-0df577fe5931.jsonl`

12. **Laat Codex de volgende stap noemen** — `01a11794-c9e5-7560-af5a-8b205d369b26`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/07/rollout-2026-10-07T20-16-29-01a11794-c9e5-7560-af5a-8b205d369b26.jsonl`

13. **Onderzoek geldigheidsduur QR-login** — `01a1128b-b14f-7f01-a13e-076f0afeb976`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/06/rollout-2026-10-06T20-48-27-01a1128b-b14f-7f01-a13e-076f0afeb976.jsonl`

14. **Pak reviewverzoek op** — `01a11376-22b9-78c2-b420-c1e5e9b4dbb4`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/07/rollout-2026-10-07T01-04-31-01a11376-22b9-78c2-b420-c1e5e9b4dbb4.jsonl`

15. **Verwijder folders direct met rm** — `01a11270-1c3a-7980-940b-e29f652b42fa`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/06/rollout-2026-10-06T20-18-19-01a11270-1c3a-7980-940b-e29f652b42fa.jsonl`

16. **Onderzoek optionele PPE-parameters** — `01a1127d-b864-7702-a615-ac781cc9dee0`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/06/rollout-2026-10-06T20-33-11-01a1127d-b864-7702-a615-ac781cc9dee0.jsonl`

17. **Start queue monitor** — `01a107e4-4d5f-7591-bf11-944dca7f0c67`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/04/rollout-2026-10-04T19-09-24-01a107e4-4d5f-7591-bf11-944dca7f0c67.jsonl`

18. **Review M42-vis-design-migratie** — `01a1021b-297d-70a0-8d6b-1c4668415533`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/03/rollout-2026-10-03T16-11-37-01a1021b-297d-70a0-8d6b-1c4668415533.jsonl`

19. **Vervang GitHub-verwijzingen in CLAU** — `01a101f4-0f54-7981-831b-c63b2fbbdbfe`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/03/rollout-2026-10-03T15-28-54-01a101f4-0f54-7981-831b-c63b2fbbdbfe.jsonl`

20. **Onderzoek Superpowers-updates** — `01a1011c-9393-78b1-8494-305e637d1605`
   Rollout: `/Users/janpetervisser/.codex/sessions/2026/10/03/rollout-2026-10-03T11-33-32-01a1011c-9393-78b1-8494-305e637d1605.jsonl`

## Resultaat en volgende stap

**Resultaat:** twintig hoofdchats met hun onderliggende agentwerk onderzocht; lokale containers/images geïnventariseerd; historische Mac-creatie van remote werk onderscheiden; Docker-API-toegang naar max2 live read-only bewezen. Onderzoek en advies zijn opgeleverd. Er is geen context gewijzigd, container gestart, image gebouwd/gepullt, test uitgevoerd, data gemigreerd of Docker-resource verwijderd tijdens dit onderzoek.

**Volgende stap — JP:** kies en autoriseer het eerste increment: één PostgreSQL-test op de bestaande max2-engine, of eerst een afzonderlijke ontwikkelengine. Codex kan daarna de gekozen concrete proef uitvoeren. Dit besluit is nodig omdat het huidige verzoek onderzoek en migratieadvies betreft en max2 ook productie bedient.
