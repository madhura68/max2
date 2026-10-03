#!/usr/bin/env python3
"""Task-bench driver (M7, Task 7): `harness task-bench` for each case and each model on max2, with one ledger of the cost and
the stop rules of spec 4.1, 4.4 and 4.6.

  ./run.py --harness "node /home/janpeter/Development/agent-harness-m7/dist/cli.js" --models qwen3.8-openrouter \\
      --cases cases.jsonl --task-config task-config.json --out $R/gehost --ledger $R/ledger.jsonl [--budget-stop 14]
  (name the harness by its full path: a ~ is not expanded inside the quotes)

--models are labels of models.json (--models-file): base_url, name, retry_transient, optionally api_key_env (the NAME of the
environment variable that holds the key) and extraBody. The driver hands the harness the name, never the value: `--api-key-env`
is all that goes into argv, and the value travels in the environment the driver inherited.

For each label, in the order of --models:
  1. stop flag and budget stop (at the stop nothing more is paid for, the probe included); for an OpenRouter label the public
     endpoint list (no key), saved as <out>/endpoints-<label>-<ts>.json; it has to show a 16-bit (bf16 or fp16) endpoint that
     takes tools, or the driver stops (5);
  2. stop flag; `harness probe` with the extraBody of the label, in a directory of its own, <out>/probes/<label>-<ts>/; its cost
     goes into the ledger as probe-<label>-<ts> at once. Then the stop flag again, before anything is concluded from the probe:
     the real probe has no signal handler, so a signal kills it without a probe.json, and that is a stop (6). Only then a probe
     that is missing or not `reliable` stops the driver (5);
  3. for each case of cases.jsonl: stop flag; resume or skip (below); the budget stop; `harness task-bench --label <label>
     --out <out>/<label>` with --api-key-env and --retry-transient as the label says; read the result; book it in the ledger;
     the benchfout rule. The model config of a label is <out>/model-<label>.json (baseUrl, name, extraBody; no key), a case is
     <out>/cases/<id>.json, and the extra body of a label's probe <out>/extra-body-<label>.json.
  <ts> is the UTC time of the start of the label, as %Y%m%dT%H%M%SZ.

The result of a call is the new run directory in <out>/<label>/ (<case>-<label>-<8 hex>) with a readable bench-result.json of that
case and label; the exit status of the harness does not decide. Anything else is a benchfout "no usable result" that costs an
unknown amount (null in the ledger, id <case>-<label>-geen-resultaat-<ts> when there is no directory to name). Only
bench-result.json of a run is ever read: ws/ and ws-deps/ hold work trees where a named pipe would hang a read.

Resuming: per (label, case) the valid results on disk count. A result of a model status (geslaagd, verborgen_tests_rood,
verify_rood, limiet, geen_wijzigingen) means the case is done. Else the benchfouten count, not the ones aborted by a stop
(benchError "afgebroken"): none, run it; one, run it once more; two, stop (3), also when they were already on disk.

The ledger (--ledger, one JSON line per probe or run, only ever added to):
  {"id", "kind": "probe", "label", "cost_usd"} and {"id", "kind": "run", "label", "case", "cost_usd"}.
cost_usd of a run is usage.costUsd of its bench-result.json; of a probe the sum of every usage.costUsd under steps of probe.json
(raw.turn1 and raw.turn2 for c_two_tools too). An amount that is not there is null: it counts as 0 in the total (math.fsum),
and score.py --ledger says how many there are. From --budget-stop (14) dollars on, no run starts (4); the ledger of the practice
run counts, as it is the same file.

Exit status: 0 done, 2 the call or a configuration is wrong (almost always before anything runs, but a RunError can also fall
mid-run: a ledger that has become unreadable, a harness that cannot be started), 3 a second benchfout of one case, 4 the budget,
5 a probe or an endpoint list that does not do, 6 stopped by SIGINT or SIGTERM. Reasons go to stderr. An unexpected error in the
driver itself is a traceback and exit status 1.

Stopping: the handlers for SIGINT and SIGTERM only set a flag. They do not raise, so subprocess.run keeps waiting for the
harness, which got the same signal (pkill -s in the window), cleans up its containers and writes a bench-result.json with
benchError "afgebroken". The driver never kills it. Then the driver reads that result, books its cost, and stops (6) without
starting anything new: it looks at the flag before the endpoint list, the probe, every run and every repeat, and before the next
label, and once more after the last one (a signal is a stop, whatever was left to do). An aborted result is no benchfout; when the
driver is started again that case simply runs again. A bench that reports itself aborted while the driver got no signal (somebody
stopped only the node process) ends the driver with 6 as well: it neither repeats that run nor goes on to the next case.

Stdlib only.
"""
import argparse
import json
import math
import os
import re
import shlex
import signal
import subprocess
import sys
import urllib.request
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

