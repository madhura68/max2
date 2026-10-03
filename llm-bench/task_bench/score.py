#!/usr/bin/env python3
"""Task-bench scorer (M7, Task 7): the table per task and model, the counts and the verdict of spec 1.

  ./score.py <dir> --models <hosted> <gsq> [--ledger <ledger.jsonl>]

<dir> is the --out of a window of run.py, or any directory above it (the copy of a whole window directory, say). A result counts
when it is <dir>/**/<label>/<run>/bench-result.json, with <label> a directory named after the label in its own bench-result.json,
as run.py lays them out. A run that sits anywhere else, like the practice run in proef/, is not the driver's and is not read.
Only bench-result.json of a run is ever opened: ws/ and ws-deps/ hold work trees, where a named pipe would hang a read, and they
are not walked.

--models are the two labels, the hosted one first: verdict(h, g) wants h of the hosted label and g of the other. The scorer only
scores a complete set: it refuses (exit 2, and nothing is written) unless each label has exactly 12 different cases, the same 12
for both, and the last status of every one of them is a model status (geslaagd, verborgen_tests_rood, verify_rood, limiet,
geen_wijzigingen). The last status of a case is that of its newest bench-result.json by mtime (rsync -a keeps them); when two share
one, the benchfout counts as the later, so a case whose last status cannot be told is not scored. A benchfout as the last status,
an aborted run included, means the set is not complete.

It writes <dir>/summary.csv (a row per case and label, from the result that counts), prints the table, the counts and the verdict, and
with --ledger the total of the ledger (math.fsum, a missing amount counted as 0) and how many amounts are missing.

Stdlib only.
"""
import argparse
import csv
import os
import sys
from collections import namedtuple
from pathlib import Path

from run import MODEL_STATUSES, RunError, amount, ledger_total, ledger_unknown, load_bench_result, read_ledger

THRESHOLD = 9  # van 12 (spec §1)
SET_SIZE = 12
PRUNED = ("ws", "ws-deps")        # the work trees of a run: never walked
CSV_COLUMNS = ["case", "label", "status", "run_id", "attempts", "run_status", "error_code", "model_turns", "tool_calls", "tool_errors",
               "input_tokens", "output_tokens", "cost_usd", "duration_s", "providers", "retries", "hidden_pass"]

# One bench-result.json of a case: the mtime of the file (ns), the name of its run directory, the parsed result.
Attempt = namedtuple("Attempt", "mtime_ns name result")


def verdict(h, g):
    """Spec §1: oordeel voor gehost h en gsq g (geslaagd van 12), met de grensregels."""
    if h < THRESHOLD:
        row, base = 1, "gezakt"
    elif g >= THRESHOLD:
        row, base = 2, "max2 volstaat"
    elif h - g >= 3:
        row, base = 3, "meerwaarde"
    else:
        return "onbeslist"  # rij 4: verschil te klein
    boundary = h in (THRESHOLD, THRESHOLD - 1)                                 # gehost precies 9 of 8
    boundary |= row in (2, 3) and g in (THRESHOLD, THRESHOLD - 1)               # gsq 9 of 8 waar die beslist
    boundary |= row == 3 and h - g == 3                                          # verschil precies 3, alleen rij 3
    return "onbeslist" if boundary else base


def find_results(root, labels):
    """{label: {case id: [Attempt, ...]}} for every result of the labels under root. A directory named like a label is a label
    directory; each of its subdirectories that holds a bench-result.json is a run (and not walked into: its work trees are in there),
    the others are walked on. A result counts when it has a status of the six, says the label of its directory, and names a case."""
    found = {label: {} for label in labels}
    for here, dirs, _ in os.walk(root):
        dirs[:] = [d for d in dirs if d not in PRUNED]
        label = os.path.basename(here)
        if label not in found:
            continue
        for name in list(dirs):
            path = Path(here, name, "bench-result.json")
            try:
                is_run = path.is_file()          # False for a named pipe, which is never opened
            except OSError:
                is_run = False
            if not is_run:
                continue
            dirs.remove(name)
            result = load_bench_result(path)
            case_id = result.get("caseId") if result is not None else None
            if result is None or result.get("label") != label or not (isinstance(case_id, str) and case_id):
                continue
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                continue
            found[label].setdefault(case_id, []).append(Attempt(mtime, name, result))
    return found


def last_result(attempts):
    """The Attempt that counts: the newest mtime; on a tie the benchfout is the later one (fail closed), then the name."""
    return max(attempts, key=lambda a: (a.mtime_ns, a.result["status"] == "benchfout", a.name))


