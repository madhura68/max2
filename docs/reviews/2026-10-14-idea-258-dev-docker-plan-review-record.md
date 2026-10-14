# Reviewrecord — IDEA-258 implementatieplan `dev-docker/PLAN.md` (plan-fase)

**Document:** `dev-docker/PLAN.md` in de max2-repo, branch `docs/idea-258-dev-docker-spec` (PR 33). **Fase:** plan (review-loop, max. 10 rondes, twee onafhankelijke reviewers per ronde als dispatch-jobs: `runtime: CODEX` en `runtime: CLAUDE`). **Idee:** `cmv762uop001om97rsic6a6o9` (IDEA-258), `idea_phase: PLAN`. **Opdracht JP (14-10-2026):** "ga door met de planfase. doe ook een review-loop". **Spec:** `dev-docker/SPEC.md` dubbel GO op rev. 9 (`44abc5bc`), zie het spec-reviewrecord; rev. 11 corrigeert het hostadres in §6.2 (gemeten: `max2` lost op de Mac op naar Tailscale) en wordt in deze loop als context-pin meegegeven met de vraag die correctie te toetsen.

**Vaste pins per ronde:** `doc` = `dev-docker/PLAN.md` (git, commit + sha256 per ronde); `spec` = `dev-docker/SPEC.md` rev. 11 (git); `grill` = ProductDoc `GRILLS/idea-258-grill` doc `cmv7rt01o000eyl178y3js2kd` rev `cmv7rt021000fyl174lrf4iyu` sha256 `4c8c691a36c71f4d5cf89e40f104ec681e740ee3c4b6b3885369c047d0de3312`. Repository-checkout: `base_sha` = dezelfde commit.

## Ronde 1 — 2026-10-14

**Gepind:** `dev-docker/PLAN.md` revisie 1 @ `bd7129caa496b1c6b46389396ac465b853f357c2`; `dev-docker/SPEC.md` rev. 11 @ dezelfde commit.

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | `cc293c8d-cd6d-497d-aa60-d5e6893a7825` | `f2b9e588-098d-4577-931b-e69f01728b28` | job (SUCCEEDED) | `4646daa2-4dd7-4283-aceb-ced7c8e8c1db` | linked |
| CLAUDE | `0d16fd19-ff89-40fe-acca-19a8078724f7` | `6149efa8-248c-49f3-bac3-ea7699e17f76` | job (SUCCEEDED) | `3abccade-b456-4570-93f4-7e16fc7ab69f` | linked |

**Uitslag:** CODEX **NO-GO** (1 BLOCKER, 2 MAJOR, 4 MINOR; 12:45 UTC). CLAUDE **GO** (0 BLOCKER, 0 MAJOR, 12 MINOR; 12:47 UTC). Beide: geen taak schrapbaar; alle drie de afwijkingen sound (claude: afwijking 1 met aanvulling "gedrag buiten het LAN"); spec rev. 11 §6.2 sound, geen resterend `max2` als DB-host in de spec (de grill noemt nog `@max2`, is een besluitdocument). Convergent: maskeerrecept (codex BLOCKER / claude m3), time-out zonder mechanisme (codex MAJOR / claude m1), `client_addr`-verwachting ongemeten (codex MAJOR / claude m4), overrides schrappen (codex m / claude m10), stopregel niet live (codex m / claude m8), bootstrap-dbnamen vallen mogelijk binnen de regex (codex m / claude m11d).

**Triage** (alle bevindingen geverifieerd; extra metingen 14-10-2026: Mac heeft Homebrew-bash 5.3 vóór `/bin/bash` op het PATH, `perl`, `jq`, `nc`, geen `timeout`; max2 heeft bash 5.3, `jq`, `perl`; s4m-queue-migraties 001–005 en ppe-fixtures bevatten geen `CREATE EXTENSION/ROLE`; 37 van 67 testbestanden zijn DB-afhankelijk; alias `max2` heeft nu geen `ConnectTimeout`):

