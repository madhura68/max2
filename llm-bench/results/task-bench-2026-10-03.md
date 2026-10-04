# Task-bench: Qwen 3.8 voor een 96 GB-machine op echt werk (M7, 2026-10-03)

## Kort

- **Oordeel: onbeslist.** Gehost (`qwen/qwen3.8-27b` in BF16, zoals hij op een Mac van 96 GB zou draaien) haalde **8 van 12**, `gsq-lokaal` op max2 ook **8 van 12**. Gehost ligt op de grens (8), dus volgens spec §1 is het oordeel onbeslist, wat gsq ook haalt.
- **JP koos op 2026-10-04: stoppen.** Volgens spec §1 betekent dat: geen meerwaarde aangetoond. Geen Mac voor dit doel.
- Op deze 12 taken haalt max2 nu al wat de 27B op volle precisie haalt. De twee modellen verschillen op twee taken, één naar elke kant (AH-08 alleen gehost, AH-16 alleen gsq). Drie taken haalde geen van beide.
- Geen benchfouten en geen herhaalde verzoeken. Kosten van heel M7: **$1,1747** (budget $19,08). Gehost duurde 112 min voor de 12 runs, gsq 139 min.

## Opzet

- **Echt werk:** 12 oude, afgeronde Scrum4Me-taken (`TASK_IMPLEMENTATION`), opnieuw uitgevoerd vanaf hun begincommit met de taaktekst zoals de productieworker die krijgt. Een run is **geslaagd** als de verify-gate van de repo groen is én de verborgen tests van de echte oplossing (`ref_commit`) slagen; daarvoor worden `__tests__/` en de runnerconfig exact teruggezet.
- **Bench:** `harness task-bench` (agent-harness `24aa096`), dezelfde lus, tools, gate (`maxVerifyRepairs` 3) en limieten als `runTaskJob` (`maxTurns` 40, `maxOutputTokens` 80000, `maxWallSeconds` 2400, `maxToolErrors` 8, `contextTokens` 65536), zonder doc-tools.
- **Modellen:** `qwen3.8-openrouter` = `qwen/qwen3.8-27b` via OpenRouter, alleen op een 16-bit-route (`quantizations: [bf16, fp16]`, `data_collection: deny`, `require_parameters`, `reasoning.effort: medium`), herhaling bij storingen aan; `gsq-lokaal` = `qwen3.8-gsq-rco:27b-iq3_s-text` op max2 (Ollama, 64k context, thinking aan), zoals de productieworker. Eén run per taak.
- **Beslisregel (spec §1):** een model kan het werk aan bij minstens 9 van 12; meerwaarde vraagt bovendien minstens 3 meer dan gsq; een telling op de grens (9 of 8) of een verschil van precies 3 maakt het oordeel onbeslist.
- Spec: `docs/specs/2026-10-02-task-bench-design.md` (rev 5) en plan `docs/plans/M7-task-bench.md` (rev 4 met uitvoeringsnotities) in agent-harness.

## De takenset

Bron-pin (origin/main, 2026-10-03): agent-harness `67377014`, scrum4me-mcp `a6b3fe0b`. Filter, koppeling, beoordeling van criteria 4/5 en het `--check-case`-bewijs per kandidaat staan in `task-bench-2026-10-03/selectie/` (voorstel.md, case-check/). JP keurde de set goed vóór increment 3; hij is bevroren in `llm-bench/task_bench/cases.jsonl`.

| id | repo | taak | ref | regels | klasse | soort | verborgen tests |
|---|---|---|---|---|---|---|---|
| AH-01 | agent-harness | T-34 | `64829bce` | 199 | middel | feat | `redact.test.ts` |
| AH-02 | agent-harness | T-33 | `5dc01bd2` | 37 | klein | feat | `task-impl.test.ts`, `trace.test.ts` |
| AH-04 | agent-harness | T-46 | `f6577078` | 196 | middel | fix | `cli.test.ts`, `model-client.test.ts`, `probe.test.ts`, `run-answer.test.ts` |
| AH-07 | agent-harness | T-64 | `764f1c15` | 112 | middel | fix | `cli-worker.test.ts`, `doc-tools.test.ts` |
| AH-08 | agent-harness | T-8 | `fc2130cf` | 115 | middel | feat | `policy.test.ts` |
| AH-12 | agent-harness | T-50 | `17899f01` | 261 | groot | feat | `model-client.test.ts`, `run-answer.test.ts` |
| AH-16 | agent-harness | T-24 | `92dd44d3` | 347 | groot | feat | `worker-config.test.ts`, `worker.test.ts` |
| AH-17 | agent-harness | T-13 | `3f7ddb93` | 336 | groot | feat | `idea-chat-prompt.test.ts`, `worker-config.test.ts` |
| MC-11 | scrum4me-mcp | T-1555 | `4a29990c` | 198 | middel | feat | `queue-archive.test.ts`, `queue-registration.test.ts` |
| MC-19 | scrum4me-mcp | T-19 | `4b94e5a9` | 56 | klein | feat | `dispatch-job.test.ts`, `dispatch-task-implementation.test.ts` |
| MC-29 | scrum4me-mcp | T-1431 | `e92ff481` | 189 | middel | feat | `git/pr-enable-auto-merge.test.ts` |
| MC-31 | scrum4me-mcp | T-1428 | `daa3989e` | 234 | groot | feat | `sprint-batch-auto-deploy.test.ts` |

