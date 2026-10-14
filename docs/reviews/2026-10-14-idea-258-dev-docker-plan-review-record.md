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

**Scope-delta ronde 1:** zeven → zes taken (context in taak 2); toegevoegd binnen bestaande taken: `proof-checks.sh`, deadline-functie, FIFO-maskering, ALARM-bewaking, schijfwaarschuwing; geschrapt: twee overrides, `client_addr`-claim. Eerste bruikbare resultaat en praktijkproef ongewijzigd. Plan 189 → 211 regels.

## Ronde 2 — 2026-10-14

**Gepind:** `dev-docker/PLAN.md` revisie 2 @ `d800544c46ca5e2ba4648144bb34c4911e352e12`; `dev-docker/SPEC.md` rev. 11 @ dezelfde commit (ongewijzigd sinds ronde 1).

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | `97d50cca-9e36-4f94-a99b-f2122bec6ed1` | `a0825641-276c-46dc-b458-1a1210dadf9f` | job (SUCCEEDED) | `050b43af-a004-481d-9a4e-1bb7b1420a89` | linked |
| CLAUDE | `cf1cf15f-88ce-4607-9884-ee1fd0c59edf` | `c65295ab-b827-4a51-9a4d-f0949d78f588` | job (SUCCEEDED) | `bd56670a-60fe-4f07-a2f0-6a360a01304a` | linked |

**Uitslag:** CODEX **NO-GO** (1 BLOCKER, 3 MAJOR, 2 MINOR; 12:57 UTC). CLAUDE **NO-GO** (0 BLOCKER, 1 MAJOR, 9 MINOR; 13:01 UTC). Beide: zes taken minimaal, geen schrapkandidaat; afwijkingen sound. Convergent: secretscan met het wachtwoord in grep-argv en fail-open (codex BLOCKER / claude F8); `nc`/`tcp_open`-pre-check zonder test-seam zodat de positieve `db run`-tests het echte LAN raken (codex MAJOR / claude MAJOR); `proof-checks.sh` onder `set -e` stopt op verwachte niet-nul-resultaten (codex MAJOR / claude F6c); deadline-recept zonder procesboom-cleanup en met stdin `/dev/null` bij `&` (codex MAJOR / claude F3); test (g) zwak (codex m / claude F2).

**Triage:**

