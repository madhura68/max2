# Review-bench 2026-10-21

Case `macsearch-idea263-spec-r5`. 18 van 24 verwachte runs beoordeeld (8 configuraties x 3 runs).

Geldigheid van de bench: in orde: minstens één harness-controle is kandidaat.

## Oordeel per model

| Model | Oordeel | Voldoet | Verdicts | F1 per run | F2 per run | Minors (gem.) | Extra's |
| --- | --- | --- | --- | --- | --- | --- | --- |
| qwen3.8-or-128k | valt af | 0/3 | - / GO / GO | - / nee / nee | - / nee / nee | 0,0 | - |
| deepseek-v4-flash-or | valt af | 0/3 | - / - / - | - / - / - | - / - / - | - | - |
| deepseek-v4-pro-or | valt af | 0/3 | GO / - / - | nee / - / - | nee / - / - | 1,0 | - |
| glm-5.3-or | valt af | 0/3 | NO-GO / GO / GO | nee / minor / nee | nee / nee / minor | 1,0 | x-route-c-retry-temp-path (ongeldig) |
| minimax-m3-or | valt af | 0/3 | GO / GO / GO | nee / nee / nee | nee / minor / nee | 0,0 | - |
| gpt-6-luna-or | kandidaat | 3/3 | NO-GO / NO-GO / NO-GO | major / major / major | nee / nee / nee | 0,0 | - |
| claude-sonnet-5.5-or (controle) | valt af | 1/3 | NO-GO / GO / GO | major / minor / nee | minor / minor / minor | 2,3 | - |
| gpt-6.1-sol-or (controle) | kandidaat | 3/3 | NO-GO / NO-GO / NO-GO | major / major / major | major / major / major | 0,0 | - |

Oordeel: kandidaat is 3 van 3 runs die voldoen, twijfel 2 van 3, anders valt het model af; open zolang een extra geen beslissing heeft. Een run voldoet als het resultaat is aanvaard (beoordeeld), outcome succeeded is, het verdict NO-GO is, F1 als major is gevonden en geen extra ongeldig is verklaard. Een model dat nooit gedraaid heeft, valt af; waarom staat erbij.

## Eerste vergelijking: open modellen tegenover de harness-controles

Geldigheid van de bench: in orde: minstens één harness-controle is kandidaat.

| Groep | Model | Oordeel | Voldoet | F1 als major gevonden |
| --- | --- | --- | --- | --- |
| harness-controle | claude-sonnet-5.5-or | valt af | 1/3 | 1/3 |
| harness-controle | gpt-6.1-sol-or | kandidaat | 3/3 | 3/3 |
| open model | qwen3.8-or-128k | valt af | 0/3 | 0/3 |
| open model | deepseek-v4-flash-or | valt af | 0/3 | 0/3 |
| open model | deepseek-v4-pro-or | valt af | 0/3 | 0/3 |
| open model | glm-5.3-or | valt af | 0/3 | 0/3 |
| open model | minimax-m3-or | valt af | 0/3 | 0/3 |
| propriëtair, geen controle | gpt-6-luna-or | kandidaat | 3/3 | 3/3 |

## Kosten, tokens, context en tijd

| Model | Kosten gem. | Kosten max. | Tokens in / uit (gem.) | Piek input / venster | Wandtijd (gem.) | Turns (gem.) | Toolfouten | Outcome per run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| qwen3.8-or-128k | $0,1170 | $0,1376 | 156088 / 52671 | 29548 / 131072 (23%) | 1315,7 s | 10,3 | 0 | - / succeeded / succeeded |
| deepseek-v4-flash-or | $0,0184 | $0,0211 | 120302 / 64000 | 28021 / 131072 (21%) | 1204,2 s | 8,0 | 0 | - / - / - |
| deepseek-v4-pro-or | $0,1361 | $0,1363 | 80382 / 63672 | 19889 / 131072 (15%) | 1261,7 s | 7,3 | 0 | succeeded / - / - |
| glm-5.3-or | $0,0982 | $0,0991 | 34194 / 20834 | 17198 / 131072 (13%) | 395,8 s | 4,3 | 0 | succeeded / succeeded / succeeded |
| minimax-m3-or | $0,0642 | $0,1234 | 539870 / 30014 | 73421 / 131072 (56%) | 404,6 s | 15,7 | 0 | succeeded / succeeded / succeeded |
| gpt-6-luna-or | $0,0031 | $0,0032 | 18225 / 2989 | 12401 / 131072 (9%) | 30,2 s | 4,0 | 0 | succeeded / succeeded / succeeded |
| claude-sonnet-5.5-or (controle) | $0,2070 | $0,2345 | 44477 / 11801 | 21188 / 131072 (16%) | 95,4 s | 4,0 | 0 | succeeded / succeeded / succeeded |
| gpt-6.1-sol-or (controle) | $0,0632 | $0,0662 | 24816 / 3092 | 12392 / 131072 (9%) | 86,4 s | 4,0 | 0 | succeeded / succeeded / succeeded |

