#!/usr/bin/env python3
"""Promptverfijner eval: multi-turn conversations with scripted user replies (PBI-8, T-2; M5, T-11a, T-11b).

Per model x case x seed the model gets the promptverfijner system prompt and the case input.
Until it answers with a fenced prompt it gets the case's scripted replies (max 4 user turns);
after the fence, R01/R02 get a pressure turn and R03/R05 a revision turn. Unlike speed.py the
prefix cache is left alone: reuse across turns is how the refiner is actually used.

Two backends send the conversations, with one conversation flow (converse) for both:
  ollama   (default) Ollama's own /api/chat. The ten plain cases; a case with variant "docs" is skipped.
  harness  every turn is one `harness run` of a manifest, after one `harness probe` per model. The labels of --models
           are those of models.json (endpoint, name, key variable, settings per variant). --variant nodocs runs
           the plain cases with profile answer; --variant docs runs the docs cases with profile tools, the docs addendum
           behind the system prompt and the four doc tools served from --docset. One invocation is one variant of one
           prompt version and has a run directory of its own:
             raw.jsonl       a row per turn and per conversation, and a row per probe (row contract: see turn_row, probe_row)
             blind-key.json  transcripts/<blind id>.md   as for the backend ollama
             manifests/      one manifest per turn, <blind id>-p<poging>-t<turn>.json, and the extra body of each probe
             harness/        what the harness wrote: <id>/result.json, trace.jsonl, tools/ and probe-<model>/probe.json
  What counts is what the harness wrote to those files and not its exit status: a run that does not complete exits 1 too.
  The key of a model is never a value here: a label names the environment variable (api_key_env) and only that name goes
  to the harness (--api-key-env).

  An invocation runs in three steps. First the probes of all the models, a row each. A model whose probe failed completely
  (every step an HTTP error, `model HTTP <status>`) runs nothing: its probe row has the label "geen aanbieder" (404 or 503 and
  a message that names a provider) or "probe-fout <status>". Then, for each model that runs, a plan row
  {"turn": "plan", "model", "variant", "conversations": [[case, seed], ...]} with every conversation it is going to have, so that
  score.py counts a conversation that never ran. Then the conversations, model after model.
  A harness run that does not complete ends the attempt as error and earns one second attempt of the whole conversation: the same
  seed and blind id, maxOutputTokens and maxWallSeconds doubled, rows with poging 2. transcripts/<blind id>.md is the attempt
  that counts, <blind id>-p1.md the first one. A conversation that ends no_final gets none.
  Three things end more than an attempt, each with a failing exit status:
    a model HTTP 401, 402 or 403 (the key, the credit or the rights, not the model) in a probe or a run: the whole invocation
      stops, a row {"turn": "stop", "model", "reason": "http_<status>"} follows the rows of that probe or attempt;
    --max-cost-usd: before every attempt, a second one too, the cost_usd of the turn rows so far (a missing amount is 0) is
      added up; from the cap on a row {"turn": "stop", "model", "reason": "max_cost"} ends the invocation;
    a run call that leaves no usable result (no result.json, one that is no result, or a trace.jsonl that cannot be read: a
      manifest the harness refused, a crash): the conversation ends as {"turn": "end", "status": "invocation_error"}, that
      model stops, the other models go on. What the harness said goes to stderr, masked, and into no row.
  After the run, check_key.py counts the files of the run directory that hold the key, once for each key variable of the models.

Stdlib only. Usage:
  ./run.py --models qwen3.8-gsq-rco:27b-iq3_s-text qwen3.6:35b-a3b-coding --seeds 1
  ./run.py --backend harness --harness "node /path/to/agent-harness/dist/cli.js" --variant nodocs \\
      --models gsq-lokaal qwen3.6-openrouter --seeds 1 2 3 --max-cost-usd 1
  (name the harness by its full path: a ~ is not expanded inside the quotes)
"""
import argparse
import hashlib
import json
import math
import os
import random
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROMPT = HERE.parent / "prompts" / "promptverfijner-systeem.txt"
ADDENDUM = HERE.parent / "prompts" / "promptverfijner-docs-addendum.txt"
CASES = HERE / "cases.jsonl"
MODELS = HERE / "models.json"
DOCSET = HERE / "docset"
CHECK_KEY = HERE / "check_key.py"
MAX_USER_TURNS = 4
# the harness limits that do not vary; --max-output-tokens and --max-wall-seconds set the other two (Task 13 settles them)
MAX_TURNS, MAX_TOOL_ERRORS, CONTEXT_TOKENS = 8, 2, 65536
MAX_OUTPUT_TOKENS, MAX_WALL_SECONDS = 4096, 240
DOC_TOOLS = ["search_product_docs", "get_product_doc", "list_product_docs", "related_product_docs"]
MASK, MIN_MASKED_LENGTH = "<redacted>", 8     # as in the harness (model-client.ts): a shorter value is a placeholder
RUN_STATUSES = ("completed", "failed", "budget_exceeded", "timed_out")
VERDICTS = ("reliable", "unreliable", "none")
KEY_STATUSES = (401, 402, 403)                  # the key, the credit (402: the limit is used up) or the rights, not the model
NO_PROVIDER_STATUSES = (404, 503)               # what OpenRouter answers when no provider of the model fits the provider block
HTTP_ERROR = re.compile(r"model HTTP (\d{3})\b")      # the start of the message of the harness's ModelError (model-client.ts)
OLLAMA_ONLY = ("num_ctx", "think", "host")     # the options the backend harness does not have
HARNESS_ONLY = ("models_file", "variant", "harness", "docset", "max_output_tokens", "max_wall_seconds", "max_cost_usd")


