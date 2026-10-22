# Review-bench 2026-10-22

Case `macsearch-idea263-spec-r5`. 6 van 9 verwachte runs beoordeeld (3 configuraties x 3 runs).

Geldigheid van de bench: in orde: minstens één harness-controle is kandidaat.

## Oordeel per model

| Model | Oordeel | Voldoet | Verdicts | F1 per run | F2 per run | Minors (gem.) | Extra's |
| --- | --- | --- | --- | --- | --- | --- | --- |
| deepseek-v4-flash-or | valt af | 0/3 | - / - / - | - / - / - | - / - / - | - | - |
| deepseek-v4-pro-or | valt af | 0/3 | GO / GO / NO-GO | nee / nee / nee | minor / nee / major | 0,3 | - |
| gpt-6.1-sol-or (controle) | kandidaat | 3/3 | NO-GO / NO-GO / NO-GO | major / major / major | major / major / major | 0,0 | - |

Oordeel: kandidaat is 3 van 3 runs die voldoen, twijfel 2 van 3, anders valt het model af; open zolang een extra geen beslissing heeft. Een run voldoet als het resultaat is aanvaard (beoordeeld), outcome succeeded is, het verdict NO-GO is, F1 als major is gevonden en geen extra ongeldig is verklaard. Een model dat nooit gedraaid heeft, valt af; waarom staat erbij.

## Eerste vergelijking: open modellen tegenover de harness-controles

Geldigheid van de bench: in orde: minstens één harness-controle is kandidaat.

| Groep | Model | Oordeel | Voldoet | F1 als major gevonden |
| --- | --- | --- | --- | --- |
| harness-controle | gpt-6.1-sol-or | kandidaat | 3/3 | 3/3 |
| open model | deepseek-v4-flash-or | valt af | 0/3 | 0/3 |
| open model | deepseek-v4-pro-or | valt af | 0/3 | 0/3 |

Controle niet in --models: claude-sonnet-5.5-or.

## Kosten, tokens, context en tijd

| Model | Kosten gem. | Kosten max. | Tokens in / uit (gem.) | Piek input / venster | Wandtijd (gem.) | Turns (gem.) | Toolfouten | Outcome per run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deepseek-v4-flash-or | $0,0392 | $0,0392 | - / - | - / 131072 | - | - | - | - / - / - |
| deepseek-v4-pro-or | $0,2722 | $0,3625 | 158540 / 128951 | 24570 / 131072 (19%) | 2578,0 s | 11,0 | 0 | succeeded / succeeded / succeeded |
| gpt-6.1-sol-or (controle) | $0,0625 | $0,0637 | 24907 / 3030 | 12392 / 131072 (9%) | 87,7 s | 4,0 | 0 | succeeded / succeeded / succeeded |

Kosten: alle runs met een bedrag (0 runs hebben er geen). De rest: runs met een modelstatus. De piek is `peakInputTokens` naast het venster van 131072.

## Per run

| Model | Run | Status | Outcome | Verdict | F1 | F2 | Minors | Voldoet | read_file sources/doc | waarvan met offset/limit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deepseek-v4-flash-or | 1 | benchfout | - | - | - | - | - | nee | 8 | 7 |
| deepseek-v4-pro-or | 1 | beoordeeld | succeeded | GO | nee | minor | - | nee | 7 | 6 |
| deepseek-v4-pro-or | 2 | beoordeeld | succeeded | GO | nee | nee | - | nee | 6 | 5 |
| deepseek-v4-pro-or | 3 | beoordeeld | succeeded | NO-GO | nee | major | M2 | nee | 9 | 8 |
| gpt-6.1-sol-or | 1 | beoordeeld | succeeded | NO-GO | major | major | - | ja | 2 | 2 |
| gpt-6.1-sol-or | 2 | beoordeeld | succeeded | NO-GO | major | major | - | ja | 2 | 2 |
| gpt-6.1-sol-or | 3 | beoordeeld | succeeded | NO-GO | major | major | - | ja | 2 | 2 |

## Runs zonder oordeel

| Model | Run | Reden |
| --- | --- | --- |
| deepseek-v4-flash-or | 1 | benchfout: MODEL_ERROR |
| deepseek-v4-flash-or | 2 | gestopt na tweede benchfout op deepseek-v4-flash-or |
| deepseek-v4-flash-or | 3 | gestopt na tweede benchfout op deepseek-v4-flash-or |

## Preflight

| Model | Preflight | Reden | Bedrag (grootboek) |
| --- | --- | --- | --- |
| deepseek-v4-flash-or | ok | - | $0,0000 |
| deepseek-v4-pro-or | ok | - | $0,0001 |
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

Totaal $1,1522 over 12 regels, 0 zonder bedrag (die tellen als 0, het totaal is een ondergrens).

