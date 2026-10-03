# llm-bench — lokale LLM's op de RTX 5070 Ti

Herhaalbare metingen van Ollama-modellen op max2 (16 GB VRAM, 30 GB RAM).
Plan en besluiten: Scrum4Me max2 → PBI-1, ProductDoc `PLANS/qwen3x-ollama-coding-benchmark`.

## Voorwaarden

- Ollama draait als systemd-service op `127.0.0.1:11434` (nooit breder binden: geen auth).
  Instellingen in `/etc/systemd/system/ollama.service.d/override.conf`: flash attention aan,
  KV-cache `q8_0`, één model tegelijk, `NUM_PARALLEL=1`, standaardcontext `OLLAMA_CONTEXT_LENGTH=65536`
  (stand 2026-09-29; de scripts zetten `num_ctx` zelf).
- Voor representatieve cijfers geen andere GPU-last. TEI (`tei-gpu`) houdt ~2,5 GB VRAM vast;
  tijdelijk stoppen met `docker compose -f /srv/apps/tei/docker-compose.yml stop`, daarna `start`.
- Geen andere Ollama-clients tijdens een meting. Open WebUI (`open-webui`) en DeepSeek-Harness (`dsh`)
  gebruiken dezelfde Ollama, die één model tegelijk laadt: één request van hen wisselt het gemeten model.
  Stop ze met `docker stop open-webui dsh` en start ze daarna weer met `docker start open-webui dsh`.

## Modellen

De `hf.co/`-pull van een GGUF levert geen chat-template. Maak voor zulke modellen eerst een afgeleid model uit `modelfiles/` (bijv. `ollama create qwen3.8-gsq-rco:27b-iq3_s -f modelfiles/qwen3.8-gsq-rco-iq3_s.Modelfile`) en controleer met `ollama show --modelfile` dat `RENDERER`/`PARSER` gelijk zijn aan de officiële tag.

## Snelheid en geheugen

```bash
./speed.py --models qwen3.5:9b qwen3.8:27b --ctx 8192 32768 --reps 3
```

Per model × context: één warm-up (laadtijd, GPU/CPU-split uit `/api/ps`), daarna per prompt
`--reps` runs; de samenvatting geeft de mediaan (bij `--reps 2` is dat het gemiddelde; gebruik er
minstens 3). Elke run krijgt een unieke regel, zodat Ollama's prompt-prefixcache de prompt niet
hergebruikt. Die regel staat wel ná de chat-template, dus dat korte stuk komt uit de cache en telt mee
in `prompt_tps` (naar schatting: lange prompt <1%, korte prompt enkele procenten, bij qwen2.5-coder met
zijn standaard-systeemprompt ~20%). Thinking staat uit, tenzij `--think`.

| Kolom | Betekenis |
|---|---|
| `gpu_pct` | deel van het geladen model dat in VRAM staat (100 = volledig op de GPU); `/api/ps` telt een vision-projector (~0,9 GB) niet mee |
| `prompt_tps` | prompt-verwerking, tokens/s (Ollama `prompt_eval_*`) |
| `gen_tps` | generatie, tokens/s (Ollama `eval_*`) |
| `ttft_s` | tijd tot het eerste token, gemeten op de stream (met `--think`: het eerste redeneertoken) |
| `peak_vram_mib` | piek `nvidia-smi memory.used` tijdens het model × context-blok (hele GPU) |
| `min_mem_available_mib` | laagste `MemAvailable` tijdens dat blok; modelgewichten die via mmap in het RAM staan tellen als beschikbaar |

