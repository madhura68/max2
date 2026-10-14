# Review record — spec IDEA-258 Dev-Docker op max2 (`dev-docker/SPEC.md`)

**Fase:** spec. **Max rondes:** 10. **Reviewers:** twee dispatch-jobs per ronde (`runtime: CODEX` en `runtime: CLAUDE`), onafhankelijk; geen listener-fallback besteld. **Idee:** IDEA-258 (`cmv762uop001om97rsic6a6o9`), `idea_phase: SPEC`. **Product:** max2 (`cmsx8wyex0000hk7rx1428yyl`). **Orchestrator:** max2:claude (Claude Fable 5.1) in sessie met JP, 14-10-2026.

Dit record is de persistente toestand van de loop; het wordt nooit gepind. Een nieuwe sessie herneemt vanaf dit bestand plus `get_dispatch` op de request-ids.

## Ronde 1 — 2026-10-14

**Gepind:** `dev-docker/SPEC.md` @ `69cc7d8a74c883a51f94d8478c8877020b4a25be` (sha256 `224a0e5c8cf2c4bb263ea6286179b449bd178325ffc63aba685ce696acb52177`); context-pins: grill (ProductDoc GRILLS/idea-258-grill, rev `cmv7rt021000fyl174lrf4iyu`) en het PR-32-rapport (`docs/reports/2026-10-14-codex-docker/onderzoek-en-migratieadvies.md` @ `43f724b37c5f076e5cbbc1b7cbf1822080d9f3ec`).

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | `2558726a-a853-4cda-bbf8-4c9d224cc8a0` | `e4c5b78b-be11-457b-804d-97842e26aedc` | job (route job, SUCCEEDED) | `1a896f1d-a48b-4e9b-8fdc-afcea8b77ce9` | linked |
| CLAUDE | `8081f982-d1c1-49ed-a3e0-6cb92178c6f8` | `9e3b551e-e528-4fbd-8824-705411ff8e4f` | job (route job, SUCCEEDED) | `b83d3347-6f6d-42c0-880b-c4dc9e754eac` | linked |

**Dispatch:** beide 07:37 UTC ingediend, state WAITING (waiting_for_capacity).

**Uitslag:** CODEX **NO-GO** (2 BLOCKER, 3 MAJOR, 1 MINOR; antwoord 07:40 UTC). CLAUDE **NO-GO** (0 BLOCKER, 3 MAJOR, 7 MINOR; antwoord 07:41 UTC). Convergent: `docker system prune -af` in prune-stap 4 doorbreekt de leeftijds- en keep-regels en kan een gestopte dev-postgres verwijderen.

**Triage** (elke bevinding tegen de boom en de hostfeiten geverifieerd; metingen 14-10-2026 op max2 en de Mac):