class RunError(Exception):
    """A problem run.py reports in one line before it exits with status 1."""


class HarnessError(RunError):
    """The harness did not deliver what run.py needs: no result.json, trace.jsonl or probe.json, or one it cannot read."""


class NoResult(HarnessError):
    """A run call produced no usable result: there is no result.json, or read_result rejects it (not JSON, no usable status),
    or read_trace rejects the trace.jsonl (missing, not UTF-8, a line that is no JSON or no event). That is a fault of the
    call and not of the model (spec 5.7): a manifest the harness refused, PROBE_REQUIRED, a run directory that was there
    already, a crash, a harness that broke down while it wrote. It gets an invocation_error and no second attempt. Only
    Harness.run raises it; a harness that cannot be started at all, or an unusable probe.json, stay plain HarnessErrors and
    stop run.py."""


class Stop(Exception):
    """The invocation ends here, for every model: the stop row names the model that was about to be asked (reason http_<status>
    or max_cost), run.py says why on stderr and exits with a failure status. Nothing more is sent to any model."""

    def __init__(self, model, reason, why):
        super().__init__(why)
        self.model, self.reason = model, reason


def key_stop(label, reason):
    """The Stop for a model HTTP 401, 402 or 403 (reason is key_problem's http_<status>)."""
    status = reason.split("_", 1)[1]
    return Stop(label, reason, f"{label}: model HTTP {status}, a problem with the key, the credit (402: the limit is used up) "
                               f"or the rights and not with the model; no model is asked anything more")


# One attempt at a conversation: status (final, no_final, error, or invocation_error when a run call left no usable result), the
# messages of the conversation, its wall time, `stop` (http_<status>, when a model call got a 401, 402 or 403; else None) and
# `problem` (for an invocation_error what the harness said, with the key masked; else None)
Attempt = namedtuple("Attempt", "status messages wall stop problem")


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


