# Promptverfijner: qwen3.8-27b lokaal op Q8, met docs (M6, 2026-10-01)

Sprint S-2026-10-01-1 (IDEA-229), PBI-7, Taak 2–4 en 7. Spec `docs/specs/2026-10-01-local-precision-refiner-design.md` en plan `docs/plans/M6-local-precision-refiner.md` in agent-harness (beide revisie 4). Ruwe gegevens in `refiner-precisie-2026-10-01/`.

## Kort

- **Oordeel: Q8 gezakt.** `qwen3.8:27b-q8_0` rondt 12 van de 15 gesprekken af (80%). De zeef vraagt 90%, dus 14. Dat is twee onder de grens. Het model zakt dus niet alleen op een regel die één eronder ligt, en geen `timed_out` bepaalt de uitkomst. Daarom is het oordeel gezakt en niet onbeslist (spec §1).
- **Betekenis voor de aankoop (spec §1):** Q8 voldoet in deze opzet niet. M6 toont geen lokale route met docs op het niveau van gehost. Of de precisie meespeelt, blijft open. Er komt geen Q4-run, en M6 eindigt.
- **Waar het misgaat:** in het afronden, niet in de antwoorden. De 12 afgeronde gesprekken halen elke check. De drie andere lopen vast op de docs-tools:
  - D01/1 en D01/3 gebruiken alle acht modelbeurten aan zoeken;
  - D04/1 stopt na drie toolfouten (`maxToolErrors` 2).
  - Telkens vraagt het model een kop of document op dat niet bestaat.
- **Tegen M5:** `gsq-lokaal` (3-bit, 11 GB) rondde 13/15 af en gehost (`qwen/qwen3.8-27b`) 14/15. Q8 rondt dus niet beter af dan gsq. Op D2 haalt Q8 10/12, net als gehost en één meer dan gsq.
- **Vlaggen:** geen. D5 geldt alleen voor D02 en is drie keer `pass`. Er was geen reviewpagina nodig.
- **Ter informatie:** op max2 haalt Q8 2,90 tok/s, met 57% van het model op de CPU. De run duurde 5 u 52 min.

## Opzet

- **Route:** `run.py --backend harness` draaide op max2 zelf, in tmux, tegen Ollama 0.34.4 op `127.0.0.1:11434`.
  - Harness: `node /home/janpeter/Development/agent-harness/dist/cli.js` op main `15c1e26`, met een schone checkout. `harness run`, `probe` en `doc-server` zijn daar gelijk aan de M5-build `aaae1a0`.
  - Bank: branch `feat/m6-precisie`, commit `57eb4a4`, in de worktree `~/Development/max2-m6` op max2.
- **Model:** `qwen3.8:27b-q8_0` (label `qwen3.8-q8-lokaal`). Dit is de officiële tag met ID `8f5fb6b71ea0`, 29 GB op schijf.
- **Ongewijzigd uit M5:**
  - prompt v3 met het docs-addendum;
  - de bevroren docset `refiner/docset/`;
  - de cases D01–D05 met seeds 1, 2 en 3, dus 15 gesprekken;
  - de checks en de zeef van `score.py`.
- **Instellingen:**
  - Temperature 0,7, en de seed is de herhaling.
  - Met docs blijft de reasoning op de standaard (thinking aan), net als bij gsq in M5.
  - `maxOutputTokens` is 16384. `maxWallSeconds` is 8520 per beurt; die grens komt uit de rooktest, in M5 was hij 960. Een tweede poging verdubbelt beide.
  - `maxTurns` 8, `maxToolErrors` 2 en `contextTokens` 65536 liggen vast in `run.py`.

## Met docs (15 gesprekken per model)

De rijen van `gsq-lokaal` en `qwen3.8-openrouter` komen ongewijzigd uit M5: `refiner-vergelijking-2026-10-01.md`, tabel "Met docs".

