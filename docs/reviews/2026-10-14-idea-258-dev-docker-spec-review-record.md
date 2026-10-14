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

**Gepind:** `dev-docker/SPEC.md` revisie 2 @ `<r2_sha>`; context-pins ongewijzigd (grill rev `cmv7rt021000fyl174lrf4iyu`, PR-32-rapport @ `43f724b37c5f076e5cbbc1b7cbf1822080d9f3ec`).

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | (volgt) | | | | |
| CLAUDE | (volgt) | | | | |

**Uitslag:** (volgt)