def converse(system, case, ask):
    """Run one conversation, whatever the backend. ask(messages, turn) sends the messages to the model (the system prompt
    first, the new user message last), writes the row of that turn and returns the model's text, or None when the turn
    failed. Returns (status, messages): final, no_final or error (a turn that failed)."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": case["input"]}]
    replies = list(case.get("replies") or [])
    pressure, revision = case.get("pressure_reply"), case.get("revision")
    extra_sent = False
    user_turns, turn = 1, 0
    while True:
        turn += 1
        content = ask(messages, turn)
        if content is None:
            return "error", messages
        messages.append({"role": "assistant", "content": content})
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


def ollama_ask(api, model, seed, opts, think, log):
    """The model call of the backend ollama for converse: /api/chat, and the row of the turn (or of its error) to log."""
    def ask(messages, turn):
        t0 = time.perf_counter()
        try:
            r = api.call("/api/chat", {"model": model, "messages": messages, "stream": False,
                                       "think": think, "keep_alive": "10m",
                                       "options": {**opts, "seed": seed}})
        except Exception as e:  # HTTP error, timeout: record and move on
            log({"turn": turn, "error": str(e)[:300], "wall_s": round(time.perf_counter() - t0, 2)})
            return None
        msg = r.get("message", {})
        content = msg.get("content", "")
        ns = 1e9
        log({"turn": turn, "content": content, "thinking_chars": len(msg.get("thinking") or ""),
             "prompt_eval_count": r.get("prompt_eval_count"),
             "prompt_eval_s": round((r.get("prompt_eval_duration") or 0) / ns, 3),
             "eval_count": r.get("eval_count"), "eval_s": round((r.get("eval_duration") or 0) / ns, 3),
             "load_s": round((r.get("load_duration") or 0) / ns, 3),
             "total_s": round((r.get("total_duration") or 0) / ns, 3),
             "done_reason": r.get("done_reason"), "wall_s": round(time.perf_counter() - t0, 2)})
        return content
    return ask


def transcript(messages):
    out = []
    for m in messages[1:]:
        who = "Gebruiker" if m["role"] == "user" else "Model"
        out.append(f"### {who}\n\n{m['content']}\n")
    return "\n".join(out)


def system_text(prompt_path, variant, product_id):
    """The system text as it is sent. Without docs it is the prompt file as it is (so its hash is that of the backend
    ollama). With docs it is the prompt file, a blank line and the docs addendum, both without trailing whitespace, with the
    product id filled into the addendum (str.replace: only the addendum has the placeholder, and a brace elsewhere is no
    field)."""
    prompt = Path(prompt_path).read_text(encoding="utf-8")
    if variant != "docs":
        return prompt
    addendum = ADDENDUM.read_text(encoding="utf-8").rstrip().replace("{product_id}", product_id)
    return prompt.rstrip() + "\n\n" + addendum


def select_cases(ids, variant):
    """The cases of cases.jsonl that belong to variant (docs: those with variant "docs"; nodocs and the backend ollama:
    the others), narrowed to the comma-separated ids when given."""
    cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
    cases = [c for c in cases if (c.get("variant") == "docs") == (variant == "docs")]
    if ids:
        wanted = set(ids.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    return cases


def load_models(path, labels):
    """{label: settings} for the labels from the models file. Per label: base_url, name, optionally api_key_env (the NAME
    of the environment variable that holds the key), and a block per variant (nodocs, docs, probe) with an extraBody."""
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
        for field in ("base_url", "name"):
            if not (isinstance(cfg.get(field), str) and cfg[field]):
                raise RunError(f"label {label} has no {field} in {path}")
        # a value in this field would end up in argv: it must read as the name of a variable (^[A-Z_][A-Z0-9_]*$), and it
        # is never quoted back
        if "api_key_env" in cfg and not (isinstance(cfg["api_key_env"], str)
                                         and re.fullmatch(r"[A-Z_][A-Z0-9_]*", cfg["api_key_env"])):
            raise RunError(f"label {label}: api_key_env in {path} must be the name of an environment variable")
        for variant in ("nodocs", "docs", "probe"):
            block = cfg.get(variant)
            if not isinstance(block, dict):
                raise RunError(f"label {label} has no {variant} block in {path}")
            if not isinstance(block.get("extraBody"), dict):
                raise RunError(f"label {label}: the {variant} block has no extraBody object in {path}")
    return {label: models[label] for label in labels}


def read_product_id(docset_dir):
    """The product id of the docset (docset.json), which the doc tools and the addendum use."""
    path = Path(docset_dir) / "docset.json"
    try:
        product_id = json.loads(path.read_text(encoding="utf-8")).get("product_id")
    except (OSError, ValueError, AttributeError) as e:
        raise RunError(f"cannot read the docset: {path} ({type(e).__name__})") from None
    if not (isinstance(product_id, str) and product_id):
        raise RunError(f"{path} has no product_id")
    return product_id


def tools_block(command, docset_dir, product_id):
    """The tools of a docs manifest: the doc server is the harness itself (`<harness> doc-server`), so its command and first
    arguments are those of --harness."""
    return {"server": {"command": command[0],
                       "args": [*command[1:], "doc-server", "--dir", str(docset_dir), "--product-id", product_id]},
            "allow": list(DOC_TOOLS)}


def probe_dir_name(model):
    """The directory harness probe writes to under --out: probeDir of agent-harness src/probe.ts."""
    return "probe-" + re.sub(r"[^a-z0-9.-]+", "-", model.lower())


def mask_secrets(text, secrets):
    """text with every occurrence of a secret replaced by MASK, on top of the masking the harness does itself. The trimmed
    form of a secret counts too (undici trims a header value, so that is what a server echoes), the longest form goes first
    (one can contain another), and a value shorter than MIN_MASKED_LENGTH is a placeholder that is left alone."""
    forms = {form for secret in secrets for form in (secret, secret.strip()) if len(form) >= MIN_MASKED_LENGTH}
    for form in sorted(forms, key=len, reverse=True):
        text = text.replace(form, MASK)
    return text


def excerpt(text, secrets=(), limit=300):
    """The start of text on one line, for an error message, with the secrets masked first and the cut made second: a value
    that straddles the limit would otherwise leave its first characters behind."""
    return " ".join(mask_secrets(text, secrets).split())[:limit] or "no output"


def read_result(run_dir):
    """result.json of a harness run, as the harness wrote it (HarnessError when it is not there or no result)."""
    path = Path(run_dir) / "result.json"
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise HarnessError(f"{run_dir}: the harness wrote no result.json") from None
    except ValueError:
        raise HarnessError(f"{path} is not JSON") from None
    if not isinstance(result, dict) or result.get("status") not in RUN_STATUSES:
        raise HarnessError(f"{path} is no result: it has no status ({', '.join(RUN_STATUSES)})")
    return result


def read_trace(run_dir):
    """The events of trace.jsonl of a harness run, in order (HarnessError when it is not there or a line is no event)."""
    path = Path(run_dir) / "trace.jsonl"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise HarnessError(f"{run_dir}: the harness wrote no trace.jsonl") from None
    except ValueError:      # a UnicodeDecodeError: a trace that is not UTF-8 is as unusable as one that is not JSON
        raise HarnessError(f"{path} is not UTF-8") from None
    events = []
    # split on "\n" only: str.splitlines() also cuts at U+2028, U+2029 and U+0085, which JSON.stringify leaves raw in a string
    for n, line in enumerate(text.split("\n"), start=1):
        if line.strip():
            try:
                event = json.loads(line)
            except ValueError:
                raise HarnessError(f"{path}: line {n} is not JSON") from None
            if not isinstance(event, dict):
                raise HarnessError(f"{path}: line {n} is no event")
            events.append(event)
    return events


def parse_arguments(text):
    """The arguments of a traced tool call (the harness traces them as a string): the object when the string is a JSON
    object, else the string as it is, so a model's malformed arguments stay readable."""
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return text
    return parsed if isinstance(parsed, dict) else text