| # | Bron | Sev | Bevinding | Oordeel | Remedie in rev. 2 |
|---|---|---|---|---|---|
| 1 | codex F1 / claude m3 | BLOCKER / MINOR | `sed "s|$pw|***|"` zet het wachtwoord in argv, maskeert de percent-encoded vorm niet, `escape` ongedefinieerd, `2>&1` vernietigt het stderr-onderscheid, test (g) is leeg | accept | taak 3: maskering via `perl -pe` dat beide vormen uit de **omgeving** leest (`\Q…\E`), FIFO's per stream, exitcode behouden (recept in het plan); tests (c)/(f)/(g) herschreven: tempbestand met ongemaskeerde kind-uitvoer, stderr apart, `ps -Ao args` tweemaal gescand op URL, ruwe en encoded waarde |
| 2 | codex F2 / claude m1 | MAJOR / MINOR | geen transport-deadline, classificatie van exit 3 ongedefinieerd, stub met `exit 1` bewijst geen time-out; nieuw faalpad "SSH werkt, LAN-pad dicht" door afwijking 1 | accept | taak 3: `with_deadline` (achtergrond + killer, macOS zonder `timeout`) op elke docker/ssh-aanroep (15 s), niet op het kind; classificatie op stderr-patronen; `tcp_open` met deadline vóór het kind → exit 3 met LAN-melding; `PGCONNECT_TIMEOUT=5`; alias met `ConnectTimeout 5`/`ServerAliveInterval 15` (taak 2); tests: modus `hang` (≤ 17 s, geen achterblijvende stub), `unreachable`, `tcp_open 127.0.0.1 1` via `--lib`; SKILL.md-zin over buiten-LAN; afwijking 1 aangevuld |
| 3 | codex F3 / claude m4 | MAJOR / MINOR | `client_addr = 192.168.0.50` ongemeten en bewijst het `enp4s0`-pad niet (poortdriver kan vertalen, spec §4.5) | accept | taak 4 stap 2: waarde vastleggen zoals gemeten naast `ipconfig getifaddr en0`; claim geschrapt; LAN-pad volgt uit taak 2 stap 6 + geslaagde verbinding |
| 4 | codex m1 / claude m8 | MINOR | stopregel alleen achteraf | accept | sampler schrijft ALARM-regel bij < 12 582 912 kB; live `tail -f | grep ALARM` tijdens uitrol en testrun; minimum gelezen na elke stap; stop/verlaag/herhaal-recept |
| 5 | codex m2 / claude m10 | MINOR | `MAX2_DOCKER_CONTEXT`/`MAX2_DOCKER_PGHOST` overbodig en onveilig | accept (SCHRAP) | overrides weg; context en host hard; `--lib` voor functietests; acceptatie-grep uitgebreid |
| 6 | codex m3 / claude m11d | MINOR | `s4m_queue_bootstrap_<hex>` kan binnen de regex vallen | accept | taak 4 stap 5: per naam toetsen, `db drop` als geldig, directe SQL alleen bij weigering, gelogd |
| 7 | codex m4 | MINOR | externe bronnen (PR 32, scrum4me-server-docs) niet in de bundel | accept (herkomst-regel) | planheader: herkomst en gezaghebbende invoer benoemd |
| 8 | claude m2 | MINOR | `max2-docker` niet op het PATH; "schone main" botst met niet-gemergde branch | accept | taak 3: symlink `~/bin/max2-docker` + absolute pad in SKILL.md; taak 4 draait vanaf `feat/max2-docker-skill` of na merge |
| 9 | claude m5 | MINOR | `git grep 'ensure()' dev-docker/` matcht PLAN.md zelf | accept | `-- dev-docker/host` |
| 10 | claude m6 | MINOR | dekking: `systemd-cgtop` ontbrak, registerstand vóór/ná dry-run ontbrak, schijfwaarschuwing < 20 % zonder eigenaar, §4.4-controles na herstart/reboot onvolledig | accept | taak 4 stap 3 (`systemd-cgtop`/`memory.peak`), stap 5 (`db list` vóór/ná); taak 1 (`disk` in `last-run.json` met `warn_below_pct`, selftest-fixture 15 %); taak 5: `proof-checks.sh` na herstart én reboot |
| 11 | claude m7 | MINOR | exit 2 vs 3 bij gate-weigering | accept | gate = exit 3; `--check-args`-test aangepast; `X_eff`-ondergrens-test toegevoegd |
| 12 | claude m9 | MINOR | sudo-leesopdrachten buiten de uitzondering | accept | nieuw `proof-checks.sh` (root, read-only, één sessie, uitvoer naar bestand, `scp` daarna); baseline-sudo-deel in één sessie |
| 13 | claude m11a–g | MINOR | stubprotocol onderbepaald; gezondheid niet via `inspect`; negatieve `psql` zonder libpq-PATH/`PGPASSFILE`; bash 3.2; secretscan-commando lekt; `jq`-afhankelijkheid; "DB-afhankelijk" ongedefinieerd, migraties niet gecontroleerd | accept | taak 3: stub-protocol (modi, `MAX2_DOCKER_STUB_PASSWORD`, argv+stdin-log, ssh-stub), `ps --filter … --format '{{.Status}}'`; taak 4: `PATH` libpq + `PGPASSFILE=/dev/null`; bash 5.3 gemeten op beide hosts; secretscan met `grep -qF` + leegte-controle als benoemde uitzondering; `jq` gemeten aanwezig; "DB-afhankelijk" = 37 bestanden; migraties gecontroleerd (geen superuser-eisen) |
| 14 | claude m12 | MINOR | PR te vroeg "ter review"; taak 3 (context) te klein voor een eigen taak | accept | PR pas na laatste taak; context-taak samengevoegd in taak 2 stap 7 → zes taken (hernummerd) |

Afgewezen: geen.

**Scope-delta ronde 1:** zeven → zes taken (context in taak 2); toegevoegd binnen bestaande taken: `proof-checks.sh`, deadline-functie, FIFO-maskering, ALARM-bewaking, schijfwaarschuwing; geschrapt: twee overrides, `client_addr`-claim. Eerste bruikbare resultaat en praktijkproef ongewijzigd. Plan 189 → 204 regels.

## Ronde 2 — 2026-10-14

**Gepind:** `dev-docker/PLAN.md` revisie 2 @ `<r2_sha>`; `dev-docker/SPEC.md` rev. 11 @ dezelfde commit (ongewijzigd sinds ronde 1).

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | (volgt) | | | | |
| CLAUDE | (volgt) | | | | |

**Uitslag:** (volgt)
