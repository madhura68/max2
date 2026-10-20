#!/usr/bin/env python3
"""Review-bench driver (M8, Task 10): `harness review-bench` for each round and each configuration on max2, with a preflight, one ledger
of the cost, a budget and the stop rules of spec 4.7. It follows task_bench/run.py (M7); what differs is said below.

  ./run.py --harness "node /srv/agent-harness/current/dist/cli.js" --config harness.json --probe-dir $P \\
      --case cases/macsearch-idea263-spec-r5 --models qwen3.8-or-128k claude-sonnet-5.5-or ... --runs 3 --out $R/venster \\
      --ledger $R/ledger.jsonl --budget 8 --key-file /run/user/1000/m8-litellm.key [--preflight] [--preflight-file F]
  (name the harness by its full path: a ~ is not expanded inside the quotes)

There is no models file: a model is a configuration of --config (harness.json), --models names them, and the name is the label of the
run. A name that --config does not have is refused (2). The case is a directory (--case) of which the driver reads case.json for `id`
and `maxCostUsd` (a decimal string, the soft ceiling of one run); the harness checks the rest.

The key. --key-file is read once and stripped of white space. A value shorter than 8 characters, one that starts with
`LITELLM_MASTER_KEY=` or one with a quote in it is refused (2): all three are mistakes of putting it in the file. The value goes into
the environment of the harness as LITELLM_MASTER_KEY and into the Authorization header of the preflight, and nowhere else: argv gets
`--api-key-env LITELLM_MASTER_KEY`, and nothing the driver writes or prints holds it (what it quotes is masked first).

With --preflight (no run) the driver asks LiteLLM once for each configuration, POST <litellm.baseUrl>/chat/completions with
model = the configuration, max_tokens 64000 (the real ceiling of the case), the reasoning_effort that harness.json says (if it says
one), one dummy tool `noop` and the instruction "Antwoord alleen: OK". A configuration is `ok` for HTTP 200 and a finite number in
usage.cost of the body, the field the harness reads (src/model-client.ts parseUsage). The amount goes into the ledger as
preflight-<label>-<ts>, null when unknown. The outcome goes to --preflight-file (default <out>/preflight.json) as
{label: {"ok", "reason"}}: the entries of the labels asked for now replace those of an earlier call, the others stay. The reason is
masked. The runs read that file, so a smoke run and the main runs can have an --out each and share one preflight.

Without --preflight the driver runs, for a run n from 1 to --runs, each label of --models in that order: the runs go round by round
(round 1 over all labels, then round 2, ...), so that a disturbance that depends on the time does not always fall on the same model.
Run n of a label goes to --out <out>/<label>/r<n> of the harness; a result lands in <out>/<label>/r<n>/<case>-<label>-<8 hex>/
bench-result.json. A label that the preflight file lacks is refused (2, "no preflight"); one with ok false does not run.
Before each run: the stop flag, then resuming, then the budget.

Resuming: per (label, n) the valid results on disk count. A result of a model status (beoordeeld, limiet, resultaat_ongeldig) means
the run is done. Else the benchfouten count, not the ones aborted by a stop (benchError "afgebroken") and not the ones that say
CONFIGURATION_NOT_PROBED: none, run it; one, run it once more; two, stop (3), also when they were already on disk. A run that says
CONFIGURATION_NOT_PROBED is neither repeated nor a stop: the label does not run again in this call, and the next call tries it once
more (a probe may have been made in the meantime).

The ledger (--ledger, one JSON line per preflight or run, only ever added to):
  {"id", "kind": "preflight", "label", "cost_usd"} and {"id", "kind": "run", "label", "run", "case", "cost_usd"}.
cost_usd of a run is usage.costUsd of its bench-result.json, a benchfout included. An amount that is not there is null: it counts as 0
in the total (math.fsum). The budget (--budget) differs from M7 here: a run does not start when the total + maxCostUsd of the case
would be more than the budget. The ceiling of a run is a soft one, and the margin of $2 under the limit of the key covers what a run
goes over it.

At the end of every call that runs (not the --preflight), also at an exit 3, 4 or 6, <out>/skipped.json is written again: a list of
{label, run, reason} for each expected run (--models x --runs) without a bench-result.json, the first reason that fits being
`preflight afgewezen: <reason>`, `niet geprobed: <detail>`, `budget bereikt`, `gestopt (stopvlag)` or `gestopt na tweede benchfout op
<label>`. A run that nothing of this explains is `niet gestart`; a call that ends in an error of the driver itself says `gestopt (fout)`.
It is made from what is on disk, so a later call that finishes the work empties it. The rows of a label that the call does not name stay
for as long as their runs have no bench-result.json (JP can skip a label in a later call, and its stop reason must not vanish). A --preflight leaves it alone, so that a new
preflight of one configuration does not wipe the reasons of the last runs. If it cannot be written, that is said on stderr; the exit
status of a call that was stopped (3, 4, 6) or failed stays what it was, and a call that was done becomes 2.

Exit status: 0 done, 2 the call or a configuration is wrong (almost always before anything runs, but a RunError can also fall
mid-run: a ledger that has become unreadable, a harness that cannot be started), 3 a second benchfout of one run, 4 the budget,
6 stopped by SIGINT or SIGTERM. (5, the probe of M7, is not used: the harness checks the probe, and a configuration without one is a
CONFIGURATION_NOT_PROBED.) Reasons go to stderr. An unexpected error in the driver itself is a traceback and exit status 1.

Stopping: as in M7. The handlers for SIGINT and SIGTERM only set a flag. They do not raise, so subprocess.run keeps waiting for the
harness, which got the same signal (pkill -s in the window) and writes a bench-result.json with benchError "afgebroken". The driver
never kills it. Then it reads that result, books its cost, and stops (6) without starting anything new: it looks at the flag before
every run and every repeat, and once more after the last one. An aborted result is no benchfout; when the driver is started again
that run simply runs again. A bench that reports itself aborted while the driver got no signal ends the driver with 6 as well.

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
import urllib.error
import urllib.request
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

MODEL_STATUSES = ("beoordeeld", "limiet", "resultaat_ongeldig")      # spec 4.1: the model answered, or ran into a limit of its own
STATUSES = MODEL_STATUSES + ("benchfout",)
ABORTED = "afgebroken"          # the benchError of a bench that SIGINT or SIGTERM stopped (agent-harness src/bench/review-bench.ts)
NOT_PROBED = "CONFIGURATION_NOT_PROBED"      # the start of the benchError of a configuration without an accepted probe
EXIT_USAGE, EXIT_BENCH, EXIT_BUDGET, EXIT_PROBE, EXIT_ABORTED = 2, 3, 4, 5, 6       # EXIT_PROBE is M7's: not used here
KEY_ENV = "LITELLM_MASTER_KEY"          # the variable the harness reads the key from (--api-key-env)
MIN_KEY_LENGTH = 8
SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")      # one plain path segment: a label (BENCH_LABEL of the harness), a case id
DECIMAL = re.compile(r"[0-9]+(\.[0-9]+)?")      # maxCostUsd of a case: a decimal string
MASK, MIN_MASKED_LENGTH = "<redacted>", 8               # as in the harness (model-client.ts): a shorter value is a placeholder
MAX_TOKENS = 64000            # the real ceiling of the case (spec 4.2)
PREFLIGHT_TIMEOUT = 300                 # seconds: a reasoning model on high effort may think for a while
PREFLIGHT_PROMPT = "Antwoord alleen: OK"
SKIP_BUDGET, SKIP_FLAG, SKIP_ERROR, SKIP_NOT_STARTED = "budget bereikt", "gestopt (stopvlag)", "gestopt (fout)", "niet gestart"


class RunError(Exception):
    """A problem with how run.py was called or configured: one line on stderr and exit status 2."""


class Stop(Exception):
    """The driver ends here with this exit status: 3 a second benchfout, 4 the budget, 6 a signal. skip is the reason that
    skipped.json gives for the runs that were left."""

    def __init__(self, status, message, skip):
        super().__init__(message)
        self.status, self.skip = status, skip


# ---------------------------------------------------------------------------------------------------------------------
# small pure helpers
# ---------------------------------------------------------------------------------------------------------------------

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


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_json_replacing(path, value):
    """write_json by way of a file next to it, so that a reader (or a stop in the middle) never meets half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    write_json(temporary, value)
    os.replace(temporary, path)


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
# the key, the configurations, the case, the preflight file
# ---------------------------------------------------------------------------------------------------------------------