| # | Bron | Sev | Bevinding | Oordeel | Remedie in rev. 2 |
|---|---|---|---|---|---|
| 1 | codex B1 / claude M1 | BLOCKER | `docker system prune -af` verwijdert alle gestopte containers, geen dry-run | accept | §4.7: containers alleen in stap 1; stap 4 = `image prune -af` + `builder prune -af` + `network prune -f`; stap 0 bewaakt dev-postgres (nooit verwijderen, alarm bij gestopt); dry-run uit dezelfde filters, met bewaarde items + reden |
| 2 | codex B2 | BLOCKER | base64-wachtwoord (`/`, `+`, `=`) breekt de URL | accept | §4.5: `openssl rand -hex 24`; helper percent-encodeert toch |
| 3 | codex M3 / claude m4 | MAJOR | volumes zonder 7-dagenregel; `CreatedAt` bestaat wel | accept (gemeten: `docker volume inspect` geeft `CreatedAt`) | §4.7 stap 2: `CreatedAt` > 7 d, `dev.keep`-label, onparseerbaar → overslaan |
| 4 | codex M4 / claude m10 | MAJOR | §7.8-gate zonder invoer en te laat | accept, repair i.p.v. pin | §8: formule en getallen met bron (caps-som 6,0 GiB → ROOD < 12,0 GiB; P6-reeks min 21,53 GiB, 1584 samples); budgetregel `min(8, laagste − 12,0)`; gate in bootstrap-preflight vóór mutaties; sampler tijdens de proef; stopregel. Het ontwerpdocument zelf wordt niet gepind (andere repo); de toepasselijke regel en bronpaden staan nu in de spec |
| 5 | codex M5 / claude m9 | MAJOR | Desktop verwijderd vóór standalone-CLI-controle; dump na afsluiten | accept (gemeten: Homebrew-formulae beschikbaar, `/opt/homebrew/bin` vóór `/usr/local/bin`) | §5.2: fase 3 = Homebrew-CLI + keychain-helper controleren met Desktop afgesloten; fase 4 = dump (Desktop éénmalig gestart) en verwijderen; backups 30 d via prune stap 6 |
| 6 | codex m6 | MINOR | dry-run-acceptatie eist output die de helper niet belooft | accept | §4.7 en §9: dry-run toont bewaarde items met reden; acceptatie via `db list` + bewaard-lijst |
| 7 | claude M2 | MAJOR | `db create`/`db url` printen het wachtwoord naar stdout → transcripten op de Mac-schijf | accept | §6.2: gemaskeerde URL, nieuw `db run <naam> -- <cmd>` (URL alleen in kind-env), `db url --reveal` alleen voor JP; §6.1, §7, §9 aangepast |
| 8 | claude M3 | MAJOR | rootless-installatie niet uitvoerbaar: geen gebruikerssessie/bus; AppArmor-userns-beperking; uidmap/dbus niet gecontroleerd | accept (gemeten: `apparmor_restrict_unprivileged_userns=1` **en** profiel `/etc/apparmor.d/rootlesskit` aanwezig; `uidmap` en `slirp4netns` ontbreken, `setuptool check --force` eist `uidmap`; `Delegate=yes cpu memory pids`) | §4.1: preflight + `apt-get install uidmap slirp4netns`; §4.2: install-user.sh via echte SSH-login vanaf de Mac, bestanden per scp; §10 en §11 aangevuld |
| 9 | claude m5 | MINOR | naamvalidatie laat systeemdatabases door | accept | §4.6 denylist (`postgres`, `template0/1`, `pg_*`); §6.2 regex eist `<project>_<taak>` |
| 10 | claude m6 | MINOR | dry-run schrijft register; drop zonder IF EXISTS/FORCE | accept (gemeten: image = PostgreSQL 17.11) | §4.7: dry-run schrijft niets; `DROP DATABASE IF EXISTS … WITH (FORCE)` |
| 11 | claude m7 | MINOR | `inet_server_addr()` via `docker exec` bewijst het LAN-pad niet; testkeuze mist allowlist-criterium | accept | §9 stap 4 via `db run … psql` vanaf de Mac (libpq aanwezig); selectiecriterium toegevoegd |
| 12 | claude m8 | MINOR | skill mist bind-mount-regel | accept | §6.1 |
| 13 | claude m10 | MINOR | bootstrap kan janpeters checkout niet lezen; 8 GiB als feit geformuleerd; baseline vals-negatief bij legitieme uitrol | accept | §4.2 scp; §4.3/§8 plafond = worstgeval; §8 baseline met uitrol-tijdstempels |

Afgewezen: geen. Deels anders opgelost: #4 (reproductie met bron in plaats van een pin van het ontwerp uit de andere repo).

**Scope-delta ronde 1:** toegevoegd: `db run`, preflight-stap en pakketinstallatie in bootstrap, headroom-sampler en budgetregel, backup-retentie, denylist; verwijderd: `docker system prune`. Eerste bruikbare resultaat en praktijkproef ongewijzigd; de proef krijgt één extra selectiecriterium (niet-loopback host). Spec 280 → 312 regels.

**Scope-delta:** ongewijzigd t.o.v. de grill; enige afwijking is het pad `dev-docker/` i.p.v. `hosts/max2/dev-docker/` (repo-conventie).

## Ronde 2 — 2026-10-14

**Gepind:** `dev-docker/SPEC.md` revisie 2 @ `a10a4d81d586d8acf46fd6cb43c70f8c8aae0cea`; context-pins ongewijzigd (grill rev `cmv7rt021000fyl174lrf4iyu`, PR-32-rapport @ `43f724b37c5f076e5cbbc1b7cbf1822080d9f3ec`).

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | `22b00c9c-c984-4d3c-98cb-3c0eb033eef3` | `f4e6928d-6521-4346-8294-d28129657810` | job (SUCCEEDED) | `c5bc4830-29f2-4711-84ff-c48f57fd323c` | linked |
| CLAUDE | `eb94d1b0-7651-4a3b-a034-b37cfe6c53d2` | `35eaad4e-d20e-4ccf-a5e5-a2a123c2ff8a` | job (SUCCEEDED) | `2e987899-73b1-4a17-8057-adae5247fe96` | linked |

**Dispatch:** beide 07:49–07:50 UTC ingediend, state WAITING (waiting_for_capacity).

**Uitslag:** CODEX **NO-GO** (0 BLOCKER, 1 MAJOR, 3 MINOR; 07:53 UTC). CLAUDE **GO** (0 BLOCKER, 0 MAJOR, 10 MINOR; 07:55 UTC). Convergent: §9 stap 4 expandeert `"$DATABASE_URL"` in de aanroepende shell vóór `db run` de omgeving zet; alias `max2-dev` wordt gebruikt vóór hij bestaat. Codex kon de diff tegen 69cc7d8 niet lezen (depth-1 checkout) en beoordeelde de volledige revisie; claude las pr32 tot regel 229.

