"""Generate EvalPlus samples from an Ollama model (runs inside the evalplus image).

Uses Ollama's native /api/chat so thinking can be switched off explicitly; the
prompt matches EvalPlus's chat instruction. Output: <out>/<dataset>.raw.jsonl with
{"task_id", "solution"} (raw model text; evalplus.sanitize extracts the code).
Resumable: task_ids already present in the output file are skipped.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

from evalplus.data import get_human_eval_plus, get_mbpp_plus

PREFIX = "Please provide a self-contained Python script that solves the following problem in a markdown code block:"


def chat(host, model, content, num_ctx, num_predict):
    body = {"model": model, "stream": False, "think": False,
            "messages": [{"role": "user", "content": content}],
            "options": {"temperature": 0, "seed": 42, "num_ctx": num_ctx, "num_predict": num_predict}}
    req = urllib.request.Request(host + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)


def main(model, dataset, out, host="http://127.0.0.1:11434", num_ctx=8192, num_predict=1024, limit=None):
    problems = get_human_eval_plus() if dataset == "humaneval" else get_mbpp_plus()
    if limit:
        problems = dict(list(problems.items())[:limit])
    path = Path(out) / f"{dataset}.raw.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if path.exists():
        done = {json.loads(l)["task_id"] for l in path.open()}
    t0 = time.time()
    with path.open("a") as f:
        for i, (tid, p) in enumerate(problems.items()):
            if tid in done:
                continue
            content = f"{PREFIX}\n```\n{p['prompt'].strip()}\n```"
            try:
                r = chat(host, model, content, num_ctx, num_predict)
            except Exception:
                try:
                    r = chat(host, model, content, num_ctx, num_predict)
                except Exception as e:
                    # Record an empty solution; a missing sample would otherwise be silently skipped.
                    r = {"message": {"content": ""}, "error": str(e)}
            f.write(json.dumps({"task_id": tid, "solution": r["message"]["content"],
                                "eval_count": r.get("eval_count"), "error": r.get("error")}) + "\n")
            f.flush()
            if i % 25 == 0:
                print(f"{model} {dataset} {i}/{len(problems)} {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    import fire
    fire.Fire(main)