Prompts staan in `prompts/`: `short.txt` (klein codeerverzoek, ~100–120 tokens) en
`long_code.py.txt` + `long_question.txt` (~4,9k tokens, ~4,6k bij qwen2.5-coder en qwen3-coder; het begin
van CPython's `argparse.py`, PSF-licentie).

Uitvoer: `results/speed-<UTC-timestamp>/raw.jsonl` (elke run) en `summary.csv`.

Resultaten per datum: `results/fit-<datum>.md` en `results/speed-<datum>.md`.

## Codeerkwaliteit

Alle code die een model schrijft wordt uitgevoerd in Docker, nooit op de host.

**EvalPlus** (HumanEval+ 164, MBPP+ 378 opgaven), `evalplus/`:

```bash
evalplus/run.sh /var/tmp/llm-bench/evalplus-<datum> qwen3.5:9b qwen3.8-gsq-rco:27b-iq3_s
```

Genereren via Ollama's `/api/chat` (`think:false`, temperature 0, seed 42, num_ctx 8192,
num_predict 1024) in een container met `--network host` — alleen HTTP, er wordt niets uitgevoerd.
Van de sampling-instellingen worden alleen temperature en seed overschreven: penalty-defaults van een tag (bijv. `presence_penalty`)
blijven actief. `evalplus.sanitize` + `evalplus.evaluate` voeren de code uit in een container met
`--network none`. Datasets zitten in het image (`llm-bench-evalplus:0.3.1`). De instructietekst is die van
EvalPlus' HF/vLLM-backends, maar zonder hun response-prefill (Ollama chat); de cijfers zijn daarom niet
één-op-één vergelijkbaar met gepubliceerde EvalPlus-scores. `sanitize` haalt de code uit het markdown-blok.

**Aider polyglot** en de **eigen taken**, `aider/`:

```bash
aider/network.sh up          # intern Docker-netwerk: alleen Ollama bereikbaar
aider/run.sh polyglot-subset30 qwen3.6:35b-a3b-coding
aider/run.sh own-tasks qwen3.6:35b-a3b-coding
aider/network.sh down        # socat, iptables-regels en netwerk weer weg
```

Benodigd:

- een checkout van Aider-AI/aider op commit `5dc9490` in `/var/tmp/llm-bench/aider` en het image daaruit
  (`docker build -f benchmark/Dockerfile -t aider-benchmark:5dc9490 .`);
- `aider/Dockerfile.warm` erbovenop, getagd als `aider-benchmark:5dc9490-warm` (de naam die `run.sh`
  gebruikt). De build-context moet een map `java/` bevatten met `exercises/practice/` uit
  Aider-AI/polyglot-benchmark; Gradle en JUnit komen dan in de cache, zodat Java-tests zonder internet draaien;
- de opgaven in `$RUNS` (standaard `/var/tmp/llm-bench/aider-runs`): `$RUNS/polyglot-subset30/<taal>/exercises/practice/<opgave>`
  voor elke regel uit `aider/subset30.txt`, en een kopie van `own-tasks/` als `$RUNS/own-tasks`.

De polyglot-subset (`aider/subset30.txt`) is vast en komt uit Aider-AI/polyglot-benchmark `7e0611e`:
één gedeelde `random.Random(42)`, de talen in gesorteerde volgorde, en per taal
`rng.sample(sorted(opgaven), 5)`. Thinking uit, num_ctx 32768, edit-format `diff`, 2 pogingen.

Draai `aider/network.sh check` vóór elke run: `run.sh` controleert de isolatie zelf niet. De socat-brug
luistert op het gateway-IP van het interne netwerk en geeft de hele Ollama-API door. Omdat de
INPUT-policy van max2 ACCEPT is, kunnen ook containers op andere Docker-netwerken daar tijdens een run bij.

`own-tasks/` bevat zes eigen opgaven in het polyglot-formaat, afgeleid van ons eigen werk
(queue-reclaim, docker-ports, backup-excludes in Python; sprint-code, story-status, envelope-log in
JavaScript). Elke opgave heeft een referentie-oplossing in `.meta/` waartegen de tests groen zijn.

## Promptverfijner (`refiner/`)