**Fixes ronde 1 volgens de reviewers:** codex 10 held, 2 partially (gate, transcript), 1 did not hold (LAN-check); claude 8 held, 5 partially (prune-netwerk, gate-lezing, dry-run-reden, transcript, LAN-check).

**Triage** (geverifieerd tegen de spec en de hostfeiten):

| # | Bron | Sev | Bevinding | Oordeel | Remedie in rev. 3 |
|---|---|---|---|---|---|
| 1 | codex M1 / claude F1 | MAJOR | `psql "$DATABASE_URL"` wordt door de aanroeper geëxpandeerd; URL in argv zichtbaar in `ps` | accept | §6.1/§6.2/§9: `db run` zet ook `PGHOST/PGPORT/PGUSER/PGDATABASE/PGPASSWORD`; `psql -Atc …` zonder URL-argument; skillregel "nooit als argument" |
| 2 | codex m2 / claude F3a | MINOR | alias `max2-dev` gebruikt vóór aanmaak | accept | §9 stappen herordend (alias → rsync+install → context) |
| 3 | codex m3 / claude F1b | MINOR | kind-env is beleid, geen controle; kinduitvoer kan lekken | accept | §6.1/§7: expliciet "bescherming door instructie"; `db run` maskeert kinduitvoer (`--no-redact` niet voor agents); vooraf check van het testcommando; §11 rij 10 |
| 4 | codex m4 | MINOR | minimumbudget: clampen vs weigeren | accept | §8: weigeren onder 2 GiB, nooit omhoog afronden; ook bij hernieuwde proef |
| 5 | claude F2 | MINOR | `network prune` neemt netwerk van gestopte dev-postgres; stap-4-dry-run ongedefinieerd; geen `until`-filter; tag vs digest | accept | §4.7 stap 0: bij falen alleen stap 1 en stoppen; netwerk gelabeld `dev.keep=true` + `label!=`-filter; `until=168h`; dry-run-berekening beschreven; `images.txt` met dezelfde digest als compose |
| 6 | claude F3b | MINOR | `scp -r` niet idempotent; bron en compose-map gemengd | accept | §4 intro/§4.2: `rsync -a --delete` naar `~/dev-docker-src/`, stack in `~/dev-docker/` |
| 7 | claude F4 | MINOR | `bash -s` zonder argumenten; stdin-conflict; sudo zonder tty; AllowUsers | accept (gemeten: sshd heeft geen AllowUsers/AllowGroups) | §4.1: scp + `ssh -t sudo bash /tmp/bootstrap.sh --…`; `DEBIAN_FRONTEND=noninteractive`, apt `</dev/null`; preflight controleert `sshd -T` |
| 8 | claude F5 | MINOR | §8 presenteert eigen lezing als §7.8; venster; drop-in na linger; cgtop toont geen limiet | accept | §8: expliciet als afgeleide regel met de letterlijke 50 %-berekening (14,0 > 10,77 ROOD) en waarom niet gebruikt; **besluit JP** als open punt §12; venster ≥ 24 h met werkdag; §4.1 drop-in vóór linger + `systemctl show`/`memory.max`-controle; §11 rij 4 |
| 9 | claude F6 | MINOR | bind op vast IP kan racen met netwerk bij boot | accept | §4.4/§4.5: publicatie op `0.0.0.0` met ufw als grens (binnen grill-besluit 3); reboot-test §9 stap 9 en §11 rij 2 |
| 10 | claude F7 | MINOR | reden "jonger dan 14 dagen" ontbrak; hex-grep vals positief door digests | accept | §4.7 redenlijst; §9 `grep -F` op de letterlijke waarde + `dev:` zonder `***` |
| 11 | claude F8 | MINOR | CREATE/DROP DATABASE niet in DO-blok; `format('%I')` alleen met `\gexec` | accept | §4.6/§6.2/§4.7: losse statements met `\gexec`; registratie apart; faalsemantiek |
| 12 | claude F9 | MINOR | Desktop-restanten (`cli-plugins`, `desktop-linux`, credsStore); dump zonder `--context` | accept | §5.2 fase 4 |
| 13 | claude F10 | MINOR | `POSTGRES_USER=dev` is superuser; "alleen dev-data" overdreven | accept | §4.5: superuser `postgres` alleen in de container, clientrol `dev` met `CREATEDB`, pgvector in `template1`; `DEV_PASSWORD` apart; §7 herformuleerd |

Afgewezen: geen.