Afwijkingen van spec §4.2 op JP's besluit (2026-10-03): 8 agent-harness + 4 scrum4me-mcp in plaats van 6 + 6; 2 kleine taken in plaats van 4; MC-19 (T-19) komt uit product Agent-harness (M3) in plaats van Scrum4Me; voor scrum4me-mcp is verbreed naar commits sinds 2026-05-01. Reden: op het productierecept waren scrum4me-mcp-bases tussen 2026-08-12 en 2026-09-14 rood (ppe-tests zonder databasefixture), M20-bases (juli) rood op een job-config-pariteitstest, veel plannen bevatten de volledige code (criterium 5), en git-tests slagen niet in de container. Drie selectierondes `--check-case` (33 kandidaten) staan in `selectie/case-check/`.

## Uitkomst per taak

| Taak | qwen3.8-openrouter | gsq-lokaal |
|---|---|---|
| AH-01 (T-34) | geslaagd | geslaagd |
| AH-02 (T-33) | geslaagd | geslaagd |
| AH-04 (T-46) | geslaagd | geslaagd |
| AH-07 (T-64) | geslaagd | geslaagd |
| AH-08 (T-8) | geslaagd | verborgen tests rood (1) |
| AH-12 (T-50) | geslaagd | geslaagd |
| AH-16 (T-24) | limiet (40 beurten) | geslaagd |
| AH-17 (T-13) | verborgen tests rood (1) | verborgen tests rood (1) |
| MC-11 (T-1555) | limiet (40 beurten) | limiet (40 beurten) |
| MC-19 (T-19) | geslaagd | geslaagd |
| MC-29 (T-1431) | geslaagd | geslaagd |
| MC-31 (T-1428) | limiet (40 beurten) | limiet (40 beurten) |

**Redenen van falen.**

- **Limiet:** elke limiet-run eindigde op `budget_exceeded` na 40 modelbeurten, zonder eindantwoord en zonder dat de gate rood was: AH-16 (alleen gehost), MC-11 en MC-31 (beide modellen). gsq haalde AH-16 wel, in 27 beurten (21,5 min).
- **Verborgen tests rood** (de gate was groen; de falende tests uit `hidden-vitest.json`):
  - AH-08, gsq-lokaal: `policy.test.ts` › createPolicy treats empty arguments as {} only when nothing is required — `AssertionError: expected { ok: false, …(2) } to match object { ok: false, …(1) }`
  - AH-17, qwen3.8-openrouter: `idea-chat-prompt.test.ts` › IDEA_CHAT_SYSTEM_PROMPT points at the pending section and forbids changes — `AssertionError: expected 'Je bent de assistent van de eigenaar …' to match /wijzigt niets/i`
  - AH-17, gsq-lokaal: `idea-chat-prompt.test.ts` › IDEA_CHAT_SYSTEM_PROMPT points at the pending section and forbids changes — `AssertionError: expected 'Je bent de assistent van de eigenaar …' to match /wijzigt niets/i`
  - AH-17 faalt bij beide modellen op dezelfde test: de prompt moet `wijzigt niets` bevatten. Die woorden staan in de taaktekst, dus de test was eerlijk maar letterlijk (spec §6: JP beoordeelt). AH-08 bij gsq: `createPolicy` geeft bij lege argumenten een extra veld terug.

## Tellingen en oordeel (spec §1)

