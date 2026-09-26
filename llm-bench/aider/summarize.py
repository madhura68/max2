#!/usr/bin/env python3
"""Summarize Aider benchmark run directories into a markdown table per exercise set.

  ./summarize.py /var/tmp/llm-bench/aider-runs > table.md

Reads every <RUNS>/<timestamp>--<exercises>--<model>/**/.aider.results.json. "Pass" = the last
try's tests passed (pass_rate_2 with --tries 2); "1e poging" = passed on the first try.
"""
import collections
import glob
import json
import sys
from pathlib import Path


def main(runs):
    sets = collections.defaultdict(dict)
    for d in sorted(Path(runs).glob("20*--*--*")):
        _, ex, model = d.name.split("--", 2)
        results = [json.loads(Path(f).read_text()) for f in glob.glob(f"{d}/*/exercises/practice/*/.aider.results.json")]
        langs = {f.split("/")[-5]: None for f in glob.glob(f"{d}/*/exercises/practice/*/.aider.results.json")}
        per = collections.defaultdict(lambda: [0, 0])
        for f in glob.glob(f"{d}/*/exercises/practice/*/.aider.results.json"):
            r = json.loads(Path(f).read_text())
            lang = f.split("/")[-5]
            per[lang][1] += 1
            per[lang][0] += bool(r["tests_outcomes"] and r["tests_outcomes"][-1])
        n = len(results)
        sets[ex][model] = {
            "n": n,
            "pass1": sum(bool(r["tests_outcomes"] and r["tests_outcomes"][0]) for r in results),
            "pass2": sum(bool(r["tests_outcomes"] and r["tests_outcomes"][-1]) for r in results),
            "malformed": sum(1 for r in results if r["num_malformed_responses"]),
            "sec": round(sum(r["duration"] for r in results) / n) if n else 0,
            "per": dict(sorted(per.items())),
        }
        del langs

    for ex, models in sets.items():
        langs = sorted({l for m in models.values() for l in m["per"]})
        print(f"### {ex}\n")
        print("| Model | 1e poging | Na 2 pogingen | Opgaven met onbruikbare edit | s/opgave | " + " | ".join(langs) + " |")
        print("|---|---|---|---|---|" + "---|" * len(langs))
        for model, m in sorted(models.items(), key=lambda kv: -kv[1]["pass2"]):
            cells = " | ".join(f"{m['per'].get(l, [0, 0])[0]}/{m['per'].get(l, [0, 0])[1]}" for l in langs)
            print(f"| {model} | {m['pass1']}/{m['n']} | **{m['pass2']}/{m['n']}** ({100 * m['pass2'] / m['n']:.1f}%) | "
                  f"{m['malformed']} | {m['sec']} | {cells} |")
        print()


if __name__ == "__main__":
    main(sys.argv[1])
