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

Meet welk model de rol van *promptverfijner* het best vervult: een Nederlandstalig gesprek waarin het
model hooguit 4 verduidelijkingsvragen per ronde stelt en daarna een prompt voor Claude Opus 5.5 schrijft,
zonder de vraag zelf te beantwoorden. Systeemprompt: `prompts/promptverfijner-systeem.txt`
(bron: Scrum4Me `SPECS/promptverfijner-systeemprompt`); plan: `PLANS/refiner-eval` (PBI-8).

```bash
./refiner/run.py --models qwen3.8-gsq-rco:27b-iq3_s-text qwen3.6:35b-a3b-coding --seeds 1 \
  --num-ctx 16384 --temperature 0.7 --out results/refiner-<datum>
./refiner/score.py results/refiner-<datum>
python3 -m unittest refiner/test_refiner.py     # nep-Ollama, geen GPU nodig
```

`refiner/cases.jsonl` bevat 10 cases met gescripte antwoorden (drukbeurt bij R01/R02, revisie bij
R03/R05). De runner laat Ollama's prefix-cache bewust aan (zo wordt het echt gebruikt), logt per beurt
tokens, duur, `done_reason`, `/api/ps` en de TEI-status in `raw.jsonl`, en schrijft transcripten met
een blinde id (`blind-key.json` koppelt ze aan het model). Er wordt geen modelcode uitgevoerd.

`score.py` draait heuristische checks: A1 taal (alleen wélke taal, niet hoe goed), A2 vraagvorm,
A3 rondes, A4 eindvorm, A5 terughoudendheid (een vlag; pas diskwalificerend na bevestiging door JP),
A6 trouw aan de gegeven feiten, A7 Opus-regels, A8 revisie. Kwaliteit van het Nederlands, de waarde
van de vragen en verzonnen feiten beoordeelt JP blind aan de hand van de transcripten.

## Resultaten 2026-09-25/26

`results/fit-2026-09-25.md`, `results/speed-2026-09-25.md`, `results/evalplus-2026-09-25.md`,
`results/aider-2026-09-26.md` en `results/speed-2026-09-26-tei-on.md`. Samenvatting en aanbeveling:
Scrum4Me ProductDoc `RUNBOOKS/lokale-llm-qwen3x-benchmark` (product max2).

`modelfiles/qwen3.8-gsq-rco-iq3_s-text.Modelfile` wijst naar een blob-pad in Ollama's modelmap
(alleen leesbaar voor de gebruiker `ollama`): kopieer het bestand naar een voor `ollama` leesbare
plek en maak het model met `sudo -u ollama ollama create qwen3.8-gsq-rco:27b-iq3_s-text -f <pad>`.