| Meting | Model | Backend | Probe | A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 | D1 | D2 | D3 | D4 | D5 | D6 | Afgerond | Eerste poging | Mediaan s | Tokens in | Tokens uit | Kosten $ (alle pogingen) | Aanbieders | Zeef |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M6 | qwen3.8-q8-lokaal | harness | reliable | 13/15 | 15/15 | 12/15 | 12/15 | - | 12/15 | 12/15 | - | 15/15 | 10/12 | 15/15 | 3/3* | 3/3 | 12/15 | 12/15 | 12 | 1031 | 1048425 | 56214 | - | - | gezakt |
| M5 | gsq-lokaal | harness | reliable | 14/15 | 15/15 | 14/15 | 14/15 | - | 14/15 | 13/15 | - | 15/15 | 9/12 | 15/15 | 3/3* | 3/3 | 13/15 | 13/15 | 13 | 79 | 1001690 | 53973 | - | - | gezakt |
| M5 | qwen3.8-openrouter | harness | reliable | 14/15 | 15/15 | 14/15 | 14/15 | - | 14/15 | 14/15 | - | 15/15 | 10/12 | 15/15 | 3/3* | 3/3 | 14/15 | 14/15 | 13 | 90 | 1129403 | 58866 | 0.3056 | Reka, Wafer | door |

`*` = minder dan vijf gesprekken in de noemer: getoond, telt niet mee in de zeef. Tokens: van de poging die telt; kosten: van alle pogingen.

De mediane tijd is niet vergelijkbaar. In M5 draaide gsq geheel op de GPU van max2. Q8 draait voor 57% op de CPU, en gehost bij een wisselende aanbieder.

**Zeef zoals `score.py` hem rekent** (`q8-docs.score.txt`):

- `qwen3.8-q8-lokaal`: **gezakt**. Afgerond: 12 van 15 (80.0%), minder dan 90%. Niet afgerond: 3× `error` (D01/1, D01/3, D04/1).

In M5 was de definitieve zeef met docs: `gsq-lokaal` gezakt (afgerond 13 van 15, D2 9 van 12) en `qwen3.8-openrouter` door.

## Vlaggen

Er zijn geen nieuwe vlaggen. D5 geldt alleen voor D02 en is in alle drie de gesprekken `pass`. A5 telt met docs niet: die regel heet daar D5. Er is dus geen reviewpagina en geen `vlaggen-besluiten.json` (plan Taak 4). De zeef van `score.py` is ook de definitieve zeef.

## Grens per regel (spec §1)

Een regel ligt _op de grens_ als zijn telling de kleinste is die slaagt (`meets()`: `n*100 >= totaal*procent`). Hij ligt _één eronder_ als één gesprek meer hem laat slagen.

| Regel | Teller / noemer | Kleinste die slaagt | Eén eronder | Stand |
|---|---|---|---|---|
| Afgerond (90%) | 12/15 | 14 | 13 | **zakt, twee onder de grens** |
| A1 | 13/15 | 12 | 11 | slaagt, één boven de grens |
| A2 | 15/15 | 12 | 11 | slaagt |
| A3 | 12/15 | 12 | 11 | slaagt, _op de grens_ |
| A4 | 12/15 | 12 | 11 | slaagt, _op de grens_ |
| A6 | 12/15 | 12 | 11 | slaagt, _op de grens_ |
| A7 | 12/15 | 12 | 11 | slaagt, _op de grens_ |
| D1 | 15/15 | 12 | 11 | slaagt |
| D2 | 10/12 | 10 | 9 | slaagt, _op de grens_ |
| D3 | 15/15 | 12 | 11 | slaagt |
| D4 | 3/3 | - | - | telt niet mee: minder dan vijf gesprekken |
| D5 | 3/3 | - | - | vlagcheck, zonder grens: geen vlag |
| D6 | 12/15 | - | - | telt niet mee (spec 5.8): volgt uit afgerond |

A5 en A8 gelden voor geen enkele docs-case.

**Oordeel: gezakt.** Q8 zakt op één regel, afgerond, en die ligt twee onder de grens. Spec §1 noemt een gezakt model alleen onbeslist als het uitsluitend zakt op regels één eronder, of als een `timed_out` de uitkomst bepaalt. Geen van beide geldt.

De vijf regels op de grens (A3, A4, A6, A7, D2) veranderen het oordeel niet. Een regel op de grens maakt alleen een model dat door is onbeslist. Ze liggen op de grens door dezelfde drie gesprekken: een gesprek dat niet afrondt, faalt ook die checks (`q8-docs/summary.csv`).

## Niet afgeronde gesprekken en tweede pogingen

- `qwen3.8-q8-lokaal`, D01/1 (`21f5ea`): poging 1 `error` (beurt 1 `budget_exceeded`), daarna poging 2 `error` (beurt 1 `budget_exceeded`).
- `qwen3.8-q8-lokaal`, D01/3 (`beec98`): poging 1 `error` (beurt 1 `budget_exceeded`), daarna poging 2 `error` (beurt 1 `budget_exceeded`).
- `qwen3.8-q8-lokaal`, D04/1 (`b46f20`): poging 1 `error` (beurt 2 `failed`, `TOO_MANY_TOOL_ERRORS`), daarna poging 2 `error` (beurt 2 `failed`, `TOO_MANY_TOOL_ERRORS`).

