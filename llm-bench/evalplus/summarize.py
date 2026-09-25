#!/usr/bin/env python3
"""Summarize an EvalPlus run directory from run.sh into a CSV and a markdown table.

  ./summarize.py /var/tmp/llm-bench/evalplus-2026-09-25 > table.md

pass@1 is computed from the *_eval_results.json files (greedy, one sample per task):
base = base tests pass, plus = base and extra tests pass. Tasks without a result count as a fail.
"naam-gecorrigeerd" uses mbpp.aliased.jsonl from alias_fix.py (see there) when present.
"""
import csv
import json
import statistics
import sys
from pathlib import Path

TOTALS = {"humaneval": 164, "mbpp": 378}


def score(results_file, total):
    ev = json.loads(results_file.read_text())["eval"]
    base = sum(v[0]["base_status"] == "pass" for v in ev.values())
    plus = sum(v[0]["base_status"] == "pass" and v[0]["plus_status"] == "pass" for v in ev.values())
    return round(100 * base / total, 1), round(100 * plus / total, 1)


def main(root):
    root = Path(root)
    rows = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        row = {"model": d.name}
        for ds, total in TOTALS.items():
            res = d / f"{ds}.raw-sanitized_eval_results.json"
            raw = d / f"{ds}.raw.jsonl"
            if res.exists():
                row[f"{ds}_base"], row[f"{ds}_plus"] = score(res, total)
            if raw.exists():
                lines = [json.loads(l) for l in raw.open()]
                row[f"{ds}_n"] = len(lines)
                row[f"{ds}_errors"] = sum(1 for l in lines if l.get("error"))
                counts = [l["eval_count"] for l in lines if l.get("eval_count")]
                row[f"{ds}_median_tokens"] = int(statistics.median(counts)) if counts else None
        aliased = d / "mbpp.aliased_eval_results.json"
        if aliased.exists():
            row["mbpp_named_base"], row["mbpp_named_plus"] = score(aliased, TOTALS["mbpp"])
        rows.append(row)

    fields = ["model"] + [f"{ds}_{k}" for ds in TOTALS for k in ("base", "plus", "n", "errors", "median_tokens")] \
        + ["mbpp_named_base", "mbpp_named_plus"]
    with open(root / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print("| Model | HumanEval | HumanEval+ | MBPP | MBPP+ | MBPP / MBPP+ naam-gecorrigeerd | Mediaan tokens HE / MBPP |")
    print("|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: -(r.get("humaneval_plus") or 0) - (r.get("mbpp_plus") or 0)):
        g = lambda k: "–" if r.get(k) is None else r[k]
        print(f"| {r['model']} | {g('humaneval_base')} | {g('humaneval_plus')} | {g('mbpp_base')} | "
              f"{g('mbpp_plus')} | {g('mbpp_named_base')} / {g('mbpp_named_plus')} | {g('humaneval_median_tokens')} / {g('mbpp_median_tokens')} |")


if __name__ == "__main__":
    main(sys.argv[1])