Kosten: alle runs met een bedrag (0 runs hebben er geen). De rest: runs met een modelstatus. De piek is `peakInputTokens` naast het venster van 131072.

## Per run

| Model | Run | Status | Outcome | Verdict | F1 | F2 | Minors | Voldoet | read_file sources/doc | waarvan met offset/limit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| qwen3.8-or-128k | 1 | limiet | - | - | - | - | - | nee | 3 | 2 |
| qwen3.8-or-128k | 2 | beoordeeld | succeeded | GO | nee | nee | - | nee | 4 | 3 |
| qwen3.8-or-128k | 3 | beoordeeld | succeeded | GO | nee | nee | - | nee | 5 | 4 |
| deepseek-v4-flash-or | 1 | limiet | - | - | - | - | - | nee | 6 | 4 |
| deepseek-v4-flash-or | 2 | limiet | - | - | - | - | - | nee | 2 | 1 |
| deepseek-v4-flash-or | 3 | limiet | - | - | - | - | - | nee | 5 | 4 |
| deepseek-v4-pro-or | 1 | beoordeeld | succeeded | GO | nee | nee | M4 | nee | 4 | 3 |
| deepseek-v4-pro-or | 2 | limiet | - | - | - | - | - | nee | 5 | 4 |
| deepseek-v4-pro-or | 3 | limiet | - | - | - | - | - | nee | 2 | 1 |
| glm-5.3-or | 1 | beoordeeld | succeeded | NO-GO | nee | nee | M2 | nee | 2 | 1 |
| glm-5.3-or | 2 | beoordeeld | succeeded | GO | minor | nee | M4 | nee | 2 | 1 |
| glm-5.3-or | 3 | beoordeeld | succeeded | GO | nee | minor | M2 | nee | 2 | 1 |
| minimax-m3-or | 1 | beoordeeld | succeeded | GO | nee | nee | - | nee | 3 | 2 |
| minimax-m3-or | 2 | beoordeeld | succeeded | GO | nee | minor | - | nee | 11 | 10 |
| minimax-m3-or | 3 | beoordeeld | succeeded | GO | nee | nee | - | nee | 6 | 5 |
| gpt-6-luna-or | 1 | beoordeeld | succeeded | NO-GO | major | nee | - | ja | 1 | 1 |
| gpt-6-luna-or | 2 | beoordeeld | succeeded | NO-GO | major | nee | - | ja | 1 | 1 |
| gpt-6-luna-or | 3 | beoordeeld | succeeded | NO-GO | major | nee | - | ja | 1 | 1 |
| claude-sonnet-5.5-or | 1 | beoordeeld | succeeded | NO-GO | major | minor | M2 M5 | ja | 2 | 1 |
| claude-sonnet-5.5-or | 2 | beoordeeld | succeeded | GO | minor | minor | M2 M4 | nee | 2 | 1 |
| claude-sonnet-5.5-or | 3 | beoordeeld | succeeded | GO | nee | minor | M2 M3 M4 | nee | 2 | 1 |
| gpt-6.1-sol-or | 1 | beoordeeld | succeeded | NO-GO | major | major | - | ja | 2 | 2 |
| gpt-6.1-sol-or | 2 | beoordeeld | succeeded | NO-GO | major | major | - | ja | 2 | 2 |
| gpt-6.1-sol-or | 3 | beoordeeld | succeeded | NO-GO | major | major | - | ja | 2 | 2 |

## Runs zonder oordeel

| Model | Run | Reden |
| --- | --- | --- |
| qwen3.8-or-128k | 1 | limiet |
| deepseek-v4-flash-or | 1 | limiet |
| deepseek-v4-flash-or | 2 | limiet |
| deepseek-v4-flash-or | 3 | limiet |
| deepseek-v4-pro-or | 2 | limiet |
| deepseek-v4-pro-or | 3 | limiet |

## Preflight