- **qwen3.8-openrouter:** geslaagd 8, verborgen_tests_rood 1, verify_rood 0, limiet 3, geen_wijzigingen 0, benchfout 0.
- **gsq-lokaal:** geslaagd 8, verborgen_tests_rood 2, verify_rood 0, limiet 2, geen_wijzigingen 0, benchfout 0.
- `verdict(8, 8)` = **onbeslist** (`task_bench/score.py`, zelfde uitkomst als deze regels). Gehost 8 valt in rij 1 (gezakt, 8 of minder), maar 8 is de grens min één: daarmee is het oordeel onbeslist. Dat geldt voor elke gsq-telling.
- **Betekenis voor de aankoop:** bij onbeslist kiest JP tussen meer taken en stoppen. JP koos stoppen: geen meerwaarde aangetoond, geen Mac voor dit doel. De gelijke stand (8 tegen 8, verschillen op twee taken) wijst dezelfde kant op: wat de 96 GB-klasse met dit model zou toevoegen, haalt max2 met gsq nu al.

## Per run: tijd, beurten, toolfouten, kosten en aanbieders

**qwen3.8-openrouter**

| Taak | uitkomst | min | beurten | tools | toolfouten | in / uit (reasoning) tokens | kosten | aanbieders | herhalingen |
|---|---|---|---|---|---|---|---|---|---|
| AH-01 | geslaagd | 10,2 | 23 | 28 | 0 | 820.265 / 22.222 (14.132) | $0,1217 | DeepInfra ×23 | 0 |
| AH-02 | geslaagd | 2,5 | 13 | 20 | 0 | 312.097 / 4.080 (1.463) | $0,0239 | DeepInfra ×13 | 0 |
| AH-04 | geslaagd | 10,9 | 25 | 29 | 0 | 904.524 / 21.462 (14.531) | $0,1146 | DeepInfra ×25 | 0 |
| AH-07 | geslaagd | 2,1 | 7 | 12 | 0 | 100.178 / 2.967 (237) | $0,0131 | DeepInfra ×7 | 0 |
| AH-08 | geslaagd | 6,3 | 25 | 32 | 1 | 645.308 / 10.582 (6.503) | $0,0584 | DeepInfra ×25 | 0 |
| AH-12 | geslaagd | 4,8 | 20 | 33 | 0 | 702.713 / 6.639 (2.177) | $0,0678 | DeepInfra ×20 | 0 |
| AH-16 | limiet (40 beurten) | 13,9 | 40 | 51 | 0 | 1.577.731 / 28.729 (18.061) | $0,1717 | DeepInfra ×40 | 0 |
| AH-17 | verborgen tests rood (1) | 3,7 | 12 | 16 | 0 | 213.655 / 7.661 (2.108) | $0,0292 | DeepInfra ×12 | 0 |
| MC-11 | limiet (40 beurten) | 10,8 | 40 | 65 | 0 | 1.442.235 / 20.020 (10.350) | $0,1441 | DeepInfra ×40 | 0 |
| MC-19 | geslaagd | 6,5 | 17 | 24 | 0 | 321.788 / 6.444 (1.448) | $0,0422 | DeepInfra ×17 | 0 |
| MC-29 | geslaagd | 11,4 | 16 | 20 | 0 | 449.441 / 15.871 (6.285) | $0,0761 | DeepInfra ×16 | 0 |
| MC-31 | limiet (40 beurten) | 28,4 | 40 | 61 | 2 | 1.395.353 / 42.975 (38.743) | $0,2445 | DeepInfra ×40 | 0 |

**gsq-lokaal**

| Taak | uitkomst | min | beurten | tools | toolfouten | in / uit (reasoning) tokens | kosten | aanbieders | herhalingen |
|---|---|---|---|---|---|---|---|---|---|
| AH-01 | geslaagd | 9,6 | 20 | 28 | 0 | 530.568 / 22.525 (–) | – | – | 0 |
| AH-02 | geslaagd | 3,3 | 19 | 28 | 0 | 448.933 / 5.852 (–) | – | – | 0 |
| AH-04 | geslaagd | 13,8 | 27 | 39 | 2 | 1.019.701 / 23.802 (–) | – | – | 0 |
| AH-07 | geslaagd | 2,1 | 9 | 12 | 0 | 159.323 / 3.389 (–) | – | – | 0 |
| AH-08 | verborgen tests rood (1) | 3,7 | 23 | 30 | 1 | 386.117 / 8.384 (–) | – | – | 0 |
| AH-12 | geslaagd | 8,1 | 20 | 36 | 1 | 736.256 / 13.508 (–) | – | – | 0 |
| AH-16 | geslaagd | 21,5 | 27 | 41 | 0 | 799.484 / 52.214 (–) | – | – | 0 |
| AH-17 | verborgen tests rood (1) | 4,3 | 18 | 24 | 1 | 439.297 / 9.342 (–) | – | – | 0 |
| MC-11 | limiet (40 beurten) | 22,7 | 40 | 72 | 1 | 1.452.995 / 42.170 (–) | – | – | 0 |
| MC-19 | geslaagd | 7,0 | 11 | 21 | 0 | 272.543 / 6.169 (–) | – | – | 0 |
| MC-29 | geslaagd | 10,1 | 16 | 20 | 0 | 346.705 / 19.679 (–) | – | – | 0 |
| MC-31 | limiet (40 beurten) | 32,7 | 40 | 63 | 2 | 1.368.345 / 63.391 (–) | – | – | 0 |