**Scope-delta ronde 2:** toegevoegd: PG*-variabelen en uitvoermaskering in `db run`, clientrol zonder superuser, reboot-test, slice-limietcontrole, `until`-filters, netwerklabel; gewijzigd: publicatie op `0.0.0.0` i.p.v. het vaste IP (binnen besluit 3), bron- en compose-map gescheiden. Eerste bruikbare resultaat en praktijkproef ongewijzigd; één extra proefstap (reboot) en één JP-besluit (gate-lezing) als open punt. Spec 312 → 320 regels.

## Ronde 3 — 2026-10-14

**Gepind:** `dev-docker/SPEC.md` revisie 3 @ `03f041cefdb149c6e5ca4dc35e1d09a71d75170f`; context-pins ongewijzigd.

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | `98643a7a-e702-4a1d-9946-75e63c6e0933` | `2c03e343-9ad4-45ea-9121-9f18e40e00bf` | job (SUCCEEDED) | `54a3a75e-e7ae-4a44-94d4-6bf332960966` | linked |
| CLAUDE | `590fdd93-39b5-4015-bb67-0dcbeb9787c7` | `ba8fbeb3-4338-4ca9-a0bc-ded21e3900e4` | job (SUCCEEDED) | `af8bb0db-a17d-41eb-a0a8-b1a4da82fc0b` | linked |

**Dispatch:** beide 08:00–08:01 UTC ingediend, state WAITING (waiting_for_capacity).

**Uitslag:** CODEX **NO-GO** (0 BLOCKER, 1 MAJOR, 3 MINOR; 08:03 UTC). CLAUDE **GO** (0 BLOCKER, 0 MAJOR, 7 MINOR; 08:04 UTC). Convergent: de LAN-grens van de `0.0.0.0`-publicatie hangt aan een niet-gemeten ufw-regellijst (codex MAJOR, claude F6 MINOR); quoting van het bootstrap-commando over ssh; dry-run-imageberekening vergelijkt namen met ID's.

**Fixes ronde 2 volgens de reviewers:** codex 10 held, 3 partially (5, 7, 9); claude 11 held, 2 partially (5, 7).

**Triage** (geverifieerd; aanvullende metingen 14-10-2026: `enp4s0` 192.168.0.158/24 statisch (`ipv4.method manual`), `tailscale0` 100.102.8.64/32; `docker ps --format {{.ImageID}}` bestaat niet in 29.9):

| # | Bron | Sev | Bevinding | Oordeel | Remedie in rev. 4 |
|---|---|---|---|---|---|
| 1 | codex M1 / claude F6 | MAJOR | LAN-grens niet gemeten; default-deny-check bewijst geen effectieve INPUT-policy; host heeft eigen INPUT-regels buiten ufw | accept | §4.4/§4.5: bind op het statische LAN-adres als eerste grens (kernel), ufw als tweede; boot-race opgelost met user-unit `dev-postgres.service` die op het adres wacht; §4.1 preflight toetst `iptables -S INPUT` + `ufw status numbered` op accepts voor 55432 buiten het LAN en generieke accepts op tailscale0/bridges; §9/§11: `ss -ltn` alleen LAN-adres, `nc` via Tailscale-adres geweigerd; `0.0.0.0` alleen als gemeten terugval |
| 2 | codex m2 / claude F4 | MINOR | dry-run vergelijkt image-refs met ID's; `until` = bouwdatum; buildcache geen exacte lijst | accept | §4.7 stap 4: eigen kandidaatberekening op ID via `docker inspect --format {{.Image}}`, uitsluiting van `images.txt`, verwijderen met `docker rmi` zodat dry-run en echte run hetzelfde pad delen; buildcache expliciet schatting |
| 3 | codex m3 / claude F1 | MINOR | quotes gaan verloren over ssh; interface kent één waarde terwijl §8 "laagste van de reeksen" zegt; pubkey-transport ongespecificeerd | accept | §4.1: één gequoteerde remote string, `scp` van script én pubkey, herhaalbare `--series <GiB>:<bron>` |
| 4 | codex m4 | MINOR | onderliggend bewijs niet in de bundel | accept | P6-reeks en sampler als `evidence/dev-docker/` in deze repo (README met sha256); ronde 4 pint `caps.md` en `migratieontwerp.md` uit scrum4me-server |
| 5 | claude F2 | MINOR | reboot-test vóór eindbaseline breekt sampler en baseline; statusvelden maken "identiek" ontoetsbaar | accept | §9: baseline en sampler-stop vóór de reboot; reboot als aparte gelogde acceptatieregel; §8 baseline-formats zonder statusvelden |
| 6 | claude F3 | MINOR | init alleen op leeg volume; healthcheck via unix-socket slaagt tijdens init; `.env`-regeneratie | accept | §4.5: `pg_isready -h 127.0.0.1`; init eenmalig, wachtwoordwijziging = `ALTER ROLE` + `.env`; §4.2: `.env` alleen aanmaken als hij ontbreekt |
| 7 | claude F5 | MINOR | `psql` niet op PATH van de Mac | accept | §6.2: `db run` zet `/opt/homebrew/opt/libpq/bin` vooraan in PATH; tekst verduidelijkt |
| 8 | claude F7 | MINOR | `userdel -r` zonder user-manager te stoppen; drop-in te vroeg weg | accept | §10: `terminate-user`/`stop user@<uid>` vóór `userdel`; drop-in als laatste |