def read_key(path):
    """The key in the file at path, without the white space around it. RunError for a value that cannot be the key. The message
    names the file and the mistake, never the value."""
    try:
        key = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, ValueError) as e:
        raise RunError(f"cannot read the key file {path}: {type(e).__name__}") from None
    if len(key) < MIN_KEY_LENGTH:
        raise RunError(f"the key file {path} holds a value shorter than {MIN_KEY_LENGTH} characters")
    if key.startswith(f"{KEY_ENV}="):
        raise RunError(f"the key file {path} holds {KEY_ENV}=<value>; it has to hold the bare value")
    if '"' in key or "'" in key:
        raise RunError(f"the key file {path} holds a quote; it has to hold the bare value")
    return key


def load_config(path):
    """(the base URL of LiteLLM, {configuration: settings}) of the worker config (harness.json)."""
    config = read_json_object(path)
    if config is None:
        raise RunError(f"--config {path} is not a file with a JSON object")
    litellm = config.get("litellm")
    base_url = litellm.get("baseUrl") if isinstance(litellm, dict) else None
    if not (isinstance(base_url, str) and urlsplit(base_url).scheme in ("http", "https") and urlsplit(base_url).hostname):
        raise RunError(f"--config {path} has no litellm.baseUrl that is an http(s) URL")
    configurations = config.get("configurations")
    if not isinstance(configurations, dict):
        raise RunError(f"--config {path} has no configurations object")
    return base_url, configurations