| Id | Soort | Configuratie | Run | Case | Kosten |
| --- | --- | --- | --- | --- | --- |
| preflight-deepseek-v4-flash-or-20261021T233412Z | preflight | deepseek-v4-flash-or | - | - | $0,0000 |
| preflight-deepseek-v4-pro-or-20261021T233414Z | preflight | deepseek-v4-pro-or | - | - | $0,0001 |
| preflight-gpt-6.1-sol-or-20261021T233417Z | preflight | gpt-6.1-sol-or | - | - | $0,0001 |
| macsearch-idea263-spec-r5-out256k-deepseek-v4-flash-or-914607f6 | run | deepseek-v4-flash-or | 1 | macsearch-idea263-spec-r5-out256k | $0,0398 |
| macsearch-idea263-spec-r5-out256k-deepseek-v4-flash-or-2aa18e81 | run | deepseek-v4-flash-or | 1 | macsearch-idea263-spec-r5-out256k | $0,0392 |
| macsearch-idea263-spec-r5-out256k-deepseek-v4-pro-or-5833863e | run | deepseek-v4-pro-or | 1 | macsearch-idea263-spec-r5-out256k | $0,0689 |
| macsearch-idea263-spec-r5-out256k-deepseek-v4-pro-or-ca215f6e | run | deepseek-v4-pro-or | 1 | macsearch-idea263-spec-r5-out256k | $0,2403 |
| macsearch-idea263-spec-r5-out256k-gpt-6.1-sol-or-dc142fa2 | run | gpt-6.1-sol-or | 1 | macsearch-idea263-spec-r5-out256k | $0,0637 |
| macsearch-idea263-spec-r5-out256k-deepseek-v4-pro-or-069c183e | run | deepseek-v4-pro-or | 2 | macsearch-idea263-spec-r5-out256k | $0,2138 |
| macsearch-idea263-spec-r5-out256k-gpt-6.1-sol-or-d4d62050 | run | gpt-6.1-sol-or | 2 | macsearch-idea263-spec-r5-out256k | $0,0616 |
| macsearch-idea263-spec-r5-out256k-deepseek-v4-pro-or-44688a42 | run | deepseek-v4-pro-or | 3 | macsearch-idea263-spec-r5-out256k | $0,3625 |
| macsearch-idea263-spec-r5-out256k-gpt-6.1-sol-or-40518ecb | run | gpt-6.1-sol-or | 3 | macsearch-idea263-spec-r5-out256k | $0,0624 |

## Venster, probes en afwijkingen

### Venster (2026-10-21/22, UTC)

Dit is het 256k-venster van M9 (IDEA-272, plan `docs/plans/M9-review-bench-output-limit.md` rev 3 in agent-harness). Het is het laatste venster van M9. De case is de variant `macsearch-idea263-spec-r5-out256k`, met limieten `maxOutputTokens` 256 000, `maxWallSeconds` 7200, `maxTurns` 30 en `maxToolErrors` 8. Naast de limieten is ook het id anders; de bytes die het model ziet, zijn gelijk aan die van de M8-case.

Volgens de regel van stap 2 (plan §4.3) gingen deepseek-v4-flash-or en deepseek-v4-pro-or door: ze vielen bij 128k af en hadden minstens één `limiet`-run met oorzaak budget. qwen3.8-or-128k stopte na 128k. gpt-6.1-sol-or draaide mee als controle.

| Stap | Tijd | Uitkomst |
| --- | --- | --- |
| Releasecontrole vóór de preflight | 21 okt 23:34:12 | `current` → `releases/a68a74627660f2afd355e2f11d54be582466db7a`, link-mtime 2026-10-21 06:50:18 UTC |
| Preflight | 23:34:12–23:34:18 | alle 3 ok, `max_tokens` 127874, samen $0,0002 |
| Eerste aanroep (flash, pro, sol) | 23:34:26 – 22 okt 02:02:40 | stop met exit 3: tweede benchfout op deepseek-v4-flash-or r1 |
| Releasecontrole bij hervatting | 04:38:19 | ongewijzigd: readlink en link-mtime gelijk |
| Tweede aanroep (pro, sol), op JP's besluit | 04:38:19–07:08:41 | 6/6 resultaten, 1 benchfout (herhaald), exit 0 |
| Releasecontrole na de laatste run | 07:09:06 | ongewijzigd: readlink en link-mtime gelijk |

Het tegoed was $32,04. Het verschil met het tegoed van vóór het 128k-venster ($33,20 − $32,04 = $1,16) klopte met het grootboek van dat venster ($1,1607). Het budget was $10 (`min(10, 32,04 − 2)`). Het grootboek van dit venster komt uit op $1,1522 (12 regels: 3 preflights en 9 runs).

### Controles

- **Preflight (§4.2).** De preflight stuurde `max_tokens` 127874: `min(maxOutputTokens 256 000, contextTokens 131 072 − 3198)`. Bij 256k is dus niet het budget, maar de context het plafond per request. Het budget van 256 000 geldt voor de hele run.
- **Turn 1 (§4.2).** In alle 9 pogingen vroeg turn 1 `maxTokens` 127874. Elke configuratie is gecontroleerd vóór haar tweede run.
- **Release (§4.5).** Readlink en link-mtime waren vóór de preflight, bij de hervatting en na de laatste run gelijk.

### Oorzaak per `limiet`-run (§4.3)

