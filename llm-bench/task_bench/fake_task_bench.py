#!/usr/bin/env python3
"""A stand-in for the agent-harness CLI (dist/cli.js), for the tests of run.py only (M7, Task 7).

It has the two commands run.py calls, with the argument checks, the file layout, the file shapes and the exit codes of the real
ones (agent-harness src/cli.ts, probe.ts, bench/task-bench.ts); it is no harness and proves nothing about one.

  fake_task_bench.py probe --base-url U --model M [--out DIR] [--api-key-env VAR] [--extra-body-file F] [--step-timeout S]
      writes DIR/probe-<M in lower case, runs of [^a-z0-9.-] as '-'>/probe.json; exit 0 only for tool_calling "reliable"
  fake_task_bench.py task-bench --case F --model-config F --task-config F --label L --out DIR [--api-key-env VAR]
                                [--retry-transient]
      one case as a JSON file; the model config is read strictly (baseUrl, name, extraBody, reasoningEffort; an apiKey or any
      other key is refused); writes DIR/<case>-<label>-<8 hex>/bench-result.json; exit 0 as soon as that file is written,
      whatever its status

What it answers comes from the JSON file named by the environment variable FAKE_TASK_BENCH_CONFIG (none: all defaults), and
every invocation appends {"command", "argv", "ledger_lines", ...} to the file named by FAKE_TASK_BENCH_LOG, ledger_lines being
the number of lines the file named by FAKE_TASK_BENCH_LEDGER holds at that moment. It never prints the value of an environment
variable: of the one --api-key-env names it only asks whether it is set (and logs that as key_env_set).

The config is {"probe": {...}, "probe_by_model": {model: {...}}, "default": {...}, "cases": {"<case>" or "<label>/<case>": ...}}.
  probe (all optional)
    verdict         reliable (default), unreliable or none
    costs           [a_plain, b_single_tool, c_two_tools turn 1, c_two_tools turn 2, d_nonexistent_tool]: the usage.costUsd of
                    each response, null for one that names none; the default is null for all (a probe without any amount).
                    With the verdict none the second turn of c_two_tools does not happen, as in the real probe.
    crash           a message: stop with exit 1 and no probe.json
    sigint_parent   send SIGINT to the parent (the driver) during the probe and end normally
    stderr          text the probe writes to stderr
  a case answer is one attempt, or a list of them: the n-th call for a (label, case) uses the n-th attempt, and the last
  one goes on repeating. "default" is merged under every attempt. An attempt (all optional):
    status          one of the six statuses (default geslaagd)
    cost            usage.costUsd; null: the field is absent, as for a local model (default null)
    benchError      the benchError of a benchfout (default: none, as for a MODEL_ERROR)
    no_result       write no bench-result.json and exit 1 (make_dir: leave the empty run directory behind)
    result_text     the text of bench-result.json, exactly as given (a test leaves it broken)
    result_case     the caseId in the result, for a result of another case; result_label likewise
    extra_runs      n more run directories with a result, next to the one that counts
    exit            the exit status (default 0, or 1 for no_result)
    stderr          text the run writes to stderr
    fifo            put a named pipe in <run>/ws/, where the real bench leaves the work tree: opening it would hang
    sigint_parent   send SIGINT to the parent after the result is written, and end normally
    wait_for_signal install SIGINT and SIGTERM handlers, write the file marker, and wait for a signal; then wait abort_delay
                    seconds (default 2: the bench cleans up its containers), and write a benchfout with benchError
                    "afgebroken", usage.costUsd abort_cost (default: cost); wait_timeout (default 30) ends a wait that
                    nobody answers, with exit 3
    marker          the file written once the handlers are installed
    providers, retries, duration_ms   those of the result
"""
import argparse
import json
import os
import re
import secrets
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CASE_ID = re.compile(r"[A-Z]{2}-\d{2}")                               # BenchCaseSchema, src/bench/case.ts
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")                # BENCH_LABEL, src/cli.ts
MODEL_KEYS = ("baseUrl", "name", "extraBody", "reasoningEffort", "apiKey")
STATUSES = ("geslaagd", "verborgen_tests_rood", "verify_rood", "limiet", "geen_wijzigingen", "benchfout")
PROBE_STEPS = ("a_plain", "b_single_tool", "c_two_tools", "d_nonexistent_tool")


class Parser(argparse.ArgumentParser):
    def error(self, message):      # the real CLI exits with 1 on a usage error
        die(f"{message}\n{self.format_usage()}")


def die(message, code=1):
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.exit(code)


