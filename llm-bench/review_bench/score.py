#!/usr/bin/env python3
"""Review-bench scorer (M8, Task 11): the blind score sheets, the decision rule of spec 1 and the report of spec 4.9. It reads what
run.py leaves on disk and writes nothing into a run.

  ./score.py sheets <out> [--only-f1]
  ./score.py smoke <dir> --scores <scores.jsonl>
  ./score.py report <out> --scores <scores.jsonl> --decisions <decisions.json> --ledger <file> --date <YYYY-MM-DD> --preflight <file>
                     --models <configuration...> --runs <n> [--smoke-dir <dir> --smoke-scores <file>] [--results-dir <dir>]

Every subcommand reads <out>/<label>/r<n>/*/bench-result.json (the layout of run.py). Of the results of one (label, n) the one that
counts is a result of a model status (beoordeeld, limiet, resultaat_ongeldig) before any other, and then the newest by mtime; a tie
goes to the later run directory name. A result counts only when its own `label` is that of the directory. Everything is decided on
`status`, not on whether a result is present: an accepted result can sit on a run that did not end beoordeeld.

sheets. A sheet <out>/sheets/<id>.md for each run that ended beoordeeld, with <id> 8 random hex characters, and nothing of the run but
result.summary and result.report_markdown. The link id -> run directory (a path under <out>) is in <out>/sheets-key.json and nowhere
else; whoever scores does not open it. A second call keeps the ids it has and adds the new runs. The text of the model is masked first:
every configuration name, every OpenRouter model of the bench and the words claude, anthropic, sonnet, gpt, openai, qwen, deepseek, glm,
z-ai, z.ai, minimax, luna, sol, opus, haiku, codex, gemini and kimi (a letter on either side makes it another word, a digit or a dash
does not) become [model], in any case, because a report can name its own model, also one of a family the eight do not cover.
--only-f1 asks for f1 only (the smoke).

scores.jsonl, one line per sheet, written by hand with rubric.md:
  {"sheet", "f1": major|minor|nee, "f2": major|minor|nee, "minors": ["M1".."M6"], "extra": [{"key", "voorstel": geldig|ongeldig, "reden"}]}
  (the smoke: {"sheet", "f1"}). decisions.json: {key: geldig|ongeldig}, one decision per key for every run that has the key.

The decision rule (spec 1), as pure functions: run_voldoet, model_oordeel, oordelen. A run complies when it is beoordeeld, its result
has outcome succeeded and verdict NO-GO, f1 is major, and no extra of it is decided ongeldig. A model is `open` while any extra of it has
no decision, else kandidaat when every run of the expected ones complies (3 of 3), twijfel when all but one do, and valt af otherwise.
When neither claude-sonnet-5.5-or nor gpt-6.1-sol-or is kandidaat, every model is `onbeslist: runtime`.

smoke. One line per run (status, outcome, verdict, f1) and then `rookproef: door` (exit 0) or `rookproef: stop` (exit 1). It is door
when a result exists of qwen3.8-or-128k and of claude-sonnet-5.5-or, neither is a benchfout, and the runs of sonnet are beoordeeld with
outcome succeeded, NO-GO and f1 major. A result that is missing is a stop, and so is a scores file that is not there: with no run
beoordeeld there is no sheet and no scores. A scores file that is there but cannot be read is an error (exit 2).

report. <results-dir>/review-bench-<date>.md (default llm-bench/results): the verdict per model, the open models set against the harness
controls (spec 4.9, "Eerste vergelijking"), cost, tokens, context and time, one row
per run with the read_file calls on sources/doc from trace.jsonl (the path is normalised first: an absolute path with /<runId>/root/ in
it becomes the part after it, then posixpath.normpath), every expected run (--models x --runs, also of a configuration that never ran)
that was not judged with the first reason that fits, the preflight, the smoke, the production runs as context, and the ledger. The
reason is, in this order: preflight afgewezen (the preflight file, or skipped.json), niet geprobed (the benchError, or skipped.json),
the status of the result with its error code, budget bereikt or gestopt (skipped.json), niet gestart. A run with a result of a model
status that is not beoordeeld says that status: it ran. The report is refused (exit 2) when a judged expected run has no sheet or no
score, when a score cannot be used, or when an argument is wrong: a verdict from incomplete input would be a wrong one.

Exit status: 0 done, 1 `rookproef: stop`, 2 the call or the input is wrong. Stdlib only.
"""
import argparse
import importlib.util
import json
import math
import os
import posixpath
import random
import re
import sys
import uuid
from collections import namedtuple
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_driver():
    """run.py of this directory, loaded by its path under a name of its own: task_bench has a run.py and a score.py too, and a plain
    `import run` would find whichever comes first on sys.path."""
    spec = importlib.util.spec_from_file_location("review_bench_run", HERE / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load_driver()
MODEL_STATUSES = R.MODEL_STATUSES
JUDGED = "beoordeeld"
BENCHFOUT = "benchfout"
EXIT_STOP, EXIT_USAGE = 1, 2

CASE_ID = "macsearch-idea263-spec-r5"
RUBRIC = f"llm-bench/review_bench/cases/{CASE_ID}/rubric.md"
DEFAULT_RESULTS_DIR = HERE.parent / "results"
KEY_FILE, SKIPPED_FILE = "sheets-key.json", "skipped.json"
WINDOW = 131072                 # the contextTokens of the case: the window peakInputTokens is put next to
MASK = "[model]"
SOURCE_DOC = "sources/doc"

OPENROUTER = {      # the configurations of spec 4.6 and the OpenRouter model behind each
    "qwen3.8-or-128k": "qwen/qwen3.8-27b",
    "deepseek-v4-flash-or": "deepseek/deepseek-v4-flash",
    "deepseek-v4-pro-or": "deepseek/deepseek-v4-pro",
    "glm-5.3-or": "z-ai/glm-5.3",
    "minimax-m3-or": "minimax/minimax-m3",
    "gpt-6-luna-or": "openai/gpt-6-luna",
    "claude-sonnet-5.5-or": "anthropic/claude-sonnet-5.5",
    "gpt-6.1-sol-or": "openai/gpt-6.1-sol",
}
VENDOR_WORDS = ("claude", "anthropic", "sonnet", "gpt", "openai", "qwen", "deepseek", "glm", "z-ai", "z.ai", "minimax", "luna", "sol",
                "opus", "haiku", "codex", "gemini", "kimi")
CONTROLS = ("claude-sonnet-5.5-or", "gpt-6.1-sol-or")           # the harness controls of spec 1
OPEN_MODELS = ("qwen3.8-or-128k", "deepseek-v4-flash-or", "deepseek-v4-pro-or", "glm-5.3-or", "minimax-m3-or")      # the five existing ones (spec 4.6)
PROPRIETARY = ("gpt-6-luna-or",)                                # proprietary, and no control
SMOKE_LABELS = ("qwen3.8-or-128k", "claude-sonnet-5.5-or")      # the smoke (spec 4.8, step 6): the first one is judged on not failing
SMOKE_CONTROL = SMOKE_LABELS[1]                                 # ... the second on finding the known MAJOR

GROUP_CONTROL, GROUP_OPEN, GROUP_PROPRIETARY, GROUP_OTHER = "harness-controle", "open model", "propriëtair, geen controle", "overig"
GROUP_ORDER = (GROUP_CONTROL, GROUP_OPEN, GROUP_PROPRIETARY, GROUP_OTHER)

GRADES = ("major", "minor", "nee")
MINORS = tuple(f"M{n}" for n in range(1, 7))
PROPOSALS = ("geldig", "ongeldig")                              # a proposal of the scorer and a decision of JP
KANDIDAAT, TWIJFEL, VALT_AF, OPEN, RUNTIME = "kandidaat", "twijfel", "valt af", "open", "onbeslist: runtime"

PRODUCTION_RUNS = (("1a78c1b8", "Claude Code", "$0,39"), ("7146cbe9", "Codex CLI", "≈ $0,10"))      # spec 4.9: context rows


class ScoreError(Exception):
    """A problem with the call or with the input: one line on stderr and exit status 2."""


# ---------------------------------------------------------------------------------------------------------------------
# the decision rule (spec 1): pure functions
# ---------------------------------------------------------------------------------------------------------------------

def run_voldoet(result, score, decisions):
    """Whether a run complies. result is its bench-result.json (a dict), score its line of scores.jsonl (None: not scored) and decisions
    {key: geldig|ongeldig}. It does when the status is beoordeeld, the DispatchResult has outcome succeeded and verdict NO-GO, f1 is
    major, and no extra of the run is decided ongeldig. An extra without a decision does not fail the run: it makes the model open."""
    if not (isinstance(result, dict) and result.get("status") == JUDGED):
        return False
    dispatch = result.get("result")
    review = dispatch.get("review") if isinstance(dispatch, dict) else None
    if not (isinstance(dispatch, dict) and dispatch.get("outcome") == "succeeded"
            and isinstance(review, dict) and review.get("verdict") == "NO-GO"):
        return False
    if not (isinstance(score, dict) and score.get("f1") == "major"):
        return False
    return not any(decisions.get(item["key"]) == "ongeldig" for item in score.get("extra") or ())


def open_keys(score, decisions):
    """The keys of the extras of a score that have no decision yet."""
    return [item["key"] for item in (score or {}).get("extra") or () if item["key"] not in decisions]


def beoordeel_run(result, score, decisions):
    """The record model_oordeel works on: {"voldoet": bool, "open": bool}. A run is open when it is beoordeeld and has no score yet, or
    an extra without a decision. A run that is missing (result None) or not beoordeeld is neither: it does not comply."""
    judged = isinstance(result, dict) and result.get("status") == JUDGED
    return {"voldoet": run_voldoet(result, score, decisions), "open": judged and (score is None or bool(open_keys(score, decisions)))}


def model_oordeel(runs):
    """The verdict of one model from the records of its expected runs (a missing run is a record that does not comply): open as long as
    any run has an extra without a decision, else kandidaat when all of them comply, twijfel when all but one do, and valt af."""
    if any(run["open"] for run in runs):
        return OPEN
    total, complying = len(runs), sum(1 for run in runs if run["voldoet"])
    if total and complying == total:
        return KANDIDAAT
    if total >= 2 and complying == total - 1:
        return TWIJFEL
    return VALT_AF


def bench_geldig(eigen, controls=CONTROLS):
    """Whether the bench is valid: at least one of the harness controls is a kandidaat. eigen is {model: its own verdict}; a control that
    did not run has no run that complies, and a control that is open is no kandidaat."""
    return any(eigen.get(control) == KANDIDAAT for control in controls)


def oordelen(modellen, controls=CONTROLS):
    """{model: verdict} for modellen = {model: [records]}. When neither harness control is a kandidaat, the verdict of every model is
    `onbeslist: runtime` (spec 1): the difference with the production reviewers is then in the harness, and is looked into first."""
    eigen = {label: model_oordeel(runs) for label, runs in modellen.items()}
    return eigen if bench_geldig(eigen, controls) else {label: RUNTIME for label in eigen}


# ---------------------------------------------------------------------------------------------------------------------
# the blind sheet
# ---------------------------------------------------------------------------------------------------------------------

def build_mask():
    """One expression for everything that names a model: the configurations, the OpenRouter models and the family words, longest first.
    A letter on either side makes a word another word (solution, console), a digit or a dash does not (Qwen3, GPT-6)."""
    names = sorted({*OPENROUTER, *OPENROUTER.values(), *VENDOR_WORDS}, key=len, reverse=True)
    return re.compile(r"(?<![^\W\d_])(?:" + "|".join(re.escape(name) for name in names) + r")(?![^\W\d_])", re.IGNORECASE)


IDENTITY = build_mask()


def mask_identity(text):
    return IDENTITY.sub(MASK, text)


def sheet_fields(sheet_id, only_f1):
    """The one line with the fields to fill, and the lines that explain them."""
    if only_f1:
        line = '{"sheet": "%s", "f1": "major|minor|nee"}' % sheet_id
        return line, ["- `f1`: het label dat het model zelf gaf aan de bevinding die de kern van F1 raakt: `major` voor MAJOR of BLOCKER, "
                      "`minor` voor MINOR, `nee` als geen bevinding die kern raakt."]
    line = ('{"sheet": "%s", "f1": "major|minor|nee", "f2": "major|minor|nee", "minors": ["M1".."M6"], '
            '"extra": [{"key": "...", "voorstel": "geldig|ongeldig", "reden": "..."}]}' % sheet_id)
    return line, ["- `f1`, `f2`: het label dat het model zelf gaf aan de bevinding die die kern raakt: `major` voor MAJOR of BLOCKER, "
                  "`minor` voor MINOR, `nee` als geen bevinding die kern raakt.",
                  "- `minors`: de M-punten uit de rubric die een bevinding raakt; `[]` als er geen is.",
                  "- `extra`: elke andere BLOCKER of MAJOR, met een genormaliseerde `key`, een voorstel `geldig` of `ongeldig` en één zin `reden`; "
                  "`[]` als er geen is."]


def sheet_text(sheet_id, dispatch, only_f1):
    """The sheet of one run: the instruction, and result.summary and result.report_markdown with the names of models masked.
    Nothing else of the run, and nothing that links the sheet to a model."""
    line, explanation = sheet_fields(sheet_id, only_f1)
    asked = "Rookproef: vul alleen `f1` in." if only_f1 else "Vul alle velden in."
    summary = mask_identity(str(dispatch.get("summary") or "")).strip()
    report = mask_identity(str(dispatch.get("report_markdown") or "")).strip()
    return "\n".join([
        f"# Scoreblad {sheet_id}", "",
        "Dit blad is blind: het noemt geen model en geen configuratie, en `sheets-key.json` blijft dicht. "
        f"Beoordeel de tekst hieronder met de rubric `{RUBRIC}`. {asked}", "",
        "Schrijf één regel in scores.jsonl, met precies deze velden:", "", line, "", *explanation, "",
        "## Samenvatting", "", summary, "",
        "## Rapport", "", report, ""])


# ---------------------------------------------------------------------------------------------------------------------
# what is on disk
# ---------------------------------------------------------------------------------------------------------------------

# One result that counts: its label, the run number, the run directory, the mtime of its bench-result.json (ns) and the parsed result.
Found = namedtuple("Found", "label run directory mtime_ns result")


def run_path(found):
    """The place of a run under <out>: what sheets-key.json holds."""
    return f"{found.label}/r{found.run}/{found.directory.name}"


def subdirectories(path):
    try:
        return sorted(p for p in Path(path).iterdir() if p.is_dir())
    except OSError as e:
        raise ScoreError(f"cannot list {path}: {e.strerror or type(e).__name__}") from None


def newest(found):
    """The result that counts of one (label, n): one with a model status before any other, then the newest by mtime, then the later name."""
    pool = [f for f in found if f.result["status"] in MODEL_STATUSES] or found
    return max(pool, key=lambda f: (f.mtime_ns, f.directory.name))


def collect(out, dropped=None):
    """{(label, n): Found} for <out>/<label>/r<n>/*/bench-result.json. Only a valid result whose own label is that of its directory.
    A bench-result.json that is there but is not one (unreadable, no valid status, another label) is left out, and its path under
    <out> goes into the list dropped, when one is given."""
    out = Path(out)
    if not out.is_dir():
        raise ScoreError(f"{out} is not a directory")
    found = {}
    for label_dir in subdirectories(out):
        for round_dir in subdirectories(label_dir):
            match = re.fullmatch(r"r([1-9][0-9]*)", round_dir.name)
            if not match:
                continue
            for run_dir in subdirectories(round_dir):
                path = run_dir / "bench-result.json"
                result = R.load_bench_result(path)
                if result is None or result.get("label") != label_dir.name:
                    if dropped is not None and os.path.lexists(path):
                        dropped.append(path.relative_to(out).as_posix())
                    continue
                found.setdefault((label_dir.name, int(match[1])), []).append(
                    Found(label_dir.name, int(match[1]), run_dir, path.stat().st_mtime_ns, result))
    return {key: newest(candidates) for key, candidates in found.items()}


def read_key(out):
    """{sheet id: run path} of <out>/sheets-key.json, None when there is none."""
    path = Path(out) / KEY_FILE
    if not path.is_file():
        return None
    key = R.read_json_object(path)
    if key is None or not all(isinstance(sheet, str) and isinstance(where, str) for sheet, where in key.items()):
        raise ScoreError(f"{path} is no {KEY_FILE}: it has to be an object of sheet id -> run directory")
    return key


def read_jsonl(path, what):
    """[(line number, object)] of a JSON-lines file; a blank line is skipped. An error names the line and never quotes it."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError) as e:
        raise ScoreError(f"cannot read {what} {path}: {type(e).__name__}") from None
    rows = []
    for n, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (ValueError, RecursionError):
            raise ScoreError(f"{what} {path}: line {n} is not JSON") from None
        if not isinstance(value, dict):
            raise ScoreError(f"{what} {path}: line {n} is no JSON object")
        rows.append((n, value))
    return rows


def check_score(entry, only_f1, where):
    """The fields of one line of scores.jsonl, checked: {f1} or {f1, f2, minors, extra}. A finding counts once, so a repeated M-point is one."""
    def grade(name):
        if entry.get(name) not in GRADES:
            raise ScoreError(f"{where}: {name} has to be one of {', '.join(GRADES)}")
        return entry[name]
    checked = {"f1": grade("f1")}
    if only_f1:
        return checked
    checked["f2"] = grade("f2")
    minors = entry.get("minors")
    if not (isinstance(minors, list) and all(isinstance(m, str) and m in MINORS for m in minors)):
        raise ScoreError(f"{where}: minors has to be a list with points from {MINORS[0]} to {MINORS[-1]}")
    checked["minors"] = sorted(set(minors))
    extras = entry.get("extra")
    if not isinstance(extras, list):
        raise ScoreError(f"{where}: extra has to be a list")
    checked["extra"] = []
    for item in extras:
        if not (isinstance(item, dict) and isinstance(item.get("key"), str) and item["key"].strip()
                and item.get("voorstel") in PROPOSALS and isinstance(item.get("reden"), str)):
            raise ScoreError(f"{where}: an extra needs a key, a voorstel ({' or '.join(PROPOSALS)}) and a reden")
        checked["extra"].append({"key": item["key"], "voorstel": item["voorstel"], "reden": item["reden"]})
    return checked


def load_scores(path, key, only_f1=False):
    """{sheet id: score} of scores.jsonl. A sheet that is not in key, a sheet twice and a field that does not fit are errors (ScoreError)."""
    scores = {}
    for n, entry in read_jsonl(path, "scores"):
        where = f"scores {path}: line {n}"
        sheet = entry.get("sheet")
        if not (isinstance(sheet, str) and sheet in key):
            raise ScoreError(f"{where}: the sheet is not in {KEY_FILE}")
        if sheet in scores:
            raise ScoreError(f"{where}: the sheet {sheet} has a score already")
        scores[sheet] = check_score(entry, only_f1, where)
    return scores


def load_decisions(path):
    """{key: geldig|ongeldig} of decisions.json."""
    decisions = R.read_json_object(path)
    if decisions is None:
        raise ScoreError(f"--decisions {path} is not a file with a JSON object")
    for name, decision in decisions.items():
        if decision not in PROPOSALS:
            raise ScoreError(f"--decisions {path}: the decision for {name} has to be {' or '.join(PROPOSALS)}")
    return decisions


def load_skipped(directory):
    """{(label, run): reason} of <directory>/skipped.json; {} when there is none or it is unusable (the results are the facts)."""
    try:
        rows = json.loads((Path(directory) / SKIPPED_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    if not isinstance(rows, list):
        return {}
    return {(row["label"], row["run"]): row["reason"] for row in rows
            if isinstance(row, dict) and isinstance(row.get("label"), str) and isinstance(row.get("run"), int)
            and isinstance(row.get("reason"), str)}


def scores_by_run(out, scores_path, only_f1):
    """({run path: score}, {sheet id: run path}) for the scores of a directory of runs. No key at all is an error as soon as something
    has to be tied to it."""
    key = read_key(out)
    if key is None:
        if read_jsonl(scores_path, "scores"):
            raise ScoreError(f"{Path(out) / KEY_FILE} is not there; run `score.py sheets {out}` first")
        return {}, {}
    scores = load_scores(scores_path, key, only_f1)
    return {key[sheet]: score for sheet, score in scores.items()}, key


# ---------------------------------------------------------------------------------------------------------------------
# the trace
# ---------------------------------------------------------------------------------------------------------------------

def normalise_path(path, run_id):
    """The path of a tool call relative to the root of the run: an absolute path with /<runId>/root/ in it becomes the part after it, and
    posixpath.normpath settles ./ and // and ../ (so ./sources/doc is sources/doc)."""
    marker = f"/{run_id}/root/"
    if path.startswith("/") and marker in path:
        path = path.split(marker, 1)[1]
    return posixpath.normpath(path)


def count_sources_doc(trace_path, run_id):
    """(read_file calls on sources/doc, of which with an offset or a limit) from a trace.jsonl, None when there is no trace. A call whose
    arguments are not parseable is no call on sources/doc. 'With offset/limit' is a call whose arguments carry that key."""
    total = limited = 0
    if not Path(trace_path).is_file():          # a named pipe is no file, and reading one would hang
        return None
    try:
        with open(trace_path, encoding="utf-8", errors="replace") as trace:
            for line in trace:
                try:
                    entry = json.loads(line)
                except (ValueError, RecursionError):
                    continue
                if not (isinstance(entry, dict) and entry.get("type") == "tool_call" and entry.get("name") == "read_file"):
                    continue
                arguments = entry.get("arguments")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except (ValueError, RecursionError):
                        continue
                if not (isinstance(arguments, dict) and isinstance(arguments.get("path"), str)):
                    continue
                if normalise_path(arguments["path"], run_id) == SOURCE_DOC:
                    total += 1
                    limited += "offset" in arguments or "limit" in arguments
    except OSError:
        return None
    return total, limited


# ---------------------------------------------------------------------------------------------------------------------
# small formatters
# ---------------------------------------------------------------------------------------------------------------------

def runs_phrase(n, what):
    """'1 run heeft er geen' / '2 runs hebben er geen': what is the rest of the sentence for the singular and the plural."""
    singular, plural = what
    return f"{n} {'run' if n == 1 else 'runs'} {singular if n == 1 else plural}"


def one_line(text, limit=200):
    return " ".join(str(text).split())[:limit]


def cell(value):
    return one_line(value, 400).replace("|", "\\|")


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    return lines + ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]


