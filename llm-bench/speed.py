#!/usr/bin/env python3
"""Speed/memory benchmark for Ollama models on max2 (PBI-1, ST-001 T-4).

Per model x context length: one warm-up (captures load time and GPU/CPU split),
then N measured runs per prompt. Timings come from the Ollama API counters, not
wall-clock guesses; TTFT is measured on the stream. Peak VRAM is sampled with
nvidia-smi, minimum MemAvailable from /proc/meminfo.

Stdlib only. Usage:
  ./speed.py --models qwen3.5:9b qwen3.8:27b --ctx 8192 32768 --reps 3
"""
import argparse
import csv
import json
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOST = "http://127.0.0.1:11434"


def api(path, payload=None, timeout=1800):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(HOST + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def stream_generate(payload, timeout=1800):
    """Stream /api/generate; return (final_chunk, ttft_s, full_response)."""
    req = urllib.request.Request(HOST + "/api/generate",
                                 data=json.dumps({**payload, "stream": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    ttft, text, last = None, [], None
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            if not line.strip():
                continue
            chunk = json.loads(line)
            if "error" in chunk:
                raise RuntimeError(chunk["error"])
            piece = chunk.get("response", "") or chunk.get("thinking", "")
            if piece and ttft is None:
                ttft = time.perf_counter() - t0
            text.append(chunk.get("response", ""))
            last = chunk
    return last, ttft, "".join(text)


class Sampler(threading.Thread):
    """Peak VRAM (MiB) and minimum MemAvailable (MiB) while running."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.peak_vram = 0
        self.min_avail = None

    def run(self):
        while not self.stop.is_set():
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5).stdout
                self.peak_vram = max(self.peak_vram, int(out.split()[0]))
            except Exception:
                pass
            for line in open("/proc/meminfo"):
                if line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) // 1024
                    self.min_avail = avail if self.min_avail is None else min(self.min_avail, avail)
            self.stop.wait(0.5)


def unload_all():
    for m in api("/api/ps").get("models", []):
        api("/api/generate", {"model": m["name"], "keep_alive": 0})
    time.sleep(2)


def loaded_split(model):
    for m in api("/api/ps").get("models", []):
        if m["name"] == model or m["model"] == model:
            size, vram = m.get("size", 0), m.get("size_vram", 0)
            return {"size_mib": size // 2**20, "vram_mib": vram // 2**20,
                    "gpu_pct": round(100 * vram / size, 1) if size else None,
                    "context": m.get("context_length")}
    return {}


def run_one(model, prompt, ctx, think, num_predict):
    # A unique first line defeats Ollama's prompt-prefix cache, so every run
    # pays full prompt processing and TTFT/prompt_tps stay comparable.
    prompt = f"# run {uuid.uuid4()}\n{prompt}"
    payload = {"model": model, "prompt": prompt, "keep_alive": "10m",
               "options": {"num_ctx": ctx, "temperature": 0, "seed": 42,
                           "num_predict": num_predict}}
    if think is not None:
        payload["think"] = think
    try:
        final, ttft, text = stream_generate(payload)
    except (RuntimeError, urllib.error.HTTPError) as e:
        # Models without a thinking-capable template reject the flag; retry without it.
        if think is not None and "think" in str(e).lower():
            payload.pop("think")
            final, ttft, text = stream_generate(payload)
        else:
            raise
    ns = 1e9
    return {
        "prompt_tokens": final.get("prompt_eval_count", 0),
        "prompt_tps": round(final.get("prompt_eval_count", 0) / (final.get("prompt_eval_duration", 1) / ns), 1),
        "gen_tokens": final.get("eval_count", 0),
        "gen_tps": round(final.get("eval_count", 0) / (final.get("eval_duration", 1) / ns), 1),
        "ttft_s": round(ttft, 3) if ttft is not None else None,
        "load_s": round(final.get("load_duration", 0) / ns, 2),
        "total_s": round(final.get("total_duration", 0) / ns, 2),
        "think_sent": "think" in payload,
        "sample": text[:160],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--ctx", nargs="+", type=int, default=[8192, 32768])
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--num-predict", type=int, default=512)
    ap.add_argument("--think", action="store_true", help="enable thinking (default: think=false)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    p = HERE / "prompts"
    prompts = {
        "short": (p / "short.txt").read_text(),
        "long": (p / "long_code.py.txt").read_text() + "\n\n" + (p / "long_question.txt").read_text(),
    }
    version = api("/api/version")["version"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or HERE / "results" / f"speed-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    raw = open(out / "raw.jsonl", "w")
    rows = []

    for model in args.models:
        for ctx in args.ctx:
            unload_all()
            sampler = Sampler()
            sampler.start()
            base = {"model": model, "ctx": ctx, "think": args.think, "ollama": version}
            try:
                warm = run_one(model, "Reply with OK.", ctx, args.think, 8)
                split = loaded_split(model)
                for name, text in prompts.items():
                    runs = []
                    for rep in range(args.reps):
                        r = run_one(model, text, ctx, args.think, args.num_predict)
                        raw.write(json.dumps({**base, **split, "prompt": name, "rep": rep, **r}) + "\n")
                        raw.flush()
                        runs.append(r)
                    med = lambda k: statistics.median(x[k] for x in runs if x[k] is not None)
                    rows.append({**base, "prompt": name, "load_s": warm["load_s"], **split,
                                 "prompt_tokens": runs[0]["prompt_tokens"],
                                 "prompt_tps": med("prompt_tps"), "gen_tps": med("gen_tps"),
                                 "ttft_s": med("ttft_s"), "error": ""})
                    print(f"{model:55} ctx={ctx:<6} {name:5} gpu={split.get('gpu_pct')}% "
                          f"pp={rows[-1]['prompt_tps']} tg={rows[-1]['gen_tps']} ttft={rows[-1]['ttft_s']}", flush=True)
            except Exception as e:
                rows.append({**base, "prompt": "-", "error": str(e)[:300]})
                print(f"{model} ctx={ctx}: ERROR {e}", flush=True)
            finally:
                sampler.stop.set()
                sampler.join()
                for r in rows:
                    if r["model"] == model and r["ctx"] == ctx:
                        r["peak_vram_mib"] = sampler.peak_vram
                        r["min_mem_available_mib"] = sampler.min_avail

    unload_all()
    fields = ["model", "ctx", "think", "prompt", "gpu_pct", "vram_mib", "size_mib", "context",
              "load_s", "prompt_tokens", "prompt_tps", "gen_tps", "ttft_s", "peak_vram_mib",
              "min_mem_available_mib", "ollama", "error"]
    with open(out / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\nresults: {out}")


if __name__ == "__main__":
    main()
