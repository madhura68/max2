# Review-bench 2026-10-21

Case `macsearch-idea263-spec-r5`. 8 van 12 verwachte runs beoordeeld (4 configuraties x 3 runs).

Geldigheid van de bench: in orde: minstens één harness-controle is kandidaat.

## Oordeel per model

| Model | Oordeel | Voldoet | Verdicts | F1 per run | F2 per run | Minors (gem.) | Extra's |
| --- | --- | --- | --- | --- | --- | --- | --- |
| deepseek-v4-flash-or | valt af | 0/3 | GO / GO / - | nee / nee / - | minor / minor / - | 0,0 | - |
| deepseek-v4-pro-or | valt af | 0/3 | - / - / - | - / - / - | - / - / - | - | - |
| qwen3.8-or-128k | valt af | 0/3 | GO / GO / GO | nee / minor / nee | minor / nee / minor | 0,3 | - |
| gpt-6.1-sol-or (controle) | kandidaat | 3/3 | NO-GO / NO-GO / NO-GO | major / major / major | major / major / major | 0,0 | - |

Oordeel: kandidaat is 3 van 3 runs die voldoen, twijfel 2 van 3, anders valt het model af; open zolang een extra geen beslissing heeft. Een run voldoet als het resultaat is aanvaard (beoordeeld), outcome succeeded is, het verdict NO-GO is, F1 als major is gevonden en geen extra ongeldig is verklaard. Een model dat nooit gedraaid heeft, valt af; waarom staat erbij.

## Eerste vergelijking: open modellen tegenover de harness-controles

Geldigheid van de bench: in orde: minstens één harness-controle is kandidaat.

| Groep | Model | Oordeel | Voldoet | F1 als major gevonden |
| --- | --- | --- | --- | --- |
| harness-controle | gpt-6.1-sol-or | kandidaat | 3/3 | 3/3 |
| open model | deepseek-v4-flash-or | valt af | 0/3 | 0/3 |
| open model | deepseek-v4-pro-or | valt af | 0/3 | 0/3 |
| open model | qwen3.8-or-128k | valt af | 0/3 | 0/3 |

Controle niet in --models: claude-sonnet-5.5-or.

## Kosten, tokens, context en tijd

| Model | Kosten gem. | Kosten max. | Tokens in / uit (gem.) | Piek input / venster | Wandtijd (gem.) | Turns (gem.) | Toolfouten | Outcome per run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deepseek-v4-flash-or | $0,0178 | $0,0194 | 255835 / 120550 | 48840 / 131072 (37%) | 1171,8 s | 12,0 | 2 | succeeded / succeeded / - |
| deepseek-v4-pro-or | $0,1219 | $0,1269 | 169609 / 127143 | 30240 / 131072 (23%) | 2673,2 s | 11,3 | 0 | - / - / - |
| qwen3.8-or-128k | $0,1455 | $0,2132 | 139638 / 68027 | 25524 / 131072 (19%) | 2399,2 s | 9,7 | 0 | succeeded / succeeded / succeeded |
| gpt-6.1-sol-or (controle) | $0,0671 | $0,0710 | 31516 / 3406 | 12441 / 131072 (9%) | 82,3 s | 4,7 | 0 | succeeded / succeeded / succeeded |

Kosten: alle runs met een bedrag (0 runs hebben er geen). De rest: runs met een modelstatus. De piek is `peakInputTokens` naast het venster van 131072.

## Per run

| Model | Run | Status | Outcome | Verdict | F1 | F2 | Minors | Voldoet | read_file sources/doc | waarvan met offset/limit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deepseek-v4-flash-or | 1 | beoordeeld | succeeded | GO | nee | minor | - | nee | 5 | 4 |
| deepseek-v4-flash-or | 2 | beoordeeld | succeeded | GO | nee | minor | - | nee | 4 | 2 |
| deepseek-v4-flash-or | 3 | limiet | - | - | - | - | - | nee | 8 | 7 |
| deepseek-v4-pro-or | 1 | limiet | - | - | - | - | - | nee | 8 | 6 |
| deepseek-v4-pro-or | 2 | limiet | - | - | - | - | - | nee | 4 | 3 |
| deepseek-v4-pro-or | 3 | resultaat_ongeldig | - | - | - | - | - | nee | 6 | 5 |
| qwen3.8-or-128k | 1 | beoordeeld | succeeded | GO | nee | minor | - | nee | 2 | 1 |
| qwen3.8-or-128k | 2 | beoordeeld | succeeded | GO | minor | nee | - | nee | 6 | 5 |
| qwen3.8-or-128k | 3 | beoordeeld | succeeded | GO | nee | minor | M6 | nee | 2 | 1 |
| gpt-6.1-sol-or | 1 | beoordeeld | succeeded | NO-GO | major | major | - | ja | 3 | 3 |
| gpt-6.1-sol-or | 2 | beoordeeld | succeeded | NO-GO | major | major | - | ja | 2 | 2 |
| gpt-6.1-sol-or | 3 | beoordeeld | succeeded | NO-GO | major | major | - | ja | 2 | 2 |