Gehost kwam elke respons van DeepInfra in BF16 (278 antwoorden, plus 12 in de praktijkproef). gsq draait lokaal en meldt geen kosten en geen aparte reasoning-tokens.

## Benchfouten, herhalingen en afgebroken runs

Geen. Geen enkele run eindigde als benchfout, geen enkel verzoek werd herhaald (`retries` leeg in alle 25 runs), en geen run werd afgebroken: het vangnet van het nachtvenster bleef ongebruikt. Geen enkele run schreef in een submodule (controle op `write_file`/`edit_file` onder `vendor/` in elke `trace.jsonl`).

## Kosten (grootboek)

| post | bedrag |
|---|---|
| praktijkproef (probe + run AH-01) | $0,0666 |
| probe gehost (Taak 9) | $0,0008 |
| 12 gehoste runs (Taak 9) | $1,1073 |
| gsq (probe + 12 runs) | $0 (13 regels zonder bedrag) |
| **totaal M7** | **$1,1747** |

Het totaal is gelijk aan de stijging van het verbruik van de OpenRouter-sleutel (0,9238 → 2,0985, gelezen zonder de sleutel te tonen). De spec schatte $0,54 per gehoste run; gemeten was het $0,013–$0,245, gemiddeld $0,09.

## Endpointlijsten

Bij het begin van beide gehoste vensters toonde de publieke endpointlijst van `qwen/qwen3.8-27b` 17 aanbieders, waarvan alleen DeepInfra (BF16) 16-bit met tools aanbiedt (Cerebras is FP16 maar zonder tools). Bestanden: `vensters/endpoints-proef.json` en `vensters/gehost/endpoints-qwen3.8-openrouter-20261003T121905Z.json`. De probes: proef reliable ($0,00078; a_plain via Cerebras, de rest DeepInfra), gehost reliable ($0,00077), gsq reliable.

## Verschillen met productie en kanttekeningen

- **Bewust anders dan productie (spec §4.1):** geen doc-tools (de bijzin in de systeemprompt en het blok `## Product` vallen weg), een eigen werkmap met de gitdir buiten de containermount, de verborgen toets na de run (schone installatie op een verse clone van `ref_commit`, dan `__tests__/` en runnerconfig terug), herhaling bij storingen alleen op de gehoste route, en een benchfout als de bench of de aanbieder faalt in plaats van een modelstatus.
- **Kleine aantallen:** bij 12 taken scheelt één taak 8 procentpunt; daarom is 8 van 12 onbeslist en geen bewijs.
- **Gehost ≠ lokaal op een Mac:** precisie vastgelegd op BF16, maar engine en template verschillen. Eén aanbieder (DeepInfra).
- **Eén run per taak:** een steekproef; gehost is niet herhaalbaar.
- **Verborgen tests kunnen streng zijn:** zie AH-17 hierboven.
- **Selectie:** de set is anders samengesteld dan spec §4.2 voorschreef (zie De takenset); scrum4me-mcp telt 4 van de 12 taken.
- **Bekende restpunten van de bench** (plan, uitvoeringsnotities): modelcode wordt in de verborgen toets niet geïsoleerd; `vite.config.*`/`vitest.workspace.*` worden niet teruggezet; de schone installatie komt na de betaalde run.
- **Base met een bekende flake:** de bases van AH-01 en AH-02 bevatten de later gefixte search-flake in `task-tools.test.ts`. Die kan alleen de gate raken; beide modellen haalden beide taken.

## Vensters en dienststand (spec §5, criterium 6)

Alle vensters volgens de Vensterprocedure (M6) met de M7-punten: M4-stop fail-closed, containers volgens de dienststand gestopt, tmux met sessie-ID, eindvoorwaarde zonder `harness-`-containers, herstel. Vooraf was het telkens: worker `active`, `dsh` en `open-webui` draaiden, `tei-gpu` niet; na het herstel telkens gelijk.

