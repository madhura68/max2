#!/usr/bin/env python3
"""Stand-ins for the tests of run.py only (M8, Task 10): a fake `harness review-bench`, and a fake LiteLLM (class FakeLiteLLM below).
Neither is a harness nor a gateway and neither proves anything about the real one.

The fake harness has the one command run.py calls, with the argument checks, the file layout, the file shapes and the exit codes of
the real one (agent-harness src/cli.ts cmdReviewBench, src/bench/review-bench.ts):

  fake_review_bench.py review-bench --case DIR --config harness.json --configuration NAME --probe-dir DIR --label L --out DIR
                                    --api-key-env VAR
      DIR/case.json is read for its id (an unusable case: `CASE_INVALID: ...` on stderr, exit 1 and no result); the variable
      VAR has to be set (only whether it is set is asked, never its value); writes OUT/<case>-<label>-<8 hex>/{bench-result.json,
      trace.jsonl,root/} and prints `<status> <run dir>`; exit 0 as soon as bench-result.json is written, whatever its status

What it answers comes from the JSON file named by the environment variable FAKE_REVIEW_BENCH_CONFIG (none: all defaults), and every
invocation appends {"command", "argv", "label", "run", "case", "out", "key_env_set", "key_env_len", "ledger_lines"} to the file
named by FAKE_REVIEW_BENCH_LOG, ledger_lines being the number of lines the file named by FAKE_REVIEW_BENCH_LEDGER holds at that
moment. It never logs or prints the value of an environment variable, only whether it is set and how long it is.

The config is {"default": {...}, "labels": {"<label>" or "<label>/r<n>": attempt or [attempts]}}. The run n is the `r<n>` that
--out ends in, as run.py has it. An answer is one attempt, or a list of them: the n-th call for a (label, --out) uses the n-th
attempt and the last one goes on repeating. "default" is merged under every attempt. An attempt (all optional):
    status          beoordeeld (default), resultaat_ongeldig, limiet or benchfout
    cost            usage.costUsd; null: the field is absent (default)
    benchError      the benchError of a benchfout (none: the benchfout comes from an error code, MODEL_ERROR)
    error           the `error` of the result ({code, message}), instead of the one the status brings
    over            fields that replace those of the result, at the top level
    no_result       write no bench-result.json and exit 1 (make_dir: leave the empty run directory behind)
    result_text     the text of bench-result.json, exactly as given (a test leaves it broken)
    result_case     the caseId in the result, for a result of another case; result_label likewise
    exit            the exit status (default 0, or 1 for no_result)
    stderr          text the run writes to stderr
    sigint_parent   send SIGINT to the parent (the driver) after the result is written, and end normally
    wait_for_signal install SIGINT and SIGTERM handlers, write the file marker, and wait for a signal; then wait abort_delay
                    seconds (default 2: the bench cleans up), and write a benchfout with benchError "afgebroken", usage.costUsd
                    abort_cost (default: cost); wait_timeout (default 30) ends a wait that nobody answers, with exit 3
    marker          the file written once the handlers are installed
    duration_ms     durationMs of the result
"""
import argparse
import json
import os
import re
import secrets
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")      # BENCH_LABEL (src/cli.ts) and a case id: one plain path segment
MODEL_STATUSES = ("beoordeeld", "limiet", "resultaat_ongeldig")
STATUSES = MODEL_STATUSES + ("benchfout",)
DEFAULT_COST = 0.0021       # usage.cost of the fake LiteLLM when nothing else is said for a model


class Parser(argparse.ArgumentParser):
    def error(self, message):      # the real CLI exits with 1 on a usage error
        die(f"{message}\n{self.format_usage()}")


def die(message, code=1):
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.exit(code)


def dump(path, value):
    """JSON.stringify(value, null, 2) + a newline, as the harness writes bench-result.json."""
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_config():
    path = os.environ.get("FAKE_REVIEW_BENCH_CONFIG")
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else {}


def previous_calls(label, out):
    """How many earlier invocations the log holds for this label and this --out."""
    path = os.environ.get("FAKE_REVIEW_BENCH_LOG")
    if not path or not Path(path).exists():
        return 0
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return sum(row.get("label") == label and row.get("out") == out for row in rows)


def ledger_lines():
    """How many lines the ledger (FAKE_REVIEW_BENCH_LEDGER) holds right now: a test sees what run.py had booked before this call."""
    path = os.environ.get("FAKE_REVIEW_BENCH_LEDGER")
    if not path or not Path(path).exists():
        return 0
    return sum(1 for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip())