## Runs zonder oordeel

| Model | Run | Reden |
| --- | --- | --- |
| deepseek-v4-flash-or | 3 | limiet |
| deepseek-v4-pro-or | 1 | limiet |
| deepseek-v4-pro-or | 2 | limiet |
| deepseek-v4-pro-or | 3 | resultaat_ongeldig: REVIEW_RESULT_INVALID |

## Preflight

| Model | Preflight | Reden | Bedrag (grootboek) |
| --- | --- | --- | --- |
| deepseek-v4-flash-or | ok | - | $0,0000 |
| deepseek-v4-pro-or | ok | - | $0,0000 |
| qwen3.8-or-128k | ok | - | $0,0001 |
| gpt-6.1-sol-or | ok | - | $0,0001 |

## Rookproef

De rookproef is niet meegegeven (--smoke-dir en --smoke-scores).

## Context: productieruns

De productieruns van dezelfde review, ter vergelijking. Het zijn geen bench-runs en ze tellen niet mee in het oordeel.

| Run | Uitvoerder | Kosten |
| --- | --- | --- |
| 1a78c1b8 | Claude Code | $0,39 |
| 7146cbe9 | Codex CLI | ≈ $0,10 |

## Grootboek

Totaal $1,1607 over 17 regels, 0 zonder bedrag (die tellen als 0, het totaal is een ondergrens).

| Id | Soort | Configuratie | Run | Case | Kosten |
| --- | --- | --- | --- | --- | --- |
| preflight-deepseek-v4-flash-or-20261021T171203Z | preflight | deepseek-v4-flash-or | - | - | $0,0000 |
| preflight-deepseek-v4-pro-or-20261021T171204Z | preflight | deepseek-v4-pro-or | - | - | $0,0000 |
| preflight-qwen3.8-or-128k-20261021T171207Z | preflight | qwen3.8-or-128k | - | - | $0,0001 |
| preflight-gpt-6.1-sol-or-20261021T171208Z | preflight | gpt-6.1-sol-or | - | - | $0,0001 |
| macsearch-idea263-spec-r5-out128k-deepseek-v4-flash-or-2e1398b1 | run | deepseek-v4-flash-or | 1 | macsearch-idea263-spec-r5-out128k | $0,0194 |
| macsearch-idea263-spec-r5-out128k-deepseek-v4-pro-or-5a5548c7 | run | deepseek-v4-pro-or | 1 | macsearch-idea263-spec-r5-out128k | $0,1210 |
| macsearch-idea263-spec-r5-out128k-qwen3.8-or-128k-2ee15335 | run | qwen3.8-or-128k | 1 | macsearch-idea263-spec-r5-out128k | $0,1334 |
| macsearch-idea263-spec-r5-out128k-gpt-6.1-sol-or-950778b0 | run | gpt-6.1-sol-or | 1 | macsearch-idea263-spec-r5-out128k | $0,0619 |
| macsearch-idea263-spec-r5-out128k-deepseek-v4-flash-or-4a5cf7e5 | run | deepseek-v4-flash-or | 2 | macsearch-idea263-spec-r5-out128k | $0,0177 |
| macsearch-idea263-spec-r5-out128k-deepseek-v4-pro-or-839fc0af | run | deepseek-v4-pro-or | 2 | macsearch-idea263-spec-r5-out128k | $0,1036 |
| macsearch-idea263-spec-r5-out128k-deepseek-v4-pro-or-82da5467 | run | deepseek-v4-pro-or | 2 | macsearch-idea263-spec-r5-out128k | $0,1178 |
| macsearch-idea263-spec-r5-out128k-qwen3.8-or-128k-e12fa8d3 | run | qwen3.8-or-128k | 2 | macsearch-idea263-spec-r5-out128k | $0,2132 |
| macsearch-idea263-spec-r5-out128k-gpt-6.1-sol-or-b1c47c78 | run | gpt-6.1-sol-or | 2 | macsearch-idea263-spec-r5-out128k | $0,0710 |
| macsearch-idea263-spec-r5-out128k-deepseek-v4-flash-or-659e5c90 | run | deepseek-v4-flash-or | 3 | macsearch-idea263-spec-r5-out128k | $0,0163 |
| macsearch-idea263-spec-r5-out128k-deepseek-v4-pro-or-ba1159c0 | run | deepseek-v4-pro-or | 3 | macsearch-idea263-spec-r5-out128k | $0,1269 |
| macsearch-idea263-spec-r5-out128k-qwen3.8-or-128k-c02ad9e2 | run | qwen3.8-or-128k | 3 | macsearch-idea263-spec-r5-out128k | $0,0900 |
| macsearch-idea263-spec-r5-out128k-gpt-6.1-sol-or-7f97ea6f | run | gpt-6.1-sol-or | 3 | macsearch-idea263-spec-r5-out128k | $0,0682 |