**Hoe ze vastliepen:**
- **D01:** `budget_exceeded` kwam van `maxTurns`: acht modelaanroepen, steeds opnieuw zoeken (`model_turns` 8). Twee aanroepen faalden:
  - D01/1: de kop `check-run-logs` in `specs/2026-09-28-harness-run-logging-design`, en het document `plans/M4-harness-run-logging`, dat niet in de docset staat;
  - D01/3: de koppen `check-run-logs` en `9`.
- **D04/1:** drie toolfouten op koppen die niet bestaan: twee keer `Joblifecycle` en één keer `Configuratie`.

**Tweede pogingen:** die waren gelijk aan de eerste, met dezelfde tool-aanroepen en dezelfde tokens. De verdubbelde grenzen hielpen dus niet: `maxTurns` en `maxToolErrors` worden in een tweede poging niet verdubbeld.

In M5 zakte gsq op dezelfde soorten fouten: D01/3 met `budget_exceeded` en D02/1 met `TOO_MANY_TOOL_ERRORS`.

**`timed_out`:** geen enkele beurt. De statussen van de beurten zijn `completed`, `budget_exceeded` en `failed`, dus de timeout-tegenproef (spec §4) is niet nodig.

## Rooktest en metingen (ter informatie)

- **Rooktest** `rooktest-q8`: D03 met seed 1 en `--max-wall-seconds 3600`.
  - De map is geldig, en de probe is `reliable`.
  - Het gesprek eindigde `final` na 2 beurten, in 1.344 s.
- **Snelheid:** 3.895 uitvoertokens in 1.343,5 s, dus 2,90 tok/s. Daaruit volgt `W` = ⌈16384 / 2,90 × 1,5⌉, op de minuut: 8.520 s.
- **Duur:** geschat op max(60.556 / 2,90; 15 × 1.344) = 20.888 s (5 u 48 min). De run duurde werkelijk 21.092 s: van 20:51:37 tot 02:43:09, 5 u 52 min.
- **Grootte en verdeling,** uit `ollama ps` na het gesprek: 32 GB, verdeeld 57% CPU en 43% GPU, context 65.536.
  - `size_vram` was 13,8 GB.
  - Volgens het Ollama-log stonden 28 van de 66 lagen op de GPU: CUDA0 11.311 MiB, CPU_Mapped 15.950 MiB.
  - De GPU van max2 is een RTX 5070 Ti met 16 GB.
- **Geheugen** (max2 heeft 30 GB RAM): MemAvailable daalde van 27,9 naar 23,4 GB (27.928.492 naar 23.412.184 kB).
  - Swap tijdens het rooktestgesprek: `pswpin` +375.282 pagina's (1,43 GiB), `pswpout` +779.605 pagina's (2,97 GiB).
  - Swappen verandert de antwoorden niet, alleen de snelheid (spec §6).
- **Modelfile tegen gsq** (`q8-model.txt`):
  - RENDERER `qwen3.8` en PARSER `qwen3.5` zijn gelijk.
  - De PARAMETERs zijn gelijk (`top_k` 20, `top_p` 0.95, `min_p` 0, `presence_penalty` 0, `repeat_penalty` 1, `temperature` 1); alleen de volgorde verschilt. Geen enkel PARAMETER wijkt af.
  - Wat overblijft is het verschil uit spec §1: de template van Ollama en de beeldprojector, tegenover de afgeleide Modelfile van gsq.
- **Herhaalbaarheid:**
  - Binnen de run gaven de tweede pogingen dezelfde tokens als de eerste.
  - De rooktest en hetzelfde gesprek in de run (D03/1) verschilden wel: beurt 1 had 2.173 tegen 1.146 uitvoertokens.
  - De herhaalbaarheid uit spec §6 gold hier dus alleen binnen één run. Het oordeel komt alleen uit de run.

## Conclusie (spec §1)

| Uitslag | Vervolg | Betekenis voor de aankoop |
|---|---|---|
| Q8 gezakt | Geen Q4; M6 eindigt. | Q8 voldoet in deze opzet niet: M6 toont geen lokale route met docs op het niveau van gehost. Of de precisie meespeelt, blijft open. |

M6 levert dus geen kandidaat voor een proef op een Mac.