Er is geen `limiet`-run in dit venster. De drie runs van pro gebruikten 113 325, 99 812 en 173 716 output-tokens, ruim onder het budget; r3 ging wel ruim over het oude budget van 128 000.

### Afwijkingen van het plan

- **De driver stopte na een tweede benchfout (exit 3).** deepseek-v4-flash-or r1 faalde twee keer op dezelfde manier: OpenRouter gaf een antwoord dat geen JSON was ("Unable to get json response"). Beide pogingen faalden bij turn 16, na ongeveer 168 000 output-tokens en 74 minuten. De mislukte requests vroegen `maxTokens` 87408 en 88213, met een input van 24 000 à 26 000 tokens, en faalden na 163 en 258 s. Dat is geen contextgrens en geen limietoorzaak (§4.2).
- **JP besliste: door met pro en sol.** Een nieuwe aanroep met flash zou direct weer stoppen op zijn r1. Op JP's besluit van 2026-10-22 draaide de tweede aanroep alleen deepseek-v4-pro-or en gpt-6.1-sol-or. deepseek-v4-flash-or r2 en r3 zijn niet gedraaid ("gestopt na tweede benchfout op deepseek-v4-flash-or"). Flash valt bij 256k af volgens de regel (0/3), maar zonder één beoordeelde run: dat is een fout van de provider, geen resultaat van het model.
- **Nog een benchfout, herhaald.** deepseek-v4-pro-or r1 faalde de eerste keer na 17 minuten met dezelfde fout (turn 6, `maxTokens` 116503, na 409 s). De herhaling werd beoordeeld.
- **De provider.** Alle vier de benchfouten van M9, ook die van pro bij 128k, kwamen van gesprekken die OpenRouter naar de provider StreamLake stuurde. Flash liep bij 128k via Baidu, zonder fouten. De geslaagde runs van pro bij 256k liepen ook via StreamLake. De oorzaak bij StreamLake of OpenRouter is niet onderzocht; de provider is niet vastgezet, want dat zou een tweede variabele naast de output-limiet zijn.
- **De kop van het rapport.** De kop noemt de basiscase `macsearch-idea263-spec-r5`, niet de variant. JP aanvaardde dat (plan §4.4). De datum van het rapport is 2026-10-22: het venster begon op 21 oktober om 23:34 en liep verder door op 22 oktober.
- **Alleen sol als controle.** claude-sonnet-5.5-or staat bewust niet in `--models` (plan). Daarom meldt het rapport "Controle niet in --models".
- **Scoren.** Claude scoorde de 6 bladen blind, zonder `sheets-key.json`, met de rubric van M8. Er was geen extra-key, dus `decisions.json` is leeg.

### Oordeel per venster

| Model | 64k (M8) | 128k | 256k |
| --- | --- | --- | --- |
| deepseek-v4-flash-or | valt af (0/3): 3× limiet (budget) | valt af (0/3): 2× GO zonder F1, 1× limiet (budget) | valt af (0/3): geen beoordeelde run; r1 2× benchfout (StreamLake), r2 en r3 niet gedraaid |
| deepseek-v4-pro-or | valt af (0/3): 1× GO zonder F1, 2× limiet | valt af (0/3): 2× limiet (budget), 1× ongeldige JSON | valt af (0/3): GO, GO, NO-GO; F1 in geen enkele run |
| qwen3.8-or-128k | valt af (0/3): 1× limiet, 2× GO zonder F1 | valt af (0/3): 3× GO, F1 één keer als MINOR | niet gedraaid (geen `limiet`-run bij 128k) |
| gpt-6.1-sol-or (controle) | kandidaat (3/3) | kandidaat (3/3) | kandidaat (3/3) |

### Wat het oordeel betekent

- **De bench is in elk venster geldig.** De controle gpt-6.1-sol-or vond F1 en F2 in alle 6 runs van M9 als MAJOR, net als in M8.
- **Meer output-budget maakt geen van de drie open modellen kandidaat.**
  - Met meer ruimte maakten de modellen hun runs wel vaker af: bij 64k werd 3 van de 9 runs beoordeeld, bij 128k 5 van de 9, en bij 256k pro 3 van de 3.
  - Geen afgemaakte run vond F1 als MAJOR. qwen zag de F1-kern één keer als MINOR (128k). Pro gaf bij 256k één keer NO-GO, op F2.
  - Het tekort zit dus niet in het budget, maar in wat de modellen vinden.
- **Het output-budget verklaart het oordeel van M8 niet.** Het vervolgidee "de open modellen opnieuw met ruimere output-limiet" is hiermee afgerond. Een lagere reasoning-effort is niet onderzocht.
- **StreamLake.** Lange generaties via StreamLake gaven vier keer een lege respons. Voor een productierunner met deepseek-modellen via OpenRouter is dat een risico dat eerst onderzocht moet worden.

## Grenzen en vervolg

De bench dekt één case en alleen een document: geen shell, git of code lezen. De runs zijn blind met de hand gescoord, volgens de rubric van de case; JP besliste één keer per extra-key. Er is geen judge-model.

Geen enkel model buiten de controles is kandidaat; de uitkomst hierboven is de volledige uitslag.