## Venster, probes en afwijkingen

### Venster (2026-10-21, UTC)

Dit is het 128k-venster van M9 (IDEA-272, plan `docs/plans/M9-review-bench-output-limit.md` rev 3 in agent-harness). De case is de variant `macsearch-idea263-spec-r5-out128k`, met limieten `maxOutputTokens` 128 000, `maxWallSeconds` 3600, `maxTurns` 30 en `maxToolErrors` 8. Naast de limieten is ook het id anders; de bytes die het model ziet, zijn gelijk aan die van de M8-case.

| Stap | Tijd | Uitkomst |
| --- | --- | --- |
| Releasecontrole vóór de preflight | 17:11:59 | `current` → `releases/a68a74627660f2afd355e2f11d54be582466db7a`, link-mtime 2026-10-21 06:50:18 UTC (de uitrol van P1 in M8) |
| Preflight | 17:12:03–17:12:08 | alle 4 ok, `max_tokens` 127874, samen $0,0003 |
| De 12 runs | 17:12:27–23:14:43 | 12/12 resultaten, 1 benchfout (herhaald), `skipped.json` leeg, exit 0 |
| Releasecontrole bij hervatting | 21:05 | ongewijzigd: readlink en link-mtime gelijk |
| Releasecontrole na de laatste run | 23:15:00 | ongewijzigd: readlink en link-mtime gelijk |

Het venster draaide op max2 tegen de productie-release, via LiteLLM en OpenRouter. Het budget was $10: `min(10, tegoed − 2)`, met een tegoed van $33,20. Het grootboek komt uit op $1,1607 (17 regels: 4 preflights en 13 runs).

### Controles

- **Preflight (§4.2).** De preflight stuurde `max_tokens` 127874: `min(maxOutputTokens 128 000, contextTokens 131 072 − 3198)`. Alle vier de configuraties aanvaardden dat, ook qwen.
- **Turn 1 (§4.2).** In alle 13 pogingen vroeg turn 1 `maxTokens` 127874, met `promptEstimate` 3198. Dat geldt ook voor de benchfout en haar herhaling. Elke configuratie is gecontroleerd vóór haar tweede run.
- **Release (§4.5).** Readlink en link-mtime waren vóór de preflight, bij de hervatting en na de laatste run gelijk. De hervatting was een herstart van de Claude-sessie rond 21:00; run.py liep door en max2 is niet herstart.

### Oorzaak per `limiet`-run (§4.3)

| Model | Run | Output | Laatste antwoord | Oorzaak |
| --- | --- | --- | --- | --- |
| deepseek-v4-flash-or | 3 | 128 000 (reasoning 126 830), 13 turns | `length`, zonder toolcalls | budget |
| deepseek-v4-pro-or | 1 | 128 000 (reasoning 127 249), 11 turns | `length`, zonder toolcalls | budget |
| deepseek-v4-pro-or | 2 | 128 000 (reasoning 127 258), 11 turns | `length`, zonder toolcalls | budget |