| # | Bron | Sev | Bevinding | Oordeel | Remedie in rev. 3 |
|---|---|---|---|---|---|
| 1 | codex F1 / claude F8 | BLOCKER / MINOR | secretscan: wachtwoord in grep-argv; `schoon` bij lege ophaal of grep-fout; `raw/` niet gescand | accept | taak 4 stap 7: `perl` leest de waarde uit de omgeving, scant `git ls-files evidence/dev-docker` (incl. `raw/`), onderscheidt LEK/schoon/FOUT-ophaal/FOUT-leeg/FOUT-lees; commit alleen bij `schoon` |
| 2 | codex F4 / claude F1 | MAJOR / MAJOR | pre-check via bash-builtin `/dev/tcp` op een hard doel is niet te stubben → tests (c)/(f)/(g)/exit-7 vereisen een live LAN; taak 3 niet parallel | accept | pre-check = `nc -z -w3 192.168.0.158 55432` (programma op PATH, stub-`nc` met `MAX2_DOCKER_STUB_LAN=open|closed`); geen doelen instelbaar; test "LAN dicht → exit 3, kind niet gestart"; echte `nc` tegen `127.0.0.1:1` als unit-test; acceptatie-grep verbiedt nu ook `/dev/tcp` |
| 3 | codex F2 / claude F6c | MAJOR / MINOR | `proof-checks.sh` onder `set -euo pipefail` sterft op `grep -c` = 0 en op de verwachte `nc`-weigering | accept | interface herschreven: bewust zonder `set -e`, `|| true` per blok, `nc`-status eerst gevangen, `SUMMARY`-regel met exit 0/1 op afwijking; `&&`-keten in taak 2 stap 6 stopt alleen op een echte afwijking |
| 4 | codex F3 / claude F3 | MAJOR / MINOR | `with_deadline`: `kill <pid>` raakt geen kleinkinderen; achtergrondcommando krijgt stdin `/dev/null` (SQL verloren); 143 vs 124; killer-`sleep` houdt `$(…)` open | accept | perl-wrapper: eigen procesgroep (`setpgrp`), `fork`+`exec` met geërfde stdin/stdout/stderr, `alarm` → TERM/KILL op de hele groep, exit 124; `hang`-stub met kleinkind, test eist dat beide pids weg zijn; eigen deadline 120 s voor `cleanup --dry-run` (duur gemeten in taak 2) |
| 5 | codex m1 / claude F2 | MINOR | (g) twee snapshots missen kortlevende processen; machinebreed → vals rood | accept | invariant: stub-log (argv+stdin) bevat nergens ruwe/encoded waarde of `postgresql://`; (g) wacht op het kind, scant alleen nakomelingen van de helper, grens benoemd |
| 6 | claude F4 | MINOR | maskering: `set -e`-afbreking, perl-buffering, geen trap, lege waarde hergebruikt vorig patroon | accept | `rc=0; … || rc=$?`, `BEGIN{$|=1}`, `trap rm EXIT`, exit 4 bij leeg wachtwoord, interleaving benoemd |
| 7 | claude F5 | MINOR | exit-3-patronen onvolledig; daemon-uit hoort bij 4 | accept | patroonlijst uitgebreid; `Cannot connect to the Docker daemon` → exit 4; één stub-test per patroon |
| 8 | claude F6a/b/d | MINOR | `/tmp` leeg na reboot; proof direct na user-manager-herstart vóór de listener; journal-wachten vergt herhaalde sudo | accept | `scp` als eerste stap in taak 5; `--wait-listener`/`--wait-tick` in `proof-checks.sh` |
| 9 | claude F7 | MINOR | §11 rij 10 niet in de echte proef | accept | taak 4 stap 2: `db run … pg_sleep(3)` met gelijktijdige `ps`-scan in het bewijs |
| 10 | claude F9 | MINOR | `pgrep -x Docker` mogelijk vacuüm; `memory.peak` vertroebeld | accept | vóór/ná: `pgrep -fl 'Docker|com.docker'` en `docker --context desktop-linux info`; `memory.events` (`max`, `oom_kill`) + `anon` uit `memory.stat` als criterium |
| 11 | claude F10 | MINOR | 23→28 tekens; `dry_run` in `last-run.json` strijdig met spec; `status` toont verouderde schijfstand; `nohup while` ongeldig; `psql` zonder `-w`; absolute stub-PATH; bash-versiecheck | accept | alle zeven verwerkt (sampler als `host/sampler.sh`; dry-run schrijft niets; `status` doet live `df`; `-w`; versiecheck exit 2) |
| 12 | codex m2 | MINOR | externe bronnen blijven onverifieerbaar in de bundel | accept (benoemd) | header: historische bronnen zijn context, niet opnieuw geverifieerd in de plan-loop |

Afgewezen: geen.

**Scope-delta ronde 2:** geen nieuwe taak; toegevoegd binnen taak 1 en 3: `sampler.sh`, `nc`-stub, perl-deadline-wrapper, `SUMMARY`/wachtopties in `proof-checks.sh`; geschrapt: `/dev/tcp`, `dry_run`-veld. Eerste bruikbare resultaat en praktijkproef ongewijzigd. Plan 211 → 221 regels.

## Ronde 3 — 2026-10-14

**Gepind:** `dev-docker/PLAN.md` revisie 3 @ `e6f9c53cbfaf85814d6e11d4e82b41d3e61a2a0b`; `dev-docker/SPEC.md` rev. 11 @ dezelfde commit (ongewijzigd).

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | `58b0e065-c985-4759-96a1-a4cf0e5bc4b0` | `9bd3cf51-7f2e-47f0-b5aa-fb6a86bc7d1a` | job (SUCCEEDED) | `6d8080f5-ded5-411e-a200-1a193863a8c6` | linked |
| CLAUDE | `9c2241a2-479c-4909-a6ed-765874937a09` | `5ab4e101-83b7-4c98-ac59-e21f44ca9a24` | job (SUCCEEDED) | `c7ceb52f-25ea-4132-9760-10433d135dd7` | linked |

**Uitslag:** CODEX **NO-GO** (1 BLOCKER, 1 MAJOR, 4 MINOR; 13:11 UTC). CLAUDE **NO-GO** (0 BLOCKER, 2 MAJOR, 8 MINOR; 13:10 UTC). Volledig convergent op de twee hoofdpunten: (1) de perl-wrapper deed `setpgrp` op zichzelf en doodde met `kill … -$$` zijn eigen groep vóór `exit 124`, en `$?>>8` maakt van een gesignaleerd kind exit 0 (codex MAJOR / claude MAJOR); (2) de secretscan draaide in de verkeerde repo (taak 4 zit in s4m-queue) op alleen getrackte bestanden, dus `schoon` bij een lege lijst en nieuwe `raw/`-bestanden ongescand (codex BLOCKER / claude MAJOR). Beide: zes taken minimaal; fixgroep 2 (nc-seam) en 5 (test g) gehouden.