HERE = Path(__file__).resolve().parent
MODELS = HERE / "models.json"
MODEL_STATUSES = ("geslaagd", "verborgen_tests_rood", "verify_rood", "limiet", "geen_wijzigingen")      # spec 4.1
STATUSES = MODEL_STATUSES + ("benchfout",)
ABORTED = "afgebroken"          # the benchError of a bench that SIGINT or SIGTERM stopped (agent-harness src/bench/task-bench.ts)
VERDICTS = ("reliable", "unreliable", "none")          # tool_calling in probe.json
BUDGET_STOP = 14.0              # dollars (spec 4.6); the limit of the key, $20, is the only hard limit
PINNED_QUANTIZATIONS = ["bf16", "fp16"]                 # spec 4.3: the hosted model runs on 16 bits or not at all
SIXTEEN_BIT = ("bf16", "fp16")
EXIT_USAGE, EXIT_BENCH, EXIT_BUDGET, EXIT_PROBE, EXIT_ABORTED = 2, 3, 4, 5, 6
KEY_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")             # what api_key_env has to look like: a value would end up in argv
SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")      # one plain path segment: a label (BENCH_LABEL of the harness), a case id
MASK, MIN_MASKED_LENGTH = "<redacted>", 8               # as in the harness (model-client.ts): a shorter value is a placeholder


class RunError(Exception):
    """A problem with how run.py was called or configured: one line on stderr and exit status 2."""


class Stop(Exception):
    """The driver ends here with this exit status: 3 a second benchfout, 4 the budget, 5 a probe or an endpoint list, 6 a signal."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------------------------------------------------
# small pure helpers
# ---------------------------------------------------------------------------------------------------------------------

def on_openrouter(base_url):
    """Whether the host of base_url is openrouter.ai (or a subdomain of it): the host decides, not the text of the URL."""
    try:
        host = (urlsplit(base_url).hostname or "").rstrip(".")
    except ValueError:      # not a URL at all: nothing there to be OpenRouter
        return False
    return host == "openrouter.ai" or host.endswith(".openrouter.ai")


def mask_secrets(text, secrets):
    """text with every occurrence of a secret replaced by MASK, on top of the masking the harness does itself. The trimmed form of
    a secret counts too (a server echoes the trimmed header value), the longest form goes first (one can contain another), and a
    value shorter than MIN_MASKED_LENGTH is a placeholder that is left alone."""
    forms = {form for secret in secrets for form in (secret, secret.strip()) if len(form) >= MIN_MASKED_LENGTH}
    for form in sorted(forms, key=len, reverse=True):
        text = text.replace(form, MASK)
    return text


def excerpt(text, secrets=(), limit=300):
    """The start of text on one line, for a message, with the secrets masked first and the cut made second: a value that straddles
    the limit would otherwise leave its first characters behind."""
    return " ".join(mask_secrets(text, secrets).split())[:limit] or "no output"


def amount(value):
    """A cost as the float it is, or None when value is no amount: absent, not a number (a bool is not one), not finite or
    negative. 0 is an amount: a cost of nothing is a cost, an unknown one is not."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value >= 0 else None


