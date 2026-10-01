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
  --models gsq-lokaal qwen3.6-lokaal --seeds 1 2 3 --out results/refiner-<datum>-nodocs
./refiner/run.py --backend harness --harness "node /pad/naar/agent-harness/dist/cli.js" --variant docs \
  --models qwen3.6-openrouter qwen3.8-openrouter --seeds 1 2 3 --max-cost-usd 1 --out results/refiner-<datum>-docs
./refiner/score.py results/refiner-<datum>      # per run-map; --docset <map>: andere docset voor D3
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
backends) en een eigen run-map. Per harness-run gelden `--max-output-tokens` (4096) en `--max-wall-seconds` (240);
`--seeds`, `--cases` (bijv. `R01,R04`), `--temperature`, `--out` en de rest staan in `run.py --help`.

`refiner/models.json` (`--models-file`) kent zeven labels: `gsq-lokaal` en `qwen3.6-lokaal` (via Ollama's
OpenAI-endpoint) en vijf via OpenRouter. Een label heeft `base_url`, `name`, eventueel `api_key_env`, en per variant
(`nodocs`, `docs`, `probe`) een blok met `extraBody`. Elk OpenRouter-blok, ook dat van de probe, heeft
`provider: {data_collection: "deny", require_parameters: true}`. Reasoning staat zonder docs en in de probe uit en met
docs op `medium` (de lokale modellen krijgen met docs geen instelling: thinking blijft aan). run.py voegt `temperature`
(`--temperature`, standaard 0,7) en `seed` (het nummer uit `--seeds`, de herhaling) toe aan de `extraBody` van elk
manifest. `api_key_env` is alleen de naam van de variabele (`OPENROUTER_API_KEY`); die naam gaat als `--api-key-env`
naar de harness, die de waarde zelf leest: de sleutel staat nooit in argv of in een bestand.

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
`probe-fout <status>`. Een onbereikbaar eindpunt (geen HTTP-status) telt niet als mislukte probe: zonder docs draait het
model dan door, mislukt elk gesprek en eindigt run.py toch met 0. Kijk dus naar de proberij in `raw.jsonl` (kolom
`Probe` van `score.py`) voordat je een run vertrouwt.

### Pogingen, stops en kosten

- **Plan.** Na de probes schrijft run.py per model dat draait een plan-rij met al zijn gesprekken (`[case, seed]`), de
  noemer van de zeef: een gesprek dat door een stop of crash nooit draaide, telt als niet afgerond.
- **Tweede poging.** Eindigt een harness-run niet `completed` (`failed`, `budget_exceeded`, `timed_out`), dan eindigt
  die poging als `error` en volgt één tweede poging van het hele gesprek: dezelfde seed en blinde id, `maxOutputTokens`
  en `maxWallSeconds` verdubbeld, rijen met `poging: 2`. `<blind id>.md` is het transcript van de poging die telt,
  `<blind id>-p1.md` dat van de eerste. Na `no_final` volgt geen tweede poging.
- **`invocation_error`.** Geeft een run-aanroep geen bruikbaar resultaat (geen of ongeldige `result.json`, onleesbare
  `trace.jsonl`), dan eindigt het gesprek zo, zonder tweede poging: dat model stopt, de andere gaan door en run.py
  eindigt met exit 1. Wat de harness zei gaat gemaskeerd naar stderr, in geen rij.
- **Stops.** `model HTTP 401`, `402` of `403` in een probe of run (sleutel, tegoed of rechten, niet het model) of het
  bereiken van `--max-cost-usd` stopt de hele aanroep met een rij `stop` (reden `http_<status>` of `max_cost`). Een stop
  in de probefase laat de latere modellen zonder rij: ze kregen geen kans. Exit 1 volgt op een stop, een
  `invocation_error` of een sleutel in de run-map, met de reden op stderr; `done: <map>` komt ook na een stop. Een
  gesprek dat na de tweede poging `error` blijft, geeft géén foutstatus: kijk naar `Afgerond` in `score.py`.
- **Kostengrens.** `--max-cost-usd` heeft geen standaard: geef hem bij elke OpenRouter-run mee. Vóór elke poging, ook
  vóór een tweede, telt run.py de `cost_usd` van alle beurtrijen op (een ontbrekend bedrag is 0); vanaf de grens volgt
  de stop. Binnen een poging wordt niet gecontroleerd, en probe-aanvragen en een betaalde aanvraag die op een fout
  eindigt staan in geen `cost_usd`: houd een marge. De limiet van de sleutel blijft de controle:
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
- `manifests/`: een manifest per beurt, `<blind id>-p<poging>-t<beurt>.json`, en de extra body van elke probe;
- `harness/`: wat de harness schreef, `probe-<model>/probe.json` en per beurt `<blind id>-p<poging>-t<beurt>/` met
  `result.json`, `trace.jsonl` en `tools/`.

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

## Resultaten 2026-09-25/26

`results/fit-2026-09-25.md`, `results/speed-2026-09-25.md`, `results/evalplus-2026-09-25.md`,
`results/aider-2026-09-26.md` en `results/speed-2026-09-26-tei-on.md`. Samenvatting en aanbeveling:
Scrum4Me ProductDoc `RUNBOOKS/lokale-llm-qwen3x-benchmark` (product max2).

`modelfiles/qwen3.8-gsq-rco-iq3_s-text.Modelfile` wijst naar een blob-pad in Ollama's modelmap
(alleen leesbaar voor de gebruiker `ollama`): kopieer het bestand naar een voor `ollama` leesbare
plek en maak het model met `sudo -u ollama ollama create qwen3.8-gsq-rco:27b-iq3_s-text -f <pad>`.