def log_invocation(row):
    path = os.environ.get("FAKE_REVIEW_BENCH_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({**row, "ledger_lines": ledger_lines()}, ensure_ascii=False) + "\n")


def read_json_object(path, what):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        die(f"cannot read {what} {path}: {err}")
    if not isinstance(value, dict):
        die(f"invalid {what} {path}: moet een JSON-object zijn")
    return value


# ---------------------------------------------------------------------------------------------------------------------
# bench-result.json: the shape of ReviewBenchResult (agent-harness src/bench/review-bench.ts)
# ---------------------------------------------------------------------------------------------------------------------

def dispatch_result():
    """An accepted DispatchResult of a review that says NO-GO (src/bench/dispatch-result.ts)."""
    return {"version": 1, "outcome": "succeeded", "summary": "Synthetische review: een bevinding.",
            "report_markdown": "# Synthetisch rapport\n\nEen bevinding over een synthetische regel.\n", "checks": [],
            "review": {"verdict": "NO-GO",
                       "documents": {"version": 1, "items": [{"key": "doc", "title": "Synthetisch", "product_id": "product-1",
                                                              "sha256": "0" * 64, "source": "product_doc", "doc_id": "doc-1",
                                                              "revision_id": "rev-1"}]}}}


# what a status brings: the runStatus, the error of the run and the attempts of the validator; the order of the rules is the
# meaning of mapReviewStatus
SHAPES = {
    "beoordeeld": ("completed", None, 1),
    "resultaat_ongeldig": ("failed", {"code": "REVIEW_RESULT_INVALID", "message": "het resultaat bleef ongeldig"}, 2),
    "limiet": ("budget_exceeded", {"code": "COST_LIMIT_EXCEEDED", "message": "de kostengrens is bereikt"}, 1),
    "benchfout": ("failed", {"code": "MODEL_ERROR", "message": "fout van het model"}, 1),
}


def bench_result(case_id, label, run_id, status, cost=None, *, bench_error=None, duration_ms=1500, error=None, configuration=None,
                 context_tokens=131072):
    """A ReviewBenchResult for status, with the optional fields where the real bench has them: `error` for a run that failed (a bench
    that failed before the run, with a benchError, has none and a runStatus not_run), `result` only for a judged run, costUsd only
    when there is one, and benchError last."""
    run_status, shaped_error, attempts = SHAPES[status]
    if status == "benchfout" and bench_error:
        run_status, shaped_error = "not_run", None
    usage = {"source": "provider_reported", "inputTokens": 52000, "outputTokens": 3100, "turns": 12, "toolCalls": 11, "toolErrors": 0,
             "cachedTokens": 0}
    if cost is not None:
        usage["costUsd"] = cost
    usage["reasoningTokens"] = 900
    result = {"caseId": case_id, "label": label, "runId": run_id, "configuration": configuration or {"name": label, "costMode": "hosted"},
              "contextTokens": context_tokens, "status": status, "runStatus": run_status}
    if error or shaped_error:
        result["error"] = error or shaped_error
    result["result"] = dispatch_result() if status == "beoordeeld" else None
    result["validation"] = {"attempts": attempts, "errors": [] if attempts == 1 else ["Het resultaat past niet in het schema."]}
    result["usage"] = usage
    result["peakInputTokens"] = 61000
    result["turns"], result["toolCalls"], result["toolErrors"] = usage["turns"], usage["toolCalls"], usage["toolErrors"]
    result["providers"] = ["Fake"]
    result["retries"] = []
    result["durationMs"] = duration_ms
    if bench_error:
        result["benchError"] = bench_error
    return result


# ---------------------------------------------------------------------------------------------------------------------
# harness review-bench
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
        die("fake_review_bench: no stop signal came", 3)
    time.sleep(attempt.get("abort_delay", 2.0))


def review_bench(args):
    if not SEGMENT.fullmatch(args.label):
        die(f"--label must be one plain path segment (letters, digits, '.', '_' and '-'): {json.dumps(args.label)}")
    config = read_json_object(args.config, "config")
    if not isinstance(config.get("configurations"), dict):
        die(f"invalid config {args.config}: configurations: moet een object zijn")
    if not os.environ.get(args.api_key_env):
        die(f"--api-key-env: environment variable {args.api_key_env} is not set")
    try:
        case = json.loads((Path(args.case) / "case.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        die(f"CASE_INVALID: case.json: niet te lezen ({type(err).__name__})")
    if not (isinstance(case, dict) and isinstance(case.get("id"), str) and SEGMENT.fullmatch(case["id"])):
        die("CASE_INVALID: case.json: id ontbreekt of is geen gewoon padsegment")

    case_id, label, out = case["id"], args.label, Path(args.out)
    n = previous_calls(label, str(args.out))
    match = re.fullmatch(r"r(\d+)", out.name)
    run = int(match.group(1)) if match else None
    log_invocation({"command": "review-bench", "argv": sys.argv[1:], "label": label, "run": run, "case": case_id, "out": str(args.out),
                    "key_env_set": True, "key_env_len": len(os.environ[args.api_key_env])})
    fake = load_config()
    answers = fake.get("labels", {})
    answer = answers.get(f"{label}/r{run}", answers.get(label, {}))
    answer = answer if isinstance(answer, list) else [answer]
    attempt = {**fake.get("default", {}), **(answer[min(n, len(answer) - 1)] if answer else {})}

    if attempt.get("stderr"):
        sys.stderr.write(attempt["stderr"] + "\n")
    run_id = f"{case_id}-{label}-{secrets.token_hex(4)}"
    run_dir = out / run_id
    if attempt.get("no_result"):
        if attempt.get("make_dir"):
            run_dir.mkdir(parents=True)
        sys.exit(attempt.get("exit", 1))

    status = attempt.get("status", "beoordeeld")
    cost, bench_error = attempt.get("cost"), attempt.get("benchError")
    if attempt.get("wait_for_signal"):
        wait_for_stop(attempt)
        status, bench_error, cost = "benchfout", "afgebroken", attempt.get("abort_cost", cost)
    elif status not in STATUSES:
        die(f"fake_review_bench: unknown status {status}", 3)

    known = config["configurations"].get(args.configuration)
    configuration = {"name": args.configuration, "costMode": known.get("costMode") if isinstance(known, dict) else None}
    if isinstance(known, dict) and known.get("reasoningEffort") is not None:
        configuration["reasoningEffort"] = known["reasoningEffort"]
    result = bench_result(attempt.get("result_case", case_id), attempt.get("result_label", label), run_id, status, cost,
                          bench_error=bench_error, duration_ms=attempt.get("duration_ms", 1500), error=attempt.get("error"),
                          configuration=configuration, context_tokens=case.get("contextTokens", 131072))
    result.update(attempt.get("over", {}))
    run_dir.mkdir(parents=True)
    (run_dir / "trace.jsonl").write_text("", encoding="utf-8")
    (run_dir / "root").mkdir()
    path = run_dir / "bench-result.json"
    if "result_text" in attempt:
        path.write_text(attempt["result_text"], encoding="utf-8")
    else:
        dump(path, result)
    if attempt.get("sigint_parent"):
        os.kill(os.getppid(), signal.SIGINT)
    sys.stdout.write(f"{status} {run_dir}\n")
    sys.exit(attempt.get("exit", 0))


def main():
    ap = Parser(prog="fake_review_bench")
    sub = ap.add_subparsers(dest="command", required=True, parser_class=Parser)
    p = sub.add_parser("review-bench")
    for flag in ("case", "config", "configuration", "probe-dir", "label", "out", "api-key-env"):
        p.add_argument(f"--{flag}", required=True)
    review_bench(ap.parse_args())


# ---------------------------------------------------------------------------------------------------------------------
# a fake LiteLLM: what the preflight of run.py talks to
# ---------------------------------------------------------------------------------------------------------------------

class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):      # a client that went away is no news in a test
        pass


class FakeLiteLLM:
    """An HTTP server on 127.0.0.1 (a free port) in a thread of this process, for the preflight of run.py.

      server = FakeLiteLLM().start()        server.base_url is http://127.0.0.1:<port>/v1 (what litellm.baseUrl holds)
      server.answer(model, reply)           how to answer a request whose body names this model; reply is a pair
                                            (status, body) or a function of the request returning one, or a triple
                                            (status, body, {header: value}). body is a dict or list (sent as JSON) or a str
                                            or bytes (sent as it is). The default is ok(): 200 with usage.cost DEFAULT_COST.
      server.requests                       every request so far, as {"path", "authorization", "content_type", "body"}
      server.stop()
    """

    def __init__(self):
        self.requests = []
        self.answers = {}
        self.server = None
        self.thread = None

    @staticmethod
    def ok(cost=DEFAULT_COST):
        """The answer of a gateway that took the request: 200 and a completion whose usage names the cost (None: it names none)."""
        usage = {"prompt_tokens": 120, "completion_tokens": 3}
        if cost is not None:
            usage["cost"] = cost
        return 200, {"id": "chatcmpl-fake", "object": "chat.completion", "model": "fake",
                     "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "OK"}}], "usage": usage}

    def answer(self, model, reply):
        self.answers[model] = reply

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):      # no line per request on the screen of the test
                pass

            def do_POST(self):      # a GET is answered and recorded alike: where a redirect leads is a GET
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = None
                request = {"path": self.path, "authorization": self.headers.get("Authorization"),
                           "content_type": self.headers.get("Content-Type"), "body": body}
                owner.requests.append(request)
                reply = owner.answers.get(body.get("model") if isinstance(body, dict) else None)
                reply = owner.ok() if reply is None else reply(request) if callable(reply) else reply
                status, payload, *rest = reply
                data = payload if isinstance(payload, bytes) else payload.encode("utf-8") if isinstance(payload, str) \
                    else json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for name, value in (rest[0] if rest else {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST

        self.server = QuietServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(10)
            self.server = None


if __name__ == "__main__":
    main()