def tool_calls(events):
    """[{name, arguments, ok, error_code}] for the tool_call events of a trace, in order, each paired by callId with its
    tool_result. A call without a result has ok None: nobody saw it end."""
    outcomes = {e.get("callId"): e for e in events if e.get("type") == "tool_result"}
    calls = []
    for e in events:
        if e.get("type") == "tool_call":
            outcome = outcomes.get(e.get("callId"))
            calls.append({"name": e.get("name"), "arguments": parse_arguments(e.get("arguments")),
                          "ok": outcome["ok"] if outcome else None,
                          "error_code": outcome.get("errorCode") if outcome else None})
    return calls


def turn_row(result, events, turn, run_id, prompt_sha, limits):
    """The row of one conversation turn from the result and the trace of its harness run (without the conversation keys
    model, case, seed, blind_id, backend, variant and poging, which the caller puts in front). content is the answer, and ''
    for a turn that did not complete; the counts and cost_usd are those of result.usage, None where it names none (a cost of
    0 is a cost: cost does not depend on usage.source); reasoning_tokens are part of output_tokens and are not added;
    providers are the distinct providers of the model responses in the order first seen; finish_reason is that of the last
    model response; wall_s is the duration of the run in seconds; harness_run is the run directory relative to the run
    directory of run.py; prompt_sha256 is the hash of the system text as sent."""
    usage = result.get("usage") or {}
    responses = [e for e in events if e.get("type") == "model_response"]
    providers = []
    for e in responses:
        if e.get("provider") and e["provider"] not in providers:
            providers.append(e["provider"])
    duration = result.get("durationMs")
    return {"turn": turn, "content": result.get("answer") or "", "status": result["status"],
            "error_code": (result.get("error") or {}).get("code"), "model_turns": usage.get("turns"),
            "tool_calls": tool_calls(events), "input_tokens": usage.get("inputTokens"),
            "output_tokens": usage.get("outputTokens"), "cached_tokens": usage.get("cachedTokens"),
            "reasoning_tokens": usage.get("reasoningTokens"), "cost_usd": usage.get("costUsd"), "providers": providers,
            "finish_reason": responses[-1].get("finishReason") if responses else None,
            "wall_s": duration / 1000 if duration is not None else None, "harness_run": f"harness/{run_id}",
            "prompt_sha256": prompt_sha, "limits": limits}


def http_status(message):
    """The status at the start of a message of the harness that reads `model HTTP <status>`: what the ModelError of a model
    call says. run.ts quotes it as the error of a run (code MODEL_ERROR) and probe.ts as the reason of a probe step. None for
    any other text (a failed connection is `model request failed`, not an HTTP status)."""
    found = HTTP_ERROR.match(message) if isinstance(message, str) else None
    return int(found.group(1)) if found else None


def key_problem(messages):
    """`http_<status>` for the first of messages that is a model HTTP 401, 402 or 403: a problem with the key, the credit or
    the rights, and none with the model, so no other request of this key will do better. None when no message is."""
    return next((f"http_{status}" for status in map(http_status, messages) if status in KEY_STATUSES), None)


def probe_label(steps):
    """The label of a probe that failed completely: every step ended in an HTTP error (a reason that starts with
    `model HTTP `), so there is no verdict to speak of. `geen aanbieder` when every step has status 404 or 503 and a message
    that names a provider, case-insensitive (OpenRouter's answer when no provider of the model fits the provider block;
    runbook model-comparison.md, Taak 2); else `probe-fout <status of the first step>`. None for any other probe."""
    results = list(steps.values())
    statuses = [http_status(result.get("reason")) for result in results]
    if not results or any(result.get("pass") or status is None for result, status in zip(results, statuses)):
        return None
    if all(status in NO_PROVIDER_STATUSES and "provider" in result["reason"].lower()
           for result, status in zip(results, statuses)):
        return "geen aanbieder"
    return f"probe-fout {statuses[0]}"


def probe_row(label, variant, probe, secrets=()):
    """The row of a probe: its verdict (tool_calling of probe.json), the label of a probe that failed completely (probe_label;
    None otherwise) and, per step that did not pass, the reason, which score.py prints. The reasons pass through
    mask_secrets: the harness masks the key in its messages already, and this is a second line."""
    verdict = probe.get("tool_calling")
    if verdict not in VERDICTS:
        raise HarnessError(f"probe.json of {label} has no tool_calling verdict ({', '.join(VERDICTS)})")
    steps = probe.get("steps") or {}
    reasons = {step: mask_secrets(result["reason"], secrets) if isinstance(result.get("reason"), str) else result.get("reason")
               for step, result in steps.items() if not result.get("pass")}
    return {"turn": "probe", "model": label, "backend": "harness", "variant": variant, "verdict": verdict,
            "label": probe_label(steps), "reasons": reasons}


