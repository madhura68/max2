#!/usr/bin/env python3
"""Promptverfijner eval: multi-turn conversations with scripted user replies (PBI-8, T-2).

Per model x case x seed the model gets the promptverfijner system prompt and the case input.
Until it answers with a fenced prompt it gets the case's scripted replies (max 4 user turns);
after the fence, R01/R02 get a pressure turn and R03/R05 a revision turn. Unlike speed.py the
prefix cache is left alone: reuse across turns is how the refiner is actually used.

Stdlib only. Usage:
  ./run.py --models qwen3.8-gsq-rco:27b-iq3_s-text qwen3.6:35b-a3b-coding --seeds 1
"""
import argparse
import hashlib
import json
import os
import random
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROMPT = HERE.parent / "prompts" / "promptverfijner-systeem.txt"
CASES = HERE / "cases.jsonl"
MAX_USER_TURNS = 4


def has_fence(text):
    return "```" in text


class Ollama:
    def __init__(self, host, timeout=600):
        self.host, self.timeout = host.rstrip("/"), timeout

    def call(self, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.host + path, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)


def tei_state():
    """Best effort: is the TEI embedding server running next to Ollama?"""
    for cmd in (["docker", "ps", "--format", "{{.Names}}"],
                ["nvidia-smi", "--query-compute-apps=process_name", "--format=csv,noheader"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if out.returncode == 0:
                return "tei" in out.stdout.lower()
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def converse(api, model, system, case, seed, opts, think, log):
    """Run one conversation; call log(row) per model turn. Returns (status, messages)."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": case["input"]}]
    replies = list(case.get("replies") or [])
    pressure, revision = case.get("pressure_reply"), case.get("revision")
    extra_sent = False
    user_turns, turn = 1, 0
    while True:
        turn += 1
        t0 = time.perf_counter()
        try:
            r = api.call("/api/chat", {"model": model, "messages": messages, "stream": False,
                                       "think": think, "keep_alive": "10m",
                                       "options": {**opts, "seed": seed}})
        except Exception as e:  # HTTP error, timeout: record and move on
            log({"turn": turn, "error": str(e)[:300], "wall_s": round(time.perf_counter() - t0, 2)})
            return "error", messages
        msg = r.get("message", {})
        content = msg.get("content", "")
        messages.append({"role": "assistant", "content": content})
        ns = 1e9
        log({"turn": turn, "content": content, "thinking_chars": len(msg.get("thinking") or ""),
             "prompt_eval_count": r.get("prompt_eval_count"),
             "prompt_eval_s": round((r.get("prompt_eval_duration") or 0) / ns, 3),
             "eval_count": r.get("eval_count"), "eval_s": round((r.get("eval_duration") or 0) / ns, 3),
             "load_s": round((r.get("load_duration") or 0) / ns, 3),
             "total_s": round((r.get("total_duration") or 0) / ns, 3),
             "done_reason": r.get("done_reason"), "wall_s": round(time.perf_counter() - t0, 2)})
        if extra_sent:
            return "final", messages
        if has_fence(content):
            follow = pressure or revision
            if not follow:
                return "final", messages
            nxt, extra_sent = follow, True
        else:
            if user_turns >= MAX_USER_TURNS:
                return "no_final", messages
            if pressure and user_turns == 1:
                nxt, pressure, extra_sent = pressure, None, False
            elif replies:
                nxt = replies.pop(0)
            else:
                nxt = "Akkoord, schrijf nu de prompt." if case.get("lang") != "en" else "Fine, write the prompt now."
        messages.append({"role": "user", "content": nxt})
        user_turns += 1


def transcript(messages):
    out = []
    for m in messages[1:]:
        who = "Gebruiker" if m["role"] == "user" else "Model"
        out.append(f"### {who}\n\n{m['content']}\n")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--seeds", nargs="+", type=int, default=[1])
    ap.add_argument("--cases", help="comma-separated case ids, e.g. R01,R04")
    ap.add_argument("--num-ctx", type=int, default=16384)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--think", choices=["false", "true"], default="false")
    ap.add_argument("--out")
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434"))
    args = ap.parse_args()

    system = PROMPT.read_text()
    prompt_sha = hashlib.sha256(system.encode()).hexdigest()
    cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out or HERE.parent / "results" / f"refiner-{stamp}")
    (out / "transcripts").mkdir(parents=True, exist_ok=True)
    api = Ollama(args.host)
    version = api.call("/api/version").get("version")
    tei = tei_state()
    opts = {"num_ctx": args.num_ctx, "temperature": args.temperature}
    think = args.think == "true"
    rng = random.Random(stamp)
    key, used = {}, set()

    with open(out / "raw.jsonl", "a") as raw:
        for model in args.models:
            for case in cases:
                for seed in args.seeds:
                    bid = f"{rng.randrange(16**6):06x}"
                    while bid in used:
                        bid = f"{rng.randrange(16**6):06x}"
                    used.add(bid)
                    ps = [m["name"] for m in api.call("/api/ps").get("models", [])]
                    base = {"model": model, "case": case["id"], "seed": seed, "blind_id": bid,
                            "ps_before": ps, "tei_on": tei, "ollama": version,
                            "prompt_sha256": prompt_sha, "options": opts, "think": think}

                    def log(row):
                        raw.write(json.dumps({**base, **row}, ensure_ascii=False) + "\n")
                        raw.flush()

                    t0 = time.perf_counter()
                    status, messages = converse(api, model, system, case, seed, opts, think, log)
                    wall = round(time.perf_counter() - t0, 1)
                    log({"turn": "end", "status": status, "conversation_wall_s": wall})
                    (out / "transcripts" / f"{bid}.md").write_text(
                        f"# Transcript {bid} ({case['id']}: {case['titel']})\n\n{transcript(messages)}")
                    key[bid] = {"model": model, "case": case["id"], "seed": seed}
                    print(f"{model} {case['id']} seed {seed}: {status} in {wall}s", flush=True)
    (out / "blind-key.json").write_text(json.dumps(key, indent=1))
    print(f"done: {out}")


if __name__ == "__main__":
    main()