Afgewezen: geen.

**Scope-delta ronde 3:** toegevoegd: user-unit `dev-postgres.service` (wachten op adres), INPUT-policy-controle in de preflight, negatieve bereikbaarheidscontrole, P6-bewijs in de repo, `--series`-interface; gewijzigd: terug naar bind op het LAN-adres (besluit 3 letterlijk) met `0.0.0.0` als gemeten terugval. Eerste bruikbare resultaat en praktijkproef ongewijzigd; reboot-test verschuift naar het einde. Spec 320 → 335 regels.

## Ronde 4 — 2026-10-14

**Gepind:** `dev-docker/SPEC.md` revisie 4 @ `bc764bc6e8f79b06bb440160fd6a6e04b2ac05e5`; context-pins: grill (rev `cmv7rt021000fyl174lrf4iyu`), PR-32-rapport @ `43f724b37c5f076e5cbbc1b7cbf1822080d9f3ec`, **nieuw:** `docs/forgejo-runner-pool/evidence/stap-a/caps.md` @ `96e0ac272d1f5ead51fa853bbf922eb605550831` en `docs/forgejo-runner-pool/migratieontwerp.md` @ `984f5949ab131469d1fc999c32569e36333ede23` (beide scrum4me-server, product `cmsx8zbdh0002hk7rcgxxr00k`).

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | `3ef2b3bb-f851-4cb9-a28f-2ccc8e888089` | `4e3bbfe4-c0a9-4016-a028-1f65b5a191d4` | job (SUCCEEDED) | `1ca36f89-e877-4c6c-8cf5-ea9965b32d3b` | linked |
| CLAUDE | `6ca8784c-2c4e-493a-94e2-8c01a0d3c0cb` | `d4e34103-8a8e-45ab-af99-999d80878797` | job (SUCCEEDED) | `231892b2-0a7b-44a0-9eaa-f6e7f1dff5d5` | linked |

**Dispatch:** beide 08:09–08:10 UTC ingediend, state WAITING (waiting_for_capacity); vijf pins geaccepteerd (incl. twee uit scrum4me-server).

**Uitslag:** CODEX **NO-GO** (0 BLOCKER, 1 MAJOR, 3 MINOR; 08:14 UTC). CLAUDE **NO-GO** (0 BLOCKER, 1 MAJOR, 6 MINOR; 08:15 UTC). Twee verschillende MAJORs: codex — de INPUT-check (`iptables -S INPUT`) toont geen regels in gesprongen ketens en de `0.0.0.0`-terugval is niet gedekt; claude — §8 gebruikt de N = 1-lezing uit caps.md terwijl het gepinde ontwerp (R17) §7.8 host-breed maakt en max2 met twee stacks al rood is onder waiver D7 (11-10-2026), zodat de JP-vraag in §12 op een verkeerde premisse stond. Claude las pr32 alleen via grep (`not_run`), zonder bevinding die erop steunt.

**Fixes ronde 3 volgens de reviewers:** codex 5 held, 3 partially (1, 2, 4); claude 5 held, 3 partially (1, 2, 4).

**Triage** (geverifieerd; U4-record `evidence/n-stacks/2026-10-12-uitrol-stack-03.md` gelezen: D7 waiver §7.8 voor N = 2 op beide assen, U2-minimum 21,67 GiB, P6-rode lijn 10,8 GiB in één steekproef):