def decimal(value, digits=1):
    return f"{value:.{digits}f}".replace(".", ",")


def usd(value):
    return "onbekend" if value is None else "$" + decimal(value, 4)


def number(value):
    """value as a float when it is a number (a bool is none), else None."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def mean(values):
    return math.fsum(values) / len(values) if values else None


def dispatch_of(result):
    dispatch = result.get("result") if isinstance(result, dict) else None
    return dispatch if isinstance(dispatch, dict) else {}


def outcome_of(result):
    return dispatch_of(result).get("outcome") or "-"


def verdict_of(result):
    review = dispatch_of(result).get("review")
    return (review.get("verdict") if isinstance(review, dict) else None) or "-"


def error_code(result):
    """The error code of a result, else the first words of its benchError, else None."""
    error = result.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return error["code"]
    bench_error = result.get("benchError")
    return one_line(bench_error, 80) if isinstance(bench_error, str) and bench_error.strip() else None


# ---------------------------------------------------------------------------------------------------------------------
# the smoke
# ---------------------------------------------------------------------------------------------------------------------

SmokeRow = namedtuple("SmokeRow", "label run status outcome verdict f1")


def smoke_check(directory, scores_path):
    """([SmokeRow], [problems]) of a smoke directory. No problems means `rookproef: door`."""
    runs = collect(directory)
    # no run beoordeeld means no sheet, so no scores file to be written: that is a smoke that stops, not one that cannot be read
    by_run = scores_by_run(directory, scores_path, only_f1=True)[0] if Path(scores_path).exists() else {}
    skipped = load_skipped(directory)
    order = {label: n for n, label in enumerate(SMOKE_LABELS)}
    rows = []
    for (label, n), found in sorted(runs.items(), key=lambda item: (order.get(item[0][0], len(order)), item[0][0], item[0][1])):
        score = by_run.get(run_path(found)) if found.result["status"] == JUDGED else None
        rows.append(SmokeRow(label, n, found.result["status"], outcome_of(found.result), verdict_of(found.result), score["f1"] if score else "-"))
    problems = []
    for label in SMOKE_LABELS:
        mine = [row for row in rows if row.label == label]
        if not mine:
            why = next((reason for (name, _), reason in sorted(skipped.items()) if name == label), None)
            problems.append(f"{label}: geen resultaat" + (f" ({why})" if why else ""))
            continue
        for row in mine:
            where = f"{label} r{row.run}"
            if row.status == BENCHFOUT:
                problems.append(f"{where}: benchfout, de bench zelf faalde")
            elif label == SMOKE_CONTROL:
                for ok, what in ((row.status == JUDGED, f"status {row.status}, niet beoordeeld"),
                                 (row.outcome == "succeeded", f"outcome {row.outcome}, niet succeeded"),
                                 (row.verdict == "NO-GO", f"verdict {row.verdict}, niet NO-GO"),
                                 (row.f1 == "major", "f1 is niet major" if row.f1 != "-" else "f1 ontbreekt: het blad is niet gescoord")):
                    if not ok:
                        problems.append(f"{where}: {what}")
                        break
    return rows, problems


def smoke_line(row):
    return f"{row.label} r{row.run}: status={row.status} outcome={row.outcome} verdict={row.verdict} f1={row.f1}"


def command_smoke(args):
    rows, problems = smoke_check(args.dir, args.scores)
    for row in rows:
        print(smoke_line(row))
    for problem in problems:
        print(f"stop: {problem}")
    print("rookproef: stop" if problems else "rookproef: door")
    return EXIT_STOP if problems else 0


# ---------------------------------------------------------------------------------------------------------------------
# the sheets
# ---------------------------------------------------------------------------------------------------------------------

def command_sheets(args):
    out = Path(args.out)
    runs = collect(out)
    key = read_key(out) or {}
    ids = {where: sheet for sheet, where in key.items()}
    judged = [found for found in runs.values() if found.result["status"] == JUDGED]
    judged = [found for found in judged if isinstance(found.result.get("result"), dict)]
    if not judged:
        print(f"geen beoordeelde runs onder {out}: geen bladen gemaakt")
        return 0
    random.SystemRandom().shuffle(judged)           # the order of making them says nothing about the model either
    sheets = out / "sheets"
    sheets.mkdir(exist_ok=True)
    for found in judged:
        where = run_path(found)
        sheet = ids.get(where)
        while sheet is None:
            candidate = uuid.uuid4().hex[:8]
            if candidate not in key:
                sheet = candidate
        key[sheet], ids[where] = where, sheet
        (sheets / f"{sheet}.md").write_text(sheet_text(sheet, found.result["result"], args.only_f1), encoding="utf-8")
    R.write_json_replacing(out / KEY_FILE, dict(sorted(key.items())))
    print(f"{len(judged)} bladen in {sheets}; de koppeling met de runs staat in {out / KEY_FILE} (open die niet tijdens het scoren)")
    return 0


# ---------------------------------------------------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------------------------------------------------

Entry = namedtuple("Entry", "label run found score record")      # one expected run: found is None when there is no result


def not_probed(result):
    """Whether a result is the benchfout of a configuration without an accepted probe: the harness never called a model."""
    bench_error = result.get("benchError") if isinstance(result, dict) else None
    return result.get("status") == BENCHFOUT and isinstance(bench_error, str) and bench_error.startswith(R.NOT_PROBED)


def explain(found, label, n, preflight, skipped):
    """Why an expected run was not judged: the first reason that fits, in the order of the plan. None for a run that was judged."""
    status = found.result["status"] if found else None
    if status == JUDGED:
        return None
    if status in MODEL_STATUSES:            # it ran to a model status: that is what happened, whatever the preflight says now
        code = error_code(found.result)
        return f"{status}: {code}" if code else status
    skip = skipped.get((label, n), "")
    entry = preflight.get(label)
    if isinstance(entry, dict) and entry.get("ok") is False:
        return "preflight afgewezen: " + one_line(entry.get("reason") or "geen reden opgegeven")
    if skip.startswith("preflight afgewezen"):
        return skip
    if found and not_probed(found.result):
        return "niet geprobed: " + one_line(R.not_probed_detail(found.result["benchError"]))
    if skip.startswith("niet geprobed"):
        return skip
    if found:
        code = error_code(found.result)
        return f"{status}: {code}" if code else status
    return skip or R.SKIP_NOT_STARTED


def load_preflight(path, models):
    """{label: {ok, reason}} of the preflight file for the labels that have an entry; an entry that is no object with ok is an error."""
    entries = R.read_json_object(path)
    if entries is None:
        raise ScoreError(f"--preflight {path} is not a file with a JSON object")
    for label in models:
        if label in entries and not (isinstance(entries[label], dict) and isinstance(entries[label].get("ok"), bool)):
            raise ScoreError(f"--preflight {path}: the entry of {label} has to be an object with ok true or false")
    return {label: entries[label] for label in models if label in entries}


def build_entries(models, runs, found, by_run, decisions):
    entries = []
    for label in models:
        for n in range(1, runs + 1):
            result_found = found.get((label, n))
            judged = result_found is not None and result_found.result["status"] == JUDGED
            score = by_run.get(run_path(result_found)) if judged else None
            entries.append(Entry(label, n, result_found, score, beoordeel_run(result_found.result if result_found else None, score, decisions)))
    return entries


def check_complete(entries, key):
    """Every judged expected run needs a sheet and a score on it: without, a verdict would count a run that was never scored as one that
    failed. The message names sheets only, never the model behind one."""
    sheet_of = {where: sheet for sheet, where in key.items()}
    no_sheet, unscored = 0, []
    for entry in entries:
        if entry.found is None or entry.found.result["status"] != JUDGED or entry.score is not None:
            continue
        sheet = sheet_of.get(run_path(entry.found))
        if sheet is None:
            no_sheet += 1
        else:
            unscored.append(sheet)
    problems = []
    if unscored:
        problems.append(f"{len(unscored)} beoordeelde {'run heeft' if len(unscored) == 1 else 'runs hebben'} nog geen score: "
                        f"blad {', '.join(sorted(unscored))}")
    if no_sheet:
        problems.append(f"{no_sheet} beoordeelde {'run heeft' if no_sheet == 1 else 'runs hebben'} geen blad: draai `score.py sheets` opnieuw")
    if problems:
        raise ScoreError("; ".join(problems))


def warnings_for(entries, found, key, scores_path, dropped=()):
    """What is left out, said once: a bench-result.json that is no result (by its path under <out>; the report is made after the scoring,
    and `sheets` says nothing of it), results outside --models and --runs (a typo in --models shows here), and scores that belong to no
    expected, judged run that counts. A score is named by its sheet only."""
    expected = {(e.label, e.run) for e in entries}
    warnings = [f"{path} genegeerd: geen leesbaar resultaat van deze configuratie (onleesbaar, geen geldige status of een ander label)"
                for path in dropped]
    outside = sorted(name for name in found if name not in expected)
    if outside:
        warnings.append("resultaten buiten --models en --runs genegeerd: " + ", ".join(f"{label} r{n}" for label, n in outside))
    wanted = {run_path(e.found) for e in entries if e.found is not None and e.found.result["status"] == JUDGED}
    warnings += [f"het blad {sheet} hoort bij een run buiten --models en --runs, of niet meer bij het resultaat dat telt: genegeerd"
                 for sheet in sorted(load_scores(scores_path, key)) if key[sheet] not in wanted]
    return warnings


def per_model(entries, models):
    return {label: [e for e in entries if e.label == label] for label in models}


def extras_of(model_entries, decisions):
    keys = []
    for entry in model_entries:
        for item in (entry.score or {}).get("extra") or ():
            if item["key"] not in keys:
                keys.append(item["key"])
    return [f"{key} ({decisions.get(key, 'open')})" for key in keys]


def model_group(label):
    """The group of a configuration in the comparison: a fixed mapping, with `overig` for a name that is in none of the lists."""
    if label in CONTROLS:
        return GROUP_CONTROL
    if label in OPEN_MODELS:
        return GROUP_OPEN
    if label in PROPRIETARY:
        return GROUP_PROPRIETARY
    return GROUP_OTHER


def model_name(label):
    return f"{label} (controle)" if label in CONTROLS else label


def never_ran_note(group, reasons):
    """' (niet gedraaid: <reason>)' for a model of which no expected run got as far as a model: each has no result, or the benchfout of a
    configuration without a probe. The reason is the first that fits the first run (preflight afgewezen, niet geprobed, budget bereikt,
    gestopt ..., niet gestart), without its detail. The verdict word next to it does not change. '' for a model that did run."""
    if not group or not all(e.found is None or not_probed(e.found.result) for e in group):
        return ""
    why = reasons.get((group[0].label, group[0].run))
    return f" (niet gedraaid: {why.split(':')[0]})" if why else ""


def verdict_cells(models, groups, verdicts, reasons):
    """{model: verdict word, with the note of a model that never ran}."""
    return {label: verdicts[label] + never_ran_note(groups[label], reasons) for label in models}


def verdict_table(models, groups, cells, decisions):
    rows = []
    for label in models:
        group = groups[label]
        scored = [e.score for e in group if e.score and "minors" in e.score]
        rows.append([model_name(label), cells[label], f"{sum(e.record['voldoet'] for e in group)}/{len(group)}",
                     " / ".join(verdict_of(e.found.result) if e.found else "-" for e in group),
                     " / ".join(e.score["f1"] if e.score else "-" for e in group),
                     " / ".join(e.score["f2"] if e.score and "f2" in e.score else "-" for e in group),
                     decimal(mean([len(s["minors"]) for s in scored])) if scored else "-",
                     ", ".join(extras_of(group, decisions)) or "-"])
    return table(["Model", "Oordeel", "Voldoet", "Verdicts", "F1 per run", "F2 per run", "Minors (gem.)", "Extra's"], rows)


def comparison_section(models, groups, cells, own, valid):
    """Spec 4.9, 'Eerste vergelijking': the open models set against the controls, with gpt-6-luna as the proprietary one between them,
    and a group `overig` for any other name. Per model the verdict, the runs that comply and the runs in which F1 was found as major,
    and the validity of the bench. The controls come first, then the other groups, each in the order of --models."""
    def row(group_name, label):
        group = groups[label]
        return [group_name, label, cells[label], f"{sum(e.record['voldoet'] for e in group)}/{len(group)}",
                f"{sum(1 for e in group if e.score and e.score['f1'] == 'major')}/{len(group)}"]
    rows = [row(group, label) for group in GROUP_ORDER for label in models if model_group(label) == group]
    lines = [f"Geldigheid van de bench: {validity_text(own, valid)}", "",
             *table(["Groep", "Model", "Oordeel", "Voldoet", "F1 als major gevonden"], rows)]
    absent = [control for control in CONTROLS if control not in models]
    if absent:
        lines += ["", f"Controle niet in --models: {', '.join(absent)}."]
    return lines


def usage_of(result):
    return result["usage"] if isinstance(result.get("usage"), dict) else {}


def numbers(values):
    return [v for v in map(number, values) if v is not None]


def average(values, digits=0):
    values = numbers(values)
    return decimal(mean(values), digits) if values else "-"


def cost_table(models, groups):
    """Cost of all runs of a model that have an amount; the rest of the figures of the runs that ended with a model status (a benchfout
    says little about the model)."""
    rows = []
    for label in models:
        results = [e.found.result for e in groups[label] if e.found]
        ran = [r for r in results if r["status"] in MODEL_STATUSES]
        costs = [c for c in (R.amount(usage_of(r).get("costUsd")) for r in results) if c is not None]
        peaks, times = numbers(r.get("peakInputTokens") for r in ran), numbers(r.get("durationMs") for r in ran)
        errors = numbers(r.get("toolErrors") for r in ran)
        rows.append([model_name(label), usd(mean(costs)) if costs else "-", usd(max(costs)) if costs else "-",
                     f"{average(usage_of(r).get('inputTokens') for r in ran)} / {average(usage_of(r).get('outputTokens') for r in ran)}",
                     f"{int(max(peaks))} / {WINDOW} ({max(peaks) / WINDOW:.0%})" if peaks else f"- / {WINDOW}",
                     f"{decimal(mean(times) / 1000)} s" if times else "-", average((r.get("turns") for r in ran), 1),
                     str(int(math.fsum(errors))) if errors else "-",
                     " / ".join(outcome_of(e.found.result) if e.found else "-" for e in groups[label])])
    return table(["Model", "Kosten gem.", "Kosten max.", "Tokens in / uit (gem.)", "Piek input / venster", "Wandtijd (gem.)", "Turns (gem.)",
                  "Toolfouten", "Outcome per run"], rows)


def run_table(entries):
    rows = []
    for entry in entries:
        if entry.found is None:
            continue
        result = entry.found.result
        counts = count_sources_doc(entry.found.directory / "trace.jsonl", result.get("runId") or entry.found.directory.name)
        score = entry.score
        rows.append([entry.label, entry.run, result["status"], outcome_of(result), verdict_of(result),
                     score["f1"] if score else "-", score["f2"] if score and "f2" in score else "-",
                     " ".join(score["minors"]) or "-" if score and "minors" in score else "-",
                     "open" if entry.record["open"] else "ja" if entry.record["voldoet"] else "nee",
                     counts[0] if counts else "-", counts[1] if counts else "-"])
    return table(["Model", "Run", "Status", "Outcome", "Verdict", "F1", "F2", "Minors", "Voldoet", "read_file sources/doc",
                  "waarvan met offset/limit"], rows)


def preflight_table(models, preflight, ledger):
    rows = []
    for label in models:
        amounts = [row.get("cost_usd") for row in ledger if row.get("kind") == "preflight" and row.get("label") == label]
        entry = preflight.get(label)
        rows.append([label, "geen preflight" if entry is None else "ok" if entry["ok"] else "afgewezen",
                     "-" if entry is None or entry["ok"] else one_line(entry.get("reason") or "geen reden opgegeven"),
                     usd(R.amount(amounts[-1])) if amounts else "-"])
    return table(["Model", "Preflight", "Reden", "Bedrag (grootboek)"], rows)


def ledger_section(ledger):
    def run_cell(row):
        return row["run"] if row.get("run") is not None else "-"
    rows = [[row.get("id", "-"), row.get("kind", "-"), row.get("label", "-"), run_cell(row), row.get("case", "-"),
             usd(R.amount(row.get("cost_usd")))] for row in ledger]
    summary = (f"Totaal {usd(R.ledger_total(ledger))} over {len(ledger)} regels, {R.ledger_unknown(ledger)} zonder bedrag "
               f"(die tellen als 0, het totaal is een ondergrens).")
    return [summary, "", *table(["Id", "Soort", "Configuratie", "Run", "Case", "Kosten"], rows)] if rows else [summary]


def smoke_section(smoke):
    if smoke is None:
        return ["De rookproef is niet meegegeven (--smoke-dir en --smoke-scores)."]
    rows, problems = smoke
    lines = table(["Model", "Run", "Status", "Outcome", "Verdict", "F1"], [[r.label, r.run, r.status, r.outcome, r.verdict, r.f1] for r in rows])
    return [*lines, "", *[f"- stop: {problem}" for problem in problems], "rookproef: stop" if problems else "rookproef: door"]


def validity_text(verdicts_own, valid):
    if valid:
        return "in orde: minstens één harness-controle is kandidaat."
    text = (f"niet aangetoond: geen van de harness-controles ({', '.join(CONTROLS)}) is kandidaat, dus het oordeel voor alle modellen is "
            f"{RUNTIME}.")
    if any(verdicts_own.get(control) == OPEN for control in CONTROLS):
        text += " Voorlopig: een controle staat nog op open (een extra zonder beslissing)."
    return text


def follow_up(models, verdicts, valid):
    if not valid:
        return (f"Het oordeel voor alle modellen is {RUNTIME}: het verschil met de productie-reviewers ligt dan aan de harness, de prompt, de "
                "tools, of het ontbreken van Claude Code en de Codex CLI eromheen. Dat wordt eerst onderzocht, en de open modellen worden nog "
                "niet beoordeeld.")
    candidates = [label for label in models if verdicts[label] == KANDIDAAT and label not in CONTROLS]
    if candidates:
        return (f"Kandidaat: {', '.join(candidates)}. Een kandidaat is een reden voor een eigen vervolgidee (een productie-runner voor "
                f"QUEUE_REVIEW); of dat idee er komt, beslist JP.")
    return "Geen enkel model buiten de controles is kandidaat; de uitkomst hierboven is de volledige uitslag."


def build_report(date, models, runs, entries, unjudged, decisions, preflight, ledger, smoke, warnings):
    groups = per_model(entries, models)
    records = {label: [e.record for e in group] for label, group in groups.items()}
    own = {label: model_oordeel(group) for label, group in records.items()}
    verdicts = oordelen(records)
    valid = bench_geldig(own)
    cells = verdict_cells(models, groups, verdicts, {(e.label, e.run): why for e, why in unjudged})
    expected = len(entries)
    judged = sum(1 for e in entries if e.found is not None and e.found.result["status"] == JUDGED)
    unknown_cost = sum(1 for e in entries if e.found is not None and R.amount(usage_of(e.found.result).get("costUsd")) is None)
    lines = [f"# Review-bench {date}", "",
             f"Case `{CASE_ID}`. {judged} van {expected} verwachte runs beoordeeld ({len(models)} configuraties x {runs} runs).", "",
             f"Geldigheid van de bench: {validity_text(own, valid)}", "",
             "## Oordeel per model", "", *verdict_table(models, groups, cells, decisions), "",
             "Oordeel: kandidaat is 3 van 3 runs die voldoen, twijfel 2 van 3, anders valt het model af; open zolang een extra geen beslissing heeft. "
             "Een run voldoet als het resultaat is aanvaard (beoordeeld), outcome succeeded is, het verdict NO-GO is, F1 als major is gevonden "
             "en geen extra ongeldig is verklaard. Een model dat nooit gedraaid heeft, valt af; waarom staat erbij.", "",
             "## Eerste vergelijking: open modellen tegenover de harness-controles", "", *comparison_section(models, groups, cells, own, valid), "",
             "## Kosten, tokens, context en tijd", "", *cost_table(models, groups), "",
             f"Kosten: alle runs met een bedrag ({runs_phrase(unknown_cost, ('heeft er geen', 'hebben er geen'))}). De rest: runs met een modelstatus. "
             f"De piek is `peakInputTokens` naast het venster van {WINDOW}.", "",
             "## Per run", "", *run_table(entries), "",
             "## Runs zonder oordeel", ""]
    if unjudged:
        lines += [*table(["Model", "Run", "Reden"], [[e.label, e.run, why] for e, why in unjudged]), ""]
    else:
        lines += ["Alle verwachte runs zijn beoordeeld.", ""]
    lines += ["## Preflight", "", *preflight_table(models, preflight, ledger), "",
              "## Rookproef", "", *smoke_section(smoke), "",
              "## Context: productieruns", "",
              "De productieruns van dezelfde review, ter vergelijking. Het zijn geen bench-runs en ze tellen niet mee in het oordeel.", "",
              *table(["Run", "Uitvoerder", "Kosten"], [list(row) for row in PRODUCTION_RUNS]), "",
              "## Grootboek", "", *ledger_section(ledger), "",
              "## Grenzen en vervolg", "",
              "De bench dekt één case en alleen een document: geen shell, git of code lezen. De runs zijn blind met de hand gescoord, volgens "
              "de rubric van de case; JP besliste één keer per extra-key. Er is geen judge-model.", "",
              follow_up(models, verdicts, valid), ""]
    if warnings:
        lines += ["## Waarschuwingen", "", *[f"- {warning}" for warning in warnings], ""]
    return "\n".join(lines)


def check_date(text):
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            raise ValueError
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ScoreError(f"--date {text!r} is not a date like 2026-10-20") from None
    return text


def command_report(args):
    date = check_date(args.date)
    if bool(args.smoke_dir) != bool(args.smoke_scores):
        raise ScoreError("--smoke-dir and --smoke-scores go together: give both or neither")
    repeated = sorted({label for label in args.models if args.models.count(label) > 1})
    if repeated:
        raise ScoreError(f"--models names {', '.join(repeated)} more than once")
    out = Path(args.out)
    if not Path(args.ledger).is_file():
        raise ScoreError(f"--ledger {args.ledger} is not a file")
    ledger = R.read_ledger(args.ledger)
    decisions = load_decisions(args.decisions)
    preflight = load_preflight(args.preflight, args.models)
    dropped = []
    found = collect(out, dropped)
    by_run, key = scores_by_run(out, args.scores, only_f1=False)
    entries = build_entries(args.models, args.runs, found, by_run, decisions)
    check_complete(entries, key)
    warnings = warnings_for(entries, found, key, args.scores, dropped)
    skipped = load_skipped(out)
    smoke = smoke_check(args.smoke_dir, args.smoke_scores) if args.smoke_dir else None
    unjudged = [(e, why) for e in entries if (why := explain(e.found, e.label, e.run, preflight, skipped)) is not None]
    text = build_report(date, args.models, args.runs, entries, unjudged, decisions, preflight, ledger, smoke, warnings)
    results = Path(args.results_dir)
    results.mkdir(parents=True, exist_ok=True)
    path = results / f"review-bench-{date}.md"
    path.write_text(text, encoding="utf-8")
    for warning in warnings:
        print(f"score.py: waarschuwing: {warning}", file=sys.stderr)
    print(f"rapport: {path}")
    return 0


# ---------------------------------------------------------------------------------------------------------------------
# the call
# ---------------------------------------------------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("sheets", help="make the blind score sheets", allow_abbrev=False)
    p.add_argument("out", help="the --out of run.py: <out>/<label>/r<n>/*/bench-result.json")
    p.add_argument("--only-f1", action="store_true", help="the sheet asks for f1 only (the smoke)")
    p = sub.add_parser("smoke", help="the gate of the smoke: rookproef: door or stop", allow_abbrev=False)
    p.add_argument("dir", help="the --out of the smoke runs")
    p.add_argument("--scores", required=True, help="scores.jsonl of the smoke ({sheet, f1})")
    p = sub.add_parser("report", help="the verdict per model and the report", allow_abbrev=False)
    p.add_argument("out", help="the --out of the main runs")
    p.add_argument("--scores", required=True)
    p.add_argument("--decisions", required=True, help="decisions.json: {key: geldig|ongeldig}")
    p.add_argument("--ledger", required=True)
    p.add_argument("--date", required=True, help="YYYY-MM-DD: the name of the report")
    p.add_argument("--preflight", required=True, help="the preflight file of run.py: {label: {ok, reason}}")
    p.add_argument("--models", nargs="+", required=True, metavar="CONFIGURATION", help="the expected configurations, in this order")
    p.add_argument("--runs", type=R.positive_int, required=True, help="the expected runs per configuration")
    p.add_argument("--smoke-dir", help="the --out of the smoke runs")
    p.add_argument("--smoke-scores", help="scores.jsonl of the smoke")
    p.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="where the report goes (default llm-bench/results)")
    return ap


def main(argv=None):
    """Returns the exit status."""
    args = build_parser().parse_args(argv)
    commands = {"sheets": command_sheets, "smoke": command_smoke, "report": command_report}
    try:
        return commands[args.command](args)
    except (ScoreError, R.RunError) as e:
        print(f"score.py: {e}", file=sys.stderr)
        return EXIT_USAGE
    except OSError as e:
        print(f"score.py: {e.strerror or type(e).__name__}: {e.filename}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
