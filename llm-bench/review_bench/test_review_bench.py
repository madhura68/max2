"""Tests for the review bench (M8): check_case.py on a synthetic case in a tmp dir, and once on the frozen case of this repo; the
driver run.py against fake_review_bench.py (a stand-in for `harness review-bench`) and a fake LiteLLM on 127.0.0.1. No model, no
real network, no real key: the key is a dummy.

  python3 -m unittest discover -s llm-bench/review_bench -v
"""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_case  # noqa: E402
import fake_review_bench  # noqa: E402

CHECK_CASE = HERE / "check_case.py"
REAL_CASE = HERE / "cases" / "macsearch-idea263-spec-r5"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_case(root, *, documents_sha=None, artifacts=None):
    """A sound synthetic case in root: a prompt, a payload, two sources and a case.json that pins them. documents_sha replaces the
    sha256 of `doc` in review_documents; artifacts replaces source_artifacts. Returns the case dir."""
    case_dir = Path(root) / "case"
    (case_dir / "sources").mkdir(parents=True)
    doc = b"# Synthetische spec\n\nEen regel om te reviewen.\n"
    dispatch_input = b'{"action":"review","version":1}'
    (case_dir / "review.md").write_bytes(b"# Prompt\n\nLees $PAYLOAD_PATH.\n")
    (case_dir / "sources" / "doc").write_bytes(doc)
    (case_dir / "sources" / "__dispatch_input").write_bytes(dispatch_input)
    payload = {
        "dispatch": {
            "input": {
                "action": "review",
                "review_documents": {
                    "version": 1,
                    "items": [{"key": "doc", "title": "Synthetisch", "sha256": documents_sha or sha(doc), "source": "product_doc"}],
                },
            },
            "source_artifacts": artifacts
            if artifacts is not None
            else [{"key": "__dispatch_input", "sha256": sha(dispatch_input)}, {"key": "doc", "sha256": sha(doc)}],
        }
    }
    payload_bytes = json.dumps(payload, indent=2).encode()
    (case_dir / "payload.json").write_bytes(payload_bytes)
    case = {
        "id": "synthetisch",
        "prompt": {"file": "review.md", "sha256": sha((case_dir / "review.md").read_bytes())},
        "payload": {"file": "payload.json", "sha256": sha(payload_bytes)},
        "sources": [
            {"key": "doc", "file": "sources/doc", "sha256": sha(doc)},
            {"key": "__dispatch_input", "file": "sources/__dispatch_input", "sha256": sha(dispatch_input)},
        ],
        "limits": {"maxTurns": 30, "maxOutputTokens": 64000, "maxWallSeconds": 1800, "maxToolErrors": 8},
        "contextTokens": 131072,
        "maxCostUsd": "1",
    }
    (case_dir / "case.json").write_text(json.dumps(case, indent=2))
    return case_dir


def flip_byte(path, at=0):
    data = bytearray(path.read_bytes())
    data[at] ^= 0x01
    path.write_bytes(bytes(data))


def run_cli(case_dir):
    return subprocess.run([sys.executable, str(CHECK_CASE), str(case_dir)], capture_output=True, text=True, timeout=30)


class CheckCaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="review-bench-case-")
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_a_sound_case_gives_exit_0(self):
        case_dir = make_case(self.tmp)
        self.assertEqual(check_case.check_case(case_dir), [])
        done = run_cli(case_dir)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("case in orde", done.stdout)
        self.assertEqual(done.stderr, "")

    def test_one_changed_byte_in_any_pinned_file_gives_exit_1(self):
        for name in ["review.md", "payload.json", "sources/doc", "sources/__dispatch_input"]:
            with self.subTest(file=name):
                case_dir = make_case(tempfile.mkdtemp(dir=self.tmp))
                flip_byte(case_dir / name, at=5)
                done = run_cli(case_dir)
                self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
                self.assertIn(f"{name}: sha256 wijkt af", done.stdout)
                self.assertNotIn("Traceback", done.stdout + done.stderr)

    def test_a_payload_that_is_no_longer_json_is_one_line_not_a_traceback(self):
        case_dir = make_case(self.tmp)
        flip_byte(case_dir / "payload.json", at=0)   # "{" becomes "z"
        done = run_cli(case_dir)
        self.assertEqual(done.returncode, 1)
        self.assertNotIn("Traceback", done.stdout + done.stderr)
        self.assertIn("payload.json: niet te lezen als JSON", done.stdout)

    def test_a_case_json_that_is_not_json_gives_exit_1(self):
        case_dir = make_case(self.tmp)
        (case_dir / "case.json").write_text("{ niet af")
        done = run_cli(case_dir)
        self.assertEqual(done.returncode, 1)
        lines = done.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("case.json: niet te lezen als JSON", lines[0])
        self.assertNotIn("Traceback", done.stderr)

    def test_a_missing_file_gives_exit_1(self):
        case_dir = make_case(self.tmp)
        (case_dir / "sources" / "doc").unlink()
        problems = check_case.check_case(case_dir)
        self.assertIn("sources/doc: ontbreekt of is geen gewoon bestand", problems)

    def test_a_path_outside_the_case_is_refused(self):
        case_dir = make_case(self.tmp)
        case = json.loads((case_dir / "case.json").read_text())
        case["prompt"]["file"] = "../review.md"
        (case_dir / "case.json").write_text(json.dumps(case))
        problems = check_case.check_case(case_dir)
        self.assertTrue(any("geen relatief pad binnen de case" in line for line in problems), problems)

    def test_source_artifacts_must_equal_sources_in_both_directions(self):
        doc_sha = sha(b"# Synthetische spec\n\nEen regel om te reviewen.\n")
        input_sha = sha(b'{"action":"review","version":1}')
        cases = {
            "an artifact missing from sources[]": (
                [{"key": "doc", "sha256": doc_sha}, {"key": "__dispatch_input", "sha256": input_sha}, {"key": "extra", "sha256": "0" * 64}],
                "source_artifacts: extra staat niet in sources[] van case.json",
            ),
            "a source missing from the artifacts": (
                [{"key": "doc", "sha256": doc_sha}],
                "sources[]: __dispatch_input staat niet in source_artifacts van de payload",
            ),
            "a differing hash": (
                [{"key": "doc", "sha256": "1" * 64}, {"key": "__dispatch_input", "sha256": input_sha}],
                f"source_artifacts: doc heeft sha256 {'1' * 64}, case.json pint {doc_sha}",
            ),
        }
        for title, (artifacts, line) in cases.items():
            with self.subTest(title):
                case_dir = make_case(tempfile.mkdtemp(dir=self.tmp), artifacts=artifacts)
                problems = check_case.check_case(case_dir)
                self.assertEqual(problems, [line])

    def test_review_documents_must_carry_the_hash_of_the_source_file(self):
        case_dir = make_case(self.tmp, documents_sha="2" * 64)
        problems = check_case.check_case(case_dir)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("review_documents: doc heeft sha256 " + "2" * 64, problems[0])

    def edit_case(self, case_dir, change):
        case = json.loads((case_dir / "case.json").read_text())
        change(case)
        (case_dir / "case.json").write_text(json.dumps(case))

    def edit_payload(self, case_dir, change):
        """Changes payload.json and pins the new bytes, so only the change itself is a deviation."""
        payload = json.loads((case_dir / "payload.json").read_text())
        change(payload)
        data = json.dumps(payload).encode()
        (case_dir / "payload.json").write_bytes(data)
        self.edit_case(case_dir, lambda case: case["payload"].update(sha256=sha(data)))

    def test_an_absolute_path_is_refused(self):
        case_dir = make_case(self.tmp)
        self.edit_case(case_dir, lambda case: case["prompt"].update(file=str(case_dir / "review.md")))
        problems = check_case.check_case(case_dir)
        self.assertTrue(any("geen relatief pad binnen de case" in line for line in problems), problems)

    def test_a_symlink_on_the_way_is_refused_as_the_loader_does(self):
        case_dir = make_case(self.tmp)
        real = case_dir.parent / "elders"
        (case_dir / "sources").rename(real)
        (case_dir / "sources").symlink_to(real)
        problems = check_case.check_case(case_dir)
        self.assertIn("sources/doc: is een symlink, of ligt onder een symlink", problems)
        self.assertIn("sources/__dispatch_input: is een symlink, of ligt onder een symlink", problems)

    def test_a_symlink_as_the_file_itself_is_refused(self):
        case_dir = make_case(self.tmp)
        real = case_dir.parent / "doc-elders"
        (case_dir / "sources" / "doc").rename(real)
        (case_dir / "sources" / "doc").symlink_to(real)
        self.assertIn("sources/doc: is een symlink, of ligt onder een symlink", check_case.check_case(case_dir))

    def test_an_unreadable_file_is_one_line_not_a_traceback(self):
        case_dir = make_case(self.tmp)
        target = case_dir / "sources" / "doc"
        target.chmod(0)
        self.addCleanup(target.chmod, 0o644)
        if os.access(target, os.R_OK):
            self.skipTest("running as a user that reads everything")
        done = run_cli(case_dir)
        self.assertEqual(done.returncode, 1)
        self.assertIn("sources/doc: niet te lezen (PermissionError)", done.stdout)
        self.assertNotIn("Traceback", done.stdout + done.stderr)

    def test_a_missing_payload_is_one_line(self):
        case_dir = make_case(self.tmp)
        (case_dir / "payload.json").unlink()
        self.assertEqual(check_case.check_case(case_dir), ["payload.json: ontbreekt of is geen gewoon bestand"])

    def test_a_source_key_twice_in_case_json_is_a_deviation(self):
        case_dir = make_case(self.tmp)
        self.edit_case(case_dir, lambda case: case["sources"].append(dict(case["sources"][0])))
        self.assertIn("case.json: sleutel doc komt twee keer voor in sources", check_case.check_case(case_dir))

    def test_an_artifact_key_twice_in_the_payload_is_a_deviation(self):
        case_dir = make_case(self.tmp)
        self.edit_payload(case_dir, lambda payload: payload["dispatch"]["source_artifacts"].append(dict(payload["dispatch"]["source_artifacts"][1])))
        self.assertEqual(check_case.check_case(case_dir), ["source_artifacts: sleutel doc komt twee keer voor"])

    def test_a_review_document_that_is_no_source_is_a_deviation(self):
        case_dir = make_case(self.tmp)
        self.edit_payload(case_dir, lambda payload: payload["dispatch"]["input"]["review_documents"]["items"].append({"key": "ander", "sha256": "3" * 64}))
        self.assertEqual(check_case.check_case(case_dir), ["review_documents: 'ander' is geen bron in case.json"])

    def test_an_unhashable_review_document_key_is_a_line_not_a_traceback(self):
        case_dir = make_case(self.tmp)
        self.edit_payload(case_dir, lambda payload: payload["dispatch"]["input"]["review_documents"]["items"][0].update(key=["doc"]))
        done = run_cli(case_dir)
        self.assertEqual(done.returncode, 1)
        self.assertIn("review_documents: ['doc'] is geen bron in case.json", done.stdout)
        self.assertNotIn("Traceback", done.stdout + done.stderr)

    def test_no_review_documents_is_a_deviation_not_a_pass(self):
        case_dir = make_case(self.tmp)
        self.edit_payload(case_dir, lambda payload: payload["dispatch"]["input"]["review_documents"].update(items=[]))
        self.assertEqual(check_case.check_case(case_dir), ["payload.json: dispatch.input.review_documents.items ontbreekt of is leeg"])

    def test_no_arguments_is_a_usage_error(self):
        done = subprocess.run([sys.executable, str(CHECK_CASE)], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 2)
        self.assertIn("gebruik:", done.stderr)


