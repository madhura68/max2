# llm-bench — lokale LLM's op de RTX 5070 Ti

Herhaalbare metingen van Ollama-modellen op max2 (16 GB VRAM, 30 GB RAM).
Plan en besluiten: Scrum4Me max2 → PBI-1, ProductDoc `PLANS/qwen3x-ollama-coding-benchmark`.

## Voorwaarden

- Ollama draait als systemd-service op `127.0.0.1:11434` (nooit breder binden: geen auth).
  Instellingen in `/etc/systemd/system/ollama.service.d/override.conf`: flash attention aan,
  KV-cache `q8_0`, één model tegelijk, `NUM_PARALLEL=1`.
- Voor representatieve cijfers geen andere GPU-last. TEI (`tei-gpu`) houdt ~2,5 GB VRAM vast;
  tijdelijk stoppen met `docker compose -f /srv/apps/tei/docker-compose.yml stop`, daarna `start`.

## Modellen

De `hf.co/`-pull van een GGUF levert geen chat-template. Maak voor zulke modellen eerst een afgeleid model uit `modelfiles/` (bijv. `ollama create qwen3.8-gsq-rco:27b-iq3_s -f modelfiles/qwen3.8-gsq-rco-iq3_s.Modelfile`) en controleer met `ollama show --modelfile` dat `RENDERER`/`PARSER` gelijk zijn aan de officiële tag.

## Snelheid en geheugen

```bash
./speed.py --models qwen3.5:9b qwen3.8:27b --ctx 8192 32768 --reps 3
```

Per model × context: één warm-up (laadtijd, GPU/CPU-split uit `/api/ps`), daarna per prompt
`--reps` runs; de samenvatting geeft de mediaan. Elke run krijgt een unieke eerste regel, zodat
Ollama's prompt-prefixcache niet meetelt. Thinking staat uit, tenzij `--think`.

| Kolom | Betekenis |
|---|---|
| `gpu_pct` | deel van het geladen model dat in VRAM staat (100 = volledig op de GPU) |
| `prompt_tps` | prompt-verwerking, tokens/s (Ollama `prompt_eval_*`) |
| `gen_tps` | generatie, tokens/s (Ollama `eval_*`) |
| `ttft_s` | tijd tot het eerste token, gemeten op de stream |
| `peak_vram_mib` | piek `nvidia-smi memory.used` tijdens het model × context-blok (hele GPU) |
| `min_mem_available_mib` | laagste `MemAvailable` tijdens dat blok |

Prompts staan in `prompts/`: `short.txt` (klein codeerverzoek, ~120 tokens) en
`long_code.py.txt` + `long_question.txt` (~4,6k tokens; het begin van CPython's `argparse.py`, PSF-licentie).

Uitvoer: `results/speed-<UTC-timestamp>/raw.jsonl` (elke run) en `summary.csv`.

Resultaten per datum: `results/fit-<datum>.md` en `results/speed-<datum>.md`.