def load_case(case_dir):
    """(the id, the ceiling of one run in dollars) of <case_dir>/case.json. The rest of a case is the harness's to judge."""
    path = Path(case_dir) / "case.json"
    case = read_json_object(path)
    if case is None:
        raise RunError(f"--case {case_dir} has no case.json with a JSON object")
    if not (isinstance(case.get("id"), str) and SEGMENT.fullmatch(case["id"])):
        raise RunError(f"{path}: the id has to be one plain path segment (letters, digits, '.', '_' and '-')")
    max_cost = case.get("maxCostUsd")
    if not (isinstance(max_cost, str) and DECIMAL.fullmatch(max_cost) and float(max_cost) > 0):
        raise RunError(f"{path}: maxCostUsd has to be a decimal string above zero, like \"1\"")
    return case["id"], float(max_cost)


def load_preflight(path, labels):
    """{label: {ok, reason}} for the labels, from the preflight file. RunError when the file is not there or unusable, or lacks a label."""
    entries = read_json_object(path)
    if entries is None:
        raise RunError(f"no preflight: {path} is not a file with a JSON object; run with --preflight first")
    missing = [label for label in labels if label not in entries]
    if missing:
        raise RunError(f"no preflight for {', '.join(missing)} in {path}; run with --preflight first")
    for label in labels:
        if not (isinstance(entries[label], dict) and isinstance(entries[label].get("ok"), bool)):
            raise RunError(f"the preflight of {label} in {path} must be an object with ok true or false")
    return {label: {"ok": entries[label]["ok"], "reason": entries[label].get("reason")} for label in labels}


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


# ---------------------------------------------------------------------------------------------------------------------
# what the harness writes
# ---------------------------------------------------------------------------------------------------------------------

def load_bench_result(path):
    """The parsed bench-result.json at path when it is a result at all: a JSON object with a status of the four. None when the file is
    absent, cannot be read, or is no result. Only a regular file is opened."""
    result = read_json_object(path)
    return result if result is not None and result.get("status") in STATUSES else None


def read_bench_result(path, case_id, label):
    """load_bench_result, and the result has to be of this case and label (its caseId and label say so); None otherwise."""
    result = load_bench_result(path)
    return result if result is not None and result.get("caseId") == case_id and result.get("label") == label else None