| Model | Preflight | Reden | Bedrag (grootboek) |
| --- | --- | --- | --- |
| qwen3.8-or-128k | ok | - | $0,0001 |
| deepseek-v4-flash-or | ok | - | $0,0000 |
| deepseek-v4-pro-or | ok | - | $0,0001 |
| glm-5.3-or | ok | - | $0,0000 |
| minimax-m3-or | ok | - | $0,0001 |
| gpt-6-luna-or | ok | - | $0,0000 |
| claude-sonnet-5.5-or | ok | - | $0,0007 |
| gpt-6.1-sol-or | ok | - | $0,0001 |

## Rookproef

| Model | Run | Status | Outcome | Verdict | F1 |
| --- | --- | --- | --- | --- | --- |
| qwen3.8-or-128k | 1 | limiet | - | - | - |
| claude-sonnet-5.5-or | 1 | beoordeeld | succeeded | GO | minor |
| claude-sonnet-5.5-or | 2 | beoordeeld | succeeded | GO | minor |
| gpt-6.1-sol-or | 1 | beoordeeld | succeeded | NO-GO | major |

- stop: claude-sonnet-5.5-or r1: verdict GO, niet NO-GO
- stop: claude-sonnet-5.5-or r2: verdict GO, niet NO-GO
rookproef: stop

## Context: productieruns

De productieruns van dezelfde review, ter vergelijking. Het zijn geen bench-runs en ze tellen niet mee in het oordeel.

| Run | Uitvoerder | Kosten |
| --- | --- | --- |
| 1a78c1b8 | Claude Code | $0,39 |
| 7146cbe9 | Codex CLI | ≈ $0,10 |

## Grootboek

Totaal $2,7606 over 36 regels, 0 zonder bedrag (die tellen als 0, het totaal is een ondergrens).