| venster | wanneer (CEST) | wat | dienststand voor → na |
|---|---|---|---|
| proef | 2026-10-03 10:12–10:37 | check-case AH-01, probe, run AH-01 (sleutel op tmpfs, daarna weg) | gelijk |
| selectie 1 | 12:06–12:27 | 21 × check-case | gelijk |
| selectie 2 | 12:28–12:34 | 3 × check-case | gelijk |
| selectie 3 | 12:47–13:02 | 9 × check-case | gelijk |
| gehost | 14:17–16:13 | Taak 9: endpointlijst, probe, 12 runs (sleutel op tmpfs, daarna weg; vangnet ongebruikt) | gelijk |
| gsq | 22:00–00:19 (nacht) | Taak 10: probe, 12 runs; automatisch gestart vanaf de Mac, nazorg herstelde om 00:19 | gelijk |

Het nachtvenster startte automatisch: een starter op de Mac (onder `caffeinate`) deed om 22:00 de controles en de M4-stop (max2 bereikt de database op scrum4me-srv niet), daarna draaiden run, nazorg (herstel direct na afloop) en vangnet (06:40) zelfstandig op max2. Scripts en logs: `vensters/` en `vensters/mac/`.

## Commits en versies

- Bench: agent-harness `24aa096ee5f9` (merge PR #31), gebouwd in `~/Development/agent-harness-m7` op max2.
- Driver en scorer: max2 `cb99e3db1952` (merge PR #30), clone `~/Development/max2-m7` op max2.
- Worker-checkout: agent-harness `15c1e26e6d80`, vóór en na elk venster ongewijzigd; `/etc/agent-harness/worker.json` laatst gewijzigd 2026-09-29 (vóór M7), het `task`-blok was in elk venster gelijk aan `task_bench/task-config.json`.
- `ollama --version`: 0.34.4.

## Bestanden in `task-bench-2026-10-03/`

- `selectie/`: bron-pin, voorstel met afvallers, `case-check.json` van alle 33 gecontroleerde kandidaten, beoordelingen, scripts.
- `runs/<label>/<run>/`: per run `bench-result.json`, `patch.diff`, `hidden-vitest.json`, `trace.jsonl` (zonder `ws/`, `tools/`, `containers/`), ook de praktijkproef onder `runs/proef/`. Van AH-01 bij gsq ontbreken `patch.diff` en `trace.jsonl`: de secret-scan-hook van deze repo ziet de nepwaarden die het model in zijn eigen redactietest schreef (zoals `GITHUB_TOKEN: 'gh-tok…'`) als tokenachtig. De originelen staan in de kopie op de Mac en in `~/m7-runs/task-bench-2026-10-03/gsq/` op max2.
- `vensters/`: grootboek, `summary.csv`, endpointlijsten, probes, run-, nazorg- en vangnetscripts, logs, `.sid`-bestanden en dienststanden; `vensters/mac/`: de starter en controlescripts van de Mac. `rapport-data.json`: de cijfers achter dit rapport.

## Acceptatiecriteria (spec §5)

1. **Bench volgt de worker:** pariteitstest met de echte `runTaskJob` en prompttests (geen doc-toolnaam) in agent-harness PR #31 (1202 tests, `npm run verify` groen); de verborgen toets telt een aangepaste runnerconfig of weggehaalde test niet als geslaagd; herhaling alleen bij tijdelijke fouten op de gehoste route, hooguit 3. De trace van de praktijkproef toont de lus. **Gehaald.**
2. **Praktijkproef:** AH-01 met `qwen3.8-openrouter` geslaagd (17,2 min, $0,0658), elke respons DeepInfra BF16, 0 herhalingen, verborgen toets met `__tests__/` en runnerconfig van `ref_commit` (11/11). **Gehaald.**
3. **Takenset van 12 met bewijs voor criteria 2 en 3 en de bron-pin, door JP goedgekeurd vóór increment 3:** gehaald, met de verdeling 8 + 4 in plaats van 6 per repo op JP's besluit.
4. **Beide modellen 12 geldige runs:** 24 runs, elk in een modelstatus, 0 benchfouten. **Gehaald.**
5. **Rapport met §4.8 en het oordeel volgens §1; kosten binnen §4.6:** dit rapport; oordeel onbeslist; $1,1747 van $19,08. **Gehaald.**
6. **Diensten na elk venster als vooraf, worker-checkout en -config ongewijzigd, sleutel nergens:** zes vensters gelijk; checkout `15c1e26` ongewijzigd; `check_key.py` vond 0 treffers op de Mac-kopie (1509 bestanden) en op deze map. **Gehaald.**
7. **Gates:** `npm run verify` in agent-harness (PR #31) en de llm-bench-unittests (task_bench 155, refiner 462) groen. **Gehaald.**