@unittest.skipUnless(REAL_CASE.is_dir(), "the frozen case is not in this checkout")
class RealCaseTest(unittest.TestCase):
    def test_the_frozen_case_is_sound(self):
        self.assertEqual(check_case.check_case(REAL_CASE), [])

    def test_case_json_has_the_values_of_the_plan(self):
        case = json.loads((REAL_CASE / "case.json").read_text())
        self.assertEqual(case["id"], "macsearch-idea263-spec-r5")
        self.assertEqual(case["limits"], {"maxTurns": 30, "maxOutputTokens": 64000, "maxWallSeconds": 1800, "maxToolErrors": 8})
        self.assertEqual(case["contextTokens"], 131072)
        self.assertEqual(case["maxCostUsd"], "1")
        self.assertEqual(sorted(case), sorted(["id", "prompt", "payload", "sources", "limits", "contextTokens", "maxCostUsd"]))


# ---------------------------------------------------------------------------------------------------------------------
# the driver (M8, T-102): run.py against fake_review_bench.py and a fake LiteLLM
# ---------------------------------------------------------------------------------------------------------------------

RUN = HERE / "run.py"
FAKE = HERE / "fake_review_bench.py"
KEY_ENV = "LITELLM_MASTER_KEY"
DUMMY_KEY = "zQ7-Xm2Vb9_Kp4RtW8nYc3Lf"       # a test lends a child process this and nothing real; no 6 characters of it are a word
CONFIGS = ["cfg-alfa", "cfg-beta", "cfg-gamma"]
ALFA, BETA, GAMMA = CONFIGS
DRIVER_CASE_ID = "synth-case"
STAMP = r"\d{8}T\d{6}Z"
HARNESS_CONFIGURATIONS = {
    ALFA: {"costMode": "hosted", "contextTokens": 131072, "reasoningEffort": "high"},
    BETA: {"costMode": "hosted", "contextTokens": 65536},
    GAMMA: {"costMode": "hosted", "contextTokens": 131072, "reasoningEffort": "medium"},
}


def leaked_fragments(text, key, min=6):
    """Every stretch of `min` characters of key that is still in text, each once, sorted. [] means nothing of the key is left."""
    return sorted({key[i:i + min] for i in range(len(key) - min + 1) if key[i:i + min] in text})


def clean_env(**extra):
    """The environment for a child process: ours without a LITELLM_MASTER_KEY (a test never lends a real key), plus extra."""
    env = {k: v for k, v in os.environ.items() if k != KEY_ENV}
    env.update(extra)
    return env


def make_driver_case(root, case_id=DRIVER_CASE_ID, max_cost="1"):
    """A case dir for the driver: it reads `id` and `maxCostUsd` of case.json and hands the dir to the harness; the stand-in needs no more."""
    case_dir = Path(root) / "driver-case"
    case_dir.mkdir()
    (case_dir / "case.json").write_text(json.dumps({"id": case_id, "maxCostUsd": max_cost}), encoding="utf-8")
    return case_dir


def write_harness_json(path, base_url, configurations=None):
    config = {"litellm": {"baseUrl": base_url}, "configurations": configurations or HARNESS_CONFIGURATIONS}
    Path(path).write_text(json.dumps(config, indent=2), encoding="utf-8")


def tree_text(root):
    """{relative path: text} of every file under root."""
    root = Path(root)
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8", errors="replace") for p in sorted(root.rglob("*")) if p.is_file()}