| Id | Soort | Configuratie | Run | Case | Kosten |
| --- | --- | --- | --- | --- | --- |
| preflight-qwen3.8-or-128k-20261021T070351Z | preflight | qwen3.8-or-128k | - | - | $0,0001 |
| preflight-deepseek-v4-flash-or-20261021T070354Z | preflight | deepseek-v4-flash-or | - | - | $0,0000 |
| preflight-deepseek-v4-pro-or-20261021T070358Z | preflight | deepseek-v4-pro-or | - | - | $0,0001 |
| preflight-glm-5.3-or-20261021T070400Z | preflight | glm-5.3-or | - | - | $0,0000 |
| preflight-minimax-m3-or-20261021T070401Z | preflight | minimax-m3-or | - | - | $0,0001 |
| preflight-gpt-6-luna-or-20261021T070408Z | preflight | gpt-6-luna-or | - | - | $0,0000 |
| preflight-claude-sonnet-5.5-or-20261021T070409Z | preflight | claude-sonnet-5.5-or | - | - | $0,0007 |
| preflight-gpt-6.1-sol-or-20261021T070409Z | preflight | gpt-6.1-sol-or | - | - | $0,0001 |
| macsearch-idea263-spec-r5-qwen3.8-or-128k-633fe962 | run | qwen3.8-or-128k | 1 | macsearch-idea263-spec-r5 | $0,1369 |
| macsearch-idea263-spec-r5-claude-sonnet-5.5-or-a9c98b58 | run | claude-sonnet-5.5-or | 1 | macsearch-idea263-spec-r5 | $0,2203 |
| macsearch-idea263-spec-r5-claude-sonnet-5.5-or-84c04f7b | run | claude-sonnet-5.5-or | 2 | macsearch-idea263-spec-r5 | $0,2198 |
| macsearch-idea263-spec-r5-gpt-6.1-sol-or-3967023e | run | gpt-6.1-sol-or | 1 | macsearch-idea263-spec-r5 | $0,0608 |
| macsearch-idea263-spec-r5-qwen3.8-or-128k-c19cf4c1 | run | qwen3.8-or-128k | 1 | macsearch-idea263-spec-r5 | $0,1376 |
| macsearch-idea263-spec-r5-deepseek-v4-flash-or-74060adb | run | deepseek-v4-flash-or | 1 | macsearch-idea263-spec-r5 | $0,0211 |
| macsearch-idea263-spec-r5-deepseek-v4-pro-or-cd3c6069 | run | deepseek-v4-pro-or | 1 | macsearch-idea263-spec-r5 | $0,1361 |
| macsearch-idea263-spec-r5-glm-5.3-or-b5fe034f | run | glm-5.3-or | 1 | macsearch-idea263-spec-r5 | $0,0986 |
| macsearch-idea263-spec-r5-minimax-m3-or-78c0b29e | run | minimax-m3-or | 1 | macsearch-idea263-spec-r5 | $0,0203 |
| macsearch-idea263-spec-r5-gpt-6-luna-or-d29c29db | run | gpt-6-luna-or | 1 | macsearch-idea263-spec-r5 | $0,0030 |
| macsearch-idea263-spec-r5-claude-sonnet-5.5-or-b6474e64 | run | claude-sonnet-5.5-or | 1 | macsearch-idea263-spec-r5 | $0,1940 |
| macsearch-idea263-spec-r5-gpt-6.1-sol-or-2da5dec9 | run | gpt-6.1-sol-or | 1 | macsearch-idea263-spec-r5 | $0,0635 |
| macsearch-idea263-spec-r5-qwen3.8-or-128k-21c5a40b | run | qwen3.8-or-128k | 2 | macsearch-idea263-spec-r5 | $0,0944 |
| macsearch-idea263-spec-r5-deepseek-v4-flash-or-b35eed3a | run | deepseek-v4-flash-or | 2 | macsearch-idea263-spec-r5 | $0,0142 |
| macsearch-idea263-spec-r5-deepseek-v4-pro-or-331c1a22 | run | deepseek-v4-pro-or | 2 | macsearch-idea263-spec-r5 | $0,1363 |
| macsearch-idea263-spec-r5-glm-5.3-or-6d5ed276 | run | glm-5.3-or | 2 | macsearch-idea263-spec-r5 | $0,0991 |
| macsearch-idea263-spec-r5-minimax-m3-or-dd397811 | run | minimax-m3-or | 2 | macsearch-idea263-spec-r5 | $0,1234 |
| macsearch-idea263-spec-r5-gpt-6-luna-or-ab606915 | run | gpt-6-luna-or | 2 | macsearch-idea263-spec-r5 | $0,0030 |
| macsearch-idea263-spec-r5-claude-sonnet-5.5-or-1201a142 | run | claude-sonnet-5.5-or | 2 | macsearch-idea263-spec-r5 | $0,2345 |
| macsearch-idea263-spec-r5-gpt-6.1-sol-or-31e2b236 | run | gpt-6.1-sol-or | 2 | macsearch-idea263-spec-r5 | $0,0598 |
| macsearch-idea263-spec-r5-qwen3.8-or-128k-cd570ce2 | run | qwen3.8-or-128k | 3 | macsearch-idea263-spec-r5 | $0,1190 |
| macsearch-idea263-spec-r5-deepseek-v4-flash-or-f0b3736d | run | deepseek-v4-flash-or | 3 | macsearch-idea263-spec-r5 | $0,0200 |
| macsearch-idea263-spec-r5-deepseek-v4-pro-or-aa0e44f5 | run | deepseek-v4-pro-or | 3 | macsearch-idea263-spec-r5 | $0,1360 |
| macsearch-idea263-spec-r5-glm-5.3-or-79daf60e | run | glm-5.3-or | 3 | macsearch-idea263-spec-r5 | $0,0968 |
| macsearch-idea263-spec-r5-minimax-m3-or-a80eff9e | run | minimax-m3-or | 3 | macsearch-idea263-spec-r5 | $0,0490 |
| macsearch-idea263-spec-r5-gpt-6-luna-or-c7852aac | run | gpt-6-luna-or | 3 | macsearch-idea263-spec-r5 | $0,0032 |
| macsearch-idea263-spec-r5-claude-sonnet-5.5-or-85097b79 | run | claude-sonnet-5.5-or | 3 | macsearch-idea263-spec-r5 | $0,1924 |
| macsearch-idea263-spec-r5-gpt-6.1-sol-or-bb23eb37 | run | gpt-6.1-sol-or | 3 | macsearch-idea263-spec-r5 | $0,0662 |

## Venster, probes en afwijkingen

### Vensters (2026-10-21, UTC)