| # | Bron | Sev | Bevinding | Oordeel | Remedie in rev. 5 |
|---|---|---|---|---|---|
| 1 | codex M1 / claude F2 | MAJOR | `iptables -S INPUT` leest gesprongen ketens niet; terugval `0.0.0.0` ongedekt; "generieke accept op tailscale0" kan vals weigeren | accept | §4.1: `iptables-save -t filter` als root, ketens in evaluatievolgorde incl. jumps, precieze weigerregel (NEW tcp/55432 van buiten het LAN op niet-loopback-ingress; bridges tellen mee, tailscale0 alleen vastleggen), fail closed; §4.4: **`0.0.0.0`-terugval geschrapt** (bind faalt → NO-GO, JP beslist); §9/§11 aangepast |
| 2 | claude M1 / codex m1 | MAJOR | §8 op N = 1-premisse; R17 maakt §7.8 host-breed; max2 N = 2 al rood onder D7; 10,8 GiB niet geverifieerd; 6+8=14 verkeerd rekenvoorbeeld | accept | §8 herschreven: 8.1 stand van zaken met N = 2, caps-som 12 GiB, 55,7 %, waiver D7, U4-rode lijn 10,8 GiB, N = 1-lijn alleen als context; 8.2 eigen afgeleide regel met operationele vloer X (voorstel 12,0) en parametrisch budget; §12 vraag aan JP opnieuw geformuleerd (dev-last op gewaiverde host; X); U4-record wordt in ronde 5 gepind |
| 3 | codex m2 / claude F5 | MINOR | `images.txt`-uitsluiting op naam matcht digest-referentie niet; lege containerlijst | accept | §4.7 stap 4: referenties naar ID via `docker image inspect --format {{.Id}}`; guard op lege `docker ps -aq` |
| 4 | codex m3 / claude F4 | MINOR | unit zonder `WorkingDirectory`/`Type`/`Wants`/timeout; ontbreekt in §4.9 | accept | §4.5: `Type=oneshot`, `RemainAfterExit`, `Wants`, `WorkingDirectory`, `TimeoutStartSec=180`, succes = `active (exited)`; §4.9 |
| 5 | claude F3 | MINOR | voorbeeld geeft 7,5 GiB (momentopname in `--series`); splitsing op dubbele punt onbepaald | accept | §4.1: alleen de P6-reeks; eerste dubbele punt; bron vrije tekst; momentopname expliciet geen reeks |
| 6 | claude F6 | MINOR | sampler-cadans ≈ 60 s, niet 5 s; §7.8 vraagt 5 s | accept (gemeten: `vmstat 1 5` + `sleep 55`) | §8 en evidence-README gecorrigeerd; proefsampler 5 s; resolutie als beperking benoemd |
| 7 | claude F7 | MINOR | geen schijfgrens; dev deelt het productiebestandssysteem | accept | §7 restrisico met 20 %-waarschuwing in `status`/prune; §9 meet vrije ruimte vóór/na |
| 8 | claude (geen sev) | — | `pg_hba` weigert superuser over het netwerk; user-manager-herstart als goedkopere test; pubkey-pad | accept | §4.5 `host all postgres all reject` bovenaan; §9 stap 10 stop/start van `user@<uid>` vóór de reboot; §4.1 sleutel uit `ssh -G max2` |

Afgewezen: geen.

**Scope-delta ronde 4:** verwijderd: de `0.0.0.0`-terugval; toegevoegd: volledige filtertabel-doorloop in de preflight, `pg_hba`-reject voor de superuser, schijfmeting en -waarschuwing, user-manager-herstarttest, U4-pin. §8 is inhoudelijk gecorrigeerd zonder het budget te wijzigen; de JP-vraag staat nu op de juiste premisse. Eerste bruikbare resultaat en praktijkproef ongewijzigd. Herbeoordeling vóór ronde 5 (skill-regel "vóór ronde 4"): de vier rondes voegden verificatie en grenzen toe, geen nieuw subsysteem; de proef is niet verschoven; geen kleiner alternatief dat acceptatie en bescherming behoudt. Spec 335 → 349 regels.

## Ronde 5 — 2026-10-14

**Gepind:** `dev-docker/SPEC.md` revisie 5 @ `5aa595650d96338247a3e75d0440ed7a42c97cfa`; context-pins: grill, PR-32-rapport, `caps.md` @ `96e0ac27…`, `migratieontwerp.md` @ `984f5949…`, **nieuw:** U4-record `docs/forgejo-runner-pool/evidence/n-stacks/2026-10-12-uitrol-stack-03.md` @ `9a5e084a9dc99760644131cdc1e25dd4d78fbbef` (scrum4me-server).

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | `58cc25f3-c928-4710-96ca-1d6538e8f12e` | `f7948a76-8281-413c-867e-010385be4fb9` | job (SUCCEEDED) | `894f5d2e-a2dd-410b-8e26-5c782549c66e` | linked |
| CLAUDE | `2a13718a-dd90-4ea7-bb2f-5014815ebd62` | `c971ddfd-a092-42d5-bdfe-1ace33cb4b90` | job (SUCCEEDED) | `392394c7-eb71-44b0-a732-255e2917b9bb` | linked |

**Dispatch:** beide 08:20–08:21 UTC ingediend, state WAITING (waiting_for_capacity); zes pins geaccepteerd.

