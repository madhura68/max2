#!/usr/bin/env python3
"""A stand-in for the agent-harness CLI (dist/cli.js), for the tests of run.py only (M5, Task 11a).

It has the two commands run.py calls, with the layout, the file shapes and the exit codes of the real ones
(agent-harness src/cli.ts, probe.ts, trace.ts, run.ts, manifest.ts); it is no harness and proves nothing about one.

  fake_harness.py probe --base-url U --model M [--out DIR] [--api-key-env VAR] [--extra-body-file F] [--step-timeout S]
      writes DIR/probe-<M in lower case, runs of [^a-z0-9.-] as '-'>/probe.json; exit 0 only for tool_calling "reliable"
  fake_harness.py run MANIFEST [--out DIR] [--skip-probe] [--api-key-env VAR]
      refuses an invalid manifest, checks the probe gate for the profile "tools" (DIR/probe-<name>/probe.json for the same
      baseUrl and model, tool_calling "reliable"), refuses an existing DIR/<id>, and writes DIR/<id>/result.json,
      trace.jsonl and tools/<callId>.txt; exit 0 only for the status "completed"

What it answers comes from the JSON file named by the environment variable FAKE_HARNESS_CONFIG (none: all defaults), and
every invocation appends {"argv": [...]} to the file named by FAKE_HARNESS_LOG. It never prints the value of an environment
variable: of the one --api-key-env names it only asks whether it is set.

The config is {"run": [RULE, ...], "probe": [RULE, ...]}. A RULE is {"when": {...}, "response": {...}}. The response is the
shallow merge of the response of every rule whose "when" holds, in file order; a rule without "when" holds always.
  when, run:   model (manifest model.name), turn (1 + the number of earlier exchanges in history), poging (the -p<n> of the
               id), seed (model.extraBody.seed), profile, prompt_contains (a substring of the prompt)
  when, probe: model (--model)
  response, run (all optional):
    status         completed (default), failed, budget_exceeded or timed_out
    answer         the text of a completed run (default "Fake answer.")
    error          {"code": ..., "message": ...}
    calls          tool calls before the answer: {"name", "arguments" (an object, or a string that stays as it is),
                   "ok" (default true), "error_code", "call_id"}. Each gets a model response, a tool_call and a tool_result.
    respond        whether the run ends with a model response (default: the status is completed)
    finish_reason  of that last response (default "stop")
    providers      the provider of each model response in order; the last one repeats; none: the events name no provider
    usage          overrides of result.usage: source, inputTokens, outputTokens, turns, toolCalls, toolErrors,
                   cachedTokens, costUsd, reasoningTokens. The last model response in the trace holds the tokens, cost
                   included; run.py reads the totals from result.json.
    duration_ms    result.durationMs (default 1500)
    reasoning      the reasoning text of the last model response
    no_result      stop with exit 1 before result.json is written
  response, probe (all optional):
    fail           {step: reason} for the steps that do not pass
    crash          a message: stop with exit 1 and no probe.json
    usage_reported the probe's usage_reported (default true)
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PROBE_STEPS = ("a_plain", "b_single_tool", "c_two_tools", "d_nonexistent_tool")
PASS_REASONS = {"a_plain": "content: pong", "b_single_tool": 'echo("ping")',
                "c_two_tools": 'turn 1 echo("ping"); turn 2 echo("pong")',
                "d_nonexistent_tool": "no foreign tool call (0 echo calls)"}
RESERVED_BODY_KEYS = ("model", "messages", "tools", "stream", "max_tokens", "max_completion_tokens", "n")
REASONING_EFFORTS = ("none", "low", "medium", "high")
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
USAGE_ORDER = ("source", "inputTokens", "outputTokens", "turns", "toolCalls", "toolErrors",
               "cachedTokens", "costUsd", "reasoningTokens")
TRACE_USAGE = ("source", "inputTokens", "outputTokens", "cachedTokens", "costUsd", "reasoningTokens")


class Parser(argparse.ArgumentParser):
    def error(self, message):      # the real CLI exits with 1 on a usage error
        die(f"{message}\n{self.format_usage()}")


def die(message, code=1):
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.exit(code)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def dump(path, value):
    """JSON.stringify(value, null, 2) + a newline, as the harness writes result.json and probe.json."""
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_config():
    path = os.environ.get("FAKE_HARNESS_CONFIG")
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else {}


def log_invocation(argv):
    path = os.environ.get("FAKE_HARNESS_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"argv": argv}, ensure_ascii=False) + "\n")


def respond(rules, facts):
    """The shallow merge of the response of every rule whose "when" holds for facts, in file order."""
    merged = {}
    for rule in rules:
        holds = True
        for key, wanted in (rule.get("when") or {}).items():
            if key == "prompt_contains":
                holds = holds and wanted in facts["prompt"]
            elif key in facts:
                holds = holds and facts[key] == wanted
            else:
                die(f"fake_harness: unknown key in when: {key}", 3)      # a typo in a test config must be loud
        if holds:
            merged.update(rule.get("response") or {})
    return merged


def probe_dir(runs_dir, model):
    return Path(runs_dir) / ("probe-" + re.sub(r"[^a-z0-9.-]+", "-", model.lower()))


def extra_body_problem(extra_body, reasoning_effort=None):
    """assertExtraBody of src/manifest.ts: the complaint about extra_body, or None."""
    found = [key for key in extra_body if key in RESERVED_BODY_KEYS]
    if found:
        names = ", ".join(f'"{k}"' for k in found)
        return f"extraBody mag geen gereserveerde sleutels bevatten: {names} (gereserveerd: {', '.join(RESERVED_BODY_KEYS)})"
    if reasoning_effort is not None and "reasoning_effort" in extra_body:
        return "extraBody mag reasoning_effort niet bevatten naast reasoningEffort: zet het ene of het andere"
    return None


def check_api_key_env(name):
    """The real harness stops when the variable --api-key-env names is not set. Only that is asked: the value is not
    read out."""
    if name and not os.environ.get(name):
        die(f"--api-key-env: environment variable {name} is not set")


def read_extra_body_file(path):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        die(f"cannot read --extra-body-file {path}: {err}")
    if not isinstance(raw, dict):
        die(f"invalid --extra-body-file {path}: moet een JSON-object zijn")
    problem = extra_body_problem(raw)
    if problem:
        die(f"invalid --extra-body-file {path}: {problem}")
    return raw


def is_int(value, minimum):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def manifest_issues(m):
    """The complaints about a manifest, as the ManifestSchema of src/manifest.ts would make them (empty: it is valid)."""
    if not isinstance(m, dict):
        return ["<root>: expected an object"]
    issues = []

    def bad(path, message):
        issues.append(f"{path}: {message}")

    if not (isinstance(m.get("id"), str) and ID_PATTERN.fullmatch(m["id"])):
        bad("id", "must match ^[a-z0-9][a-z0-9-]{0,79}$")
    if m.get("profile") not in ("answer", "tools"):
        bad("profile", "must be answer or tools")
    if not (isinstance(m.get("prompt"), str) and m["prompt"]):
        bad("prompt", "must be a non-empty string")
    if "system" in m and not isinstance(m["system"], str):
        bad("system", "must be a string")
    history = m.get("history", [])
    if not (isinstance(history, list) and all(isinstance(h, dict) and h.get("role") in ("user", "assistant")
                                              and isinstance(h.get("content"), str) for h in history)):
        bad("history", "must be a list of {role: user|assistant, content}")
    else:      # whole exchanges: user, assistant, user, assistant, ...
        off = next((i for i, h in enumerate(history) if h["role"] != ("user" if i % 2 == 0 else "assistant")), None)
        if off == 0:
            bad("history", "history moet met een user-bericht beginnen")
        elif off is not None:
            bad("history", f"history moet afwisselen tussen user en assistant (bericht {off + 1} is {history[off]['role']})")
        elif history and history[-1]["role"] == "user":
            bad("history", "history moet met een assistant-bericht eindigen")
    model = m.get("model")
    if not isinstance(model, dict):
        bad("model", "must be an object")
    else:
        url = urlparse(model["baseUrl"]) if isinstance(model.get("baseUrl"), str) else None
        if not (url and url.scheme in ("http", "https") and url.netloc):
            bad("model.baseUrl", "must be a URL")
        if not (isinstance(model.get("name"), str) and model["name"]):
            bad("model.name", "must be a non-empty string")
        if "apiKey" in model and not isinstance(model["apiKey"], str):
            bad("model.apiKey", "must be a string")
        if "reasoningEffort" in model and model["reasoningEffort"] not in REASONING_EFFORTS:
            bad("model.reasoningEffort", f"must be one of {', '.join(REASONING_EFFORTS)}")
        if "extraBody" in model:
            if not isinstance(model["extraBody"], dict):
                bad("model.extraBody", "must be an object")
            else:
                problem = extra_body_problem(model["extraBody"], model.get("reasoningEffort"))
                if problem:
                    bad("extraBody", problem)
    tools = m.get("tools")
    if tools is not None:
        server = tools.get("server") if isinstance(tools, dict) else None
        allow = tools.get("allow") if isinstance(tools, dict) else None
        if not (isinstance(server, dict) and isinstance(server.get("command"), str) and server["command"]
                and isinstance(server.get("args"), list) and all(isinstance(a, str) for a in server["args"])):
            bad("tools.server", "must have a command and a list of args")
        if not (isinstance(allow, list) and allow and all(isinstance(a, str) and a for a in allow)):
            bad("tools.allow", "must be a non-empty list of names")
    if m.get("profile") == "tools" and tools is None:
        bad("tools", "tools is verplicht bij profile \"tools\"")
    if m.get("profile") == "answer" and tools is not None:
        bad("tools", "tools is verboden bij profile \"answer\"")
    limits = m.get("limits")
    if not isinstance(limits, dict):
        bad("limits", "must be an object")
    else:
        for key, minimum in (("maxTurns", 1), ("maxOutputTokens", 1), ("maxWallSeconds", 1), ("maxToolErrors", 0)):
            if not is_int(limits.get(key), minimum):
                bad(f"limits.{key}", f"must be an integer of at least {minimum}")
        if "contextTokens" in limits and not is_int(limits["contextTokens"], 1):
            bad("limits.contextTokens", "must be a positive integer")
    return issues


def load_manifest(path):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        die(f"cannot read manifest {path}: {err}")
    issues = manifest_issues(raw)
    if issues:
        die(f"invalid manifest {path}: {'; '.join(issues)}")
    return raw


def probe_gate(model, out):
    """The complaint when the probe result for model is missing, for another model or not reliable; None when it holds."""
    file = probe_dir(out, model["name"]) / "probe.json"
    try:
        probe = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"no probe result at {file}"
    if probe.get("baseUrl") != model["baseUrl"] or probe.get("model") != model["name"]:
        return f"{file} was made for {probe.get('model')} at {probe.get('baseUrl')}"
    if probe.get("tool_calling") != "reliable":
        return f"{file} rates tool calling as {probe.get('tool_calling')}"
    return None


def cmd_probe(opts, config):
    if not opts.base_url or not opts.model:
        die("probe needs --base-url and --model")
    if opts.extra_body_file is not None:
        read_extra_body_file(opts.extra_body_file)
    check_api_key_env(opts.api_key_env)
    spec = respond(config.get("probe") or [], {"model": opts.model})
    if spec.get("crash"):
        die(str(spec["crash"]))
    fail = spec.get("fail") or {}
    steps = {name: {"pass": name not in fail, "reason": fail.get(name, PASS_REASONS[name]), "raw": {"fake": True}}
             for name in PROBE_STEPS}
    if not steps["b_single_tool"]["pass"]:
        verdict = "none"
    elif steps["c_two_tools"]["pass"] and steps["d_nonexistent_tool"]["pass"]:
        verdict = "reliable"
    else:
        verdict = "unreliable"
    result = {"baseUrl": opts.base_url, "model": opts.model, "reportedModel": opts.model, "ranAt": now(), "steps": steps,
              "tool_calling": verdict, "usage_reported": spec.get("usage_reported", True)}
    directory = probe_dir(opts.out or "runs", opts.model)
    directory.mkdir(parents=True, exist_ok=True)
    dump(directory / "probe.json", result)
    for name, step in steps.items():
        print(f"{'PASS' if step['pass'] else 'FAIL'} {name}: {step['reason']}")
    reported = str(result["usage_reported"]).lower()
    print(f"tool_calling: {verdict} (usage_reported: {reported}) → {directory / 'probe.json'}")
    return 0 if verdict == "reliable" else 1


def redact(manifest):
    """redactManifest of src/trace.ts: no model.apiKey, and every tools.server.env value as <redacted>."""
    copy = json.loads(json.dumps(manifest))
    copy["model"].pop("apiKey", None)
    env = ((copy.get("tools") or {}).get("server") or {}).get("env")
    for key in env or {}:
        env[key] = "<redacted>"
    return copy


def poging_of(run_id):
    found = re.search(r"-p(\d+)-t\d+$", run_id)
    return int(found.group(1)) if found else None


def cmd_run(opts, config):
    if not opts.positionals:
        die("run needs a manifest path")
    if opts.extra_body_file is not None:
        die("--extra-body-file only applies to harness probe; for harness run put extraBody in the model block of the "
            "manifest (model.extraBody)")
    out = Path(opts.out or "runs")
    manifest = load_manifest(opts.positionals[0])
    check_api_key_env(opts.api_key_env)
    if manifest["profile"] == "tools" and not opts.skip_probe:
        complaint = probe_gate(manifest["model"], out)
        if complaint:
            die(f"PROBE_REQUIRED: {complaint}. Draai eerst harness probe (of gebruik --skip-probe).")
    run_dir = out / manifest["id"]
    if run_dir.exists():
        die(f"run dir already exists: {run_dir}")
    out.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir()
    facts = {"model": manifest["model"]["name"], "turn": len(manifest.get("history") or []) // 2 + 1,
             "poging": poging_of(manifest["id"]), "seed": (manifest["model"].get("extraBody") or {}).get("seed"),
             "profile": manifest["profile"], "prompt": manifest["prompt"]}
    spec = respond(config.get("run") or [], facts)

    status = spec.get("status", "completed")
    calls = spec.get("calls") or []
    final_response = spec.get("respond", status == "completed")
    providers = spec.get("providers") or []
    answer = spec.get("answer", "Fake answer.")
    tools_profile = manifest["profile"] == "tools"
    totals = {"source": "provider_reported", "inputTokens": 100, "outputTokens": 20, "turns": len(calls) + 1,
              "toolCalls": len(calls), "toolErrors": sum(c.get("ok", True) is False for c in calls)}
    totals.update(spec.get("usage") or {})
    unknown = set(totals) - set(USAGE_ORDER)
    if unknown:
        die(f"fake_harness: unknown usage keys: {sorted(unknown)}", 3)
    usage = {k: totals[k] for k in USAGE_ORDER if k in totals}

    events = []

    def event(kind, **fields):
        events.append({"ts": now(), "type": kind, **fields})

    def provider(turn):
        return {"provider": providers[min(turn - 1, len(providers) - 1)]} if providers else {}

    event("run_start", manifest=redact(manifest), **({"probeSkipped": True} if tools_profile and opts.skip_probe else {}))
    allow = sorted((manifest.get("tools") or {}).get("allow") or [])
    if tools_profile:
        snapshot_hash = hashlib.sha256(json.dumps(allow).encode()).hexdigest()
        event("tool_snapshot", names=allow, hash=snapshot_hash)
    max_tokens = manifest["limits"]["maxOutputTokens"]
    for turn, call in enumerate(calls, start=1):
        call_id = call.get("call_id") or f"call_{turn}_0"
        arguments = call.get("arguments", {})
        text = arguments if isinstance(arguments, str) else json.dumps(arguments)
        tool_call = {"id": call_id, "name": call["name"], "arguments": text, "argumentsWasObject": False}
        event("model_request", turn=turn, messages=2 * turn, tools=len(allow), maxTokens=max_tokens)
        event("model_response", turn=turn, content=None, toolCalls=[tool_call], finishReason="tool_calls",
              usage={"source": usage["source"], "inputTokens": 0, "outputTokens": 0}, durationMs=100, **provider(turn))
        event("tool_call", callId=call_id, name=call["name"], arguments=text, argumentsWasObject=False)
        content = f"fake result of {call['name']}"
        tools_dir = run_dir / "tools"
        tools_dir.mkdir(exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", call_id)[:120] or "_"
        (tools_dir / f"{safe_name}.txt").write_text(content, encoding="utf-8")
        ok = call.get("ok", True)
        event("tool_result", callId=call_id, ok=ok, **({"errorCode": call["error_code"]} if call.get("error_code") else {}),
              truncated=False, sha256=hashlib.sha256(content.encode()).hexdigest(), bytes=len(content.encode()))
    last = len(calls) + 1
    event("model_request", turn=last, messages=2 * last, tools=len(allow), maxTokens=max_tokens)
    if final_response:
        event("model_response", turn=last, content=answer, toolCalls=[], finishReason=spec.get("finish_reason", "stop"),
              usage={k: usage[k] for k in TRACE_USAGE if k in usage}, durationMs=100,
              **({"reasoning": spec["reasoning"]} if spec.get("reasoning") else {}), **provider(last))
    error = spec.get("error")
    event("run_end", status=status, **({"error": error} if error else {}))
    with open(run_dir / "trace.jsonl", "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    if spec.get("no_result"):
        die("fake_harness: stopped before result.json was written")

    result = {"runId": manifest["id"], "status": status, **({"answer": answer} if status == "completed" else {}),
              **({"error": error} if error else {}),
              "model": {"name": manifest["model"]["name"], "baseUrl": manifest["model"]["baseUrl"],
                        "reported": manifest["model"]["name"]},
              "usage": usage, "durationMs": spec.get("duration_ms", 1500),
              **({"toolSnapshotHash": snapshot_hash} if tools_profile else {})}
    dump(run_dir / "result.json", result)
    failure = f" ({error['code']}: {error['message']})" if error else ""
    print(f"{status}{failure} — turns {usage['turns']}, tokens in/out {usage['inputTokens']}/{usage['outputTokens']} "
          f"({usage['source']}), tool calls {usage['toolCalls']}, tool errors {usage['toolErrors']}, "
          f"{result['durationMs']} ms → {run_dir / 'result.json'}")
    if status == "completed":
        print(f"\n{answer}")
    return 0 if status == "completed" else 1


def main(argv):
    log_invocation(argv)
    ap = Parser(prog="fake_harness.py", add_help=False, allow_abbrev=False)
    ap.add_argument("positionals", nargs="*")
    ap.add_argument("--base-url")
    ap.add_argument("--model")
    ap.add_argument("--out")
    ap.add_argument("--api-key-env")
    ap.add_argument("--step-timeout")
    ap.add_argument("--extra-body-file")
    ap.add_argument("--skip-probe", action="store_true")
    opts = ap.parse_intermixed_args(argv)
    if not opts.positionals:
        die("usage: fake_harness.py probe|run ...")
    command, opts.positionals = opts.positionals[0], opts.positionals[1:]
    config = load_config()
    if command == "probe":
        return cmd_probe(opts, config)
    if command == "run":
        return cmd_run(opts, config)
    die(f"{command}: not implemented")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