def file_name(label):
    """label as part of a file name: a run of characters other than letters, digits, . _ - becomes one '-'."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", label)


def key_args(cfg):
    """--api-key-env <name> for a label that needs a key. The value is read by the harness; run.py never touches it."""
    return ["--api-key-env", cfg["api_key_env"]] if cfg.get("api_key_env") else []


class Harness:
    """The harness CLI as a subprocess: `node .../dist/cli.js`, or any command with probe and run (the tests use a fake)."""

    def __init__(self, command, out, secrets=()):
        """secrets: the key values of the models in use. They are masked in everything quoted from the harness."""
        self.command, self.out, self.secrets = command, Path(out), list(secrets)

    def call(self, *args):
        try:
            return subprocess.run([*self.command, *map(str, args)], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", stdin=subprocess.DEVNULL)
        except OSError as e:
            raise HarnessError(f"cannot start the harness ({self.command[0]}): {e.strerror}") from None

    def probe(self, cfg, extra_body_file):
        """harness probe for the model of cfg; the probe.json it wrote. The extra body is a file: the probe has no model
        block."""
        done = self.call("probe", "--base-url", cfg["base_url"], "--model", cfg["name"], "--out", self.out,
                         *key_args(cfg), "--extra-body-file", extra_body_file)
        path = self.out / probe_dir_name(cfg["name"]) / "probe.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HarnessError(f"no usable probe.json for {cfg['name']} at {path} "
                               f"(harness exit status {done.returncode}: {excerpt(done.stderr, self.secrets)})") from None

    def run(self, manifest_path, run_id, cfg):
        """harness run of a manifest, without --skip-probe; (result, trace events) from the files it wrote. Its exit
        status says nothing more than the result does. A call that produced no usable result raises NoResult: no result.json,
        one that read_result rejects, or a trace.jsonl that read_trace rejects. The message names the file (and the line),
        the exit status and what the harness said on stderr, masked; it never quotes the content of a file, which could
        hold the key."""
        done = self.call("run", manifest_path, "--out", self.out, *key_args(cfg))
        run_dir = self.out / run_id
        try:
            return read_result(run_dir), read_trace(run_dir)
        except HarnessError as e:
            raise NoResult(f"{e} (harness exit status {done.returncode}: {excerpt(done.stderr, self.secrets)})") from None


class HarnessBackend:
    """What holds for every conversation of one invocation of the backend harness: the variant (so the profile and the system
    text), the models, the temperature and the tools. The settings that differ per attempt (poging, limits) are the
    parameters of attempt(), so a second attempt of a conversation is another call of it."""

    def __init__(self, harness, out, variant, system, models, temperature, tools):
        self.harness, self.variant, self.system, self.models = harness, variant, system, models
        self.temperature, self.tools = temperature, tools
        self.prompt_sha = hashlib.sha256(system.encode()).hexdigest()
        self.manifests = Path(out) / "manifests"

    def probe(self, label):
        """Run the probe of a label and return its row."""
        cfg = self.models[label]
        body = self.manifests / f"probe-{file_name(label)}.extra-body.json"
        body.write_text(json.dumps(cfg["probe"]["extraBody"], indent=2) + "\n", encoding="utf-8")
        return probe_row(label, self.variant, self.harness.probe(cfg, body), self.harness.secrets)

    def manifest(self, cfg, bid, poging, turn, messages, seed, limits):
        """The manifest of one turn. messages is the conversation so far with the new user message last: the system prompt
        is `system`, the new user message is `prompt` and what lies between is `history` (left out at turn 1)."""
        block = cfg[self.variant]
        model = {"baseUrl": cfg["base_url"], "name": cfg["name"]}
        if "reasoningEffort" in block:
            model["reasoningEffort"] = block["reasoningEffort"]
        model["extraBody"] = {**block["extraBody"], "temperature": self.temperature, "seed": seed}
        manifest = {"id": f"{bid}-p{poging}-t{turn}", "profile": "tools" if self.tools else "answer", "system": self.system}
        if messages[1:-1]:
            manifest["history"] = messages[1:-1]
        manifest.update(prompt=messages[-1]["content"], model=model)
        if self.tools:
            manifest["tools"] = self.tools
        manifest["limits"] = limits
        return manifest

    def attempt(self, label, case, seed, bid, poging, limits, write):
        """One attempt at a conversation, every turn one harness run. write(row) gets the row of each turn and then the
        closing row (status final, no_final or error; conversation_wall_s; cost_usd, the sum of the known costs of the turns,
        None when no turn named one). A turn that does not end completed has its row, with content '', and ends the attempt.
        Returns an Attempt (status, messages, wall_s, stop, problem). stop is http_<status> when the model call of the turn that
        ended the attempt got a 401, 402 or 403. A run call that leaves no usable result (NoResult) has no row of its turn: the
        closing row says invocation_error, and problem is what the harness said; that text is not written to any row."""
        cfg = self.models[label]
        base = {"model": label, "case": case["id"], "seed": seed, "blind_id": bid, "backend": "harness",
                "variant": self.variant, "poging": poging}
        costs, stop, problem = [], None, None

        def ask(messages, turn):
            nonlocal stop, problem
            manifest = self.manifest(cfg, bid, poging, turn, messages, seed, limits)
            path = self.manifests / f"{manifest['id']}.json"
            path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            try:
                result, events = self.harness.run(path, manifest["id"], cfg)
            except NoResult as e:
                problem = str(e)
                return None
            row = turn_row(result, events, turn, manifest["id"], self.prompt_sha, limits)
            write({**base, **row})
            costs.append(row["cost_usd"])
            if result["status"] == "completed":
                return row["content"]
            stop = key_problem([(result.get("error") or {}).get("message")])
            return None

        t0 = time.perf_counter()
        status, messages = converse(self.system, case, ask)
        wall = round(time.perf_counter() - t0, 1)
        known = [c for c in costs if c is not None]
        status = "invocation_error" if problem else status
        write({**base, "turn": "end", "status": status, "conversation_wall_s": wall,
               "cost_usd": round(sum(known), 8) if known else None})
        return Attempt(status, messages, wall, stop, problem)


def blind_ids(stamp):
    """A generator of unique six-hexadecimal-digit blind ids, the same sequence for the same stamp."""
    rng, used = random.Random(stamp), set()
    while True:
        bid = f"{rng.randrange(16**6):06x}"
        while bid in used:
            bid = f"{rng.randrange(16**6):06x}"
        used.add(bid)
        yield bid


class Invocation:
    """One invocation of the backend harness, in three phases: the probes of all the models; then, for each model that
    runs, its plan row (every conversation it is going to have); then the conversations, model after model. The plan rows
    come before the first conversation, so that score.py counts a conversation that never ran, of any model, as not finished."""

    def __init__(self, backend, labels, cases, seeds, limits, out, ids, cap=None):
        """cap: --max-cost-usd (None: no cap)."""
        self.backend, self.labels, self.cases, self.seeds, self.limits = backend, list(labels), cases, seeds, limits
        self.out, self.ids, self.cap = Path(out), ids, cap
        self.key = {}                       # blind id -> the conversation; blind-key.json
        self.costs = []                     # the cost_usd of each turn row written so far; a missing amount counts as 0
        self.failed = False                 # a call left no result, or the invocation was stopped: the exit status is not 0
        self.raw = None

    def write(self, row):
        self.raw.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.raw.flush()
        if isinstance(row.get("turn"), int):      # not the closing row: it repeats the cost of its turns
            self.costs.append(row.get("cost_usd") or 0)

    def capped(self):
        """Whether the cost of the turns so far has reached --max-cost-usd: nothing new may start."""
        return self.cap is not None and math.fsum(self.costs) >= self.cap

    def cap_stop(self, label):
        return Stop(label, "max_cost", f"{label}: the cost of the turns so far, ${math.fsum(self.costs):.4f}, has reached "
                                       f"--max-cost-usd {self.cap}; no new attempt starts")

    def probes(self):
        """The probe of each model, in order. Returns the labels of the models that go on to conversations: not one whose
        probe failed completely (it ran nothing: it has its probe row and nothing else), and with docs only one whose probe
        is reliable."""
        running = []
        for label in self.labels:
            probe = self.backend.probe(label)
            self.write(probe)
            print(f"{label} probe: {probe['label'] or probe['verdict']}", flush=True)
            problem = key_problem(probe["reasons"].values())
            if problem:
                raise key_stop(label, problem)
            if probe["label"]:
                print(f"{label}: no conversations after a probe in which every step ended in an HTTP error", flush=True)
            elif self.backend.variant == "docs" and probe["verdict"] != "reliable":
                print(f"{label}: no docs conversations after a probe that is not reliable", flush=True)
            else:
                running.append(label)
        return running

    def plans(self, running):
        conversations = [[case["id"], seed] for case in self.cases for seed in self.seeds]
        for label in running:
            self.write({"turn": "plan", "model": label, "variant": self.backend.variant, "conversations": conversations})

    def attempt(self, label, case, seed, bid, poging, limits):
        done = self.backend.attempt(label, case, seed, bid, poging, limits, self.write)
        print(f"{label} {case['id']} seed {seed}{' (poging 2)' if poging == 2 else ''}: {done.status} in {done.wall}s",
              flush=True)
        if done.problem:      # the message is already masked; it goes to stderr and into no row
            print(f"run.py: {label} {case['id']} seed {seed}: {done.problem}", file=sys.stderr, flush=True)
            self.failed = True
        return done

    def save_transcript(self, bid, case, messages, suffix=""):
        (self.out / "transcripts" / f"{bid}{suffix}.md").write_text(
            f"# Transcript {bid} ({case['id']}: {case['titel']})\n\n{transcript(messages)}", encoding="utf-8")

    def conversation(self, label, case, seed):
        """The first attempt at a conversation and, when a harness run in it did not complete (status error), one second
        attempt: the whole conversation again, with the same seed and blind id and with maxOutputTokens and maxWallSeconds
        doubled. The transcript of the attempt that counts is <blind id>.md, that of the first <blind id>-p1.md. A key problem
        raises the Stop. Returns False when a run call left no usable result: the model stops, and there is no second attempt.
        Before every attempt the cost is checked against the cap, the second attempt included."""
        if self.capped():
            raise self.cap_stop(label)
        bid = next(self.ids)
        self.key[bid] = {"model": label, "case": case["id"], "seed": seed}      # before the rows, so a crash keeps it
        (self.out / "blind-key.json").write_text(json.dumps(self.key, indent=1))
        counting = self.attempt(label, case, seed, bid, 1, self.limits)
        if counting.status == "error" and not counting.stop:
            if self.capped():      # the second attempt would start over the cap: the first one is the attempt that counts
                self.save_transcript(bid, case, counting.messages)
                raise self.cap_stop(label)
            self.save_transcript(bid, case, counting.messages, "-p1")
            doubled = {**self.limits, "maxOutputTokens": 2 * self.limits["maxOutputTokens"],
                       "maxWallSeconds": 2 * self.limits["maxWallSeconds"]}
            counting = self.attempt(label, case, seed, bid, 2, doubled)
        self.save_transcript(bid, case, counting.messages)
        if counting.stop:      # a problem with the key, the credit or the rights: the turn and the closing row are written
            raise key_stop(label, counting.stop)
        return counting.status != "invocation_error"

    def model(self, label):
        """All the conversations of one model, up to a call that left no result."""
        for case in self.cases:
            for seed in self.seeds:
                if not self.conversation(label, case, seed):
                    print(f"{label}: no more conversations after a run call without a usable result", flush=True)
                    return

    def run(self, raw):
        """Run the invocation. Returns whether it must end with a failure status: it was stopped, or a run call left no
        result."""
        self.raw = raw
        try:
            running = self.probes()
            self.plans(running)
            for label in running:
                self.model(label)
        except Stop as stop:
            self.write({"turn": "stop", "model": stop.model, "reason": stop.reason})
            print(f"run.py: stopped: {stop}", file=sys.stderr, flush=True)
            self.failed = True
        return self.failed


def check_keys(names, run_dir, secrets):
    """check_key.py over run_dir, once for each key variable in names, with the value in the environment it inherits and only
    the name in argv. What it prints (counts and the name of the variable, never a value) is passed on, masked all the same.
    Returns whether a check found the key or could not be made."""
    failed = False
    for name in sorted(names):
        try:
            done = subprocess.run([sys.executable, str(CHECK_KEY), "--env", name, str(run_dir)], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
        except OSError as e:
            print(f"run.py: cannot run check_key.py for {name}: {e.strerror}", file=sys.stderr, flush=True)
            failed = True
            continue
        sys.stdout.write(mask_secrets(done.stdout, secrets))
        sys.stdout.flush()
        sys.stderr.write(mask_secrets(done.stderr, secrets))
        sys.stderr.flush()
        failed = failed or done.returncode != 0
    return failed


def run_ollama(args):
    system = system_text(args.prompt or PROMPT, "nodocs", None)
    prompt_sha = hashlib.sha256(system.encode()).hexdigest()
    cases = select_cases(args.cases, "nodocs")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out or HERE.parent / "results" / f"refiner-{stamp}")
    (out / "transcripts").mkdir(parents=True, exist_ok=True)
    api = Ollama(args.host or os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434"))
    version = api.call("/api/version").get("version")
    tei = tei_state()
    opts = {"num_ctx": 16384 if args.num_ctx is None else args.num_ctx, "temperature": args.temperature}
    think = args.think == "true"
    ids, key = blind_ids(stamp), {}

    with open(out / "raw.jsonl", "a") as raw:
        for model in args.models:
            for case in cases:
                for seed in args.seeds:
                    bid = next(ids)
                    ps = [m["name"] for m in api.call("/api/ps").get("models", [])]
                    base = {"model": model, "case": case["id"], "seed": seed, "blind_id": bid,
                            "ps_before": ps, "tei_on": tei, "ollama": version,
                            "prompt_sha256": prompt_sha, "options": opts, "think": think}

                    def log(row):
                        raw.write(json.dumps({**base, **row}, ensure_ascii=False) + "\n")
                        raw.flush()

                    t0 = time.perf_counter()
                    status, messages = converse(system, case, ollama_ask(api, model, seed, opts, think, log))
                    wall = round(time.perf_counter() - t0, 1)
                    log({"turn": "end", "status": status, "conversation_wall_s": wall})
                    (out / "transcripts" / f"{bid}.md").write_text(
                        f"# Transcript {bid} ({case['id']}: {case['titel']})\n\n{transcript(messages)}")
                    key[bid] = {"model": model, "case": case["id"], "seed": seed}
                    print(f"{model} {case['id']} seed {seed}: {status} in {wall}s", flush=True)
    (out / "blind-key.json").write_text(json.dumps(key, indent=1))
    print(f"done: {out}")


def run_harness(args):
    try:
        command = shlex.split(args.harness)
    except ValueError as e:
        raise RunError(f"--harness is not a command: {e}") from None
    if not command:
        raise RunError("--harness is empty")
    variant = args.variant
    cases = select_cases(args.cases, variant)
    if not cases:
        raise RunError(f"no case to run: the variant {variant} has no case "
                       f"{'among ' + args.cases if args.cases else 'in cases.jsonl'}")
    models = load_models(args.models_file or MODELS, args.models)
    # the key variables are checked before anything runs; only their names are ever shown
    names = {cfg["api_key_env"] for cfg in models.values() if cfg.get("api_key_env")}
    unset = sorted(name for name in names if not os.environ.get(name))
    if unset:
        raise RunError(f"environment variable {', '.join(unset)} is not set (the harness reads the key from it)")
    secrets = [os.environ[name] for name in sorted(names)]       # for masking only: never printed, never written
    docset_dir, product_id = Path(args.docset or DOCSET).resolve(), None
    if variant == "docs":
        product_id = read_product_id(docset_dir)
    system = system_text(args.prompt or PROMPT, variant, product_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out or HERE.parent / "results" / f"refiner-{stamp}").resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise RunError(f"{out} already holds files: one invocation has a run directory of its own")
    (out / "transcripts").mkdir(parents=True)
    (out / "manifests").mkdir()
    backend = HarnessBackend(Harness(command, out / "harness", secrets), out, variant, system, models, args.temperature,
                             tools_block(command, docset_dir, product_id) if variant == "docs" else None)
    limits = {"maxTurns": MAX_TURNS, "maxOutputTokens": args.max_output_tokens or MAX_OUTPUT_TOKENS,
              "maxWallSeconds": args.max_wall_seconds or MAX_WALL_SECONDS, "maxToolErrors": MAX_TOOL_ERRORS,
              "contextTokens": CONTEXT_TOKENS}      # both options are positive, so `or` only supplies the default
    invocation = Invocation(backend, args.models, cases, args.seeds, limits, out, blind_ids(stamp), args.max_cost_usd)
    try:
        with open(out / "raw.jsonl", "a", encoding="utf-8") as raw:
            failed = invocation.run(raw)
    except BaseException:
        check_keys(names, out, secrets)         # a run that broke off may have left the key behind as well
        raise
    (out / "blind-key.json").write_text(json.dumps(invocation.key, indent=1))
    leaked = check_keys(names, out, secrets)
    if leaked:
        print(f"run.py: check_key.py found the key in the run directory or could not check it (see above): "
              f"do not keep or share {out}", file=sys.stderr, flush=True)
    print(f"done: {out}")
    return 1 if failed or leaked else 0


def positive_int(text):
    number = int(text)
    if number < 1:
        raise argparse.ArgumentTypeError(f"{text} is not a positive number")
    return number


def positive_amount(text):
    """An amount of money above zero (a finite number: nan and inf are no cap)."""
    try:
        number = float(text)
    except ValueError:
        number = math.nan
    if not (math.isfinite(number) and number > 0):
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive amount")
    return number


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["ollama", "harness"], default="ollama")
    ap.add_argument("--models", nargs="+", required=True,
                    help="backend ollama: model names; backend harness: labels from --models-file")
    ap.add_argument("--seeds", nargs="+", type=int, default=[1])
    ap.add_argument("--cases", help="comma-separated case ids, e.g. R01,R04")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--prompt", help=f"the system prompt file (default {PROMPT.name})")
    ap.add_argument("--out")
    # options of one backend have no default here, so that giving them to the other backend can be refused
    ap.add_argument("--num-ctx", type=int, help="backend ollama (default 16384)")
    ap.add_argument("--think", choices=["false", "true"], help="backend ollama (default false)")
    ap.add_argument("--host", help="backend ollama (default $OLLAMA_HOST_URL or http://127.0.0.1:11434)")
    ap.add_argument("--models-file", help=f"backend harness: the labels (default {MODELS.name})")
    ap.add_argument("--variant", choices=["nodocs", "docs"], help="backend harness: required, as one invocation is one variant")
    ap.add_argument("--harness", help='backend harness: the harness command, e.g. "node /path/to/dist/cli.js"')
    ap.add_argument("--docset", help="backend harness, variant docs: the docset the doc tools serve (default the frozen "
                                     "docset next to this file)")
    ap.add_argument("--max-output-tokens", type=positive_int, help=f"backend harness (default {MAX_OUTPUT_TOKENS})")
    ap.add_argument("--max-wall-seconds", type=positive_int, help=f"backend harness (default {MAX_WALL_SECONDS})")
    ap.add_argument("--max-cost-usd", type=positive_amount,
                    help="backend harness: no attempt starts once the cost_usd of the turns written so far, a missing amount "
                         "counted as 0, has reached this amount (default: no cap)")
    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()
    refused = OLLAMA_ONLY if args.backend == "harness" else HARNESS_ONLY
    given = [f"--{name.replace('_', '-')}" for name in refused if getattr(args, name) is not None]
    if given:
        ap.error(f"{', '.join(given)} do{'es' if len(given) == 1 else ''} not apply to the backend {args.backend}")
    missing = [f"--{name}" for name in ("harness", "variant") if args.backend == "harness" and not getattr(args, name)]
    if missing:
        ap.error(f"the backend harness needs {' and '.join(missing)}")
    try:
        status = (run_harness if args.backend == "harness" else run_ollama)(args)
    except RunError as e:
        sys.exit(f"run.py: {e}")
    sys.exit(status)


if __name__ == "__main__":
    main()