**Uitslag:** CLAUDE **GO** (0 BLOCKER, 0 MAJOR, 6 MINOR; 08:25 UTC). CODEX **NO-GO** (0 BLOCKER, 1 MAJOR, 4 MINOR; 08:26 UTC). Convergent (codex MAJOR, claude F2 MINOR): de tailscale0-uitzondering in de weigerregel is onhoudbaar — een bind op het LAN-adres onderscheidt bestemmingen, geen ingress; onder het weak-host-model levert `-i tailscale0 -j ACCEPT` een pakket naar 192.168.0.158:55432 gewoon af. §8-cijfers door beide reviewers als correct bevestigd. Claude las `ontwerp` alleen R17 en `pr32` niet (`not_run`), zonder bevinding die erop steunt.

**Fixes ronde 4 volgens de reviewers:** codex 5 held, 3 partially (1, 6, 8); claude 3 held, 2 grotendeels, 3 deels (1, 5, 6).

**Triage** (geverifieerd; aanvullende metingen 14-10-2026 op max2: systemd 259; pgvector-entrypoint regels 266–285 voegen `host all all all <methode>` toe, initdb-sample zet loopback op `@authmethodhost@`; Tailscale `NetfilterMode: 2`; bestaand hostpatroon `dsh-firewall.sh`/`owui-firewall.sh` met `ensure`-DROP-regels op INPUT-positie 1 plus service + timer):

| # | Bron | Sev | Bevinding | Oordeel | Remedie in rev. 6 |
|---|---|---|---|---|---|
| 1 | codex M1 / claude F2 | MAJOR | tailscale0-uitzondering laat pakketten naar de LAN-gebonden listener door; bind ≠ ingress-grens | accept | §4.4: geen semantische doorloop meer; twee eigen DROP-regels bovenaan INPUT (`! -i enp4s0` en `-i enp4s0 ! -s 192.168.0.0/24`) via `dev-docker-firewall.sh` + service/timer (hostpatroon), `Before=user@<uid>.service`; controle = positie 1–2 en twee negatieve `nc`-tests vanaf max2 (incl. via `lo` naar het LAN-adres, bewijst dat de DROP vuurt); §4.1, §9, §10, §11 aangepast |
| 2 | claude F1 | MINOR | evaluatiesemantiek van de doorloop onderbepaald | accept (vervalt) | de doorloop is vervangen door de expliciete regels; `iptables-save` alleen als momentopname |
| 3 | claude F3 / codex m4 | MINOR | `ssh -G` geeft `~`-pad; `.pub` niet altijd aanwezig | accept | §4.1: tilde-expansie, `test -r`, expliciet pad bij meerdere identiteiten/agent |
| 4 | claude F4 | MINOR | X ontbreekt in de bootstrap-interface | accept | §4.1: verplicht `--floor-gib <X>` zonder default, in het bewijsbestand |
| 5 | claude F5 | MINOR | bronvermelding ROOD-rij vermengt P6-berekening met R17/U2-waarden | accept | §8.1 rij uitgesplitst (P6 10,77/55,7 %; R17 9,79/61 %; U2 10,83) |
| 6 | claude F6a / codex m2 | MINOR | `sleep 4` geeft ≈ 8 s door `vmstat 1 5` | accept | §8.2: aparte lus met `sleep 5` zonder vmstat; werkelijke deltas in het bewijs |
| 7 | claude F6b | MINOR | loopback-`trust` in pg_hba; onbekend welk bronadres de poortdriver presenteert; geen negatieve auth-test | accept (gemeten: entrypoint/initdb-gedrag) | §4.5: loopback-regels naar `scram-sha-256`, reject voor `postgres` bovenaan, `pg_ctl reload`; §9 stap 5: fout/leeg wachtwoord en `postgres` over TCP geweigerd, `client_addr` vastgelegd |
| 8 | codex m3 | MINOR | `docker image prune -f` na de ID-berekening omzeilt de leeftijdsregel | accept | §4.7 stap 4: geschrapt; ongetagde images vallen onder dezelfde berekening |
| 9 | codex m5 | MINOR | runtime-bewijs (entrypoint, systemd) niet in de bundel | accept | gemeten en in §4.5/§12 opgenomen; planpunt: image-digest + entrypoint-fragment pinnen |

Afgewezen: geen.

**Scope-delta ronde 5:** toegevoegd: `dev-docker-firewall.sh` met service en timer (bestaand hostpatroon), `--floor-gib`, pg_hba-verharding, negatieve auth-tests; verwijderd: de semantische filtertabel-doorloop en de trailing `image prune`. Eerste bruikbare resultaat en praktijkproef ongewijzigd. Spec 349 → 363 regels.

## Ronde 6 — 2026-10-14