**Triage** (extra meting 14-10-2026 op de Mac: `nc -z -w3` naar een onbeantwoord adres duurt 75 s, `nc -z -G 3` 3 s, een gesloten lokale poort weigert direct — codex' MINOR over de nc-time-out was dus terecht en materieel):

| # | Bron | Sev | Bevinding | Oordeel | Remedie in rev. 4 |
|---|---|---|---|---|---|
| 1 | codex F1 / claude F2 | BLOCKER / MAJOR | secretscan: verkeerde repo, alleen getrackte bestanden, lege lijst → `schoon` | accept | taak 4 stap 7: expliciet `cd` naar de max2-checkout met branchcontrole; `git add -A evidence/dev-docker`; scan over `git diff --cached --name-only -z` via `xargs -0`; `die` bij lege lijst; commit alleen van de gescande staged set; nieuw bewijs → opnieuw stagen en scannen; globale `git grep --untracked` |
| 2 | codex F2 / claude F1 | MAJOR / MAJOR | wrapper doodt zichzelf; `$?>>8` verliest signaaldood; ssh-connhelper mogelijk eigen pgid; tty-prompts | accept | kind doet `setpgrp(0,0)`, ouder blijft buiten de groep, `kill -$kid` TERM/KILL, `waitpid`, exit 124; status `($?&127) ? 128+($?&127) : $?>>8`; `BatchMode yes` + `ServerAliveCountMax 2` in de alias; residu (connhelper-pgid) benoemd; tests: `kill -9`-kind → 137, stub die zichzelf doodt → exit 4 |
| 3 | claude F3 | MINOR | `dev:[^*]` matcht legitieme SSH-doelen | accept | patroon `//dev:[^*]` |
| 4 | claude F4 | MINOR | daemon-uit-regel bevat ook `error during connect` | accept | `Cannot connect to the Docker daemon` eerst → 4; stub met de volledige regel |
| 5 | claude F5 / codex m1 | MINOR | `--wait-tick` niet in `SUMMARY`, time-out en afwezige dsh/owui-runs ongedefinieerd, "run" ongedefinieerd | accept | `tick=<ok|n/a-dsh|timeout|skipped>` en `listener=timeout`; run = `Finished`-regel van deze boot; time-out → exit 1; n/a → venster "n.v.t." |
| 6 | claude F6 | MINOR | root schrijft op voorspelbare naam in `/tmp` | accept | `mktemp` in root-eigen `/var/tmp/dd-proof/` (0755) |
| 7 | claude F7 | MINOR | 120 s hangt van een taak-2-meting af terwijl taak 3 parallel loopt | accept | 120 s vast; taak 2 meldt alleen |
| 8 | claude F8 | MINOR | `status`: JSON en `df` door één `jq` | accept | twee ssh-aanroepen |
| 9 | claude F9 | MINOR | bash-versiecheck exit 2; `wait` onder `set -e` | accept | exit 64; `wait … || true` |
| 10 | claude F10 | MINOR | `ps`-scan in de proef is één momentopname | accept | lus 0,2 s gedurende 4 s; grens benoemd |
| 11 | codex m2 | MINOR | macOS `nc -w` begrenst een onbeantwoorde connect niet | accept (gemeten) | `nc -z -G 3 -w 3` onder `with_deadline 5`; test tegen `10.255.255.1` (onbeantwoord) én `127.0.0.1:1` (weigering) |
| 12 | codex m3 | MINOR | sampler-`awk` leest een Mac-pad | accept | via `ssh max2 "awk …"` |
| 13 | codex m4 | MINOR | historische bronnen niet in de bundel | accept (benoemd) | herkomst-zin aangescherpt: niet in de bundel, geen nieuwe bevinding |
| 14 | codex (fixgroep 3) | MINOR | taak 1 "alle scripts `set -euo pipefail`" zonder uitzondering voor `proof-checks.sh` | accept | uitzondering expliciet |

Afgewezen: geen.

**Scope-herbeoordeling vóór ronde 4 (cap 10):** het plan is sinds ronde 1 niet gegroeid in taken (7 → 6) of in subsystemen; de rondes 2 en 3 gingen uitsluitend over de correctheid van drie shell-recepten in taak 3/4 (deadline, maskering, secretscan) en de interface van `proof-checks.sh`. Die recepten staan in het plan omdat beide reviewers in ronde 1 zero-context-uitvoerbaarheid eisten; weglaten zou de uitvoerder dezelfde fouten laten maken. Kleiner alternatief overwogen: de recepten vervangen door alleen contracten + tests — verworpen, omdat de tests de contracten al pinnen en de recepten het verschil maken tussen één en drie implementatierondes. Eerste bruikbare resultaat en praktijkproef ongewijzigd. Plan 221 → 227 regels.

## Ronde 4 — 2026-10-14

**Gepind:** `dev-docker/PLAN.md` revisie 4 @ `830077cb15b7086bbfd6f18c87bd1213a227e286`; `dev-docker/SPEC.md` rev. 11 @ dezelfde commit (ongewijzigd).

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | `4cdf2d22-9bc8-4c82-b4f3-928d1cab908c` | `942058e3-c58b-4109-9fd2-084e4aef51c9` | job (SUCCEEDED) | `0f5c3461-91a6-40f0-9fe4-382aba59aa50` | linked |
| CLAUDE | `207b35c6-d35e-4f6a-88b4-46b8531fac2f` | `93d3cab5-1cd1-4b3c-bf73-78f31c4906b4` | job (SUCCEEDED) | `3397f665-3cf9-4c57-b2e4-9b15abde9357` | linked |

**Uitslag:** CODEX **NO-GO** (1 BLOCKER, 2 MAJOR, 4 MINOR; 13:22 UTC). CLAUDE **GO** (0 BLOCKER, 0 MAJOR, 9 MINOR; 13:21 UTC). Beide: zes taken, geen schrapkandidaat; fixgroep 2 (deadline-wrapper) hield; fixgroep 1 (secretscan) hield gedeeltelijk; `nc -G 3` consistent met de metingen. Convergent (beide): `mktemp`-bestand is 0600 van root, dus de `scp` zonder sudo faalt; de alarm/`setpgrp`-race; exit 124 niet onderscheidbaar van een kind dat zelf 124 geeft.

**Triage (alle bevindingen geaccepteerd; recepten vóór revisie 5 lokaal gemeten, zie onder):**

| # | Bron | Sev | Bevinding | Oordeel | Remedie in rev. 5 |
|---|---|---|---|---|---|
| 1 | codex B1 | BLOCKER | `git grep -nE` en de `ps \| grep`-lus printen de gedetecteerde credential zelf in het transcript (spec §7) | accept | overal `-q`/`-l`, nooit `-n` zonder `-l`; `ps`-lus `grep -qE` met per snapshot `leeg`/`TREFFER`; `git grep` exit 1 = geen treffer, 0 of ≥ 2 stopt (gemeten: buiten een repo rc 128) |
| 2 | codex M1 / claude F1 | MAJOR / MINOR | `mktemp` maakt 0600 van root; `scp` als janpeter faalt | accept | interface `proof-checks.sh`: `chmod 0644 "$out"`, regel `OUT=<pad>` vóór `SUMMARY`; map via `install -d -m 0755 -o root -g root` + eigenaar/symlink-check (`FOUT-proofdir`, claude F6) |
| 3 | codex M2 / claude F2 | MAJOR / MINOR | perl leest werkboom i.p.v. gestagede blob; `unset pw` overschrijft de status; macOS-`xargs` start niets bij lege invoer (die-guard dood) en vertaalt exit 1 → 123; batches kunnen `schoon` na `LEK` printen | accept | nieuwe sectie **Secretscan**: één `perl`-aanroep leest paden van stdin (`-z`, `--diff-filter=d`) en de inhoud via `git show :<pad>` (list-form pipe, geen shell); `set -o pipefail`; `rc=$?` vóór `unset pw`; commit van precies de staged set, geen `add`/edit/`-a` ertussen. Gemeten in een scratch-repo: lege set → `FOUT-geen-bestanden` rc 255; staged secret → `LEK` rc 1; schoon → rc 0; werkboom gecorrigeerd maar index vuil → `LEK`; alleen verwijdering → FOUT; macOS `xargs -0` op lege invoer → niets gestart, rc 0 |
| 4 | codex m1 / claude F4a | MINOR | alarm kan vuren vóór het kind `setpgrp` deed → `kill -$kid` ESRCH | accept | ouder doet na `fork` ook `setpgrp($kid,$kid)` (fout genegeerd); handler kilt `-$kid, $kid` |
| 5 | codex m2 / claude F4b | MINOR | exit 124 niet onderscheidbaar van kind-exit 124 | accept | 124 gereserveerd; contract van de omhulde programma's benoemd; test `sh -c 'exit 124'` → 124 als aanvaarde dubbelzinnigheid |
| 6 | codex m3 | MINOR | stub-`ssh`-contract noemt nog de oude gecombineerde `status`-aanroep | accept | twee aanroepen afzonderlijk + `MAX2_DOCKER_STUB_LASTRUN=missing` |
| 7 | codex m4 | MINOR | historische bronnen (PR 32, caps/R17/U4) niet in de bundel | accept, geen wijziging | caveat staat al in de herkomstzin; geen nieuwe pins nodig |
| 8 | claude F3 | MINOR | het `ps`-zoekpatroon `//dev:` in het bewijs trapt de eigen `//dev:[^*]`-scan af | accept | patroon `postgresql:[/]/\|[/]/dev:` (matcht zichzelf niet) |
| 9 | claude F4c/d/e | MINOR | `exec`-fout niet gespecificeerd; Ctrl-C bereikt het kind niet; `kill -0` kan op een zombie slagen | accept | kind `exit 127` na mislukte `exec`; INT/TERM doorgestuurd naar `-$kid`; poll tot 1 s; tests 127/7 toegevoegd |
| 10 | claude F5 | MINOR | secretscan in taak 2/5/6 niet of inconsistent benoemd; "één keer" | accept | sectie Secretscan "per bewijscommit"; expliciet in taak 1 (alleen grep), 2, 4, 5, 6; zelfcontrole §7 bijgewerkt |
| 11 | claude F6 | MINOR | root-scripts uit wereld-schrijfbaar `/tmp`; `dd-proof` niet geverifieerd | accept | afwijking 4: `/home/janpeter/dd-run/` (0700) i.p.v. `/tmp` in taak 2 en 5; map-check in `proof-checks.sh` |
| 12 | claude F7 | MINOR | `SUMMARY`-verwachting mist `tick=skipped`; "laatste `Finished`" is een bewegend doel; seconde-resolutie | accept | `tick=skipped` toegevoegd; referentie = **eerste** dsh/owui-`Finished` van deze boot, strikt later op `-o short-iso-precise` |
| 13 | claude F8 | MINOR | `status` vóór de eerste echte prune-run: `cat` faalt → exit 4 | accept | `nog geen echte prune-run` + live `df`, exit 0; stub-modus en test; taak 5 stap 2 verwacht dit |
| 14 | claude F9 | MINOR | controle-run "vóór stap 3 van alleen dat bestand" is niet uitvoerbaar (falende set pas bekend na de run) | accept | controle-run = één `npm test` zonder helper vóór het afsluiten van Desktop; falende set = baseline; alleen baseline-bestanden tellen niet mee, anders stop + JP |

Afgewezen: geen.

**Lokale metingen vóór revisie 5 (14-10-2026, Mac):** perl-wrapper met ouder-`setpgrp($kid,$kid)`, `kill -$kid,$kid`, `exit 127` na mislukte `exec`: `sh -c 'sleep 30 & sleep 30'` onder 2 s → rc 124 na 3 s, geen achtergebleven `sleep`; `sh -c 'exit 124'` → 124; `/nonexistent/prog` → 127; `kill -9 $$` → 137; `exit 7` → 7; stdin bereikt `cat`. Secretscan-recept zoals in de tabel bij #3.

**Scope-delta ronde 4:** geen taak of subsysteem erbij; één nieuwe afwijking van de spec (4: pad van root-scripts, uitvoeringsdetail); het secretscan-recept verhuist uit taak 4 naar een eigen sectie die vijf taken delen. Eerste bruikbare resultaat en praktijkproef ongewijzigd. Plan 227 → 244 regels (sectie Secretscan + afwijking 4).

**Herbeoordeling vóór ronde 5:** vier rondes op rij betroffen de drie recepten en de `proof-checks.sh`-interface; ronde 4 bracht één nieuw inzicht van buiten die recepten (de `//dev:`-scan trapt op haar eigen `ps`-patroon, de controle-run was onuitvoerbaar). Alle ronde-4-recepten zijn nu lokaal gemeten in plaats van alleen beredeneerd, wat de kans op een vijfde receptronde verkleint. Geen uitbreiding; geen schrapkandidaat.

## Ronde 5 (14-10-2026)

**Gepind:** `dev-docker/PLAN.md` revisie 5 @ `978e3162dee37d7a2f7f1b732c2f53ca0cfaffda` (reviewrecord-commit volgt; `PLAN.md` byte-identiek, sha256 `6d2c9e5e…`); `dev-docker/SPEC.md` rev. 11 @ dezelfde commit (ongewijzigd).

| Slot | request id | root_message_id | job id | idempotency key | idea_link |
|---|---|---|---|---|---|
| CODEX | (volgt) | | | | |
| CLAUDE | (volgt) | | | | |

**Uitslag:** (volgt)