| Stap | Venster | Uitkomst |
| --- | --- | --- |
| P1 release en herprobe | 06:50–06:55 | release `a68a746` (agent-harness #59) en `litellm_upgrade` (klaar om 06:51:04). Alle 12 configuraties zijn aanvaard, met een probe van na 06:51:04. |
| Preflight | 07:03–07:04 | alle 8 ok, samen $0,0012 |
| Rookproef | 07:04–07:25 | qwen r1 `limiet`, sonnet r1 `beoordeeld` met GO: rookproef stop |
| Extra rookproef (JP) | 09:00–09:04 | sonnet r2 `beoordeeld` met GO, sol r1 `beoordeeld` met NO-GO en F1 major |
| De 24 runs | 09:05–13:05 | 24/24 resultaten, 0 benchfouten, `skipped.json` leeg |

De runs draaiden tegen de productie-release op max2, via LiteLLM en OpenRouter. Het budget was $10 (`min(10, tegoed − 2)`, met een tegoed van $35,96). Het grootboek komt uit op $2,7606. JP vergeleek het verbruik op het OpenRouter-dashboard met het grootboek: het valt binnen de marge. JP heeft het key-bestand na de runs verwijderd.

### Afwijkingen van het plan

- **Rookproef: stop, en JP besliste.** De controle sonnet gaf in de rookproef twee keer GO. Hij vond de F1-kern wel, maar noemde die MINOR. JP liet daarop beide controles nog één keer draaien, met als regel: door zodra minstens één controlerun NO-GO geeft met F1 major. Sol r1 haalde dat. Op JP's go zijn daarna de 24 runs gestart. De rookruns tellen niet mee in het oordeel.
- **De output-limiet van de case.** De case heeft `maxOutputTokens` 64 000 voor de hele run. Zes runs liepen daarop vast (`limiet`, runStatus `budget_exceeded`): qwen r1, deepseek-v4-flash r1–r3 en deepseek-v4-pro r2–r3. In elk van die runs ging ~63 000 van de 64 000 output-tokens naar reasoning, na 7–10 turns en zonder toolfouten. Twee keer koos JP ervoor de run te laten doorlopen. De limieten van de case zijn niet veranderd. Deze modellen vallen dus af op hun tokenbudget bij reasoning-effort medium of high, niet op de inhoud van een review.
- **Scoren.** Claude scoorde de bladen blind, zonder `sheets-key.json`.
  - In de eerste rookproef was alleen sonnet beoordeeld. Dat ene blad was dus in de praktijk niet blind.
  - Er was één extra-key, `x-route-c-retry-temp-path` (glm r1). JP verklaarde die ongeldig: in route C valt het enige EEXIST-punt vóór de record-insert, dus het beschreven temp_path-scenario kan niet ontstaan.
  - De grens tussen F1 en M1 volgt de rubric, zoals JP die op 2026-10-21 bevestigde.

### Wat het oordeel betekent

- **De bench is geldig.** De harness-controle gpt-6.1-sol-or is kandidaat (3/3). Hij vond F1 en F2 elke run als MAJOR, voor ~$0,06 per run, tegen ≈ $0,10 voor Codex in productie.
- **claude-sonnet-5.5-or valt onder de harness af (1/3).** Het is hetzelfde model als de productie-reviewer in Claude Code, en die noemde F1 MAJOR. In de 3 runs vond sonnet de kern twee keer: één keer als MAJOR (de run die voldeed) en één keer als MINOR. In de rookproef vond hij hem 2 van de 2 keer, beide keren als MINOR. Mogelijke oorzaken, niet onderzocht: de systeemprompt van Claude Code ontbreekt, de aanpassingen A1–A6, of toeval.
- **gpt-6-luna-or is kandidaat (3/3).** Elke run gaf NO-GO met F1 als MAJOR, voor ~$0,003 en ~30 s per run, in 4 turns, waarvan één `read_file` van het hele document. F2 vond luna in geen enkele run.
- **Geen van de vijf open modellen is kandidaat.**
  - qwen3.8-or-128k, deepseek-v4-flash en deepseek-v4-pro liepen vooral vast op de output-limiet. Wat ze wel afmaakten, eindigde op GO, zonder F1.
  - glm-5.3 en minimax-m3 draaiden alle drie de runs volledig uit. glm zag de F1-kern in één run, als MINOR; minimax zag hem in geen enkele run. Ze gaven overwegend GO.
- **Vervolg (JP beslist):**
  - een eigen idee voor een productie-runner voor `QUEUE_REVIEW`, met gpt-6-luna-or als kandidaat. Eerst met een tweede case: een plan-review of een review met code, want deze bench dekt één case en alleen een document;
  - apart: de open modellen opnieuw, met een hogere `maxOutputTokens` of een lagere reasoning-effort;
  - de severity-kalibratie van sonnet onder de harness.

## Grenzen en vervolg

De bench dekt één case en alleen een document: geen shell, git of code lezen. De runs zijn blind met de hand gescoord, volgens de rubric van de case; JP besliste één keer per extra-key. Er is geen judge-model.

Kandidaat: gpt-6-luna-or. Een kandidaat is een reden voor een eigen vervolgidee (een productie-runner voor QUEUE_REVIEW); of dat idee er komt, beslist JP.