Samen met M5 ziet het beeld er zo uit:
- Zonder docs haalt `gsq-lokaal` (3-bit, 11 GB) de zeef al, en die draait op max2.
- Met docs haalt geen lokaal model de zeef, ook Q8 niet.

Voor de promptverfijner laat deze meting dus geen meerwaarde zien van een Mac Mini of Mac Studio met meer geheugen. Snelheid op een Mac is niet gemeten (spec §1, niet-doelen).

## Vensters en dienststand (spec §5, criterium 5)

| Venster | Door JP gegeven | Open en dicht | Dienststand vooraf | Dienststand achteraf |
|---|---|---|---|---|
| `rooktest-q8` | 2026-10-01 20:09–22:00 | 20:18:07 – 20:43:29 | worker `active`; `open-webui` en `dsh` draaien; `tei-gpu` draait niet | gelijk |
| `q8-docs` | 2026-10-01 20:49 – 2026-10-02 08:00 | 20:51:29 – 02:43:23 | worker `active`; `open-webui` en `dsh` draaien; `tei-gpu` draait niet | gelijk |

- **Stoppen:** beide keren de M4-procedure (`m4-stop.sh`), met als uitkomst `schone stop`. Daarna `docker stop open-webui dsh`; `tei-gpu` draaide niet.
- **Herstellen:** `docker start open-webui dsh` en `systemctl start agent-harness-worker`; daarna was de worker `active`.
- **Na het herstel:** de dienstregels zijn gelijk aan vooraf. Q8 bleef nog vijf minuten geladen, tot de keep-alive van Ollama afliep.
- **Bestanden:** `dienststand-<venster>-voor.txt` en `-na.txt`.
- **Afgebroken of ongeldige mappen:** geen. Het vangnet voor het nachtvenster (`q8-docs-vangnet.sh`) brak alleen af en herstelde alleen vanaf 07:40. Het deed niets, want de run eindigde om 02:43, en is na het herstel weggehaald.

## Commits en versies

- Bank (max2-repo): `57eb4a4` op `feat/m6-precisie`, in de worktree `~/Development/max2-m6` op max2 (`voorbereiding.txt`).
- Harness: agent-harness `15c1e26`, schone checkout.
- Ollama: `ollama version is 0.34.4`.

## Bestanden in `refiner-precisie-2026-10-01/`

- **Run-mappen** `rooktest-q8/` en `q8-docs/`, met dezelfde bestanden die M5 bewaarde: `raw.jsonl`, `summary.csv`, `blind-key.json`, `transcripts/` en `harness/probe-*/probe.json`.
- **Scripts** (`*.sh`): de rooktest, de run, het vangnet, de dienststand-opname en de M4-stop.
- **Sessie-ID's** (`*.sid`).
- **Logs** (`*.log`). `q8-pull.kort.log` is het download-log zonder de tussenstanden van de voortgangsbalk.
- **Metingen, snelheid, dienststand en score-uitvoer** (`*.txt`), en `q8-docs-api-ps-na.json`.

## Acceptatiecriteria (spec §5)

1. **Gehaald.** `qwen3.8:27b-q8_0` draaide de docs-variant met 15 gesprekken.
   - Probe `reliable`.
   - `summary.csv` met de A- en D-checks.
   - Dezelfde route en instellingen als M5, met `maxWallSeconds` 8520 uit de rooktest.
   - De run is geldig: het log eindigt op `exit=0`, en "Geldige run" geeft `geldig` voor n = 15.
2. **Gehaald.** Q8 is gezakt. Dit rapport zegt dat Q8 in deze opzet niet voldoet, en er is geen Q4-run.
3. **Gehaald.**
   - De nieuwe rij staat naast gsq en gehost uit M5.
   - Er zijn geen nieuwe vlaggen.
   - De regels op of onder de grens staan erbij, met teller en noemer.
   - Het oordeel en de conclusie volgen spec §1.
4. **Gehaald.** Er was geen `timed_out`; dat staat apart vermeld onder "Niet afgeronde gesprekken".
5. **Gehaald.** In beide vensters draaiden na de meting precies de diensten van vooraf.
6. **Gehaald.**
   - `python3 -m unittest llm-bench/refiner/test_refiner.py` is groen: 462 tests.
   - `check_key.py --env OPENROUTER_API_KEY` vond `with_key=0`, met exit 0, in `~/Development/m6-runs/refiner-precisie-2026-10-01` (375 bestanden) en in `refiner-precisie-2026-10-01/` (48 bestanden).