Meet welk model de rol van *promptverfijner* het best vervult: een Nederlandstalig gesprek waarin het model hooguit 4
verduidelijkingsvragen per ronde stelt en daarna een prompt voor Claude Opus 5.5 schrijft, zonder de vraag zelf te
beantwoorden. Systeemprompt: `prompts/promptverfijner-systeem.txt` (v3; bron: Scrum4Me
`SPECS/promptverfijner-systeemprompt`; `promptverfijner-systeem-v2.txt` is de vorige tekst, bewaard om te vergelijken);
plan: `PLANS/refiner-eval` (PBI-8); harness-backend: product Agent-harness, `plans/m5-model-comparison-refiner`.

```bash
# backend ollama (standaard)
./refiner/run.py --models qwen3.8-gsq-rco:27b-iq3_s-text qwen3.6:35b-a3b-coding --seeds 1 \
  --num-ctx 16384 --temperature 0.7 --out results/refiner-<datum>
# backend harness: zonder docs op de lokale modellen, met docs op OpenRouter ($OPENROUTER_API_KEY in de omgeving)
./refiner/run.py --backend harness --harness "node /pad/naar/agent-harness/dist/cli.js" --variant nodocs \
  --models gsq-lokaal qwen3.6-lokaal --seeds 1 --extra-cases R01,R02,R04 --extra-seeds 2 3 \
  --out results/refiner-<datum>-nodocs
./refiner/run.py --backend harness --harness "node /pad/naar/agent-harness/dist/cli.js" --variant docs \
  --models qwen3.6-openrouter qwen3.8-openrouter --seeds 1 2 3 --max-cost-usd 3 --out results/refiner-<datum>-docs
./refiner/score.py results/refiner-<datum>          # per run-map (ollama); --docset <map>: andere docset voor D3
./refiner/score.py results/refiner-<datum>-nodocs   # backend harness: elke variant is een eigen run-map
./refiner/score.py results/refiner-<datum>-docs
python3 -m unittest refiner/test_refiner.py     # nep-Ollama en nep-harness: geen GPU of extern netwerk nodig
```

`refiner/cases.jsonl` bevat 15 cases met gescripte antwoorden: R01–R10 zonder docs (drukbeurt bij R01/R02, revisie bij
R03/R05) en D01–D05 met `variant: "docs"` (drukbeurt bij D02). De backend `ollama` draait alleen R01–R10, laat Ollama's
prefix-cache bewust aan (zo wordt het echt gebruikt) en logt per beurt tokens, duur, `done_reason`, `/api/ps` en de
TEI-status in `raw.jsonl`. Er wordt geen modelcode uitgevoerd.

### Backend harness

`--backend harness` stuurt elke beurt als één `harness run` door de agent-harness-CLI, na één `harness probe` per model;
dat vraagt een build met de M5-functies (agent-harness PR #24). `--harness` is dat commando met het volledige pad (geen
`~`) en `--variant nodocs|docs` is verplicht: één aanroep is één variant met één promptversie (`--prompt`, voor beide
backends) en een eigen run-map; een `--out` die al bestanden bevat wordt geweigerd, dus na een stop of crash is een
nieuwe map nodig. Per harness-run gelden `--max-output-tokens` (4096) en `--max-wall-seconds` (240); `--temperature`,
`--out` en de rest staan in `run.py --help`.

De gesprekken per model zijn `--cases` (bijv. `R01,R04`) × `--seeds`; `--extra-cases` met `--extra-seeds` voegt de paren
extra case × extra seed toe in dezelfde run-map, zodat de zeef één keer over alles oordeelt. Zonder docs is
`--seeds 1 --extra-cases R01,R02,R04 --extra-seeds 2 3` het plan (16 gesprekken per model: de tien cases één keer, R01,
R02 en R04 nog twee keer), met docs `--seeds 1 2 3`. Een extra case moet bij de variant horen, de twee opties gaan
samen, en een paar dat `--cases` × `--seeds` al heeft wordt geweigerd, net als een waarde die je twee keer noemt.