Alle drie hebben `runStatus` `budget_exceeded`, geen `error.code`, `usage.source` `provider_reported` en output ≥ B. Er is geen run met oorzaak wandtijd, "length met budget over" of "anders". JP hoeft dus geen oorzaak te beoordelen.

### Afwijkingen van het plan

- **Een benchfout, herhaald.** deepseek-v4-pro-or r2 eindigde de eerste keer na 2753 s in `MODEL_ERROR`: OpenRouter gaf een antwoord dat geen JSON was ("Unable to get json response"). De mislukte request (turn 11) vroeg `maxTokens` 13889, ver onder het providermaximum, dus de limiet was niet de oorzaak (§4.2). De driver herhaalde de run één keer, en die herhaling telt. De stopregel (een tweede benchfout op dezelfde configuratie) is niet geraakt.
- **Een ongeldig resultaat.** deepseek-v4-pro-or r3 eindigde in `resultaat_ongeldig` (`REVIEW_RESULT_INVALID`). Het antwoord was twee keer geen geldige JSON, ook na de herhaalvraag. Met 125 428 output-tokens zat de run onder het budget; het is geen `limiet`-run. Er is geen blad, dus de run is niet gescoord.
- **De kop van het rapport.** De kop noemt de basiscase `macsearch-idea263-spec-r5`, niet de variant. JP aanvaardde dat (plan §4.4); het grootboek en deze notes noemen de variant.
- **Alleen sol als controle.** M9 draait alleen gpt-6.1-sol-or als controle (plan); claude-sonnet-5.5-or staat bewust niet in `--models`. Daarom meldt het rapport "Controle niet in --models".
- **Scoren.** Claude scoorde de 8 bladen blind, zonder `sheets-key.json`, met de rubric van M8. Er was geen extra-key, dus `decisions.json` is leeg: JP hoeft geen extra-key te beslissen.

### Beslissing voor stap 2 (§4.3)

Het criterium: een model gaat naar het 256k-venster als het bij 128k afvalt en minstens één `limiet`-run met oorzaak budget of wandtijd heeft.

| Model | Oordeel 128k | `limiet`-runs met oorzaak budget of wandtijd | Naar 256k |
| --- | --- | --- | --- |
| deepseek-v4-flash-or | valt af (0/3) | r3 (budget) | ja |
| deepseek-v4-pro-or | valt af (0/3) | r1, r2 (budget) | ja |
| qwen3.8-or-128k | valt af (0/3) | geen | nee, stopt |
| gpt-6.1-sol-or (controle) | kandidaat (3/3) | — | draait als controle mee, als het 256k-venster doorgaat |

Het 256k-venster begint alleen op JP's go, met een nieuw tegoed en een nieuwe key, en na de releasecontrole van §4.5.

### Wat het oordeel betekent

- **De bench is geldig.** De controle gpt-6.1-sol-or is kandidaat (3/3): elke run gaf NO-GO met F1 en F2 als MAJOR, net als bij 64k.
- **Meer budget liet flash en qwen hun runs afmaken, maar niet F1 vinden.**
  - deepseek-v4-flash-or maakte 2 van de 3 runs af (bij 64k: 0). Beide gaven GO, zonder F1, met F2 als MINOR. De afgemaakte runs gebruikten 127 100 en 106 549 van de 128 000 output-tokens.
  - qwen3.8-or-128k maakte 3 van de 3 runs af (bij 64k: 2). Alle drie gaven GO. qwen zag de F1-kern één keer, als MINOR.
  - deepseek-v4-pro-or gaf in geen enkele run een geldig antwoord: twee keer liep het budget op, één keer was de JSON ongeldig.
- **Geen van de drie open modellen is kandidaat** bij 128k.
- **Het eindrapport.** De tabel per model met het oordeel bij 64k, 128k en 256k komt in het laatste rapport. Besluit JP om geen 256k-venster te draaien, dan is dit rapport het laatste en wordt het opnieuw gemaakt met die tabel.

## Grenzen en vervolg

De bench dekt één case en alleen een document: geen shell, git of code lezen. De runs zijn blind met de hand gescoord, volgens de rubric van de case; JP besliste één keer per extra-key. Er is geen judge-model.

Geen enkel model buiten de controles is kandidaat; de uitkomst hierboven is de volledige uitslag.