def run_dir_names(directory, case_id, label):
    """The names in directory that are run directories of this case and label: <case>-<label>-<8 hex>, exactly."""
    pattern = re.compile(re.escape(f"{case_id}-{label}-") + r"[0-9a-f]{8}")
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return []
    except OSError as e:
        raise RunError(f"cannot list {directory}: {e.strerror or type(e).__name__}") from None
    return sorted(name for name in names if pattern.fullmatch(name) and (Path(directory) / name).is_dir())


def existing_results(directory, case_id, label):
    """[(run directory name, result)] for the run directories of this case and label that hold a valid bench-result.json."""
    found = []
    for name in run_dir_names(directory, case_id, label):
        result = read_bench_result(Path(directory) / name / "bench-result.json", case_id, label)
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


def is_stop_not_failure(bench_error):
    """Whether a benchError is no failure of the bench: a stop (afgebroken), or a configuration without a probe."""
    return bench_error == ABORTED or (isinstance(bench_error, str) and bench_error.startswith(NOT_PROBED))


def not_probed_detail(bench_error):
    """The detail of `CONFIGURATION_NOT_PROBED: <detail>`; the whole benchError when there is none."""
    return bench_error.partition(":")[2].strip() or bench_error


class Harness:
    """The harness CLI as a subprocess: `node .../dist/cli.js`, or any command with review-bench (the tests use a stand-in). The key
    travels in the environment of the child, as LITELLM_MASTER_KEY, and in no argument. Its output is captured: what the driver needs it
    reads from the files the harness wrote, and what it quotes it masks."""

    def __init__(self, command, key):
        self.command = list(command)
        self.environment = {**os.environ, KEY_ENV: key}

    def call(self, *args):
        """Run it and wait for it, however long that takes: there is no timeout and nothing here ever kills it (see Stopping)."""
        try:
            return subprocess.run([*self.command, *map(str, args)], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", stdin=subprocess.DEVNULL, env=self.environment)
        except OSError as e:
            raise RunError(f"cannot start the harness ({self.command[0]}): {e.strerror or type(e).__name__}") from None


# ---------------------------------------------------------------------------------------------------------------------
# the preflight request
# ---------------------------------------------------------------------------------------------------------------------

class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is not followed: the key in the header would go along to wherever the answer points."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def kind_of(error):
    """What kind of error it is, and nothing it said: http.client puts the repr of a header value (the key) into some messages."""
    name = type(error).__name__
    inner = getattr(error, "reason", None)
    return f"{name} ({type(inner).__name__})" if isinstance(inner, BaseException) else name


def ask_litellm(base_url, configuration, settings, key, secrets):
    """The preflight of one configuration: (ok, reason, cost). cost is the usage.cost of the answer, None when there is none; reason is
    None for ok. The request is the real one in everything that matters: max_tokens, the reasoning effort, a tool, an instruction."""
    body = {"model": configuration, "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": PREFLIGHT_PROMPT}],
            "tools": [{"type": "function", "function": {"name": "noop", "description": "Doet niets.",
                                                         "parameters": {"type": "object", "properties": {}}}}]}
    if settings.get("reasoningEffort") is not None:
        body["reasoning_effort"] = settings["reasoningEffort"]
    request = urllib.request.Request(f"{base_url.rstrip('/')}/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json",
                                              "Authorization": f"Bearer {key}"})
    # no proxy: the key must go to the LiteLLM of --config and nowhere else
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    try:
        with opener.open(request, timeout=PREFLIGHT_TIMEOUT) as response:
            status, text = response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", errors="replace")      # all of it: the masking comes before the cut
        except Exception:
            text = ""
        finally:
            e.close()
        return False, f"HTTP {e.code}: {excerpt(text, secrets)}", None
    except Exception as e:          # a network, TLS, timeout or protocol problem of any kind: say what kind, not what it said
        return False, f"geen antwoord: {kind_of(e)}", None
    if status != 200:
        return False, f"HTTP {status}", None
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return False, "200 maar geen JSON", None
    usage = data.get("usage") if isinstance(data, dict) else None
    cost = amount(usage.get("cost")) if isinstance(usage, dict) else None
    if cost is None:
        return False, "200 zonder eindig getal in usage.cost", None
    return True, None, cost