`refiner/models.json` (`--models-file`) kent negen labels: vier lokaal via Ollama's OpenAI-endpoint (`gsq-lokaal`,
`qwen3.6-lokaal`, en voor M6 `qwen3.8-q8-lokaal` en `qwen3.8-q4-lokaal`, de officiële tags `qwen3.8:27b-q8_0` en
`qwen3.8:27b-q4_K_M`) en vijf via OpenRouter. Een label heeft `base_url`, `name`, eventueel `api_key_env`, en per variant
(`nodocs`, `docs`, `probe`) een blok met `extraBody`. Elk OpenRouter-blok, ook dat van de probe, heeft
`provider: {data_collection: "deny", require_parameters: true}`; ontbreekt dat in een van de drie blokken, dan weigert
run.py het label (met label en blok in de melding) voordat er iets draait. Reasoning staat zonder docs en in de probe
uit en met docs op `medium` (de lokale modellen krijgen met docs geen instelling: thinking blijft aan). run.py voegt
`temperature` (`--temperature`, standaard 0,7) en `seed` (het nummer van de herhaling, uit `--seeds` of `--extra-seeds`)
toe aan de `extraBody` van elk manifest. `api_key_env` is alleen de naam van de variabele (`OPENROUTER_API_KEY`); die
naam gaat als `--api-key-env` naar de harness, die de waarde zelf leest: de sleutel staat nooit in argv of in een
bestand.

- `nodocs`: R01–R10, profiel `answer`, de systeemprompt zoals hij is.
- `docs`: D01–D05, profiel `tools`; de systeemprompt, een lege regel en `prompts/promptverfijner-docs-addendum.txt` (met
  het `product_id` uit `docset.json` voor `{product_id}`), en de vier doc-tools via `harness doc-server` over de
  bevroren docset `refiner/docset/` (`--docset` kiest een andere): acht agent-harness-bestanden uit één vastgepinde
  commit, met `docset.json` (`product_id`, `source_commit`, `frozen_at`, sha256 per bestand).
  `./refiner/freeze_docset.py --check refiner/docset` controleert de hashes, zoekt sleutelvormen en Bearer-waarden en
  weigert bestanden die `docset.json` niet noemt; exit 1 bij elke bevinding, want de docset gaat onbewerkt naar
  OpenRouter.

**Probe.** In beide varianten draait run.py eerst per model één `harness probe`; de proberij in `raw.jsonl` bewaart het
oordeel (`reliable`, `unreliable`, `none`) en de redenen van de mislukte stappen. Met docs draait een model alleen na
`reliable`, zonder docs ook bij een ander oordeel. Faalt elke stap met een HTTP-fout, dan draait het model niets en
toont `score.py` in de kolom `Probe` het label `geen aanbieder` (404 of 503 met een melding die een provider noemt) of
`probe-fout <status>`. Een onbereikbaar eindpunt (geen HTTP-status) krijgt geen label: het oordeel is `none`, te zien in
de kolom `Probe`. Zonder docs draait het model dan gewoon door, mislukt elk gesprek en eindigt run.py toch met 0. Kijk
dus naar die kolom (of de proberij in `raw.jsonl`) voordat je een run vertrouwt.

### Pogingen, stops en kosten

- **Plan.** Na de probes schrijft run.py per model dat draait een plan-rij met al zijn gesprekken (`[case, seed]`), de
  noemer van de zeef: een gesprek dat door een stop of crash nooit draaide, telt als niet afgerond.
- **Tweede poging.** Eindigt een harness-run niet `completed` (`failed`, `budget_exceeded`, `timed_out`), dan eindigt
  die poging als `error` en volgt één tweede poging van het hele gesprek: dezelfde seed en blinde id, `maxOutputTokens`
  en `maxWallSeconds` verdubbeld, rijen met `poging: 2`. `<blind id>.md` is het transcript van de poging die telt,
  `<blind id>-p1.md` dat van de eerste. Er volgt geen tweede poging na `no_final`, na een stop door `model HTTP 401`,
  `402` of `403`, en als `--max-cost-usd` bereikt is.