def refusals(found, labels):
    """The reasons not to score this, one line each; [] when the set is complete (see the docstring of this file)."""
    problems = []
    for label in labels:
        cases = found[label]
        if len(cases) != SET_SIZE:
            problems.append(f"{label}: {len(cases)} cases with a result, {SET_SIZE} needed")
        for case_id in sorted(cases):
            last = last_result(cases[case_id])
            if last.result["status"] not in MODEL_STATUSES:
                problems.append(f"{label}: the last status of {case_id} is {last.result['status']} ({last.name}), not a model status")
    first, second = labels
    only_first, only_second = sorted(set(found[first]) - set(found[second])), sorted(set(found[second]) - set(found[first]))
    if only_first or only_second:
        problems.append(f"{first} and {second} do not have the same cases: only {first}: {', '.join(only_first) or 'none'}; "
                        f"only {second}: {', '.join(only_second) or 'none'}")
    return problems


def summary_row(case_id, label, attempts):
    """The row of summary.csv for a case and label, from the result that counts; empty where the result says nothing."""
    result = last_result(attempts).result
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    hidden = result.get("hidden") if isinstance(result.get("hidden"), dict) else {}
    cost, millis = amount(usage.get("costUsd")), result.get("durationMs")
    providers = [p for p in (result.get("providers") if isinstance(result.get("providers"), list) else []) if isinstance(p, str)]
    retries = result.get("retries") if isinstance(result.get("retries"), list) else []
    return {"case": case_id, "label": label, "status": result["status"], "run_id": last_result(attempts).name, "attempts": len(attempts),
            "run_status": result.get("runStatus", ""), "error_code": error.get("code", ""),
            "model_turns": usage.get("turns", ""), "tool_calls": usage.get("toolCalls", ""), "tool_errors": usage.get("toolErrors", ""),
            "input_tokens": usage.get("inputTokens", ""), "output_tokens": usage.get("outputTokens", ""),
            "cost_usd": "" if cost is None else cost,
            "duration_s": round(millis / 1000, 3) if isinstance(millis, (int, float)) and not isinstance(millis, bool) else "",
            "providers": ";".join(dict.fromkeys(providers)), "retries": len(retries),
            "hidden_pass": str(hidden["pass"]).lower() if isinstance(hidden.get("pass"), bool) else ""}


def write_summary(root, rows):
    try:
        with open(Path(root) / "summary.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    except OSError as e:
        raise RunError(f"cannot write summary.csv in {root}: {e.strerror or type(e).__name__}") from None


def render(root, labels, found, counts, ledger):
    hosted, gsq = labels
    cases = sorted(found[hosted])
    last = {label: {case_id: last_result(found[label][case_id]).result["status"] for case_id in cases} for label in labels}
    lines = [f"Task-bench: {root}", "", f"| Taak | {hosted} | {gsq} |", "|---|---|---|"]
    lines += [f"| {case_id} | {last[hosted][case_id]} | {last[gsq][case_id]} |" for case_id in cases]
    lines.append("")
    for label in labels:
        lines.append(f"Tellingen {label}: " + ", ".join(f"{status} {counts[label][status]}" for status in MODEL_STATUSES))
    h, g = counts[hosted]["geslaagd"], counts[gsq]["geslaagd"]
    lines += ["", f"Geslaagd: {hosted} {h} van {SET_SIZE}, {gsq} {g} van {SET_SIZE}", f"Oordeel: {verdict(h, g)}"]
    if ledger is not None:
        lines.append(f"Grootboek: ${ledger_total(ledger):.4f} in {len(ledger)} regels, {ledger_unknown(ledger)} zonder bedrag "
                     f"(null, geteld als 0)")
    return "\n".join(lines)


def score(root, labels, ledger_path=None):
    """Score the directory: the report as text, with summary.csv written next to the results. RunError when it must not be scored."""
    root = Path(root)
    if not root.is_dir():
        raise RunError(f"{root} is not a directory")
    if labels[0] == labels[1]:
        raise RunError("--models names the same label twice: it takes the hosted label and the gsq label")
    found = find_results(root, labels)
    problems = refusals(found, labels)
    if problems:
        raise RunError("\n".join(problems))
    ledger = read_ledger(ledger_path) if ledger_path else None
    counts = {label: {status: 0 for status in MODEL_STATUSES} for label in labels}
    rows = []
    for label in labels:
        for case_id in sorted(found[label]):
            row = summary_row(case_id, label, found[label][case_id])
            counts[label][row["status"]] += 1
            rows.append(row)
    write_summary(root, rows)
    return render(root, labels, found, counts, ledger)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    ap.add_argument("dir", help="the --out of a window of run.py, or a directory above it")
    ap.add_argument("--models", nargs=2, required=True, metavar=("HOSTED", "GSQ"), help="the hosted label and the gsq label, in this order")
    ap.add_argument("--ledger", help="the ledger of run.py: print its total and the number of missing amounts")
    args = ap.parse_args(argv)
    try:
        print(score(args.dir, args.models, args.ledger))
    except RunError as e:
        for line in str(e).splitlines():
            print(f"score.py: {line}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