# ---------------------------------------------------------------------------------------------------------------------
# the stop flag, and the driver
# ---------------------------------------------------------------------------------------------------------------------

class StopFlag:
    """The signal handler for SIGINT and SIGTERM. It only records that a signal came; it does not raise. That is what keeps
    subprocess.run waiting for the harness, which got the same signal and needs the time to write its result."""

    def __init__(self):
        self.signum = None

    def __call__(self, signum, frame):
        self.signum = signum

    @property
    def is_set(self):
        return self.signum is not None

    def name(self):
        return signal.Signals(self.signum).name


# What one call of the harness for a run came to: kind is "model" (a result of a model status), "aborted" (the bench was stopped),
# "not_probed" (the configuration has no accepted probe) or "benchfout"; reason says why for the last two.
Outcome = namedtuple("Outcome", "kind reason")

# Everything setup found out. preflight is {label: {ok, reason}} for the runs, None for the preflight itself.
Plan = namedtuple("Plan", "harness key out ledger budget models runs case_id case_dir max_cost config_path probe_dir base_url "
                          "configurations preflight_file preflight")


class Driver:
    def __init__(self, plan, flag):
        self.plan, self.flag = plan, flag
        self.out, self.ledger, self.models = plan.out, plan.ledger, plan.models
        self.secrets = [plan.key]
        self.verdicts = dict(plan.preflight or {})      # label -> {ok, reason}: what the preflight file says (a run call only)
        self.not_probed = {}        # label -> detail, for the labels that said CONFIGURATION_NOT_PROBED in this call
        self.halt = None            # why the runs that did not start did not: the skip reason of the Stop, else None

    @staticmethod
    def say(text):
        print(text, flush=True)

    # --- the rules --------------------------------------------------------------------------------------------------------

    def check_flag(self):
        if self.flag.is_set:
            raise Stop(EXIT_ABORTED, f"stopped by {self.flag.name()}; what was finished is booked in the ledger, nothing new starts",
                       SKIP_FLAG)

    def check_budget(self):
        """Stop before a run that could take the total over the budget: the total + the ceiling of a run (maxCostUsd of the case)."""
        total = ledger_total(read_ledger(self.ledger))
        if total + self.plan.max_cost > self.plan.budget:
            raise Stop(EXIT_BUDGET, f"the ledger total ${total:.4f} and the ceiling of a run, ${self.plan.max_cost:.2f}, would pass the "
                                    f"budget of ${self.plan.budget:.2f}; no new run starts", SKIP_BUDGET)

    # --- the two kinds of call --------------------------------------------------------------------------------------------

    def run(self):
        """rounds(), and at its end, also when it ends in a Stop or an error, skipped.json. A skipped.json that cannot be written is
        no reason to lose the exit status of a Stop that is already on its way: it is said on stderr and the Stop goes on."""
        ended = False
        try:
            self.rounds()
            ended = True
        except Stop as stop:
            self.halt = stop.skip
            raise
        except Exception:
            self.halt = SKIP_ERROR
            raise
        finally:
            try:
                self.write_skipped()
            except RunError as e:
                if ended:           # the work is done and nothing else is on its way: this is the failure
                    raise
                print(f"run.py: {mask_secrets(str(e), self.secrets)}", file=sys.stderr, flush=True)

    # --- the preflight ----------------------------------------------------------------------------------------------------

    def run_preflight(self):
        """One request per configuration; the amount into the ledger at once, the outcome into the preflight file after each one (what is
        done stays when the driver is stopped between two)."""
        path = self.plan.preflight_file
        entries = read_json_object(path) or {}
        for label in self.models:
            self.check_flag()
            stamp = utc_stamp()
            ok, reason, cost = ask_litellm(self.plan.base_url, label, self.plan.configurations[label], self.plan.key, self.secrets)
            append_ledger(self.ledger, {"id": f"preflight-{label}-{stamp}", "kind": "preflight", "label": label, "cost_usd": cost})
            reason = None if ok else mask_secrets(reason, self.secrets)
            entries[label] = {"ok": ok, "reason": reason}
            write_json_replacing(path, entries)
            self.say(f"{label} preflight: ok (${cost:.6f})" if ok else f"{label} preflight: afgewezen ({reason})")
        self.check_flag()
        ledger = read_ledger(self.ledger)
        self.say(f"preflight done: {path}; ledger ${ledger_total(ledger):.4f} ({len(ledger)} entries, {ledger_unknown(ledger)} without an amount)")

    # --- the runs ---------------------------------------------------------------------------------------------------------

    def rounds(self):
        for label in self.models:
            if self.rejected(label):
                self.say(f"{label}: the preflight rejected it ({self.rejection(label)}); it does not run")
        for n in range(1, self.plan.runs + 1):
            for label in self.models:
                self.one_run(label, n)
        self.check_flag()           # a signal at any moment is a stop, also in the last second of the last run
        entries = read_ledger(self.ledger)
        self.say(f"done: {self.out}; ledger ${ledger_total(entries):.4f} of ${self.plan.budget:.2f} "
                 f"({len(entries)} entries, {ledger_unknown(entries)} without an amount)")

    def rejected(self, label):
        return label in self.verdicts and not self.verdicts[label]["ok"]

    def rejection(self, label):
        return mask_secrets(str(self.verdicts[label]["reason"] or "no reason given"), self.secrets)

    def one_run(self, label, n):
        """Run n of a label: the stop flag, then resuming, then (in the loop) the budget."""
        self.check_flag()
        if self.rejected(label) or label in self.not_probed:
            return
        seen = existing_results(self.out / label / f"r{n}", self.plan.case_id, label)
        done = next((result for _, result in seen if result["status"] in MODEL_STATUSES), None)
        if done is not None:
            self.say(f"{label} r{n}: skipped, it has a result: {done['status']}")
            return
        # the benchfouten so far; one aborted by a stop or from a configuration without a probe is none, and a second one ends the driver
        failures = [result for _, result in seen
                    if result["status"] == "benchfout" and not is_stop_not_failure(result.get("benchError"))]
        while True:
            self.check_flag()           # first: a signal during the last attempt is a stop (6), also if that was the second benchfout
            if len(failures) >= 2:
                raise Stop(EXIT_BENCH, f"{label} r{n}: {len(failures)} benchfouten, the one repeat is used up; the last: "
                                       f"{excerpt(failure_reason(failures[-1]), self.secrets)}. The driver stops for JP",
                           f"gestopt na tweede benchfout op {label}")
            self.check_budget()
            outcome = self.attempt(label, n)
            if outcome.kind == "aborted":
                raise Stop(EXIT_ABORTED, f"{label} r{n}: the bench was stopped; its result is booked, and the run runs again "
                                         f"when the driver is started again", SKIP_FLAG)
            if outcome.kind == "not_probed":
                self.not_probed[label] = outcome.reason
                return
            if outcome.kind == "model":
                return
            failures.append({"status": "benchfout", "benchError": outcome.reason})

    def attempt(self, label, n):
        """One call of harness review-bench for a run: the call, the result, the ledger. Returns an Outcome."""
        case_id, plan = self.plan.case_id, self.plan
        directory = self.out / label / f"r{n}"
        directory.mkdir(parents=True, exist_ok=True)
        before = set(run_dir_names(directory, case_id, label))
        args = ["review-bench", "--case", plan.case_dir, "--config", plan.config_path, "--configuration", label,
                "--probe-dir", plan.probe_dir, "--label", label, "--out", directory, "--api-key-env", KEY_ENV]
        self.say(f"{label} r{n}: running")
        done = plan.harness.call(*args)
        new = sorted(set(run_dir_names(directory, case_id, label)) - before)
        result = read_bench_result(directory / new[0] / "bench-result.json", case_id, label) if len(new) == 1 else None
        if result is None:      # no usable result: a benchfout of an unknown cost, that counts for the repeat rule
            why = ("no new run directory" if not new else "more than one new run directory" if len(new) > 1
                   else "its bench-result.json is absent, unreadable, or of another case or label")
            run_id = new[0] if len(new) == 1 else f"{case_id}-{label}-r{n}-geen-resultaat-{utc_stamp()}"
            append_ledger(self.ledger, {"id": run_id, "kind": "run", "label": label, "run": n, "case": case_id, "cost_usd": None})
            reason = f"no usable result: {why} (harness exit status {done.returncode}: {excerpt(done.stderr, self.secrets)})"
            self.say(f"{label} r{n}: benchfout, {reason}")
            return Outcome("benchfout", reason)
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        cost = amount(usage.get("costUsd"))
        append_ledger(self.ledger, {"id": new[0], "kind": "run", "label": label, "run": n, "case": case_id, "cost_usd": cost})
        status, seconds = result["status"], result.get("durationMs")
        took = f" in {seconds / 1000:.1f}s" if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) else ""
        spent = "no amount" if cost is None else f"${cost:.6f}"
        self.say(f"{label} r{n}: {status}{took}, {spent} ({new[0]})")
        self.say(f"ledger total ${ledger_total(read_ledger(self.ledger)):.4f} of ${plan.budget:.2f}")
        if status in MODEL_STATUSES:
            return Outcome("model", None)
        bench_error = result.get("benchError")
        if bench_error == ABORTED:
            return Outcome("aborted", None)
        if isinstance(bench_error, str) and bench_error.startswith(NOT_PROBED):
            detail = excerpt(not_probed_detail(bench_error), self.secrets)
            self.say(f"{label} r{n}: not probed ({detail}); the label does not run again in this call")
            return Outcome("not_probed", detail)
        reason = excerpt(failure_reason(result), self.secrets)
        self.say(f"{label} r{n}: benchfout, {reason}")
        return Outcome("benchfout", reason)

    # --- skipped.json -----------------------------------------------------------------------------------------------------

    def skip_reason(self, label):
        """The first reason that fits a run of this label that has no result."""
        if self.rejected(label):
            return f"preflight afgewezen: {self.rejection(label)}"
        if label in self.not_probed:
            return f"niet geprobed: {self.not_probed[label]}"
        return self.halt or SKIP_NOT_STARTED

    def kept_rows(self):
        """The rows of the skipped.json that is there now for a label this call does not name, as long as that run still has no
        bench-result.json. A row that is no row (not a list, no plain label, no run of 1 or more, no reason) is not kept."""
        try:
            rows = json.loads((self.out / "skipped.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):
            return []
        kept = {}
        for row in rows if isinstance(rows, list) else ():
            if not (isinstance(row, dict) and isinstance(row.get("label"), str) and SEGMENT.fullmatch(row["label"])
                    and row["label"] not in self.models and isinstance(row.get("run"), int) and not isinstance(row["run"], bool)
                    and row["run"] >= 1 and isinstance(row.get("reason"), str)):
                continue
            if not existing_results(self.out / row["label"] / f"r{row['run']}", self.plan.case_id, row["label"]):
                kept.setdefault((row["label"], row["run"]), {"label": row["label"], "run": row["run"], "reason": row["reason"]})
        return list(kept.values())

    def write_skipped(self):
        """Written again at the end of every call that runs: a line for each expected run without a bench-result.json, from what is on disk,
        and the rows of a label this call does not name that still have no result."""
        rows = [{"label": label, "run": n, "reason": self.skip_reason(label)}
                for label in self.models for n in range(1, self.plan.runs + 1)
                if not existing_results(self.out / label / f"r{n}", self.plan.case_id, label)]
        rows += self.kept_rows()
        try:
            write_json(self.out / "skipped.json", rows)
        except OSError as e:
            raise RunError(f"cannot write skipped.json under {self.out}: {e.strerror or type(e).__name__}") from None


# ---------------------------------------------------------------------------------------------------------------------
# the call
# ---------------------------------------------------------------------------------------------------------------------

def setup(args):
    """Everything that can be wrong with the call, found before anything starts or is written: RunError (exit 2). Returns the Plan."""
    try:
        command = shlex.split(args.harness)
    except ValueError as e:
        raise RunError(f"--harness is not a command: {e}") from None
    if not command:
        raise RunError("--harness is empty")
    repeated = sorted({label for label in args.models if args.models.count(label) > 1})
    if repeated:
        raise RunError(f"--models names {', '.join(repeated)} more than once")
    key = read_key(args.key_file)
    base_url, configurations = load_config(args.config)
    unknown = [label for label in args.models if label not in configurations]
    if unknown:
        raise RunError(f"unknown configuration {', '.join(unknown)}; --config {args.config} has: {', '.join(configurations)}")
    for label in args.models:
        if not SEGMENT.fullmatch(label):
            raise RunError(f"configuration {label!r} in --config must be one plain path segment (letters, digits, '.', '_' and '-')")
        if not isinstance(configurations[label], dict):
            raise RunError(f"configuration {label} in --config {args.config} must be an object")
    case_id, max_cost = load_case(args.case)
    out, ledger = Path(args.out).resolve(), Path(args.ledger).resolve()
    read_ledger(ledger)
    preflight_file = Path(args.preflight_file).resolve() if args.preflight_file else out / "preflight.json"
    preflight = None if args.preflight else load_preflight(preflight_file, args.models)
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RunError(f"cannot write under {out}: {e.strerror or type(e).__name__}") from None
    return Plan(Harness(command, key), key, out, ledger, args.budget, list(args.models), args.runs, case_id,
                Path(args.case).resolve(), max_cost, Path(args.config).resolve(), Path(args.probe_dir).resolve(), base_url,
                configurations, preflight_file, preflight)


def positive_amount(text):
    """An amount of money above zero (a finite number: nan and inf are no limit)."""
    try:
        number = float(text)
    except ValueError:
        number = math.nan
    if not (math.isfinite(number) and number > 0):
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive amount")
    return number


def positive_int(text):
    try:
        number = int(text)
    except ValueError:
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number of 1 or more")
    return number


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    ap.add_argument("--harness", required=True, help='the harness command, e.g. "node /path/to/dist/cli.js"')
    ap.add_argument("--config", required=True, help="harness.json: litellm.baseUrl and the configurations")
    ap.add_argument("--probe-dir", required=True, help="the directory with the probes of the configurations (handed to the harness)")
    ap.add_argument("--case", required=True, help="the case directory (case.json: id and maxCostUsd are read here)")
    ap.add_argument("--models", nargs="+", required=True, metavar="CONFIGURATION", help="configurations of --config, run in this order")
    ap.add_argument("--runs", type=positive_int, default=3, help="runs per configuration (default 3)")
    ap.add_argument("--out", required=True, help="the output directory; it may hold the results of an earlier window: they are resumed")
    ap.add_argument("--ledger", required=True, help="the ledger of the cost, added to")
    ap.add_argument("--budget", type=positive_amount, required=True,
                    help="dollars: no run starts when the ledger total + the maxCostUsd of the case would pass this")
    ap.add_argument("--key-file", required=True, help="a file with the LiteLLM master key and nothing else; read once")
    ap.add_argument("--preflight", action="store_true", help="do the preflight (one request per configuration) instead of the runs")
    ap.add_argument("--preflight-file", help="where the preflight writes {label: {ok, reason}} and the runs read it (default <out>/preflight.json)")
    return ap


def main(argv=None):
    """Returns the exit status. Installs the handlers for SIGINT and SIGTERM for as long as it runs."""
    args = build_parser().parse_args(argv)
    flag = StopFlag()
    previous = {sig: signal.signal(sig, flag) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        plan = setup(args)
        driver = Driver(plan, flag)
        entries = read_ledger(plan.ledger)
        driver.say(f"{len(plan.models)} configurations, {plan.runs} runs each, case {plan.case_id}; ledger ${ledger_total(entries):.4f} of "
                   f"${plan.budget:.2f} ({len(entries)} entries)")
        if args.preflight:
            driver.run_preflight()
        else:
            driver.run()
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