- **`invocation_error`.** Geeft een run-aanroep geen bruikbaar resultaat (geen of ongeldige `result.json`, onleesbare
  `trace.jsonl`), dan eindigt het gesprek zo, zonder tweede poging: dat model stopt, de andere gaan door en run.py
  eindigt met exit 1. Wat de harness zei gaat gemaskeerd naar stderr, in geen rij.
- **Stops.** `model HTTP 401`, `402` of `403` in een probe of run (sleutel, tegoed of rechten, niet het model) of het
  bereiken van `--max-cost-usd` stopt de hele aanroep met een rij `stop` (reden `http_<status>` of `max_cost`). Een stop
  in de probefase laat de latere modellen zonder rij: ze kregen geen kans. Exit 1 volgt op een stop, een
  `invocation_error` of een sleutel in de run-map, met de reden op stderr; `done: <map>` komt ook na een stop. Een
  gesprek dat na de tweede poging `error` blijft, geeft géén foutstatus: kijk naar `Afgerond` in `score.py`.
- **Kostengrens.** `--max-cost-usd` heeft geen standaard: geef hem bij elke OpenRouter-run mee, met 1,5 per model per
  aanroep (twee modellen: 3). De teller begint bij 0 per aanroep en telt over alle modellen van die aanroep. Vóór elke
  poging, ook vóór een tweede, telt run.py de `cost_usd` van alle beurtrijen op (een ontbrekend bedrag is 0); vanaf de
  grens volgt de stop. Binnen een poging wordt niet gecontroleerd, en probe-aanvragen en een betaalde aanvraag die op
  een fout eindigt staan in geen `cost_usd`: houd een marge. De limiet van de sleutel blijft de controle:
  `GET https://openrouter.ai/api/v1/key` (print alleen `limit`, `limit_remaining` en `usage`).
- **Sleutelcontrole.** `refiner/check_key.py --env OPENROUTER_API_KEY <map> …` leest de waarde uit de omgeving (`--env`
  is de naam) en print per map alleen aantallen (`files_scanned`, `unreadable`, `with_key`); exit 1 bij een treffer.
  run.py draait hem na elke run, ook een afgebroken, voor elk `api_key_env` van de gebruikte modellen; een treffer of
  mislukte controle geeft exit 1 en de melding de run-map niet te bewaren of te delen.

### Uitvoer en scoren

Een run-map bevat (`manifests/` en `harness/` alleen bij de backend harness):

- `raw.jsonl`: de rijen, te onderscheiden aan `turn`: een getal voor een beurt (o.a. `content`, harness-`status`,
  `tool_calls`, tokens, `cost_usd`, `providers`, `prompt_sha256`), `end` voor het einde van een poging (`final`,
  `no_final`, `error`, `invocation_error`), en `probe`, `plan` en `stop`;
- `summary.csv` (door `score.py`) en `blind-key.json` (blinde id naar model, case, seed);
- `transcripts/<blind id>.md` en, bij een tweede poging, `<blind id>-p1.md` voor de eerste;
- `manifests/`: een manifest per beurt, `<blind id>-p<poging>-t<beurt>.json`, en de extra body van elke probe
  (`probe-<label>.extra-body.json`, met het label);
- `harness/`: wat de harness schreef: `probe-<modelnaam>/probe.json` (de naam van het model in kleine letters en
  opgeschoond, bijv. `probe-qwen-qwen3.6-35b-a3b`; niet het label) en per beurt `<blind id>-p<poging>-t<beurt>/` met
  `result.json`, `trace.jsonl` en, alleen bij een vastgelegd toolresultaat, `tools/`.

`score.py` schrijft `summary.csv`, print per variant een tabel en draait heuristische checks: A1 taal (alleen wélke
taal, niet hoe goed), A2 vraagvorm, A3 rondes, A4 eindvorm, A5 terughoudendheid (een vlag; pas diskwalificerend na
bevestiging door JP), A6 trouw aan de gegeven feiten, A7 Opus-regels, A8 revisie. Kwaliteit van het Nederlands, de
waarde van de vragen en verzonnen feiten beoordeelt JP blind aan de hand van de transcripten. Een docs-case krijgt er
D1–D6 bij:

- D1: een geslaagde doc-toolaanroep in beurt 1;
- D2: de feiten uit de docs (`doc_must_include`) staan in de laatste prompt;
- D3: niets verzonnen: elk pad en elke doc-verwijzing (`folder/slug`) in de laatste prompt komt uit de docset of een
  gebruikersbericht; bij een feit dat de docs missen (D04) vraagt het model ernaar of markeert het als onbekend;
- D4: geen vraag vóór het eerste codeblok over iets wat de docs al beantwoorden;
- D5: dezelfde terughoudendheidsregel als A5 (bij een docs-case heet de vlag D5 en is A5 n.v.t.);
- D6: elke beurt van de poging die telt eindigde `completed`.

De zeef (voorlopig, ontwerp M5 §5.8) beoordeelt per model en variant: minstens 90% van de geplande gesprekken eindigt
`final` (noemer: de plan-rij), geen vlag op A5 of D5, en A1–A4, A6–A8 en D1–D4 slagen elk in minstens 80% van de
gesprekken waarvoor ze gelden, mits dat er minstens vijf zijn. D6 staat in de tabel maar telt niet mee; een `*` bij een
cel betekent minder dan vijf gesprekken (getoond, niet meegeteld). De stops van de run staan bovenaan onder `Gestopt:`.
`--docset <map>` laat D3 een andere docset lezen dan de bevroren `refiner/docset/`.

`summary.csv` heeft per backend eigen kolommen. Een Ollama-run houdt `model … notes`, inclusief `eval_tokens`,
`max_prompt_tokens` en `other_model_loaded`; een harness-run laat die drie leeg en voegt `variant`, `poging` (die telt),
`first_attempt_status`, D1–D6, `model_turns`, `tool_calls`, tokens, `reasoning_tokens` (een deel van `output_tokens`),
`cost_usd` en `providers` toe. Tokens, `model_turns`, `tool_calls` en aanbieders komen van de poging die telt.
`cost_usd` (in de tabel `Kosten $ (alle pogingen)`) is wat het gesprek over alle pogingen kostte, want ook een
weggegooide eerste poging is betaald; meldt een poging geen kosten terwijl een andere dat wel doet, dan telt die als
`$0.0000`, en meldt geen enkele beurt kosten (een lokaal model), dan is `cost_usd` leeg: onbekend is niet gratis.

## Task-bench (task_bench/)

Meet of Qwen 3.8, zoals hij op een machine van 96 GB zou draaien, ons echte werk aankan, en of hij meer kan dan wat max2 nu al lokaal
doet (M7, IDEA-229). Echt werk: 12 oude, afgeronde Scrum4Me-taken, 6 uit agent-harness en 6 uit scrum4me-mcp. `harness task-bench`
(agent-harness) voert elke taak uit vanaf zijn begincommit, met dezelfde lus, tools, gate en limieten als de productieworker, alleen
zonder doc-tools. Een run is **geslaagd** als de verify-gate van de repo groen is én de verborgen tests uit de echte oplossing slagen.
Twee modellen, één run per taak: `qwen3.8-openrouter` (`qwen/qwen3.8-27b` via OpenRouter, alleen op een 16-bit-route: BF16 of FP16) en
`gsq-lokaal` (`qwen3.8-gsq-rco:27b-iq3_s-text` op max2). Het bindende ontwerp is de spec `docs/specs/2026-10-02-task-bench-design.md`
in agent-harness (rev 5), het plan `docs/plans/M7-task-bench.md`; de betekenis van een oordeel voor de aankoop staat in spec §1.