def dump(path, value):
    """JSON.stringify(value, null, 2) + a newline, as the harness writes probe.json and bench-result.json."""
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_config():
    path = os.environ.get("FAKE_TASK_BENCH_CONFIG")
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else {}


def previous_calls(command, **match):
    """How many earlier invocations of command the log holds with these values (label, case)."""
    path = os.environ.get("FAKE_TASK_BENCH_LOG")
    if not path or not Path(path).exists():
        return 0
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return sum(row["command"] == command and all(row.get(k) == v for k, v in match.items()) for row in rows)


def ledger_lines():
    """How many lines the ledger (FAKE_TASK_BENCH_LEDGER) holds right now: a test sees what run.py had booked before this call."""
    path = os.environ.get("FAKE_TASK_BENCH_LEDGER")
    if not path or not Path(path).exists():
        return 0
    return sum(1 for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip())


def log_invocation(row):
    path = os.environ.get("FAKE_TASK_BENCH_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({**row, "ledger_lines": ledger_lines()}, ensure_ascii=False) + "\n")


def check_api_key_env(name):
    """The real harness stops when the variable --api-key-env names is not set. Only that is asked: the value is not read out."""
    if name and not os.environ.get(name):
        die(f"--api-key-env: environment variable {name} is not set")


def read_json_object(path, what):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        die(f"cannot read {what} {path}: {err}")
    if not isinstance(value, dict):
        die(f"invalid {what} {path}: moet een JSON-object zijn")
    return value


# ---------------------------------------------------------------------------------------------------------------------
# bench-result.json: the shape of BenchResult (agent-harness src/bench/task-bench.ts) as the real run wrote it
# ---------------------------------------------------------------------------------------------------------------------

def hidden_block(passed):
    reason = ("geslaagd: 11 tests in 1 verborgen testbestand(en)" if passed
              else "verborgen tests rood: 2 van 11 tests falen in __tests__/redact.test.ts")
    return {"pass": passed, "reason": reason,
            "files": [{"file": "__tests__/redact.test.ts", "ran": True, "passed": 11 if passed else 9,
                       "failed": 0 if passed else 2, "other": 0}]}


def bench_result(case_id, label, run_id, status, cost=None, *, bench_error=None, duration_ms=1500, providers=None,
                 retries=None, model=("qwen/qwen3.8-27b", "https://openrouter.ai/api/v1")):
    """A BenchResult for status, with the optional fields where the real bench has them: `hidden` only after a green gate on a
    non-empty patch, `error` for a run that failed, `benchError` for a bench that did, and costUsd only when there is one."""
    shape = {
        "geslaagd": {"runStatus": "completed", "reds": 0, "hidden": True, "patch": 11630},
        "verborgen_tests_rood": {"runStatus": "completed", "reds": 0, "hidden": False, "patch": 11630},
        "verify_rood": {"runStatus": "failed", "reds": 3, "error": {"code": "VERIFY_FAILED", "message": "verify bleef rood"},
                        "patch": 4021},
        "limiet": {"runStatus": "timed_out", "reds": 1, "patch": 0},
        "geen_wijzigingen": {"runStatus": "completed", "reds": 0, "patch": 0},
        "benchfout": {"runStatus": "not_run", "reds": 0, "patch": 0},
    }[status]
    usage = {"source": "provider_reported", "inputTokens": 1000, "outputTokens": 200, "turns": 3, "toolCalls": 4,
             "toolErrors": 0, "cachedTokens": 0}
    if cost is not None:
        usage["costUsd"] = cost
    usage["reasoningTokens"] = 100
    result = {"caseId": case_id, "label": label, "runId": run_id, "model": {"name": model[0], "baseUrl": model[1]},
              "status": status, "runStatus": shape["runStatus"]}
    if "error" in shape:
        result["error"] = shape["error"]
    result["gate"] = {"reds": shape["reds"]}
    if "hidden" in shape:
        result["hidden"] = hidden_block(shape["hidden"])
    result["usage"] = usage
    result["providers"] = list(providers if providers is not None else ["DeepInfra"] * 3)
    result["retries"] = list(retries or [])
    result["patchBytes"] = shape["patch"]
    result["durationMs"] = duration_ms
    if bench_error:
        result["benchError"] = bench_error
    return result


# ---------------------------------------------------------------------------------------------------------------------
# harness task-bench
# ---------------------------------------------------------------------------------------------------------------------

def wait_for_stop(attempt):
    """Install the handlers, say so (the marker), and wait for SIGINT or SIGTERM; then take abort_delay seconds to 'clean up'."""
    stopped = []

    def on_signal(signum, frame):
        stopped.append(signum)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    if attempt.get("marker"):
        Path(attempt["marker"]).write_text("running\n", encoding="utf-8")
    deadline = time.monotonic() + attempt.get("wait_timeout", 30)
    while not stopped and time.monotonic() < deadline:
        time.sleep(0.02)
    if not stopped:
        die("fake_task_bench: no stop signal came", 3)
    time.sleep(attempt.get("abort_delay", 2.0))


def task_bench(args):
    case = read_json_object(args.case, "case")
    if not (isinstance(case.get("id"), str) and CASE_ID.fullmatch(case["id"])):
        die(f"invalid case {args.case}: id: moet {CASE_ID.pattern} zijn")
    model = read_json_object(args.model_config, "model config")
    unknown = [key for key in model if key not in MODEL_KEYS]
    if unknown:
        die(f"invalid model config {args.model_config}: onbekende sleutel {', '.join(unknown)}")
    if "apiKey" in model:
        die(f"invalid model config {args.model_config}: apiKey: een sleutel hoort niet in een bestand; geef hem via --api-key-env")
    if not all(isinstance(model.get(key), str) and model[key] for key in ("baseUrl", "name")):
        die(f"invalid model config {args.model_config}: baseUrl en name zijn verplicht")
    read_json_object(args.task_config, "task config")
    if not LABEL.fullmatch(args.label):
        die(f"--label must be one plain path segment: {json.dumps(args.label)}")
    check_api_key_env(args.api_key_env)

    config = load_config()
    case_id, label = case["id"], args.label
    n = previous_calls("task-bench", label=label, case=case_id)
    log_invocation({"command": "task-bench", "argv": sys.argv[1:], "label": label, "case": case_id,
                    "key_env_set": bool(args.api_key_env and os.environ.get(args.api_key_env)),
                    "retry_transient": args.retry_transient, "model_config": model})
    answers = config.get("cases", {})
    answer = answers.get(f"{label}/{case_id}", answers.get(case_id, {}))
    answer = answer if isinstance(answer, list) else [answer]
    attempt = {**config.get("default", {}), **(answer[min(n, len(answer) - 1)] if answer else {})}

    out = Path(args.out)
    run_id = f"{case_id}-{label}-{secrets.token_hex(4)}"
    run_dir = out / run_id
    if attempt.get("stderr"):
        sys.stderr.write(attempt["stderr"] + "\n")
    if attempt.get("no_result"):
        if attempt.get("make_dir"):
            run_dir.mkdir(parents=True)
        sys.exit(attempt.get("exit", 1))

    status = attempt.get("status", "geslaagd")
    cost, bench_error = attempt.get("cost"), attempt.get("benchError")
    if attempt.get("wait_for_signal"):
        wait_for_stop(attempt)
        status, bench_error, cost = "benchfout", "afgebroken", attempt.get("abort_cost", cost)
    elif status not in STATUSES:
        die(f"fake_task_bench: unknown status {status}", 3)

    for extra in range(attempt.get("extra_runs", 0)):
        other = f"{case_id}-{label}-{secrets.token_hex(4)}"
        (out / other).mkdir(parents=True)
        dump(out / other / "bench-result.json", bench_result(case_id, label, other, status, cost, bench_error=bench_error))
    run_dir.mkdir(parents=True)
    if attempt.get("fifo"):
        (run_dir / "ws").mkdir()
        os.mkfifo(run_dir / "ws" / "fifo")
    result = bench_result(attempt.get("result_case", case_id), attempt.get("result_label", label), run_id, status, cost,
                          bench_error=bench_error, duration_ms=attempt.get("duration_ms", 1500),
                          providers=attempt.get("providers"), retries=attempt.get("retries"),
                          model=(model["name"], model["baseUrl"]))
    path = run_dir / "bench-result.json"
    if "result_text" in attempt:
        path.write_text(attempt["result_text"], encoding="utf-8")
    else:
        dump(path, result)
    if attempt.get("sigint_parent"):
        os.kill(os.getppid(), signal.SIGINT)
    sys.stdout.write(f"{status} — {run_id} → {path}\n")
    sys.exit(attempt.get("exit", 0))


# ---------------------------------------------------------------------------------------------------------------------
# harness probe
# ---------------------------------------------------------------------------------------------------------------------

def probe_dir(runs_dir, model):
    return Path(runs_dir) / ("probe-" + re.sub(r"[^a-z0-9.-]+", "-", model.lower()))


def raw_response(model, cost, tool_calls):
    """The ProbeStepResult.raw of a step: a CompleteResult as probe.ts stores it; costUsd only when there is an amount."""
    usage = {"source": "provider_reported", "inputTokens": 292, "outputTokens": 47, "cachedTokens": 0}
    if cost is not None:
        usage["costUsd"] = cost
    usage["reasoningTokens"] = 20
    return {"message": {"content": None if tool_calls else "pong", "toolCalls": tool_calls}, "finishReason": "stop",
            "usage": usage, "model": model, "reasoning": "kort nagedacht", "durationMs": 900, "provider": "DeepInfra"}


def probe_json(base_url, model, setting):
    """A probe.json of the real shape (src/probe.ts ProbeResult), with the verdict and the amounts of setting."""
    verdict = setting.get("verdict", "reliable")
    costs = list(setting.get("costs") or [None] * 5)
    echo = [{"id": "call_1", "name": "echo", "arguments": '{"text":"ping"}'}]
    echo2 = [{"id": "call_2", "name": "echo", "arguments": '{"text":"pong"}'}]
    steps = {"a_plain": {"pass": True, "reason": "content: pong", "raw": raw_response(model, costs[0], [])}}
    if verdict == "none":
        steps["b_single_tool"] = {"pass": False, "reason": "expected exactly one tool call, got 0",
                                  "raw": raw_response(model, costs[1], [])}
        steps["c_two_tools"] = {"pass": False, "reason": "turn 1: expected exactly one tool call, got 0",
                                "raw": {"turn1": raw_response(model, costs[2], [])}}
    else:
        steps["b_single_tool"] = {"pass": True, "reason": 'echo("ping")', "raw": raw_response(model, costs[1], echo)}
        steps["c_two_tools"] = {"pass": True, "reason": 'turn 1 echo("ping"); turn 2 echo("pong")',
                                "raw": {"turn1": raw_response(model, costs[2], echo), "turn2": raw_response(model, costs[3], echo2)}}
    if verdict == "unreliable":
        steps["d_nonexistent_tool"] = {"pass": False, "reason": "called: delete_everything",
                                       "raw": raw_response(model, costs[4], [{"id": "call_3", "name": "delete_everything",
                                                                               "arguments": "{}"}])}
    else:
        steps["d_nonexistent_tool"] = {"pass": True, "reason": "no foreign tool call (0 echo calls)",
                                       "raw": raw_response(model, costs[4], [])}
    return {"baseUrl": base_url, "model": model, "reportedModel": model,
            "ranAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "steps": steps, "tool_calling": verdict, "usage_reported": True}


def probe(args):
    config = load_config()
    setting = {**config.get("probe", {}), **config.get("probe_by_model", {}).get(args.model, {})}
    extra_body = None
    if args.extra_body_file is not None:
        extra_body = read_json_object(args.extra_body_file, "--extra-body-file")
    check_api_key_env(args.api_key_env)
    log_invocation({"command": "probe", "argv": sys.argv[1:], "model": args.model, "extra_body": extra_body,
                    "key_env_set": bool(args.api_key_env and os.environ.get(args.api_key_env))})
    if setting.get("stderr"):
        sys.stderr.write(setting["stderr"] + "\n")
    if setting.get("crash"):
        die(setting["crash"])
    if setting.get("sigint_parent"):
        os.kill(os.getppid(), signal.SIGINT)
    result = probe_json(args.base_url, args.model, setting)
    out = probe_dir(args.out or "runs", args.model)
    out.mkdir(parents=True, exist_ok=True)
    file = out / "probe.json"
    dump(file, result)
    for name, step in result["steps"].items():
        sys.stdout.write(f"{'PASS' if step['pass'] else 'FAIL'} {name}: {step['reason']}\n")
    sys.stdout.write(f"tool_calling: {result['tool_calling']} (usage_reported: {str(result['usage_reported']).lower()}) → {file}\n")
    sys.exit(0 if result["tool_calling"] == "reliable" else 1)


def main():
    ap = Parser(prog="fake_task_bench")
    sub = ap.add_subparsers(dest="command", required=True, parser_class=Parser)
    p = sub.add_parser("probe")
    p.add_argument("--base-url", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--out")
    p.add_argument("--api-key-env")
    p.add_argument("--step-timeout")
    p.add_argument("--extra-body-file")
    t = sub.add_parser("task-bench")
    for flag in ("case", "model-config", "task-config", "label", "out"):
        t.add_argument(f"--{flag}", required=True)
    t.add_argument("--api-key-env")
    t.add_argument("--retry-transient", action="store_true")
    args = ap.parse_args()
    (probe if args.command == "probe" else task_bench)(args)


if __name__ == "__main__":
    main()