def load_driver_module():
    """run.py as a module of its own name: task_bench has a run.py too."""
    spec = importlib.util.spec_from_file_location("review_bench_run", RUN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DriverBase(unittest.TestCase):
    """run.py with fake_review_bench.py as the harness and a fake LiteLLM. It holds no test, so a subclass does not repeat any."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()          # resolved: the driver resolves its paths, and /var is /private/var
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.litellm = fake_review_bench.FakeLiteLLM().start()
        self.addCleanup(self.litellm.stop)
        self.out = self.tmp / "out"                            # run.py creates it
        self.ledger = self.tmp / "ledger.jsonl"
        self.log = self.tmp / "calls.jsonl"
        self.config_file = self.tmp / "harness.json"
        write_harness_json(self.config_file, self.litellm.base_url)
        self.case_dir = make_driver_case(self.tmp)
        self.probe_dir = self.tmp / "probes"
        self.probe_dir.mkdir()
        self.key_file = self.tmp / "litellm.key"
        self.key_file.write_text(DUMMY_KEY + "\n", encoding="utf-8")
        self.harness = f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKE))}"
        self.counter = 0

    # --- running it -----------------------------------------------------------------------------------------------------

    def command(self, models, *, config=None, runs=3, budget="10", args=(), env=None, out=None, ready=True, harness=None,
                config_file=None, case_dir=None, key_file=None):
        """(argv, environment) of the driver for the configurations in models. ready: the preflight of every configuration has
        passed (a preflight.json in out), unless the call is the preflight itself or names a preflight file."""
        out = Path(out or self.out)
        args = [str(a) for a in args]
        if ready and "--preflight" not in args and "--preflight-file" not in args and not (out / "preflight.json").exists():
            self.pass_preflight(path=out / "preflight.json")
        (self.tmp / "fake.json").write_text(json.dumps(config or {}), encoding="utf-8")
        argv = [sys.executable, str(RUN), "--harness", harness or self.harness, "--config", str(config_file or self.config_file),
                "--probe-dir", str(self.probe_dir), "--case", str(case_dir or self.case_dir), "--models", *models,
                "--runs", str(runs), "--out", str(out), "--ledger", str(self.ledger), "--budget", str(budget),
                "--key-file", str(key_file or self.key_file), *args]
        environment = clean_env(FAKE_REVIEW_BENCH_CONFIG=str(self.tmp / "fake.json"), FAKE_REVIEW_BENCH_LOG=str(self.log),
                                FAKE_REVIEW_BENCH_LEDGER=str(self.ledger), **(env or {}))
        return argv, environment

    def drive(self, models, timeout=120, **kw):
        argv, environment = self.command(models, **kw)
        return subprocess.run(argv, capture_output=True, text=True, env=environment, cwd=self.tmp, timeout=timeout)

    def reset(self):
        """Back to an empty run, for a test that tries several things in turn: out, ledger and call log go, by their exact paths."""
        shutil.rmtree(self.out, ignore_errors=True)
        for path in (self.ledger, self.log):
            if path.exists():
                path.unlink()

    # --- looking at what happened ---------------------------------------------------------------------------------------

    def calls(self):
        """What the stand-in logged, in order."""
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def ran(self):
        """[(configuration, run)] of every call of the stand-in, in order."""
        return [(row["label"], row["run"]) for row in self.calls()]

    def ledger_rows(self):
        if not self.ledger.exists():
            return []
        return [json.loads(line) for line in self.ledger.read_text(encoding="utf-8").splitlines() if line.strip()]

    def skipped(self, out=None):
        return json.loads((Path(out or self.out) / "skipped.json").read_text(encoding="utf-8"))

    def run_dirs(self, label, n):
        directory = self.out / label / f"r{n}"
        return sorted(p for p in directory.glob(f"{DRIVER_CASE_ID}-{label}-*") if p.is_dir()) if directory.exists() else []

    def everything(self, *done):
        """{where: text} of every place the key must not be: the files under out, the ledger, the log of the stand-in, the output of the
        driver calls in done."""
        texts = {f"out/{name}": text for name, text in tree_text(self.out).items()} if self.out.exists() else {}
        for name, path in (("ledger", self.ledger), ("calls", self.log)):
            if path.exists():
                texts[name] = path.read_text(encoding="utf-8")
        for n, d in enumerate(done):
            texts[f"stdout {n}"], texts[f"stderr {n}"] = d.stdout, d.stderr
        return texts

    def assert_nothing_started(self):
        self.assertFalse(self.log.exists(), "the harness was called")
        self.assertFalse(self.ledger.exists(), "the ledger was written")
        left = sorted(p.name for p in self.out.rglob("*")) if self.out.exists() else []
        self.assertIn(left, ([], ["preflight.json"]), "something was written under --out")

    # --- preparing a state to run from or resume from -------------------------------------------------------------------

    def pass_preflight(self, path=None, models=CONFIGS, rejected=None):
        """A preflight file in which every configuration is ok, except the rejected ones ({name: reason})."""
        path = Path(path or self.out / "preflight.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        entries = {name: {"ok": True, "reason": None} for name in models}
        for name, reason in (rejected or {}).items():
            entries[name] = {"ok": False, "reason": reason}
        path.write_text(json.dumps(entries), encoding="utf-8")

    def seed(self, label, n, status, *, cost=None, bench_error=None, over=None):
        """A finished run in <out>/<label>/r<n>/ as the harness leaves it: <case>-<label>-<8 hex>/bench-result.json; over replaces fields."""
        self.counter += 1
        run_id = f"{DRIVER_CASE_ID}-{label}-{self.counter:08x}"
        directory = self.out / label / f"r{n}" / run_id
        directory.mkdir(parents=True)
        result = {**fake_review_bench.bench_result(DRIVER_CASE_ID, label, run_id, status, cost, bench_error=bench_error), **(over or {})}
        (directory / "bench-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return directory

    def preload(self, *amounts):
        """A ledger that holds these amounts already (None: an unknown one), as of an earlier window."""
        self.ledger.write_text("".join(json.dumps({"id": f"x{n}", "kind": "run", "label": ALFA, "run": 1, "case": DRIVER_CASE_ID, "cost_usd": a}) + "\n"
                                       for n, a in enumerate(amounts)), encoding="utf-8")


class UsageTest(DriverBase):
    """Exit 2: the call or a configuration is wrong, and nothing has started."""

    def test_a_name_that_is_not_in_harness_json_is_a_usage_error(self):
        done = self.drive([ALFA, "cfg-onbekend"])
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("cfg-onbekend", done.stderr)
        self.assertIn("--config", done.stderr)
        self.assert_nothing_started()

    def test_the_same_name_twice_is_refused(self):
        done = self.drive([ALFA, BETA, ALFA])
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("more than once", done.stderr)
        self.assert_nothing_started()

    def test_a_configuration_that_is_no_plain_path_segment_is_refused(self):
        write_harness_json(self.config_file, self.litellm.base_url, {"../x": {"costMode": "hosted", "contextTokens": 1}})
        done = self.drive(["../x"])
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("plain path segment", done.stderr)
        self.assert_nothing_started()

    def test_a_harness_json_that_is_unusable_is_refused(self):
        for what, text in (("missing", None), ("not JSON", "{ niet af"), ("not an object", "[]"),
                           ("no litellm.baseUrl", json.dumps({"litellm": {}, "configurations": HARNESS_CONFIGURATIONS})),
                           ("a baseUrl that is no http url", json.dumps({"litellm": {"baseUrl": "ftp://x/v1"}, "configurations": HARNESS_CONFIGURATIONS})),
                           ("no configurations", json.dumps({"litellm": {"baseUrl": "http://127.0.0.1:1/v1"}}))):
            with self.subTest(what):
                self.reset()
                if text is None:
                    self.config_file.unlink(missing_ok=True)
                else:
                    self.config_file.write_text(text, encoding="utf-8")
                done = self.drive([ALFA])
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("--config", done.stderr)
                self.assert_nothing_started()

    def test_a_case_that_the_driver_cannot_use_is_refused(self):
        for what, content in (("no case.json", None), ("not JSON", "{ niet af"), ("no id", {"maxCostUsd": "1"}),
                              ("an id that is no path segment", {"id": "../x", "maxCostUsd": "1"}),
                              ("no maxCostUsd", {"id": DRIVER_CASE_ID}), ("a maxCostUsd that is a number", {"id": DRIVER_CASE_ID, "maxCostUsd": 1}),
                              ("a maxCostUsd that is no decimal", {"id": DRIVER_CASE_ID, "maxCostUsd": "veel"}),
                              ("a maxCostUsd of zero", {"id": DRIVER_CASE_ID, "maxCostUsd": "0"}),
                              ("a negative maxCostUsd", {"id": DRIVER_CASE_ID, "maxCostUsd": "-1"})):
            with self.subTest(what):
                self.reset()
                (self.case_dir / "case.json").unlink(missing_ok=True)
                if content is not None:
                    (self.case_dir / "case.json").write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
                done = self.drive([ALFA])
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("case", done.stderr)
                self.assert_nothing_started()

    def test_the_numbers_of_the_call_have_to_make_sense(self):
        for flag, value in (("--budget", "0"), ("--budget", "-3"), ("--budget", "nan"), ("--budget", "veel"), ("--runs", "0"), ("--runs", "1.5")):
            with self.subTest(flag=flag, value=value):
                argv, environment = self.command([ALFA])
                argv[argv.index(flag) + 1] = value
                done = subprocess.run(argv, capture_output=True, text=True, env=environment, cwd=self.tmp, timeout=60)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assert_nothing_started()

    def test_missing_arguments_are_a_usage_error_with_the_same_status(self):
        done = subprocess.run([sys.executable, str(RUN), "--models", ALFA], capture_output=True, text=True, env=clean_env(), timeout=60)
        self.assertEqual(done.returncode, 2)
        self.assertIn("required", done.stderr)

    def test_a_harness_that_cannot_be_started_is_a_usage_error(self):
        done = self.drive([ALFA], harness="/nonexistent/harness-binary")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("cannot start the harness", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_a_ledger_that_cannot_be_read_is_refused_before_anything_starts(self):
        self.ledger.write_text('{"id": "x", "kind": "run", "cost_usd": 1}\nniet json\n', encoding="utf-8")
        done = self.drive([ALFA])
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("line 2", done.stderr)
        self.assertFalse(self.log.exists())

    def test_an_out_that_is_a_file_is_refused(self):
        self.out.write_text("geen map", encoding="utf-8")
        done = self.drive([ALFA], ready=False)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertFalse(self.log.exists())


class FlowTest(DriverBase):
    def test_the_runs_go_round_by_round_over_the_configurations(self):
        done = self.drive(CONFIGS)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(name, n) for n in (1, 2, 3) for name in CONFIGS])

    def test_the_order_of_models_is_the_order_of_every_round(self):
        done = self.drive([GAMMA, ALFA], runs=2)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(GAMMA, 1), (ALFA, 1), (GAMMA, 2), (ALFA, 2)])

    def test_every_run_lands_in_a_directory_of_its_own_per_configuration_and_run(self):
        done = self.drive(CONFIGS)
        self.assertEqual(done.returncode, 0, done.stderr)
        for name in CONFIGS:
            for n in (1, 2, 3):
                with self.subTest(label=name, run=n):
                    [directory] = self.run_dirs(name, n)
                    self.assertRegex(directory.name, rf"^{DRIVER_CASE_ID}-{re.escape(name)}-[0-9a-f]{{8}}$")
                    result = json.loads((directory / "bench-result.json").read_text(encoding="utf-8"))
                    self.assertEqual((result["caseId"], result["label"], result["status"]), (DRIVER_CASE_ID, name, "beoordeeld"))

    def test_the_harness_gets_the_flags_of_the_real_command_and_the_name_of_the_key_variable_only(self):
        done = self.drive([BETA], runs=2)
        self.assertEqual(done.returncode, 0, done.stderr)
        first, second = self.calls()
        for n, call in ((1, first), (2, second)):
            argv = call["argv"]
            self.assertEqual(argv[0], "review-bench")
            flags = {argv[i]: argv[i + 1] for i in range(1, len(argv), 2)}
            self.assertEqual(flags, {"--case": str(self.case_dir), "--config": str(self.config_file), "--configuration": BETA,
                                     "--probe-dir": str(self.probe_dir), "--label": BETA, "--out": str(self.out / BETA / f"r{n}"),
                                     "--api-key-env": KEY_ENV})
            self.assertEqual(argv.count("--api-key-env"), 1)
            self.assertTrue(call["key_env_set"])                    # the value travelled in the environment

    def test_the_driver_says_what_it_does_and_ends_with_the_ledger(self):
        done = self.drive([ALFA], runs=1, config={"default": {"cost": 0.25}})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"{ALFA} r1: running", done.stdout)
        self.assertIn(f"{ALFA} r1: beoordeeld", done.stdout)
        self.assertRegex(done.stdout.strip().splitlines()[-1], r"^done: .*ledger \$0\.2500 of \$10\.00 \(1 entries, 0 without an amount\)$")

    def test_skipped_json_is_an_empty_list_when_everything_ran(self):
        self.assertEqual(self.drive(CONFIGS).returncode, 0)
        self.assertEqual(self.skipped(), [])

    def test_the_ledger_directory_is_made_when_it_is_not_there(self):
        self.ledger = self.tmp / "nog" / "niet" / "ledger.jsonl"
        done = self.drive([ALFA], runs=1)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.ledger_rows()), 1)


class LedgerTest(DriverBase):
    def test_the_ledger_adds_up_runs_and_preflight(self):
        pre = self.drive([ALFA, BETA], args=("--preflight",), ready=False)
        self.assertEqual(pre.returncode, 0, pre.stderr)
        done = self.drive([ALFA, BETA], runs=2, config={"default": {"cost": 0.25}})
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = self.ledger_rows()
        self.assertEqual([row["kind"] for row in rows], ["preflight"] * 2 + ["run"] * 4)
        self.assertAlmostEqual(math.fsum(row["cost_usd"] for row in rows), 2 * fake_review_bench.DEFAULT_COST + 4 * 0.25)
        self.assertIn("ledger $1.0042", done.stdout)

    def test_the_rows_have_the_shape_of_the_ledger(self):
        self.assertEqual(self.drive([ALFA], args=("--preflight",), ready=False).returncode, 0)
        self.assertEqual(self.drive([ALFA], runs=1, config={"default": {"cost": 0.25}}).returncode, 0)
        preflight, run = self.ledger_rows()
        self.assertRegex(preflight["id"], rf"^preflight-{ALFA}-{STAMP}$")
        self.assertEqual({k: v for k, v in preflight.items() if k != "id"}, {"kind": "preflight", "label": ALFA, "cost_usd": fake_review_bench.DEFAULT_COST})
        [directory] = self.run_dirs(ALFA, 1)
        self.assertEqual(run, {"id": directory.name, "kind": "run", "label": ALFA, "run": 1, "case": DRIVER_CASE_ID, "cost_usd": 0.25})

    def test_a_benchfout_costs_what_its_result_says(self):
        config = {"labels": {f"{ALFA}/r1": [{"status": "benchfout", "benchError": "harness: stuk", "cost": 0.125}, {"cost": 0.25}]}}
        self.assertEqual(self.drive([ALFA], runs=1, config=config).returncode, 0)
        self.assertEqual([row["cost_usd"] for row in self.ledger_rows()], [0.125, 0.25])

    def test_a_missing_amount_is_null_in_the_ledger_and_counts_as_zero(self):
        self.assertEqual(self.drive([ALFA], runs=1).returncode, 0)
        [row] = self.ledger_rows()
        self.assertIsNone(row["cost_usd"])
        done = self.drive([ALFA], runs=1)           # nothing left to do: the total is printed
        self.assertIn("ledger $0.0000 of $10.00 (1 entries, 1 without an amount)", done.stdout)

    def test_every_run_is_booked_before_the_next_call_is_paid(self):
        self.assertEqual(self.drive(CONFIGS, runs=2, config={"default": {"cost": 0.1}}).returncode, 0)
        self.assertEqual([call["ledger_lines"] for call in self.calls()], [0, 1, 2, 3, 4, 5])

    def test_the_ledger_is_added_to_never_rewritten(self):
        self.preload(1.0, None)
        before = self.ledger.read_text(encoding="utf-8")
        self.assertEqual(self.drive([ALFA], runs=1, config={"default": {"cost": 0.5}}).returncode, 0)
        after = self.ledger.read_text(encoding="utf-8")
        self.assertTrue(after.startswith(before))
        self.assertEqual(len(after.splitlines()), 3)

    def test_a_run_without_a_usable_result_is_a_null_row_named_after_its_run(self):
        config = {"labels": {f"{ALFA}/r1": [{"no_result": True, "stderr": "CASE_INVALID: stuk"}, {"cost": 0.25}]}}
        self.assertEqual(self.drive([ALFA], runs=1, config=config).returncode, 0)
        first, second = self.ledger_rows()
        self.assertRegex(first["id"], rf"^{DRIVER_CASE_ID}-{ALFA}-r1-geen-resultaat-{STAMP}$")
        self.assertIsNone(first["cost_usd"])
        self.assertEqual(second["cost_usd"], 0.25)


class BudgetTest(DriverBase):
    def test_a_run_that_could_take_the_total_over_the_budget_does_not_start(self):
        self.preload(9.10)                           # 9.10 + the $1 ceiling of the case > 10
        done = self.drive(CONFIGS, budget="10", config={"default": {"cost": 0}})
        self.assertEqual(done.returncode, 4, done.stderr)
        self.assertEqual(self.calls(), [])
        self.assertIn("stopped (4)", done.stderr)

    def test_a_total_that_leaves_room_for_the_ceiling_still_starts(self):
        self.preload(8.90)                           # 8.90 + 1 < 10
        done = self.drive(CONFIGS, budget="10", config={"default": {"cost": 0}})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.calls()), 9)

    def test_the_budget_itself_is_not_over_the_budget(self):
        self.preload(9.0)                            # 9 + 1 = 10, and only more than 10 stops
        done = self.drive([ALFA], runs=1, budget="10", config={"default": {"cost": 0}})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1)])

    def test_the_ceiling_is_the_max_cost_of_the_case(self):
        (self.case_dir / "case.json").write_text(json.dumps({"id": DRIVER_CASE_ID, "maxCostUsd": "2.50"}), encoding="utf-8")
        self.preload(7.40)
        self.assertEqual(self.drive([ALFA], runs=1, budget="10", config={"default": {"cost": 0}}).returncode, 0)
        self.reset()
        self.preload(7.60)
        done = self.drive([ALFA], runs=1, budget="10", config={"default": {"cost": 0}})
        self.assertEqual(done.returncode, 4, done.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_budget_stop_marks_every_run_that_did_not_start_as_budget_reached(self):
        self.preload(9.10)
        done = self.drive(CONFIGS, budget="10")
        self.assertEqual(done.returncode, 4, done.stderr)
        self.assertEqual(self.skipped(), [{"label": name, "run": n, "reason": "budget bereikt"} for name in CONFIGS for n in (1, 2, 3)])

    def test_the_driver_stops_at_the_run_that_would_pass_the_budget_and_keeps_what_it_did(self):
        self.preload(8.0)
        done = self.drive(CONFIGS, budget="10", config={"default": {"cost": 0.6}})
        self.assertEqual(done.returncode, 4, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1), (BETA, 1)])         # 8.0 -> 8.6 -> 9.2; 9.2 + 1 > 10
        rows = self.skipped()
        self.assertEqual(len(rows), 7)
        self.assertEqual({row["reason"] for row in rows}, {"budget bereikt"})
        self.assertNotIn({"label": ALFA, "run": 1, "reason": "budget bereikt"}, rows)

    def test_the_repeat_of_a_benchfout_looks_at_the_budget_too(self):
        self.preload(8.5)
        config = {"labels": {f"{ALFA}/r1": [{"status": "benchfout", "benchError": "harness: stuk", "cost": 0.6}]}}
        done = self.drive([ALFA], runs=1, budget="10", config=config)         # 8.5 -> 9.1; the repeat would end over 10
        self.assertEqual(done.returncode, 4, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1)])

    def test_skipped_json_is_written_again_by_every_call(self):
        self.preload(9.10)
        self.assertEqual(self.drive([ALFA], runs=2, budget="10").returncode, 4)
        self.assertEqual(len(self.skipped()), 2)
        self.assertEqual(self.drive([ALFA], runs=2, budget="100").returncode, 0)
        self.assertEqual(self.skipped(), [])

    def test_resuming_comes_before_the_budget_check(self):
        self.assertEqual(self.drive([ALFA], runs=1).returncode, 0)
        self.preload(50)
        done = self.drive([ALFA], runs=1, budget="10")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.calls()), 1)

    def test_the_budget_is_the_whole_ledger_the_preflight_included(self):
        self.preload(9.0)
        self.assertEqual(self.drive([ALFA], args=("--preflight",), ready=False).returncode, 0)
        # the preflight booked fake_review_bench.DEFAULT_COST: 9.0021 + 1 > 10 stops, which 9.0 + 1 alone would not
        done = self.drive([ALFA], runs=1, budget="10", config={"default": {"cost": 0}})
        self.assertEqual(done.returncode, 4, done.stderr)
        self.assertEqual(self.calls(), [])


class ResumeTest(DriverBase):
    def test_finished_runs_are_skipped_per_configuration_and_run(self):
        for name in CONFIGS:
            self.seed(name, 1, "beoordeeld")
        done = self.drive(CONFIGS)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(name, n) for n in (2, 3) for name in CONFIGS])

    def test_one_finished_run_does_not_finish_the_rest_of_its_configuration(self):
        self.seed(BETA, 2, "limiet")
        self.assertEqual(self.drive(CONFIGS).returncode, 0)
        self.assertEqual(self.ran(), [(name, n) for n in (1, 2, 3) for name in CONFIGS if (name, n) != (BETA, 2)])

    def test_each_model_status_counts_as_done(self):
        for n, status in enumerate(fake_review_bench.MODEL_STATUSES, start=1):
            self.seed(ALFA, n, status)
        done = self.drive([ALFA])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_second_call_over_a_finished_set_calls_nothing_and_changes_nothing(self):
        self.assertEqual(self.drive(CONFIGS, config={"default": {"cost": 0.1}}).returncode, 0)
        calls, ledger = len(self.calls()), self.ledger.read_text(encoding="utf-8")
        done = self.drive(CONFIGS)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.calls()), calls)
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), ledger)
        self.assertEqual(self.skipped(), [])

    def test_what_is_no_valid_result_of_this_case_and_configuration_does_not_count(self):
        cases = {
            "a result of another label": lambda: self.seed(BETA, 1, "beoordeeld", over={"label": GAMMA}),
            "a result of another case": lambda: self.seed(BETA, 1, "beoordeeld", over={"caseId": "ander"}),
            "a status that is none": lambda: self.seed(BETA, 1, "beoordeeld", over={"status": "klaar"}),
            "a result that is no object": lambda: self.seed(BETA, 1, "beoordeeld").joinpath("bench-result.json").write_text("[]"),
            "a result that is not JSON": lambda: self.seed(BETA, 1, "beoordeeld").joinpath("bench-result.json").write_text("{ niet af"),
            "a run directory without a result": lambda: (self.out / BETA / "r1" / f"{DRIVER_CASE_ID}-{BETA}-00000099").mkdir(parents=True),
            "a result of another label's directory": lambda: self.seed(ALFA, 1, "beoordeeld"),
            "a benchfout": lambda: self.seed(BETA, 1, "benchfout", bench_error="harness: stuk"),
            "a result in another run": lambda: self.seed(BETA, 2, "beoordeeld"),
        }
        for what, prepare in cases.items():
            with self.subTest(what):
                self.reset()
                self.counter = 0
                prepare()
                done = self.drive([BETA], runs=1)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(self.ran(), [(BETA, 1)])

    def test_a_result_that_was_aborted_does_not_count_as_a_benchfout(self):
        self.seed(ALFA, 1, "benchfout", bench_error="afgebroken")
        self.seed(ALFA, 1, "benchfout", bench_error="afgebroken")
        done = self.drive([ALFA], runs=1)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1)])

    def test_an_aborted_result_next_to_a_benchfout_leaves_one_more_run(self):
        self.seed(ALFA, 1, "benchfout", bench_error="afgebroken")
        self.seed(ALFA, 1, "benchfout", bench_error="harness: stuk")
        done = self.drive([ALFA], runs=1, config={"default": {"status": "benchfout", "benchError": "harness: weer stuk"}})
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1)])                     # one repeat, and that was the second benchfout

    def test_benchfouten_do_not_matter_once_the_run_has_a_result_of_a_model_status(self):
        self.seed(ALFA, 1, "benchfout", bench_error="harness: stuk")
        self.seed(ALFA, 1, "benchfout", bench_error="harness: stuk")
        self.seed(ALFA, 1, "beoordeeld")
        done = self.drive([ALFA], runs=1)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), [])

    def test_the_benchfout_counter_is_per_configuration_and_run(self):
        self.seed(ALFA, 1, "benchfout", bench_error="harness: stuk")        # one in r1 ...
        self.seed(ALFA, 2, "benchfout", bench_error="harness: stuk")        # ... and one in r2: neither is a second one
        config = {"default": {"cost": 0.1}}
        done = self.drive([ALFA], runs=2, config=config)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1), (ALFA, 2)])


class BenchfoutTest(DriverBase):
    def test_a_first_benchfout_runs_once_more_and_the_set_goes_on(self):
        config = {"labels": {f"{BETA}/r1": [{"status": "benchfout", "benchError": "harness: stuk"}, {"status": "beoordeeld"}]}}
        done = self.drive([ALFA, BETA], runs=2, config=config)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1), (BETA, 1), (BETA, 1), (ALFA, 2), (BETA, 2)])

    def test_a_second_benchfout_on_the_same_run_stops_the_driver_with_the_exit_status_of_m7(self):
        config = {"labels": {f"{BETA}/r1": {"status": "benchfout", "benchError": "harness: stuk"}}}
        done = self.drive(CONFIGS, runs=2, config=config)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1), (BETA, 1), (BETA, 1)])           # gamma never started
        self.assertIn("stopped (3)", done.stderr)
        self.assertIn("harness: stuk", done.stderr)

    def test_the_stop_marks_what_was_left_as_stopped_after_the_second_benchfout(self):
        config = {"labels": {f"{BETA}/r1": {"status": "benchfout", "benchError": "harness: stuk"}}}
        self.assertEqual(self.drive(CONFIGS, runs=2, config=config).returncode, 3)
        reason = f"gestopt na tweede benchfout op {BETA}"
        started = {(ALFA, 1), (BETA, 1)}                      # these have their results, the other four never started
        self.assertEqual(self.skipped(), [{"label": name, "run": n, "reason": reason}
                                          for name in CONFIGS for n in (1, 2) if (name, n) not in started])

    def test_two_benchfouten_on_disk_stop_the_driver_without_a_new_run_for_them(self):
        self.seed(BETA, 1, "benchfout", bench_error="harness: stuk")
        self.seed(BETA, 1, "benchfout", bench_error="harness: stuk")
        done = self.drive(CONFIGS, runs=1)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1)])

    def test_every_run_has_a_repeat_of_its_own(self):
        config = {"labels": {ALFA: [{"status": "benchfout", "benchError": "harness: stuk"}, {"status": "beoordeeld"}]}}
        done = self.drive([ALFA], runs=2, config=config)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1), (ALFA, 1), (ALFA, 2), (ALFA, 2)])

    def test_a_run_without_a_usable_result_is_a_benchfout_and_counts_for_the_rule(self):
        for what, attempt in (("no result and exit 1", {"no_result": True, "stderr": "CASE_INVALID: stuk"}),
                              ("a result that is not JSON", {"result_text": "{ niet af"}),
                              ("a result of another case", {"result_case": "ander"}),
                              ("a result of another label", {"result_label": GAMMA})):
            with self.subTest(what):
                self.reset()
                done = self.drive([ALFA], runs=1, config={"default": attempt})
                self.assertEqual(done.returncode, 3, done.stderr)
                self.assertEqual(self.ran(), [(ALFA, 1), (ALFA, 1)])
                self.assertEqual([row["cost_usd"] for row in self.ledger_rows()], [None, None])

    def test_the_stop_names_what_the_harness_said(self):
        done = self.drive([ALFA], runs=1, config={"default": {"no_result": True, "stderr": "CASE_INVALID: sources/doc ontbreekt"}})
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertIn("CASE_INVALID: sources/doc ontbreekt", done.stderr)

    def test_the_cost_of_a_result_that_is_there_counts_whatever_the_exit_status_says(self):
        done = self.drive([ALFA], runs=1, config={"default": {"cost": 0.25, "exit": 1}})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([row["cost_usd"] for row in self.ledger_rows()], [0.25])

    def test_each_model_status_ends_the_run_at_once(self):
        for status in fake_review_bench.MODEL_STATUSES:
            with self.subTest(status):
                self.reset()
                done = self.drive([ALFA], runs=1, config={"default": {"status": status}})
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(self.ran(), [(ALFA, 1)])

    def test_a_benchfout_from_an_error_code_without_a_benchError_counts_too(self):
        done = self.drive([ALFA], runs=1, config={"default": {"status": "benchfout"}})         # MODEL_ERROR, as the bench maps it
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1), (ALFA, 1)])
        self.assertIn("MODEL_ERROR", done.stderr)


class NotProbedTest(DriverBase):
    NOT_PROBED = "CONFIGURATION_NOT_PROBED: geen probe.json voor cfg-beta"

    def config(self):
        return {"labels": {BETA: {"status": "benchfout", "benchError": self.NOT_PROBED}}}

    def test_a_configuration_that_is_not_probed_is_called_once_not_repeated_and_the_exit_is_0(self):
        done = self.drive(CONFIGS, config=self.config())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([call for call in self.ran() if call[0] == BETA], [(BETA, 1)])
        self.assertEqual(self.ran(), [(ALFA, 1), (BETA, 1), (GAMMA, 1), (ALFA, 2), (GAMMA, 2), (ALFA, 3), (GAMMA, 3)])

    def test_the_runs_that_did_not_start_are_marked_not_probed_with_the_detail(self):
        self.assertEqual(self.drive(CONFIGS, config=self.config()).returncode, 0)
        reason = "niet geprobed: geen probe.json voor cfg-beta"
        self.assertEqual(self.skipped(), [{"label": BETA, "run": 2, "reason": reason}, {"label": BETA, "run": 3, "reason": reason}])

    def test_a_second_call_with_the_same_stand_in_gives_exit_0_again(self):
        self.assertEqual(self.drive(CONFIGS, config=self.config()).returncode, 0)
        done = self.drive(CONFIGS, config=self.config())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([call for call in self.ran() if call[0] == BETA], [(BETA, 1), (BETA, 1)])      # tried once more, not repeated
        self.assertEqual(len(self.ran()), 7 + 1)                  # nothing else ran again
        self.assertEqual([row["run"] for row in self.skipped()], [2, 3])

    def test_results_that_are_not_probed_never_add_up_to_a_stop(self):
        for n in (1, 2, 3):
            self.seed(BETA, n, "benchfout", bench_error=self.NOT_PROBED)
        self.seed(BETA, 1, "benchfout", bench_error=self.NOT_PROBED)
        done = self.drive([BETA], config=self.config())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(BETA, 1)])

    def test_a_probe_that_was_made_in_the_meantime_lets_the_runs_through(self):
        self.seed(BETA, 1, "benchfout", bench_error=self.NOT_PROBED)
        done = self.drive([BETA])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(BETA, 1), (BETA, 2), (BETA, 3)])
        self.assertEqual(self.skipped(), [])

    def test_a_benchError_that_only_starts_like_it_is_not_special(self):
        config = {"labels": {BETA: {"status": "benchfout", "benchError": "harness: CONFIGURATION_NOT_PROBED: erachter"}}}
        done = self.drive([BETA], runs=1, config=config)
        self.assertEqual(done.returncode, 3, done.stderr)


class PreflightTest(DriverBase):
    def preflight(self, models=(ALFA, BETA, GAMMA), **kw):
        return self.drive(list(models), args=("--preflight", *kw.pop("args", ())), ready=False, **kw)

    def preflight_file(self, path=None):
        return json.loads(Path(path or self.out / "preflight.json").read_text(encoding="utf-8"))

    def test_an_accepted_configuration_is_ok_and_its_amount_is_in_the_ledger(self):
        done = self.preflight([ALFA])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.preflight_file(), {ALFA: {"ok": True, "reason": None}})
        [row] = self.ledger_rows()
        self.assertEqual((row["kind"], row["label"], row["cost_usd"]), ("preflight", ALFA, fake_review_bench.DEFAULT_COST))
        self.assertIn(f"{ALFA} preflight: ok", done.stdout)

    def test_the_request_is_the_one_of_the_spec(self):
        self.assertEqual(self.preflight().returncode, 0)
        requests = {request["body"]["model"]: request for request in self.litellm.requests}
        self.assertEqual(sorted(requests), sorted(CONFIGS))
        for name, request in requests.items():
            body = request["body"]
            with self.subTest(name):
                self.assertEqual(request["path"], "/v1/chat/completions")
                self.assertEqual(request["authorization"], f"Bearer {DUMMY_KEY}")
                self.assertEqual(request["content_type"], "application/json")
                self.assertEqual(body["max_tokens"], 64000)
                self.assertEqual(body["messages"], [{"role": "user", "content": "Antwoord alleen: OK"}])
                [tool] = body["tools"]
                self.assertEqual(tool["type"], "function")
                self.assertEqual(tool["function"]["name"], "noop")
                self.assertEqual(tool["function"]["parameters"], {"type": "object", "properties": {}})
                effort = HARNESS_CONFIGURATIONS[name].get("reasoningEffort")
                if effort is None:
                    self.assertNotIn("reasoning_effort", body)          # only when harness.json sets it
                else:
                    self.assertEqual(body["reasoning_effort"], effort)
                self.assertEqual(sorted(body), sorted(["model", "max_tokens", "messages", "tools", *(["reasoning_effort"] if effort else [])]))

    def test_one_request_per_configuration_and_no_harness_call(self):
        self.assertEqual(self.preflight().returncode, 0)
        self.assertEqual([request["body"]["model"] for request in self.litellm.requests], CONFIGS)
        self.assertEqual(self.calls(), [])

    def test_an_http_400_is_a_rejection_with_the_reason_and_an_unknown_amount(self):
        self.litellm.answer(BETA, (400, {"error": {"message": "no healthy endpoint under max_price"}}))
        done = self.preflight()
        self.assertEqual(done.returncode, 0, done.stderr)
        entries = self.preflight_file()
        self.assertEqual(entries[ALFA], {"ok": True, "reason": None})
        self.assertFalse(entries[BETA]["ok"])
        self.assertRegex(entries[BETA]["reason"], r"^HTTP 400: .*no healthy endpoint under max_price")
        self.assertIn(f"{BETA} preflight: afgewezen", done.stdout)
        [beta] = [row for row in self.ledger_rows() if row["label"] == BETA]
        self.assertIsNone(beta["cost_usd"])

    def test_skipped_json_after_the_preflight_alone_has_the_rejection_and_for_the_rest_not_started(self):
        self.litellm.answer(BETA, (400, {"error": {"message": "no healthy endpoint"}}))
        self.assertEqual(self.preflight().returncode, 0)
        rows = self.skipped()
        self.assertEqual([(row["label"], row["run"]) for row in rows], [(name, n) for name in CONFIGS for n in (1, 2, 3)])
        for row in rows:
            if row["label"] == BETA:
                self.assertRegex(row["reason"], r"^preflight afgewezen: HTTP 400: .*no healthy endpoint")
            else:
                self.assertEqual(row["reason"], "niet gestart")

    def test_a_rejected_configuration_does_not_run_and_has_three_lines_in_skipped_json(self):
        self.litellm.answer(BETA, (400, {"error": {"message": "no healthy endpoint"}}))
        self.assertEqual(self.preflight([ALFA, BETA]).returncode, 0)
        done = self.drive([ALFA, BETA])                                 # the runs read the preflight of the call before
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1), (ALFA, 2), (ALFA, 3)])
        rows = self.skipped()
        self.assertEqual([(row["label"], row["run"]) for row in rows], [(BETA, 1), (BETA, 2), (BETA, 3)])
        for row in rows:
            self.assertRegex(row["reason"], r"^preflight afgewezen: HTTP 400: .*no healthy endpoint")

    def test_a_200_without_a_finite_usage_cost_is_a_rejection(self):
        bodies = {
            "no usage": {"choices": []},
            "no cost": {"usage": {"prompt_tokens": 5, "completion_tokens": 1}},
            "a cost that is null": {"usage": {"cost": None}},
            "a cost that is a string": {"usage": {"cost": "0.001"}},
            "a cost that is a bool": {"usage": {"cost": True}},
            "a cost that is not finite": '{"usage": {"cost": NaN}}',
            "a cost that is infinite": '{"usage": {"cost": Infinity}}',
            "a cost that is negative": {"usage": {"cost": -0.5}},
            "a usage that is no object": {"usage": 3},
            "a body that is no JSON": "<html>gateway</html>",
            "a body that is no object": [1, 2],
        }
        for what, body in bodies.items():
            with self.subTest(what):
                self.reset()
                self.litellm.answer(ALFA, (200, body))
                self.assertEqual(self.preflight([ALFA]).returncode, 0)
                entry = self.preflight_file()[ALFA]
                self.assertFalse(entry["ok"], entry)
                self.assertTrue(entry["reason"])
                [row] = self.ledger_rows()
                self.assertIsNone(row["cost_usd"])

    def test_a_cost_of_zero_is_a_cost(self):
        self.litellm.answer(ALFA, fake_review_bench.FakeLiteLLM.ok(0))
        self.assertEqual(self.preflight([ALFA]).returncode, 0)
        self.assertEqual(self.preflight_file()[ALFA], {"ok": True, "reason": None})
        self.assertEqual(self.ledger_rows()[0]["cost_usd"], 0)

    def test_a_status_other_than_200_is_a_rejection_even_with_a_cost(self):
        self.litellm.answer(ALFA, (201, fake_review_bench.FakeLiteLLM.ok(0.1)[1]))
        self.assertEqual(self.preflight([ALFA]).returncode, 0)
        entry = self.preflight_file()[ALFA]
        self.assertFalse(entry["ok"])
        self.assertIn("201", entry["reason"])

    def test_a_server_that_does_not_answer_is_a_rejection_that_names_the_kind_of_error_only(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        write_harness_json(self.config_file, f"http://127.0.0.1:{port}/v1")
        done = self.preflight([ALFA])
        self.assertEqual(done.returncode, 0, done.stderr)
        entry = self.preflight_file()[ALFA]
        self.assertFalse(entry["ok"])
        self.assertIn("URLError", entry["reason"])
        self.assertNotIn(str(port), entry["reason"])
        self.assertIsNone(self.ledger_rows()[0]["cost_usd"])

    def test_a_redirect_is_not_followed_so_the_key_stays_where_it_was_sent(self):
        elsewhere = fake_review_bench.FakeLiteLLM().start()
        self.addCleanup(elsewhere.stop)
        self.litellm.answer(ALFA, lambda request: (302, {}, {"Location": f"{elsewhere.base_url}/chat/completions"}))
        self.assertEqual(self.preflight([ALFA]).returncode, 0)
        self.assertEqual(elsewhere.requests, [])             # urllib would have gone there with the same Authorization header
        entry = self.preflight_file()[ALFA]
        self.assertFalse(entry["ok"])
        self.assertIn("302", entry["reason"])

    def test_a_proxy_in_the_environment_is_not_used_for_the_key(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            dead = f"http://127.0.0.1:{s.getsockname()[1]}"
        proxies = {name: dead for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY")}
        done = self.drive([ALFA], args=("--preflight",), ready=False, env={**proxies, "no_proxy": "", "NO_PROXY": ""})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.preflight_file()[ALFA], {"ok": True, "reason": None})

    def test_the_file_goes_to_preflight_file_and_a_second_preflight_updates_only_its_own_configurations(self):
        elders = self.tmp / "elders" / "pf.json"
        self.assertEqual(self.preflight([ALFA, BETA], args=("--preflight-file", elders)).returncode, 0)
        self.assertEqual(sorted(self.preflight_file(elders)), [ALFA, BETA])
        self.assertFalse((self.out / "preflight.json").exists())
        self.litellm.answer(BETA, (400, {"error": {"message": "nu stuk"}}))
        self.assertEqual(self.preflight([BETA, GAMMA], args=("--preflight-file", elders)).returncode, 0)
        entries = self.preflight_file(elders)
        self.assertEqual(sorted(entries), [ALFA, BETA, GAMMA])
        self.assertTrue(entries[ALFA]["ok"])
        self.assertFalse(entries[BETA]["ok"])
        self.assertTrue(entries[GAMMA]["ok"])

    def test_smoke_and_main_runs_share_one_preflight_through_preflight_file(self):
        self.assertEqual(self.preflight([ALFA]).returncode, 0)                   # --out A
        smoke = self.out / "rook"
        done = self.drive([ALFA], runs=1, out=smoke, args=("--preflight-file", self.out / "preflight.json"))
        self.assertEqual(done.returncode, 0, done.stderr)                        # no "geen preflight"
        self.assertTrue(list((smoke / ALFA / "r1").glob(f"{DRIVER_CASE_ID}-{ALFA}-*")))
        main = self.drive([ALFA], runs=1)                                        # the smoke run does not count for A
        self.assertEqual(main.returncode, 0, main.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1), (ALFA, 1)])

    def test_without_preflight_file_the_smoke_directory_has_no_preflight(self):
        self.assertEqual(self.preflight([ALFA]).returncode, 0)
        done = self.drive([ALFA], runs=1, out=self.out / "rook", ready=False)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("preflight", done.stderr)
        self.assertEqual(self.calls(), [])

    def test_runs_need_a_preflight_for_every_configuration_they_run(self):
        self.pass_preflight(models=[ALFA, BETA])
        done = self.drive([ALFA, BETA, GAMMA], ready=False)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(GAMMA, done.stderr)
        self.assertIn("preflight", done.stderr)
        self.assert_nothing_started()

    def test_a_preflight_file_that_is_unusable_is_refused(self):
        for what, text in (("not JSON", "{ niet af"), ("not an object", "[]"), ("an entry that is no object", json.dumps({ALFA: True})),
                           ("an entry without ok", json.dumps({ALFA: {"reason": "x"}})),
                           ("an ok that is no bool", json.dumps({ALFA: {"ok": "ja", "reason": None}}))):
            with self.subTest(what):
                self.reset()
                self.out.mkdir()
                (self.out / "preflight.json").write_text(text, encoding="utf-8")
                done = self.drive([ALFA], ready=False)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("preflight", done.stderr)
                self.assertFalse(self.log.exists())

    def test_every_rejected_configuration_means_nothing_runs_and_the_exit_is_still_0(self):
        self.pass_preflight(rejected={name: "HTTP 400: nee" for name in CONFIGS})
        done = self.drive(CONFIGS, ready=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(len(self.skipped()), 9)

    def test_a_signal_during_the_preflight_lets_the_request_finish_and_stops_before_the_next_configuration(self):
        gate, released = threading.Event(), threading.Event()

        def hold(request):
            gate.set()
            released.wait(30)
            return fake_review_bench.FakeLiteLLM.ok()

        self.litellm.answer(ALFA, hold)
        argv, environment = self.command(CONFIGS, args=("--preflight",), ready=False)
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment, cwd=self.tmp)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.assertTrue(gate.wait(30), "the preflight never asked")
        os.kill(proc.pid, signal.SIGINT)
        time.sleep(0.3)             # the handler only sets the flag; the request in flight is not cut off
        released.set()
        stdout, stderr = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 6, stderr)
        self.assertEqual([request["body"]["model"] for request in self.litellm.requests], [ALFA])
        self.assertEqual(sorted(self.preflight_file()), [ALFA])                 # what was done is kept
        self.assertEqual([row["label"] for row in self.ledger_rows()], [ALFA])
        self.assertEqual({row["reason"] for row in self.skipped()}, {"gestopt (stopvlag)"})


class StopTest(DriverBase):
    """SIGINT and SIGTERM: the driver sets a flag and waits for the bench, which is what lets the bench write its own result."""

    def start(self, models, **kw):
        argv, environment = self.command(models, **kw)
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment, cwd=self.tmp,
                                start_new_session=True)          # its own session: a group signal does not reach the test runner
        self.addCleanup(self.reap, proc)
        return proc

    @staticmethod
    def reap(proc):
        if proc.poll() is None:                                  # only if a test left it running: that group, by its own pid
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()

    @staticmethod
    def wait_for(path, proc, seconds=30):
        deadline = time.monotonic() + seconds
        while not path.exists():
            if proc.poll() is not None or time.monotonic() > deadline:
                raise AssertionError(f"{path.name} never came; the driver ended with {proc.poll()}")
            time.sleep(0.01)

    def stop_during_a_run(self, signum):
        marker = self.tmp / "running"
        config = {"labels": {f"{ALFA}/r1": [{"wait_for_signal": True, "marker": str(marker), "abort_delay": 0.2, "cost": 0.25},
                                            {"status": "beoordeeld", "cost": 0.5}]},
                  "default": {"cost": 0.5}}
        proc = self.start(CONFIGS, config=config)
        self.wait_for(marker, proc)
        os.killpg(proc.pid, signum)             # to the group: the driver and the bench both get it
        stdout, stderr = proc.communicate(timeout=60)
        return proc.returncode, stdout, stderr

    def check_aborted_run(self, status, stderr):
        self.assertEqual(status, 6, stderr)
        [directory] = self.run_dirs(ALFA, 1)
        result = json.loads((directory / "bench-result.json").read_text(encoding="utf-8"))   # the bench was left to write it
        self.assertEqual((result["status"], result["benchError"]), ("benchfout", "afgebroken"))
        rows = self.ledger_rows()
        self.assertEqual([(r["kind"], r["label"], r["run"]) for r in rows], [("run", ALFA, 1)])
        self.assertEqual((rows[0]["cost_usd"], rows[0]["id"]), (0.25, directory.name))      # its cost is booked
        self.assertEqual(self.ran(), [(ALFA, 1)])                                           # nothing else started
        rows = self.skipped()
        self.assertEqual(len(rows), 8)                                                      # the aborted run has its result
        self.assertEqual({row["reason"] for row in rows}, {"gestopt (stopvlag)"})

    def test_sigint_to_the_group_lets_the_running_bench_finish_and_stops_with_6(self):
        status, stdout, stderr = self.stop_during_a_run(signal.SIGINT)
        self.check_aborted_run(status, stderr)

    def test_sigterm_to_the_group_does_the_same(self):
        status, stdout, stderr = self.stop_during_a_run(signal.SIGTERM)
        self.check_aborted_run(status, stderr)

    def test_the_aborted_run_is_run_again_when_the_driver_resumes_and_is_no_benchfout(self):
        status, stdout, stderr = self.stop_during_a_run(signal.SIGINT)
        self.check_aborted_run(status, stderr)
        done = self.drive(CONFIGS, config={"default": {"cost": 0.5}})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran()[:2], [(ALFA, 1), (ALFA, 1)])
        self.assertEqual(len(self.run_dirs(ALFA, 1)), 2)               # the aborted evidence stays, next to the new run
        self.assertEqual(self.skipped(), [])

    def test_a_signal_during_a_run_that_ends_normally_stops_before_the_next_run(self):
        done = self.drive(CONFIGS, config={"labels": {f"{ALFA}/r1": {"sigint_parent": True, "cost": 0.25}}, "default": {"cost": 0.5}})
        self.assertEqual(done.returncode, 6, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1)])
        self.assertEqual([row["cost_usd"] for row in self.ledger_rows()], [0.25])
        self.assertEqual({row["reason"] for row in self.skipped()}, {"gestopt (stopvlag)"})

    def test_the_stop_flag_is_looked_at_before_resuming(self):
        self.seed(BETA, 1, "beoordeeld")
        done = self.drive([ALFA, BETA], runs=1, config={"labels": {f"{ALFA}/r1": {"sigint_parent": True}}})
        self.assertEqual(done.returncode, 6, done.stderr)
        self.assertNotIn("skipped, it has a result", done.stdout)       # the flag came first, not the look at what was finished

    def test_the_repeat_of_a_benchfout_does_not_start_after_a_signal(self):
        config = {"labels": {f"{ALFA}/r1": {"status": "benchfout", "benchError": "harness: stuk", "sigint_parent": True}}}
        done = self.drive([ALFA], runs=1, config=config)
        self.assertEqual(done.returncode, 6, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1)])

    def test_a_signal_during_the_second_benchfout_is_a_stop_with_6_and_not_3(self):
        config = {"labels": {f"{ALFA}/r1": [{"status": "benchfout", "benchError": "harness: stuk"},
                                            {"status": "benchfout", "benchError": "harness: stuk", "sigint_parent": True}]}}
        done = self.drive([ALFA], runs=1, config=config)
        self.assertEqual(done.returncode, 6, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1), (ALFA, 1)])

    def test_a_signal_is_a_stop_even_when_nothing_is_left_to_do(self):
        done = self.drive([ALFA], runs=1, config={"labels": {f"{ALFA}/r1": {"sigint_parent": True}}})
        self.assertEqual(done.returncode, 6, done.stderr)
        self.assertEqual(self.skipped(), [])

    def test_a_bench_that_reports_itself_aborted_stops_the_driver_even_without_a_signal(self):
        config = {"default": {"status": "benchfout", "benchError": "afgebroken", "cost": 0.1}}
        done = self.drive(CONFIGS, config=config)
        self.assertEqual(done.returncode, 6, done.stderr)
        self.assertEqual(self.ran(), [(ALFA, 1)])             # it neither repeats that run nor goes on to the next
        self.assertEqual([row["cost_usd"] for row in self.ledger_rows()], [0.1])

class KeyFileTest(DriverBase):
    def test_a_key_file_with_a_trailing_newline_gives_the_bare_value(self):
        for what, content in (("a newline", DUMMY_KEY + "\n"), ("two newlines", DUMMY_KEY + "\n\n"), ("spaces and a newline", f"  {DUMMY_KEY} \r\n"),
                              ("nothing", DUMMY_KEY)):
            with self.subTest(what):
                self.reset()
                self.litellm.requests.clear()
                self.key_file.write_text(content, encoding="utf-8")
                self.assertEqual(self.drive([ALFA], args=("--preflight",), ready=False).returncode, 0)
                self.assertEqual([request["authorization"] for request in self.litellm.requests], [f"Bearer {DUMMY_KEY}"])
                self.assertEqual(self.drive([ALFA], runs=1).returncode, 0)
                [call] = self.calls()
                self.assertEqual(call["key_env_len"], len(DUMMY_KEY))

    def test_a_key_file_that_cannot_be_the_key_is_refused_and_the_value_is_never_quoted_back(self):
        refused = {
            "shorter than 8 characters": "kort7ch",
            "empty": "",
            "only whitespace": " \n\n ",
            "LITELLM_MASTER_KEY=<value>": f"{KEY_ENV}={DUMMY_KEY}\n",
            "a double quote at the ends": f'"{DUMMY_KEY}"\n',
            "a single quote at the ends": f"'{DUMMY_KEY}'\n",
            "a quote inside": f'{DUMMY_KEY[:10]}"{DUMMY_KEY[10:]}',
        }
        for what, content in refused.items():
            with self.subTest(what):
                self.reset()
                self.key_file.write_text(content, encoding="utf-8")
                done = self.drive([ALFA])
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("key file", done.stderr)
                self.assertEqual(leaked_fragments(done.stdout + done.stderr, DUMMY_KEY), [])
                if content.strip():
                    self.assertNotIn(content.strip(), done.stdout + done.stderr)
                self.assert_nothing_started()

    def test_a_value_that_http_client_refuses_leaks_nothing_through_the_error(self):
        # a newline inside the value: http.client raises a ValueError that quotes the header; the driver names the kind of error only
        inner = DUMMY_KEY[:12] + "\n" + DUMMY_KEY[12:]
        self.key_file.write_text(inner + "\n", encoding="utf-8")
        done = self.drive([ALFA], args=("--preflight",), ready=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        entry = json.loads((self.out / "preflight.json").read_text(encoding="utf-8"))[ALFA]
        self.assertFalse(entry["ok"])
        self.assertIn("ValueError", entry["reason"])
        for where, text in self.everything(done).items():
            with self.subTest(where):
                self.assertEqual(leaked_fragments(text, DUMMY_KEY[:12], min=6) + leaked_fragments(text, DUMMY_KEY[12:], min=6), [])

    def test_a_missing_key_file_is_a_usage_error(self):
        self.key_file.unlink()
        done = self.drive([ALFA])
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("key file", done.stderr)
        self.assert_nothing_started()

    def test_the_value_goes_into_the_environment_of_the_harness_and_nowhere_in_its_argv(self):
        self.assertEqual(self.drive(CONFIGS, runs=2).returncode, 0)
        for call in self.calls():
            self.assertTrue(call["key_env_set"])
            self.assertEqual(call["key_env_len"], len(DUMMY_KEY))
            self.assertEqual(leaked_fragments(" ".join(call["argv"]), DUMMY_KEY), [])
            self.assertEqual(call["argv"][call["argv"].index("--api-key-env") + 1], KEY_ENV)

    def test_the_key_file_wins_over_a_variable_the_driver_inherited(self):
        self.assertEqual(self.drive([ALFA], runs=1, env={KEY_ENV: "inherited-value-that-is-longer"}).returncode, 0)
        [call] = self.calls()
        self.assertEqual(call["key_env_len"], len(DUMMY_KEY))

    def test_the_preflight_asks_with_the_value_in_the_header_and_the_driver_prints_none_of_it(self):
        done = self.drive(CONFIGS, args=("--preflight",), ready=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual({request["authorization"] for request in self.litellm.requests}, {f"Bearer {DUMMY_KEY}"})
        self.assertEqual(leaked_fragments(done.stdout + done.stderr, DUMMY_KEY), [])


class LeakTest(DriverBase):
    """Nothing of the key under --out, in the ledger, in the argv log of the harness, or on the screen of the driver: also when a
    server and the harness quote it back."""

    def test_leaked_fragments_finds_every_stretch_and_only_those(self):
        self.assertEqual(leaked_fragments("niets hier", DUMMY_KEY), [])
        self.assertEqual(leaked_fragments(f"x {DUMMY_KEY} y", DUMMY_KEY), sorted({DUMMY_KEY[i:i + 6] for i in range(len(DUMMY_KEY) - 5)}))
        self.assertEqual(leaked_fragments(f"x {DUMMY_KEY[4:12]} y", DUMMY_KEY), sorted({DUMMY_KEY[i:i + 6] for i in range(4, 7)}))
        self.assertEqual(leaked_fragments("abcde", "abcdefgh"), [])          # five of six is not a stretch
        self.assertEqual(leaked_fragments("zzabcdefzz", "abcdefgh", min=4), ["abcd", "bcde", "cdef"])

    def test_nothing_of_the_key_is_left_when_the_server_and_the_harness_quote_it_back(self):
        # the key starts 13 characters before the cut of the excerpt: cutting first and masking second would leave them behind
        self.litellm.answer(BETA, lambda request: (400, {"error": {"message": f"invalid api key: {request['authorization']}"}}))
        self.litellm.answer(GAMMA, lambda request: (400, "x" * 280 + request["authorization"]))
        pre = self.drive(CONFIGS, args=("--preflight",), ready=False)
        self.assertEqual(pre.returncode, 0, pre.stderr)
        entries = json.loads((self.out / "preflight.json").read_text(encoding="utf-8"))
        self.assertIn("<redacted>", entries[BETA]["reason"])                  # the echo did happen, and was masked
        self.assertIn("invalid api key", entries[BETA]["reason"])
        self.assertFalse(entries[GAMMA]["ok"])
        self.assertIn("<redacted>", entries[GAMMA]["reason"])
        echo = f"boom: the harness echoed {DUMMY_KEY} and {DUMMY_KEY.strip()} back"
        done = self.drive(CONFIGS, config={"labels": {f"{ALFA}/r3": {"no_result": True, "stderr": echo}}})      # beta and gamma were rejected
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertIn("boom", done.stderr)                              # it is quoted ...
        self.assertIn("<redacted>", done.stderr)                        # ... without the key
        files = self.everything(pre, done)
        self.assertGreater(len([name for name in files if name.startswith("out/")]), 5)
        for where, text in files.items():
            with self.subTest(where):
                self.assertEqual(leaked_fragments(text, DUMMY_KEY), [])

    def test_what_the_driver_quotes_from_a_result_is_masked_too(self):
        # the stand-in writes this benchError as given (the real harness masks its own files); the driver's own files and output are checked
        quoted = f"CONFIGURATION_NOT_PROBED: de sleutel {DUMMY_KEY} stond in de fout"
        config = {"labels": {BETA: {"status": "benchfout", "benchError": quoted}, GAMMA: {"status": "benchfout", "benchError": f"harness: {quoted}"}}}
        done = self.drive(CONFIGS, runs=2, config=config)
        self.assertEqual(done.returncode, 3, done.stderr)
        driver_files = {"skipped.json": (self.out / "skipped.json").read_text(encoding="utf-8"), "ledger": self.ledger.read_text(encoding="utf-8"),
                        "stdout": done.stdout, "stderr": done.stderr}
        for where, text in driver_files.items():
            with self.subTest(where):
                self.assertEqual(leaked_fragments(text, DUMMY_KEY), [])
        self.assertIn("niet geprobed: de sleutel <redacted> stond in de fout", driver_files["skipped.json"])

    def test_a_normal_set_leaves_nothing_of_the_key_either(self):
        pre = self.drive(CONFIGS, args=("--preflight",), ready=False)
        done = self.drive(CONFIGS, config={"default": {"cost": 0.1}})
        self.assertEqual((pre.returncode, done.returncode), (0, 0))
        files = self.everything(pre, done)
        self.assertGreater(len(files), 20)
        for where, text in files.items():
            with self.subTest(where):
                self.assertEqual(leaked_fragments(text, DUMMY_KEY), [])

    def test_the_check_has_teeth_a_planted_fragment_is_found_in_the_files(self):
        self.assertEqual(self.drive([ALFA], runs=1).returncode, 0)
        (self.out / "planted.txt").write_text(f"x {DUMMY_KEY[7:15]} y", encoding="utf-8")
        found = {where for where, text in self.everything().items() if leaked_fragments(text, DUMMY_KEY)}
        self.assertEqual(found, {"out/planted.txt"})


class HelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.R = load_driver_module()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_the_exit_codes_are_those_of_m7(self):
        R = self.R
        self.assertEqual((R.EXIT_USAGE, R.EXIT_BENCH, R.EXIT_BUDGET, R.EXIT_PROBE, R.EXIT_ABORTED), (2, 3, 4, 5, 6))

    def test_the_model_statuses_are_the_three_of_a_judged_run(self):
        self.assertEqual(self.R.MODEL_STATUSES, ("beoordeeld", "limiet", "resultaat_ongeldig"))
        self.assertEqual(self.R.STATUSES, self.R.MODEL_STATUSES + ("benchfout",))
        self.assertEqual(self.R.MODEL_STATUSES, fake_review_bench.MODEL_STATUSES)

    def test_mask_secrets_masks_the_value_and_its_trimmed_form_and_cuts_after_the_masking(self):
        R = self.R
        self.assertEqual(R.mask_secrets("a secret and short", ["secret"]), "a secret and short")      # a placeholder is left alone
        self.assertEqual(R.mask_secrets(f"a {DUMMY_KEY} b", [DUMMY_KEY]), "a <redacted> b")
        self.assertEqual(R.mask_secrets(f"a {DUMMY_KEY} b", [f" {DUMMY_KEY}\n"]), "a <redacted> b")      # the trimmed form too
        self.assertEqual(leaked_fragments(R.excerpt(f"{'x' * 295}{DUMMY_KEY} more", [DUMMY_KEY]), DUMMY_KEY), [])    # masked before the cut

    def test_amount_is_a_finite_non_negative_number_and_zero_is_one(self):
        R = self.R
        self.assertEqual([R.amount(v) for v in (0, 0.5, 3, "1", None, True, -1, math.nan, math.inf)], [0.0, 0.5, 3.0, None, None, None, None, None, None])

    def test_an_entry_is_one_json_line_and_the_ledger_is_added_to(self):
        path = self.tmp / "sub" / "ledger.jsonl"
        self.R.append_ledger(path, {"id": "a", "kind": "run", "cost_usd": 0.5})
        self.R.append_ledger(path, {"id": "b", "kind": "preflight", "cost_usd": None})
        self.assertEqual(path.read_text(encoding="utf-8").count("\n"), 2)
        entries = self.R.read_ledger(path)
        self.assertEqual([e["id"] for e in entries], ["a", "b"])
        self.assertEqual(self.R.ledger_total(entries), 0.5)

    def test_the_total_is_an_exact_sum_and_a_missing_amount_counts_as_zero(self):
        entries = [{"cost_usd": 0.1}, {"cost_usd": 0.2}, {"cost_usd": 0.3}, {"cost_usd": None}, {}]
        self.assertEqual(self.R.ledger_total(entries), 0.6)          # math.fsum: 0.1 + 0.2 + 0.3 in floats is 0.6000000000000001
        self.assertEqual(self.R.ledger_unknown(entries), 2)

    def test_no_ledger_yet_is_an_empty_ledger_and_a_bad_line_is_refused_without_quoting_it(self):
        self.assertEqual(self.R.read_ledger(self.tmp / "niet-er.jsonl"), [])
        path = self.tmp / "l.jsonl"
        for text in ('{"cost_usd": 1}\nstukke regel met geheim-0123456789\n', '{"cost_usd": "veel geheim-0123456789"}\n', "[1]\n",
                     '{"cost_usd": -1}\n'):
            with self.subTest(text):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(self.R.RunError) as raised:
                    self.R.read_ledger(path)
                self.assertNotIn("geheim", str(raised.exception))
        path.write_text('\n{"cost_usd": 1}\n\n', encoding="utf-8")            # blank lines are skipped
        self.assertEqual(len(self.R.read_ledger(path)), 1)

    def test_run_dir_names_are_exactly_case_label_and_eight_hex(self):
        R = self.R
        directory = self.tmp / "r1"
        for name in (f"{DRIVER_CASE_ID}-{ALFA}-0123abcd", f"{DRIVER_CASE_ID}-{ALFA}-0123abc", f"{DRIVER_CASE_ID}-{ALFA}-0123abcdef",
                     f"{DRIVER_CASE_ID}-{BETA}-0123abcd", f"ander-{ALFA}-0123abcd", f"{DRIVER_CASE_ID}-{ALFA}-0123abcg"):
            (directory / name).mkdir(parents=True)
        (directory / f"{DRIVER_CASE_ID}-{ALFA}-89abcdef").write_text("een bestand")
        self.assertEqual(R.run_dir_names(directory, DRIVER_CASE_ID, ALFA), [f"{DRIVER_CASE_ID}-{ALFA}-0123abcd"])
        self.assertEqual(R.run_dir_names(self.tmp / "niet-er", DRIVER_CASE_ID, ALFA), [])

    def test_a_label_with_dots_is_a_plain_segment_and_is_matched_literally(self):
        R = self.R
        label = "claude-sonnet-5.5-or"
        directory = self.tmp / "r1"
        (directory / f"{DRIVER_CASE_ID}-{label}-0123abcd").mkdir(parents=True)
        (directory / f"{DRIVER_CASE_ID}-claude-sonnet-5x5-or-0123abcd").mkdir()
        self.assertEqual(R.run_dir_names(directory, DRIVER_CASE_ID, label), [f"{DRIVER_CASE_ID}-{label}-0123abcd"])


# ---------------------------------------------------------------------------------------------------------------------
# the stand-ins themselves: held to the real command and to the real files
# ---------------------------------------------------------------------------------------------------------------------

class FakeHarnessTest(unittest.TestCase):
    RESULT_KEYS = ["caseId", "label", "runId", "configuration", "contextTokens", "status", "runStatus", "result", "validation", "usage",
                   "peakInputTokens", "turns", "toolCalls", "toolErrors", "providers", "retries", "durationMs"]

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.case_dir = make_driver_case(self.tmp)
        self.config_file = self.tmp / "harness.json"
        write_harness_json(self.config_file, "http://127.0.0.1:1/v1")
        self.out = self.tmp / "out" / ALFA / "r1"
        self.fake_config = self.tmp / "fake.json"
        self.log = self.tmp / "calls.jsonl"

    def fake(self, *args, config=None, **env):
        self.fake_config.write_text(json.dumps(config or {}), encoding="utf-8")
        return subprocess.run([sys.executable, str(FAKE), *map(str, args)], capture_output=True, text=True, timeout=60,
                              env=clean_env(FAKE_REVIEW_BENCH_CONFIG=str(self.fake_config), FAKE_REVIEW_BENCH_LOG=str(self.log), **env))

    def review_bench(self, *, config=None, drop=(), **over):
        flags = {"--case": self.case_dir, "--config": self.config_file, "--configuration": ALFA, "--probe-dir": self.tmp / "probes",
                 "--label": ALFA, "--out": self.out, "--api-key-env": KEY_ENV}
        flags.update({f"--{k.replace('_', '-')}": v for k, v in over.items()})
        args = [x for flag, value in flags.items() if flag not in drop for x in (flag, value)]
        return self.fake("review-bench", *args, config=config, **{KEY_ENV: DUMMY_KEY})

    def only_run_dir(self):
        [directory] = [p for p in self.out.iterdir() if p.is_dir()]
        return directory

    def test_a_result_has_the_files_the_keys_and_the_stdout_of_the_real_command(self):
        done = self.review_bench(config={"default": {"cost": 0.25}})
        self.assertEqual(done.returncode, 0, done.stderr)
        directory = self.only_run_dir()
        self.assertRegex(directory.name, rf"^{DRIVER_CASE_ID}-{ALFA}-[0-9a-f]{{8}}$")
        self.assertTrue((directory / "trace.jsonl").is_file())
        self.assertTrue((directory / "root").is_dir())
        self.assertEqual(done.stdout, f"beoordeeld {directory}\n")
        result = json.loads((directory / "bench-result.json").read_text(encoding="utf-8"))
        self.assertEqual(list(result), self.RESULT_KEYS)
        self.assertEqual(result["configuration"], {"name": ALFA, "costMode": "hosted", "reasoningEffort": "high"})
        self.assertEqual((result["runId"], result["usage"]["costUsd"], result["contextTokens"]), (directory.name, 0.25, 131072))
        self.assertEqual(result["result"]["review"]["verdict"], "NO-GO")
        self.assertEqual(result["validation"], {"attempts": 1, "errors": []})

    def test_the_four_statuses_have_the_shape_the_bench_gives_them(self):
        shapes = {
            "beoordeeld": ("completed", None),
            "resultaat_ongeldig": ("failed", "REVIEW_RESULT_INVALID"),
            "limiet": ("budget_exceeded", "COST_LIMIT_EXCEEDED"),
            "benchfout": ("failed", "MODEL_ERROR"),
        }
        for status, (run_status, code) in shapes.items():
            with self.subTest(status):
                shutil.rmtree(self.out, ignore_errors=True)
                done = self.review_bench(config={"default": {"status": status}})
                self.assertEqual(done.returncode, 0, done.stderr)
                result = json.loads((self.only_run_dir() / "bench-result.json").read_text(encoding="utf-8"))
                self.assertEqual((result["status"], result["runStatus"]), (status, run_status))
                self.assertEqual(result.get("error", {}).get("code"), code)
                self.assertEqual(result["result"] is None, status != "beoordeeld")
                self.assertNotIn("costUsd", result["usage"])                     # no amount: the field is absent
                self.assertNotIn("benchError", result)

    def test_a_benchError_is_the_last_key_and_leaves_no_run_status(self):
        done = self.review_bench(config={"default": {"status": "benchfout", "benchError": "CONFIGURATION_NOT_PROBED: nee"}})
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads((self.only_run_dir() / "bench-result.json").read_text(encoding="utf-8"))
        self.assertEqual(list(result)[-1], "benchError")
        self.assertEqual((result["status"], result["runStatus"], result["benchError"]), ("benchfout", "not_run", "CONFIGURATION_NOT_PROBED: nee"))
        self.assertNotIn("error", result)

    def test_the_attempt_that_answers_is_the_nth_call_of_a_configuration_in_that_out_dir(self):
        config = {"labels": {ALFA: [{"status": "limiet"}, {"status": "beoordeeld"}], f"{ALFA}/r2": {"status": "resultaat_ongeldig"}}}
        statuses = []
        for out in (self.out, self.out, self.out.parent / "r2"):
            done = self.review_bench(config=config, out=out)
            statuses.append(done.stdout.split()[0])
        self.assertEqual(statuses, ["limiet", "beoordeeld", "resultaat_ongeldig"])

    def test_the_log_has_the_argv_the_run_and_whether_the_key_is_set_but_never_the_value(self):
        self.assertEqual(self.review_bench().returncode, 0)
        [row] = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual((row["command"], row["label"], row["run"], row["case"]), ("review-bench", ALFA, 1, DRIVER_CASE_ID))
        self.assertEqual((row["key_env_set"], row["key_env_len"]), (True, len(DUMMY_KEY)))
        self.assertEqual(leaked_fragments(self.log.read_text(encoding="utf-8"), DUMMY_KEY), [])

    def test_the_usage_errors_of_the_real_cli_are_exit_1_without_a_result(self):
        for flag in ("--case", "--config", "--configuration", "--probe-dir", "--label", "--out", "--api-key-env"):
            with self.subTest(missing=flag):
                done = self.review_bench(drop=(flag,))
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertFalse(self.out.exists())
        done = self.review_bench(label="niet/goed")
        self.assertEqual(done.returncode, 1)
        self.assertIn("--label", done.stderr)
        done = self.fake("review-bench", "--case", self.case_dir, "--config", self.config_file, "--configuration", ALFA, "--probe-dir", self.tmp,
                         "--label", ALFA, "--out", self.out, "--api-key-env", KEY_ENV)          # the variable is not set
        self.assertEqual(done.returncode, 1)
        self.assertIn(KEY_ENV, done.stderr)
        self.assertFalse(self.out.exists())

    def test_an_invalid_case_is_case_invalid_on_stderr_exit_1_and_no_result(self):
        (self.case_dir / "case.json").write_text("{ niet af", encoding="utf-8")
        done = self.review_bench()
        self.assertEqual(done.returncode, 1)
        self.assertTrue(done.stderr.startswith("CASE_INVALID: "), done.stderr)
        self.assertFalse(self.out.exists())

    def test_no_result_leaves_nothing_and_a_result_text_is_written_as_given(self):
        done = self.review_bench(config={"default": {"no_result": True, "stderr": "stuk"}})
        self.assertEqual((done.returncode, done.stderr.strip()), (1, "stuk"))
        self.assertFalse(self.out.exists())
        done = self.review_bench(config={"default": {"result_text": "{ niet af"}})
        self.assertEqual(done.returncode, 0)
        self.assertEqual((self.only_run_dir() / "bench-result.json").read_text(encoding="utf-8"), "{ niet af")


class FakeLiteLLMTest(unittest.TestCase):
    def setUp(self):
        self.server = fake_review_bench.FakeLiteLLM().start()
        self.addCleanup(self.server.stop)

    def post(self, model, path="/chat/completions"):
        request = urllib.request.Request(self.server.base_url + path, data=json.dumps({"model": model}).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {DUMMY_KEY}"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=30) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read().decode("utf-8")
            finally:
                e.close()

    def test_it_answers_with_a_cost_by_default_and_records_what_it_was_asked(self):
        status, text = self.post("m1")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(text)["usage"]["cost"], fake_review_bench.DEFAULT_COST)
        [request] = self.server.requests
        self.assertEqual((request["path"], request["body"], request["authorization"]), ("/v1/chat/completions", {"model": "m1"}, f"Bearer {DUMMY_KEY}"))

    def test_an_answer_per_model_is_a_pair_or_a_function_of_the_request(self):
        self.server.answer("m2", (400, {"error": "nee"}))
        self.server.answer("m3", lambda request: (200, f"echo {request['body']['model']}"))
        self.assertEqual(self.post("m2"), (400, json.dumps({"error": "nee"})))
        self.assertEqual(self.post("m3"), (200, "echo m3"))

    def test_it_is_quiet(self):
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            self.post("m1")
        self.assertEqual(captured.getvalue(), "")


class StdlibOnlyTest(unittest.TestCase):
    @unittest.skipUnless(hasattr(sys, "stdlib_module_names"), "needs Python 3.10")
    def test_run_and_the_stand_in_import_nothing_outside_the_standard_library(self):
        for name in ("run.py", "fake_review_bench.py"):
            tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = ([a.name for a in node.names] if isinstance(node, ast.Import)
                           else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
                for module in modules:
                    top = module.split(".")[0]
                    with self.subTest(file=name, module=module):
                        self.assertIn(top, sys.stdlib_module_names)


if __name__ == "__main__":
    unittest.main()