```bash
# een venster op max2 (in tmux): de driver. Het grootboek is één bestand voor alle vensters, ook dat van de praktijkproef.
./task_bench/run.py --harness "node /home/janpeter/Development/agent-harness-m7/dist/cli.js" --models qwen3.8-openrouter \
  --cases task_bench/cases.jsonl --task-config task_bench/task-config.json --out $R/gehost --ledger $R/ledger.jsonl [--budget-stop 14]
# daarna op de kopie van de vensters (rsync -a): tabel, tellingen en oordeel; schrijft summary.csv in die map
./task_bench/score.py $M --models qwen3.8-openrouter gsq-lokaal [--ledger $M/ledger.jsonl]
python3 -m unittest discover -s llm-bench/task_bench -p 'test_*.py'    # vanuit de repo-root; nep-harness: geen model, netwerk of sleutel
```

`--harness` is het commando met het volledige pad (geen `~`). `models.json` (`--models-file`) heeft de twee labels: `base_url`, `name`,
`retry_transient` (herhalen bij storingen van de aanbieder: aan voor het gehoste label, uit voor `gsq-lokaal`), eventueel `api_key_env`
(de *naam* van de variabele) en `extraBody`. Het gehoste label draagt `provider: {data_collection: "deny", require_parameters: true,
quantizations: ["bf16", "fp16"]}` en `reasoning: {effort: "medium"}`; ontbreekt het provider-blok of wijkt `quantizations` af, dan weigert
`run.py` het label voordat er iets draait. `task-config.json` is een letterlijke kopie van het `task`-blok van
`/etc/agent-harness/worker.json`. `fake_task_bench.py` is de nep-harness van de tests en `fixtures/real-harness/` bevat ongewijzigde
uitvoer van de praktijkproef van 2026-10-03.

**Stopcodes van `run.py`** (de reden staat op stderr):

| Code | Betekenis |
|---|---|
| 0 | klaar |
| 1 | een onverwachte fout in de driver zelf: een Python-traceback op stderr; dit is geen stopcode van de regels hieronder |
| 2 | gebruiksfout: de aanroep of een configuratie klopt niet, ook een ontbrekende sleutelvariabele. Meestal valt dit vóór er iets draait, maar het kan ook midden in een venster vallen (een grootboek dat onleesbaar is geworden, een harness die niet start); wat dan al klaar was staat in het grootboek |
| 3 | een tweede benchfout bij dezelfde taak: de driver stopt voor JP |
| 4 | het grootboek staat op `--budget-stop` (14 dollar) of meer: er start geen run meer |
| 5 | de probe is niet `reliable`, of de endpointlijst toont geen 16-bit-endpoint met tools |
| 6 | afgebroken met SIGINT of SIGTERM |

**Wat de driver doet.** Per label, in de volgorde van `--models`: bij OpenRouter eerst de publieke endpointlijst
(`<out>/endpoints-<label>-<ts>.json`, het bewijs van de precisie), dan `harness probe` met de `extraBody` van het label (in
`<out>/probes/<label>-<ts>/`), dan de taken van `cases.jsonl` in volgorde, met de uitvoer van het label in `<out>/<label>/`. Een taak
die al een geldig resultaat van een modelstatus heeft (`geslaagd`, `verborgen_tests_rood`, `verify_rood`, `limiet`,
`geen_wijzigingen`) draait niet opnieuw, dus een volgend venster hervat de set. Een benchfout draait één keer opnieuw; de tweede stopt de
driver (3), ook als de eerste uit een eerder venster komt. Een resultaat met `benchError: "afgebroken"` telt niet als benchfout: die taak
draait bij hervatten gewoon opnieuw. Alleen `bench-result.json` van een run wordt gelezen: `ws/` en `ws-deps/` bevatten werkbomen
waarin modelcode draaide, en een named pipe daarin laat een `open()` hangen.

**Grootboek.** Elke probe en elke run is een regel in `--ledger`: `{"id", "kind": "probe", "label", "cost_usd"}` of `{"id", "kind":
"run", "label", "case", "cost_usd"}`. De kosten van een run zijn `usage.costUsd` van zijn `bench-result.json`; die van een probe de
som van elke `usage.costUsd` onder `steps` in `probe.json`. Een bedrag dat er niet is, is `null`: het telt als 0 in het totaal
(`math.fsum`), en `score.py --ledger` noemt hoeveel het er zijn. Staat het totaal op de stop of erboven, dan start er niets meer: geen
run en ook geen probe, want die kost ook geld (gecontroleerd aan het begin van elk label en vóór elke run en herhaling). De limiet van
de sleutel (20 dollar) blijft de enige harde grens.