def utc_stamp(moment=None):
    return (moment or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")


def probe_dir_name(model):
    """The directory harness probe writes to under --out: probeDir of agent-harness src/probe.ts."""
    return "probe-" + re.sub(r"[^a-z0-9.-]+", "-", model.lower())


def key_args(cfg):
    """--api-key-env <name> for a label that needs a key. The value is read by the harness; run.py hands over the name only."""
    return ["--api-key-env", cfg["api_key_env"]] if cfg.get("api_key_env") else []


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json_object(path):
    """The JSON object in the file at path, or None when it is not there, cannot be read or is no object. A named pipe is no file."""
    path = Path(path)
    try:
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------------------------------------------------------------
# the models file, the cases
# ---------------------------------------------------------------------------------------------------------------------

def load_models(path, labels):
    """{label: settings} for the labels from the models file. Per label: base_url, name, retry_transient (true or false: always said,
    as the spec makes it a decision per label), optionally api_key_env (the NAME of the environment variable that holds the key)
    and extraBody (the extra body of the model; none: none is sent).
    Guard: on an OpenRouter endpoint extraBody.provider has to pin the route (spec 4.3): data_collection "deny", require_parameters
    true and quantizations exactly ["bf16", "fp16"], so that a label that lost one of them cannot send the prompts to a provider that
    keeps them, or run the model on a lower precision. RunError naming the label otherwise."""
    try:
        models = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RunError(f"cannot read the models file {path}: {type(e).__name__}") from None
    if not isinstance(models, dict):
        raise RunError(f"the models file {path} must be an object with a label per model")
    unknown = [label for label in labels if label not in models]
    if unknown:
        raise RunError(f"unknown model label {', '.join(unknown)}; {path} has: {', '.join(models)}")
    for label in labels:
        cfg = models[label]
        if not SEGMENT.fullmatch(label):
            raise RunError(f"label {label!r} in {path} must be one plain path segment (letters, digits, '.', '_' and '-')")
        if not isinstance(cfg, dict):
            raise RunError(f"label {label} in {path} must be an object")
        for field in ("base_url", "name"):
            if not (isinstance(cfg.get(field), str) and cfg[field]):
                raise RunError(f"label {label} has no {field} in {path}")
        # a value in this field would end up in argv: it must read as the name of a variable, and it is never quoted back
        if "api_key_env" in cfg and not (isinstance(cfg["api_key_env"], str) and KEY_NAME.fullmatch(cfg["api_key_env"])):
            raise RunError(f"label {label}: api_key_env in {path} must be the name of an environment variable")
        if not isinstance(cfg.get("retry_transient"), bool):
            raise RunError(f"label {label}: retry_transient in {path} must be true or false")
        if "extraBody" in cfg and not isinstance(cfg["extraBody"], dict):
            raise RunError(f"label {label}: extraBody in {path} must be an object")
        if on_openrouter(cfg["base_url"]):
            provider = (cfg.get("extraBody") or {}).get("provider")
            if not isinstance(provider, dict):
                raise RunError(f"label {label}: an OpenRouter label has to pin the route in {path}: extraBody.provider is missing")
            if provider.get("data_collection") != "deny":
                raise RunError(f'label {label}: extraBody.provider.data_collection must be "deny" in {path}')
            if provider.get("require_parameters") is not True:
                raise RunError(f"label {label}: extraBody.provider.require_parameters must be true in {path}")
            if provider.get("quantizations") != PINNED_QUANTIZATIONS:
                raise RunError(f"label {label}: extraBody.provider.quantizations must be exactly {json.dumps(PINNED_QUANTIZATIONS)} "
                               f"(16 bits or no run, spec 4.3) in {path}")
    return {label: models[label] for label in labels}


def model_config(cfg):
    """The --model-config file of a label: baseUrl, name and, when the label has one, extraBody. Never a key: the harness refuses a
    file with one, and reads the key from --api-key-env."""
    config = {"baseUrl": cfg["base_url"], "name": cfg["name"]}
    if "extraBody" in cfg:
        config["extraBody"] = cfg["extraBody"]
    return config


def read_cases(path):
    """The cases of the JSONL file, in its order. Each line is a JSON object with an id that is one plain path segment (it names the
    file the harness gets, and the run directories), and no id comes twice. The rest of a case is the harness's to judge."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError) as e:
        raise RunError(f"cannot read the cases file {path}: {type(e).__name__}") from None
    cases, seen = [], set()
    # split on "\n" only: str.splitlines() also cuts at U+2028, U+2029 and U+0085, which JSON leaves raw in a string
    for n, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except ValueError:
            raise RunError(f"{path}: line {n} is not JSON") from None
        if not (isinstance(case, dict) and isinstance(case.get("id"), str) and SEGMENT.fullmatch(case["id"])):
            raise RunError(f"{path}: line {n} is no case: it needs an id that is one plain path segment")
        if case["id"] in seen:
            raise RunError(f"{path}: case {case['id']} comes twice")
        seen.add(case["id"])
        cases.append(case)
    if not cases:
        raise RunError(f"{path} holds no case")
    return cases


# ---------------------------------------------------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------------------------------------------------

def read_ledger(path):
    """The entries of the ledger, in order; [] when there is none yet. A line that is no entry, or has an amount that is no amount,
    is a RunError that names the line and not what is in it: a ledger that cannot be read is a budget that nobody knows."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise RunError(f"cannot read the ledger {path}: {type(e).__name__}") from None
    entries = []
    for n, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            raise RunError(f"ledger {path}: line {n} is not JSON") from None
        if not isinstance(entry, dict):
            raise RunError(f"ledger {path}: line {n} is no entry")
        if entry.get("cost_usd") is not None and amount(entry["cost_usd"]) is None:
            raise RunError(f"ledger {path}: line {n} has a cost_usd that is no amount")
        entries.append(entry)
    return entries


def ledger_total(entries):
    """The total cost of the entries, summed exactly (math.fsum); an entry without an amount counts as 0."""
    return math.fsum(amount(entry.get("cost_usd")) or 0.0 for entry in entries)


def ledger_unknown(entries):
    """How many entries have no amount (null): their cost is unknown, and the total is a lower bound by that many."""
    return sum(1 for entry in entries if entry.get("cost_usd") is None)


def append_ledger(path, entry):
    """Add one entry as a JSON line. The ledger is only ever added to, and each line is on disk before the next call is paid."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def probe_cost(probe):
    """The cost of a probe: the sum (math.fsum) of every usage.costUsd under steps of its probe.json: steps.<step>.raw.usage.costUsd
    and, for c_two_tools, raw.turn1.usage.costUsd and raw.turn2.usage.costUsd. None when there is no amount at all. A step that threw
    has raw null and adds nothing, so the sum is then a lower bound; the key limit is the hard limit."""
    steps = probe.get("steps") if isinstance(probe, dict) else None
    found = []
    for step in (steps.values() if isinstance(steps, dict) else ()):
        raw = step.get("raw") if isinstance(step, dict) else None
        if not isinstance(raw, dict):
            continue
        for part in (raw, raw.get("turn1"), raw.get("turn2")):
            usage = part.get("usage") if isinstance(part, dict) else None
            cost = amount(usage.get("costUsd")) if isinstance(usage, dict) else None
            if cost is not None:
                found.append(cost)
    return math.fsum(found) if found else None


# ---------------------------------------------------------------------------------------------------------------------
# what the harness writes
# ---------------------------------------------------------------------------------------------------------------------

def fetch_endpoints(base_url, model):
    """The public endpoint list of an OpenRouter model, parsed: GET <base_url>/models/<model>/endpoints. No key goes with it: the list
    is public, and a key would only be one more thing to leak. The tests replace this function."""
    url = f"{base_url.rstrip('/')}/models/{quote(model, safe='/')}/endpoints"
    # a plain User-Agent of our own: the default of urllib is one that services behind a CDN are known to refuse
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "llm-bench-task-bench/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def sixteen_bit_with_tools(listing):
    """The providers in an endpoint list (data.endpoints of /models/<model>/endpoints) that run the model on 16 bits (quantization bf16
    or fp16) and take tools (supported_parameters has `tools`): the ones that the provider block of a hosted label leaves. [] for a
    list that has none, or is none."""
    data = listing.get("data") if isinstance(listing, dict) else None
    endpoints = data.get("endpoints") if isinstance(data, dict) else None
    if not isinstance(endpoints, list):
        return []
    return [str(e.get("provider_name")) for e in endpoints
            if isinstance(e, dict) and e.get("quantization") in SIXTEEN_BIT
            and isinstance(e.get("supported_parameters"), list) and "tools" in e["supported_parameters"]]


def load_bench_result(path):
    """The parsed bench-result.json at path when it is a result at all: a JSON object with a status of the six. None when the file is
    absent, cannot be read, or is no result. Only a regular file is opened (score.py reads results with this too)."""
    result = read_json_object(path)
    return result if result is not None and result.get("status") in STATUSES else None


def read_bench_result(path, case_id, label):
    """load_bench_result, and the result has to be of this case and label (its caseId and label say so); None otherwise."""
    result = load_bench_result(path)
    return result if result is not None and result.get("caseId") == case_id and result.get("label") == label else None


def run_dir_names(label_dir, case_id, label):
    """The names in label_dir that are run directories of this case and label: <case>-<label>-<8 hex>, exactly."""
    pattern = re.compile(re.escape(f"{case_id}-{label}-") + r"[0-9a-f]{8}")
    try:
        names = os.listdir(label_dir)
    except FileNotFoundError:
        return []
    except OSError as e:
        raise RunError(f"cannot list {label_dir}: {e.strerror or type(e).__name__}") from None
    return sorted(name for name in names if pattern.fullmatch(name) and (Path(label_dir) / name).is_dir())


def existing_results(label_dir, case_id, label):
    """[(run directory name, result)] for the run directories of this case and label that hold a valid bench-result.json."""
    found = []
    for name in run_dir_names(label_dir, case_id, label):
        result = read_bench_result(Path(label_dir) / name / "bench-result.json", case_id, label)
        if result is not None:
            found.append((name, result))
    return found


def failure_reason(result):
    """Why a result is a benchfout, in a few words: its benchError, else the code and message of its error."""
    if result.get("benchError"):
        return str(result["benchError"])
    error = result.get("error")
    if isinstance(error, dict):
        return f"{error.get('code')}: {error.get('message')}"
    return "no reason given"


class Harness:
    """The harness CLI as a subprocess: `node .../dist/cli.js`, or any command with probe and task-bench (the tests use a stand-in).
    Its output is captured: what the driver needs it reads from the files the harness wrote, and what it quotes it masks."""

    def __init__(self, command):
        self.command = list(command)

    def call(self, *args):
        """Run it and wait for it, however long that takes: there is no timeout and nothing here ever kills it (see Stopping)."""
        try:
            return subprocess.run([*self.command, *map(str, args)], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", stdin=subprocess.DEVNULL)
        except OSError as e:
            raise RunError(f"cannot start the harness ({self.command[0]}): {e.strerror or type(e).__name__}") from None


# ---------------------------------------------------------------------------------------------------------------------
# the stop flag, and the driver
# ---------------------------------------------------------------------------------------------------------------------

class StopFlag:
    """The signal handler for SIGINT and SIGTERM. It only records that a signal came; it does not raise. That is what keeps
    subprocess.run waiting for the harness, which got the same signal and needs the time to clean up its containers."""

    def __init__(self):
        self.signum = None

    def __call__(self, signum, frame):
        self.signum = signum

    @property
    def is_set(self):
        return self.signum is not None

    def name(self):
        return signal.Signals(self.signum).name


# What one call of the harness for a case came to: kind is "model" (a result of a model status), "aborted" (the bench was stopped) or
# "benchfout"; reason says why for a benchfout.
Outcome = namedtuple("Outcome", "kind reason")


class Driver:
    def __init__(self, harness, out, ledger, budget_stop, models, cases, task_config, flag, secrets=()):
        self.harness, self.out, self.ledger, self.budget_stop = harness, Path(out), Path(ledger), budget_stop
        self.models, self.cases, self.task_config, self.flag, self.secrets = models, cases, Path(task_config), flag, list(secrets)

    @staticmethod
    def say(text):
        print(text, flush=True)

    # --- the rules --------------------------------------------------------------------------------------------------------

    def check_flag(self):
        if self.flag.is_set:
            raise Stop(EXIT_ABORTED, f"stopped by {self.flag.name()}; what was finished is booked in the ledger, nothing new starts")

    def check_budget(self):
        total = ledger_total(read_ledger(self.ledger))
        if total >= self.budget_stop:
            raise Stop(EXIT_BUDGET, f"the ledger total ${total:.4f} has reached the stop at ${self.budget_stop:.2f}; no new run starts")

    def free_stamp(self, label):
        """The UTC time of the start of a label as %Y%m%dT%H%M%SZ, moved on by whole seconds until neither its evidence file nor its
        probe directory exists: a probe always gets a directory of its own, so that a probe.json from before cannot be taken for the
        new one."""
        moment = datetime.now(timezone.utc).replace(microsecond=0)
        while True:
            stamp = utc_stamp(moment)
            if not (self.out / "probes" / f"{label}-{stamp}").exists() and not (self.out / f"endpoints-{label}-{stamp}.json").exists():
                return stamp
            moment += timedelta(seconds=1)

    # --- one label ----------------------------------------------------------------------------------------------------------

    def run(self):
        for label in self.models:
            self.label(label)
        self.check_flag()           # a signal at any moment is a stop, also in the last second of the last run
        entries = read_ledger(self.ledger)
        self.say(f"done: {self.out}; ledger ${ledger_total(entries):.4f} of ${self.budget_stop:.2f} "
                 f"({len(entries)} entries, {ledger_unknown(entries)} without an amount)")

    def label(self, label):
        cfg = self.models[label]
        self.check_flag()
        self.check_budget()         # at the stop nothing more is paid for: not the probe either
        stamp = self.free_stamp(label)
        if on_openrouter(cfg["base_url"]):
            self.endpoints(label, cfg, stamp)
            self.check_flag()
        self.probe(label, cfg, stamp)
        for case in self.cases:
            self.case(label, cfg, case)

    def endpoints(self, label, cfg, stamp):
        """The public endpoint list, as evidence of the precision, and the check that a 16-bit endpoint with tools is there."""
        try:
            listing = fetch_endpoints(cfg["base_url"], cfg["name"])
        except Exception as e:          # a network, HTTP or parse problem of any kind: say what kind, not what it said
            raise Stop(EXIT_PROBE, f"{label}: cannot fetch the endpoint list ({type(e).__name__}); no probe, no run") from None
        path = self.out / f"endpoints-{label}-{stamp}.json"
        write_json(path, listing)
        providers = sixteen_bit_with_tools(listing)
        if not providers:
            raise Stop(EXIT_PROBE, f"{label}: the endpoint list ({path.name}) shows no 16-bit (bf16 or fp16) endpoint that takes tools; "
                                   f"no probe, no run")
        self.say(f"{label} endpoints: 16-bit with tools: {', '.join(providers)} -> {path}")

    def probe(self, label, cfg, stamp):
        """harness probe in a directory of its own; its cost goes into the ledger before anything else is paid for, and a verdict
        other than reliable stops the driver."""
        directory = self.out / "probes" / f"{label}-{stamp}"
        directory.mkdir(parents=True)
        args = ["probe", "--base-url", cfg["base_url"], "--model", cfg["name"], "--out", directory, *key_args(cfg)]
        if "extraBody" in cfg:
            args += ["--extra-body-file", self.out / f"extra-body-{label}.json"]
        done = self.harness.call(*args)
        probe = read_json_object(directory / probe_dir_name(cfg["name"]) / "probe.json")
        cost = probe_cost(probe) if probe is not None else None
        append_ledger(self.ledger, {"id": f"probe-{label}-{stamp}", "kind": "probe", "label": label, "cost_usd": cost})
        # before the verdicts: the real probe has no signal handler, so a SIGINT or SIGTERM kills it where it stands, with no
        # probe.json, and that is a stop (6) and not a probe that failed (5)
        self.check_flag()
        if probe is None:
            self.say(f"{label} probe: no probe.json (harness exit status {done.returncode}: {excerpt(done.stderr, self.secrets)})")
            raise Stop(EXIT_PROBE, f"{label}: the probe left no probe.json; no run starts")
        verdict = probe.get("tool_calling")
        shown = verdict if verdict in VERDICTS else "no verdict"
        spent = "" if cost is None else f" (${cost:.6f})"
        self.say(f"{label} probe: {shown}{spent}")
        if verdict != "reliable":
            raise Stop(EXIT_PROBE, f"{label}: the probe rates tool calling as {shown}; no run starts")

    # --- one case -----------------------------------------------------------------------------------------------------------

    def case(self, label, cfg, case):
        case_id = case["id"]
        self.check_flag()
        seen = existing_results(self.out / label, case_id, label)
        done = next((result for _, result in seen if result["status"] in MODEL_STATUSES), None)
        if done is not None:
            self.say(f"{label} {case_id}: skipped, it has a result: {done['status']}")
            return
        # the benchfouten so far; one aborted by a stop is no benchfout (it is run again), and a second one ends the driver
        failures = [result for _, result in seen if result["status"] == "benchfout" and result.get("benchError") != ABORTED]
        while True:
            self.check_flag()           # first: a signal during the last attempt is a stop (6), also if that was the second benchfout
            if len(failures) >= 2:
                raise Stop(EXIT_BENCH, f"{label} {case_id}: {len(failures)} benchfouten, the one repeat is used up; the last: "
                                       f"{excerpt(failure_reason(failures[-1]), self.secrets)}. The driver stops for JP")
            self.check_budget()
            outcome = self.attempt(label, cfg, case)
            if outcome.kind == "aborted":
                raise Stop(EXIT_ABORTED, f"{label} {case_id}: the bench was stopped; its result is booked, and the case runs again "
                                         f"when the driver is started again")
            if outcome.kind == "model":
                return
            failures.append({"status": "benchfout", "benchError": outcome.reason})

    def attempt(self, label, cfg, case):
        """One call of harness task-bench for a case: the call, the result, the ledger. Returns an Outcome."""
        case_id = case["id"]
        label_dir = self.out / label
        label_dir.mkdir(parents=True, exist_ok=True)
        before = set(run_dir_names(label_dir, case_id, label))
        args = ["task-bench", "--case", self.out / "cases" / f"{case_id}.json", "--model-config", self.out / f"model-{label}.json",
                "--task-config", self.task_config, "--label", label, "--out", label_dir, *key_args(cfg)]
        if cfg["retry_transient"]:
            args.append("--retry-transient")
        self.say(f"{label} {case_id}: running")
        done = self.harness.call(*args)
        new = sorted(set(run_dir_names(label_dir, case_id, label)) - before)
        result = read_bench_result(label_dir / new[0] / "bench-result.json", case_id, label) if len(new) == 1 else None
        if result is None:      # no usable result: a benchfout of an unknown cost, that counts for the repeat rule
            why = ("no new run directory" if not new else "more than one new run directory" if len(new) > 1
                   else "its bench-result.json is absent, unreadable, or of another case or label")
            run_id = new[0] if len(new) == 1 else f"{case_id}-{label}-geen-resultaat-{utc_stamp()}"
            append_ledger(self.ledger, {"id": run_id, "kind": "run", "label": label, "case": case_id, "cost_usd": None})
            reason = f"no usable result: {why} (harness exit status {done.returncode}: {excerpt(done.stderr, self.secrets)})"
            self.say(f"{label} {case_id}: benchfout, {reason}")
            return Outcome("benchfout", reason)
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        cost = amount(usage.get("costUsd"))
        append_ledger(self.ledger, {"id": new[0], "kind": "run", "label": label, "case": case_id, "cost_usd": cost})
        status, seconds = result["status"], result.get("durationMs")
        took = f" in {seconds / 1000:.1f}s" if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) else ""
        spent = "no amount" if cost is None else f"${cost:.6f}"
        self.say(f"{label} {case_id}: {status}{took}, {spent} ({new[0]})")
        self.say(f"ledger total ${ledger_total(read_ledger(self.ledger)):.4f} of ${self.budget_stop:.2f}")
        if status in MODEL_STATUSES:
            return Outcome("model", None)
        if result.get("benchError") == ABORTED:
            return Outcome("aborted", None)
        reason = excerpt(failure_reason(result), self.secrets)
        self.say(f"{label} {case_id}: benchfout, {reason}")
        return Outcome("benchfout", reason)


# ---------------------------------------------------------------------------------------------------------------------
# the call
# ---------------------------------------------------------------------------------------------------------------------

def setup(args, flag):
    """Everything that can be wrong with the call, found before anything starts or is written: RunError (exit 2). Returns the Driver."""
    try:
        command = shlex.split(args.harness)
    except ValueError as e:
        raise RunError(f"--harness is not a command: {e}") from None
    if not command:
        raise RunError("--harness is empty")
    repeated = sorted({label for label in args.models if args.models.count(label) > 1})
    if repeated:
        raise RunError(f"--models names {', '.join(repeated)} more than once")
    models = load_models(args.models_file or MODELS, args.models)
    # the key variables are checked before anything runs; only their names are ever shown
    names = sorted({cfg["api_key_env"] for cfg in models.values() if cfg.get("api_key_env")})
    unset = [name for name in names if not os.environ.get(name, "").strip()]
    if unset:
        raise RunError(f"environment variable {', '.join(unset)} is not set (the harness reads the key from it)")
    secrets = [os.environ[name] for name in names]          # for masking only: never printed, never written
    cases = read_cases(args.cases)
    task_config = Path(args.task_config).resolve()
    if read_json_object(task_config) is None:
        raise RunError(f"--task-config {args.task_config} is not a file with a JSON object")
    out, ledger = Path(args.out).resolve(), Path(args.ledger).resolve()
    entries = read_ledger(ledger)
    try:
        (out / "cases").mkdir(parents=True, exist_ok=True)
        for case in cases:
            write_json(out / "cases" / f"{case['id']}.json", case)
        for label, cfg in models.items():
            write_json(out / f"model-{label}.json", model_config(cfg))
            if "extraBody" in cfg:
                write_json(out / f"extra-body-{label}.json", cfg["extraBody"])
    except OSError as e:
        raise RunError(f"cannot write under {out}: {e.strerror or type(e).__name__}") from None
    driver = Driver(Harness(command), out, ledger, args.budget_stop, models, cases, task_config, flag, secrets)
    driver.say(f"{len(cases)} cases, labels {', '.join(models)}; ledger ${ledger_total(entries):.4f} of ${args.budget_stop:.2f} "
               f"({len(entries)} entries)")
    return driver


def positive_amount(text):
    """An amount of money above zero (a finite number: nan and inf are no limit)."""
    try:
        number = float(text)
    except ValueError:
        number = math.nan
    if not (math.isfinite(number) and number > 0):
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive amount")
    return number


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    ap.add_argument("--harness", required=True, help='the harness command, e.g. "node /path/to/dist/cli.js"')
    ap.add_argument("--models", nargs="+", required=True, metavar="LABEL", help="labels from --models-file, run in this order")
    ap.add_argument("--models-file", help=f"the labels (default {MODELS.name} next to this file)")
    ap.add_argument("--cases", required=True, help="cases.jsonl: one case (a JSON object with an id) per line")
    ap.add_argument("--task-config", required=True, help="the task block of worker.json (task-config.json)")
    ap.add_argument("--out", required=True, help="the output directory; it may hold the results of an earlier window: they are resumed")
    ap.add_argument("--ledger", required=True, help="the ledger of the cost, added to; the practice run's ledger counts when it is this file")
    ap.add_argument("--budget-stop", type=positive_amount, default=BUDGET_STOP,
                    help=f"dollars: from this total on no run starts (default {BUDGET_STOP:g})")
    return ap


def main(argv=None):
    """Returns the exit status. Installs the handlers for SIGINT and SIGTERM for as long as it runs."""
    args = build_parser().parse_args(argv)
    flag = StopFlag()
    previous = {sig: signal.signal(sig, flag) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        setup(args, flag).run()
        return 0
    except Stop as stop:
        print(f"run.py: stopped ({stop.status}): {stop}", file=sys.stderr, flush=True)
        return stop.status
    except RunError as e:
        print(f"run.py: {e}", file=sys.stderr, flush=True)
        return EXIT_USAGE
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