**Gepind:** `dev-docker/SPEC.md` revisie 6 @ `dd54fc35555bebe423008deec51f1d6fbdacb7f4`; context-pins ongewijzigd (grill, pr32, caps, ontwerp, u4).

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | `f088dce1-a4b0-4df4-86bb-d7dbe5d80258` | `f81334fd-06f7-41f1-b0dd-f32a9d105419` | job (SUCCEEDED) | `b99b6fea-1ab8-4461-af9c-30fc6c5bffeb` | linked |
| CLAUDE | `4a79ae0a-d12d-4eac-af60-9c8ee6199a55` | `ee717da5-631e-49b6-958e-77ef3cc309bc` | job (SUCCEEDED) | `8749b6df-8b1b-4bb1-8b4f-71a93c90c184` | linked |

**Dispatch:** beide 08:31–08:32 UTC ingediend, state WAITING (waiting_for_capacity).

**Uitslag:** CLAUDE **NO-GO** (0 BLOCKER, 1 MAJOR, 5 MINOR; 08:35 UTC). CODEX **NO-GO** (0 BLOCKER, 1 MAJOR, 3 MINOR; 08:37 UTC). **Convergent MAJOR:** `ensure` met `iptables -C` is positieblind; ufw-reload, tailscaled en `dsh`/`owui-firewall` (die zelf op positie 1 invoegen, `After=docker.service`) duwen de DROP-regels naar beneden en de timer herstelt dat niet; de acceptatie "positie 1 en 2" houdt alleen op het installatiemoment. Beide reviewers: alle overige ronde-5-fixes hielden; §8-cijfers opnieuw bevestigd; geen schrapkandidaat.

**Triage:**

| # | Bron | Sev | Bevinding | Oordeel | Remedie in rev. 7 |
|---|---|---|---|---|---|
| 1 | claude M1 / codex M1 | MAJOR | positie van de DROP-regels niet onderhouden | accept | §4.4: eigen keten `dev-docker-in` met de twee DROP-regels; één sprong die het script positiebewust op INPUT-positie 1 houdt (eerste `-A`-regel controleren, alleen de eigen sprong verwijderen en opnieuw invoegen); service `After=` de andere schrijvers (ufw, tailscaled, docker, dsh/owui-firewall) en `Before=user@<uid>`; timer `OnBootSec=30s` + `OnUnitActiveSec=5min`; begrensd gat van ≤ 5 min expliciet geaccepteerd; herstelproef (dsh-firewall opnieuw starten → sprong terug op 1) en controle na herstart/reboot in §9/§11 |
| 2 | claude m2 / codex F2 | MINOR | `head -2` toont de policy-regel; invoegvolgorde omgekeerd; "regel 1"-formulering | accept | `awk '$1 == "-A" {print; exit}'`; keteninhoud via `iptables -S dev-docker-in`; regels bij naam |
| 3 | claude m3 | MINOR | geen `--ctstate NEW`: antwoordverkeer met bronpoort 55432 gedropt | accept | beide regels met `-m conntrack --ctstate NEW` |
| 4 | claude m4 | MINOR | units en slice-sjabloon niet gekopieerd; timer zonder `OnBootSec`; geen `enable --now`; installatiepad | accept | §4.1: `scp -r … systemd`; stap 4 installeert script en units, `enable --now`; `OnBootSec=30s` |
| 5 | claude m5 | MINOR | `pg_ctl reload` overbodig | accept | §4.5 geschrapt met reden |
| 6 | claude m6 / codex F3 | MINOR | "914 GB" zonder bron; `--floor-gib 12.0` hardgecodeerd; validatie en ondergrens 10,8 ontbreken | accept (914 GB is op 14-10 met `df -h` gemeten; bron nu genoemd) | §4.1: `--floor-gib <X>`, numerieke validatie, exit 2; §8.2: `X_eff = max(X, 10,8)` consistent in budget, stopregel en acceptatie |
| 7 | codex F4 | MINOR | rollback laat unitbestanden en script achter | accept | §10: sprong en keten verwijderen, unitbestanden en script verwijderen, één afsluitende `daemon-reload` |

Afgewezen: geen.

**Scope-delta ronde 6:** gewijzigd: twee losse DROP-regels → eigen keten met positiebewuste sprong, `--ctstate NEW`, `X_eff`; toegevoegd: herstelproef en controle na herstart. Geen nieuw subsysteem; eerste bruikbare resultaat en praktijkproef ongewijzigd. Spec 363 → 367 regels. Trend: ronde 5 en 6 gingen alleen nog over het firewallmechanisme; beide reviewers noemen de rest stabiel.

## Ronde 7 — 2026-10-14

**Gepind:** `dev-docker/SPEC.md` revisie 7 @ `<r7_sha>`; context-pins ongewijzigd (grill, pr32, caps, ontwerp, u4).

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | (volgt) | | | | |
| CLAUDE | (volgt) | | | | |

**Uitslag:** (volgt)