**Stoppen en de sleutel.** SIGINT en SIGTERM zetten alleen een stopvlag. De driver wacht de lopende harness-aanroep af (die kreeg
hetzelfde signaal, bijvoorbeeld via `pkill -s`, en ruimt zijn containers zelf op), boekt de kosten en stopt met 6, zonder nieuwe run;
hij doodt de bench nooit. Een probe die door het signaal sterft (`harness probe` heeft geen handler en laat dan geen `probe.json` na)
is ook een stop, 6, en geen mislukte probe, 5; de probe staat dan met een onbekend bedrag (`null`) in het grootboek. De sleutel
(`OPENROUTER_API_KEY`) komt alleen via de omgeving binnen: in argv staat `--api-key-env OPENROUTER_API_KEY`, nooit de waarde. Een
gevraagd label met een sleutelvariabele die leeg of afwezig is geeft exit 2 vóór er iets start. De sleutelcontrole
(`refiner/check_key.py`) draait niet in de driver maar als vensterstap op de kopie zonder `ws*/`.

**Beslisregel** (spec §1): een model kan het werk aan bij minstens 9 van de 12 taken geslaagd.

| Gehost (van 12) | gsq (van 12) | Oordeel |
|---|---|---|
| 8 of minder | – | `gezakt` |
| 9 of meer | 9 of meer | `max2 volstaat` |
| 9 of meer | 8 of minder, minstens 3 minder dan gehost | `meerwaarde` |
| 9 of meer | 8 of minder, hooguit 2 minder dan gehost | `onbeslist` |

Grens: een oordeel is ook `onbeslist` als het steunt op een telling op de grens of één eronder: gehost precies 9 of 8, gsq precies 9 of 8
(als die telling het oordeel bepaalt: de rijen `max2 volstaat` en `meerwaarde`), of een verschil van precies 3 (alleen bij
`meerwaarde`). `score.verdict(h, g)` is die regel; de test telt over alle 169 paren 104 `gezakt`, 33 `onbeslist`, 23 `meerwaarde` en
9 `max2 volstaat`.

**De scorer** scoort alleen een volledige set: elk label heeft precies 12 verschillende taken, dezelfde 12 voor beide labels, en de
laatste status van elke taak (het resultaat met de nieuwste mtime van `bench-result.json`) is een modelstatus. Anders weigert hij met
exit 2 en schrijft hij niets. Hij zoekt de resultaten onder `<map>/**/<label>/<run>/`, dus de map mag boven de `--out` van de vensters
liggen; een run buiten een map met de naam van zijn label (zoals de praktijkproef in `proef/`) telt niet mee. Een run-map wordt nooit
doorlopen, ook niet als er geen resultaat in staat (een bench die afbrak): alleen zijn `bench-result.json` wordt gelezen, en links
worden niet gevolgd. `--ledger` moet een bestaand bestand zijn (anders exit 2, zonder totaalregel).

## Resultaten 2026-09-25/26

`results/fit-2026-09-25.md`, `results/speed-2026-09-25.md`, `results/evalplus-2026-09-25.md`,
`results/aider-2026-09-26.md` en `results/speed-2026-09-26-tei-on.md`. Samenvatting en aanbeveling:
Scrum4Me ProductDoc `RUNBOOKS/lokale-llm-qwen3x-benchmark` (product max2).

`modelfiles/qwen3.8-gsq-rco-iq3_s-text.Modelfile` wijst naar een blob-pad in Ollama's modelmap
(alleen leesbaar voor de gebruiker `ollama`): kopieer het bestand naar een voor `ollama` leesbare
plek en maak het model met `sudo -u ollama ollama create qwen3.8-gsq-rco:27b-iq3_s-text -f <pad>`.
