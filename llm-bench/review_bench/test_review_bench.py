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


VARIANTS = {"macsearch-idea263-spec-r5-out128k": (128000, 3600), "macsearch-idea263-spec-r5-out256k": (256000, 7200)}
PINNED = ("review.md", "payload.json", "sources/doc", "sources/__dispatch_input")


@unittest.skipUnless(REAL_CASE.is_dir(), "the frozen case is not in this checkout")
class VariantCaseTest(unittest.TestCase):
    """M9 (plan 4.1): each variant is the frozen case with another id and other limits, and nothing else."""

    def test_each_variant_is_the_frozen_case_with_other_limits(self):
        original = json.loads((REAL_CASE / "case.json").read_text())
        rest = {key: value for key, value in original.items() if key not in ("id", "limits")}
        for case_id, (max_output, wall) in VARIANTS.items():
            variant = HERE / "cases" / case_id
            with self.subTest(case_id):
                self.assertEqual(check_case.check_case(variant), [])
                for name in PINNED:
                    self.assertEqual((variant / name).read_bytes(), (REAL_CASE / name).read_bytes(), name)
                case = json.loads((variant / "case.json").read_text())
                self.assertEqual(list(case), list(original))                    # the same keys, in the same order
                self.assertEqual(case["id"], case_id)
                self.assertEqual(case["limits"], {"maxTurns": 30, "maxOutputTokens": max_output, "maxWallSeconds": wall, "maxToolErrors": 8})
                self.assertEqual({key: value for key, value in case.items() if key not in ("id", "limits")}, rest)
                files = sorted(str(path.relative_to(variant)) for path in variant.rglob("*") if path.is_file())
                self.assertEqual(files, sorted(["case.json", "SOURCE.md", *PINNED]))


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


def make_driver_case(root, case_id=DRIVER_CASE_ID, max_cost="1", max_output=64000, context=131072):
    """A case dir for the driver: it reads `id`, `maxCostUsd`, `limits.maxOutputTokens` and `contextTokens` of case.json (the defaults are
    those of the frozen case) and hands the dir to the harness; the stand-in needs no more."""
    case_dir = Path(root) / "driver-case"
    case_dir.mkdir()
    case = {"id": case_id, "maxCostUsd": max_cost, "limits": {"maxOutputTokens": max_output}, "contextTokens": context}
    (case_dir / "case.json").write_text(json.dumps(case), encoding="utf-8")
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
        case = {"id": DRIVER_CASE_ID, "maxCostUsd": "2.50", "limits": {"maxOutputTokens": 64000}, "contextTokens": 131072}
        (self.case_dir / "case.json").write_text(json.dumps(case), encoding="utf-8")
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

    def test_a_rejected_label_keeps_its_own_reason_whatever_stopped_the_driver(self):
        stops = {"the budget": (4, {"budget": "10"}, None, "budget bereikt"),
                 "a second benchfout": (3, {}, {"labels": {f"{ALFA}/r1": {"status": "benchfout", "benchError": "harness: stuk"}}},
                                        f"gestopt na tweede benchfout op {ALFA}")}
        for what, (status, kw, config, stop_reason) in stops.items():
            with self.subTest(what):
                self.reset()
                self.pass_preflight(rejected={BETA: "HTTP 400: geen endpoint"})
                if status == 4:
                    self.preload(9.10)
                done = self.drive(CONFIGS, config=config, **kw)
                self.assertEqual(done.returncode, status, done.stderr)
                rows = self.skipped()
                self.assertEqual([(row["label"], row["run"]) for row in rows if row["label"] == BETA], [(BETA, n) for n in (1, 2, 3)])
                for row in rows:
                    if row["label"] == BETA:
                        self.assertEqual(row["reason"], "preflight afgewezen: HTTP 400: geen endpoint")
                    else:
                        self.assertEqual(row["reason"], stop_reason)

    def test_a_label_that_is_not_probed_keeps_its_own_reason_when_the_budget_stops_the_driver(self):
        self.preload(8.5)
        config = {"labels": {BETA: {"status": "benchfout", "benchError": "CONFIGURATION_NOT_PROBED: geen probe", "cost": None}}, "default": {"cost": 0.6}}
        done = self.drive([BETA, ALFA], runs=2, budget="10", config=config)      # alfa r1 takes the total to 9.1, alfa r2 would pass 10
        self.assertEqual(done.returncode, 4, done.stderr)
        self.assertEqual(self.ran(), [(BETA, 1), (ALFA, 1)])
        self.assertEqual(self.skipped(), [{"label": BETA, "run": 2, "reason": "niet geprobed: geen probe"},
                                          {"label": ALFA, "run": 2, "reason": "budget bereikt"}])

    def test_a_skipped_json_that_cannot_be_written_does_not_replace_the_stop(self):
        self.out.mkdir()
        (self.out / "skipped.json").mkdir()             # a directory: write_text fails
        self.preload(9.10)
        done = self.drive(CONFIGS, budget="10")
        self.assertEqual(done.returncode, 4, done.stderr)
        self.assertIn("stopped (4)", done.stderr)
        self.assertRegex(done.stderr, r"run\.py: cannot write skipped\.json under .*out")
        self.assertEqual(self.calls(), [])

    def test_a_skipped_json_that_cannot_be_written_after_a_finished_set_is_exit_2_and_says_so(self):
        self.out.mkdir()
        (self.out / "skipped.json").mkdir()
        done = self.drive([ALFA], runs=1)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("cannot write skipped.json", done.stderr)
        self.assertEqual(len(self.run_dirs(ALFA, 1)), 1)             # the work was done and is kept

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

    def test_max_tokens_is_what_the_harness_asks_on_turn_one(self):
        # M9 plan 4.2: min(limits.maxOutputTokens, contextTokens - 3198); both M9 variants give 127874, the frozen case 64000
        for max_output, expected in ((128000, 127874), (256000, 127874), (64000, 64000), (100000, 100000)):
            with self.subTest(max_output):
                self.reset()
                self.litellm.requests.clear()
                shutil.rmtree(self.case_dir)
                self.case_dir = make_driver_case(self.tmp, max_output=max_output)
                done = self.preflight([ALFA])
                self.assertEqual(done.returncode, 0, done.stderr)
                [request] = self.litellm.requests
                self.assertEqual(request["body"]["max_tokens"], expected)
                self.assertEqual(done.stdout.count(f"preflight max_tokens {expected}"), 1)

    def test_a_case_without_usable_limits_is_refused_before_any_request(self):
        base = {"id": DRIVER_CASE_ID, "maxCostUsd": "1"}
        for what, extra in (("no limits", {"contextTokens": 131072}),
                            ("no maxOutputTokens", {"limits": {}, "contextTokens": 131072}),
                            ("a maxOutputTokens that is a string", {"limits": {"maxOutputTokens": "128000"}, "contextTokens": 131072}),
                            ("a maxOutputTokens that is a bool", {"limits": {"maxOutputTokens": True}, "contextTokens": 131072}),
                            ("no contextTokens", {"limits": {"maxOutputTokens": 128000}}),
                            ("a contextTokens of zero", {"limits": {"maxOutputTokens": 128000}, "contextTokens": 0}),
                            ("a contextTokens that is a float", {"limits": {"maxOutputTokens": 128000}, "contextTokens": 131072.0}),
                            ("no room after the first prompt", {"limits": {"maxOutputTokens": 128000}, "contextTokens": 3198})):
            with self.subTest(what):
                self.reset()
                self.litellm.requests.clear()
                (self.case_dir / "case.json").write_text(json.dumps({**base, **extra}), encoding="utf-8")
                done = self.preflight([ALFA])
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("case.json", done.stderr)
                self.assertEqual(self.litellm.requests, [])
                self.assert_nothing_started()

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

    def test_a_preflight_writes_no_skipped_json_and_leaves_the_one_of_the_last_runs_alone(self):
        self.assertEqual(self.preflight().returncode, 0)
        self.assertFalse((self.out / "skipped.json").exists())              # only a call that runs writes it
        self.preload(9.10)
        self.assertEqual(self.drive(CONFIGS, budget="10").returncode, 4)
        before = (self.out / "skipped.json").read_bytes()
        self.assertEqual(len(self.skipped()), 9)
        self.litellm.answer(BETA, (400, {"error": {"message": "nu stuk"}}))
        self.assertEqual(self.preflight([BETA]).returncode, 0)              # a new preflight of one configuration on the same --out
        self.assertEqual((self.out / "skipped.json").read_bytes(), before)

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
        self.assertFalse((self.out / "skipped.json").exists())


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

class SkippedKeepTest(DriverBase):
    """skipped.json is made again by every call from the labels of that call; the rows of a label that a later call leaves out
    (JP skips it, plan P3.2) stay for as long as those runs have no bench-result.json."""

    STOP = f"gestopt na tweede benchfout op {BETA}"

    def test_the_rows_of_a_label_a_later_call_does_not_name_stay_while_they_have_no_result(self):
        stopped = self.drive([ALFA, BETA], runs=2, config={"labels": {BETA: {"status": "benchfout"}}})
        self.assertEqual(stopped.returncode, 3, stopped.stderr)
        self.assertEqual(self.skipped(), [{"label": ALFA, "run": 2, "reason": self.STOP}, {"label": BETA, "run": 2, "reason": self.STOP}])
        self.assertEqual(self.drive([ALFA], runs=2).returncode, 0)             # JP skips beta: the next call does not name it
        self.assertEqual(self.skipped(), [{"label": BETA, "run": 2, "reason": self.STOP}])      # alfa ran: its row is gone, beta's stays
        self.seed(BETA, 2, "beoordeeld")                                         # now beta r2 has a result
        self.assertEqual(self.drive([ALFA], runs=2).returncode, 0)
        self.assertEqual(self.skipped(), [])

    def test_a_label_the_call_does_name_is_made_again_not_kept(self):
        self.assertEqual(self.drive([ALFA, BETA], runs=1, budget="1", config={"default": {"cost": 0.5}}).returncode, 4)           # budget: alfa r1 ran, beta r1 not
        self.assertEqual(self.skipped(), [{"label": BETA, "run": 1, "reason": "budget bereikt"}])
        self.pass_preflight(path=self.out / "preflight.json", rejected={BETA: "HTTP 400: nee"})              # beta is named again, and has a new reason
        self.assertEqual(self.drive([ALFA, BETA], runs=1, budget="10").returncode, 0)
        self.assertEqual(self.skipped(), [{"label": BETA, "run": 1, "reason": "preflight afgewezen: HTTP 400: nee"}])      # not also the old row
        self.pass_preflight(path=self.out / "preflight.json")
        self.assertEqual(self.drive([ALFA, BETA], runs=1, budget="10").returncode, 0)
        self.assertEqual(self.skipped(), [])

    def test_a_row_that_is_no_row_of_ours_is_not_kept(self):
        self.out.mkdir()
        (self.out / "skipped.json").write_text(json.dumps([
            {"label": BETA, "run": 3, "reason": self.STOP},                       # kept: beta is not in this call and r3 has no result
            {"label": "../buiten", "run": 1, "reason": "x"},                      # a label that is no plain path segment
            {"label": BETA, "run": "1", "reason": "x"}, {"label": BETA, "run": 0, "reason": "x"}, {"label": BETA, "run": 1},
            {"run": 1, "reason": "x"}, "tekst", 7, None]), encoding="utf-8")
        self.assertEqual(self.drive([ALFA], runs=1).returncode, 0)
        self.assertEqual(self.skipped(), [{"label": BETA, "run": 3, "reason": self.STOP}])

    def test_a_skipped_json_that_is_not_a_list_is_replaced_not_a_crash(self):
        self.out.mkdir()
        for text in ("{ stuk", '{"a": 1}', '"tekst"'):
            with self.subTest(text):
                (self.out / "skipped.json").write_text(text, encoding="utf-8")
                self.assertEqual(self.drive([ALFA], runs=1).returncode, 0)
                self.assertEqual(self.skipped(), [])


class DriverDocTest(unittest.TestCase):
    def test_the_example_command_of_the_driver_names_the_release_that_p2_uses(self):
        doc = load_driver_module().__doc__
        self.assertIn('--harness "node /srv/agent-harness/current/dist/cli.js"', doc)
        self.assertNotIn("agent-harness-m8", doc)


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



# ---------------------------------------------------------------------------------------------------------------------
# the scorer (M8, T-103): score.py makes the blind sheets, applies the decision rule and writes the report
# ---------------------------------------------------------------------------------------------------------------------

SCORE = HERE / "score.py"
SCORE_FIXTURES = HERE / "fixtures" / "score"
QWEN, SONNET, SOL = "qwen3.8-or-128k", "claude-sonnet-5.5-or", "gpt-6.1-sol-or"
LUNA, PRO, MINIMAX = "gpt-6-luna-or", "deepseek-v4-pro-or", "minimax-m3-or"
FLASH, GLM = "deepseek-v4-flash-or", "glm-5.3-or"
OPENROUTER = {      # the eight configurations of spec 4.6 and the OpenRouter model behind each
    "qwen3.8-or-128k": "qwen/qwen3.8-27b", "deepseek-v4-flash-or": "deepseek/deepseek-v4-flash",
    "deepseek-v4-pro-or": "deepseek/deepseek-v4-pro", "glm-5.3-or": "z-ai/glm-5.3", "minimax-m3-or": "minimax/minimax-m3",
    "gpt-6-luna-or": "openai/gpt-6-luna", "claude-sonnet-5.5-or": "anthropic/claude-sonnet-5.5", "gpt-6.1-sol-or": "openai/gpt-6.1-sol",
}
FAMILY_WORDS = ("claude", "anthropic", "sonnet", "gpt", "openai", "qwen", "deepseek", "glm", "z-ai", "z.ai", "minimax", "luna", "sol",
                "opus", "haiku", "codex", "gemini", "kimi")
BEOORDEELD = "bench-result-beoordeeld.json"
FIXTURE_RUN_ID = "synth-case-cfg-alfa-00000001"       # the runId of trace.jsonl in the fixtures


def load_score_module():
    """score.py as a module of its own name: task_bench has a score.py too."""
    spec = importlib.util.spec_from_file_location("review_bench_score", SCORE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_json(name):
    return json.loads((SCORE_FIXTURES / name).read_text(encoding="utf-8"))


def result_for(label, run_name, template=BEOORDEELD, **over):
    """A bench-result of the fixture template for this label and run directory; over replaces fields at the top level."""
    result = fixture_json(template)
    result.update(label=label, runId=run_name, configuration={**result["configuration"], "name": label})
    result.update(over)
    return result


def in_words(word, text):
    """Whether word is in text as a whole word, where a digit or a dash does not make it part of a longer one (Qwen3, GPT-6)."""
    return re.search(rf"(?<![^\W\d_]){re.escape(word)}(?![^\W\d_])", text, re.IGNORECASE) is not None


class ScoreBase(unittest.TestCase):
    """score.py in this process; run_main captures what it prints. It holds no test."""

    @classmethod
    def setUpClass(cls):
        cls.S = load_score_module()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = self.tmp / "out"
        self.counter = 0

    def put(self, label, n, template=BEOORDEELD, *, over=None, mtime=None, trace=None, out=None):
        """A finished run in <out>/<label>/r<n>/ as the driver leaves it; trace: a fixture file for its trace.jsonl. Returns its directory."""
        self.counter += 1
        name = f"synth-case-{label}-{self.counter:08x}"
        directory = Path(out or self.out) / label / f"r{n}" / name
        directory.mkdir(parents=True)
        path = directory / "bench-result.json"
        path.write_text(json.dumps({**result_for(label, name, template), **(over or {})}, indent=2) + "\n", encoding="utf-8")
        if trace:
            shutil.copy(SCORE_FIXTURES / trace, directory / "trace.jsonl")
        if mtime is not None:
            os.utime(path, ns=(mtime, mtime))
        return directory

    def run_main(self, *argv):
        """(exit status, stdout, stderr) of score.py main in this process."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                status = self.S.main([str(a) for a in argv])
            except SystemExit as stop:
                status = stop.code
        return status, out.getvalue(), err.getvalue()

    def sheet_ids(self, out=None):
        """{(label, n): sheet id} of the sheets-key.json in out."""
        key = json.loads((Path(out or self.out) / "sheets-key.json").read_text(encoding="utf-8"))
        return {(path.split("/")[0], int(path.split("/")[1][1:])): sheet for sheet, path in key.items()}

    def write_scores(self, path, entries):
        write_jsonl(path, entries)

    def sheet_text(self, label, n, out=None):
        out = Path(out or self.out)
        return (out / "sheets" / f"{self.sheet_ids(out)[(label, n)]}.md").read_text(encoding="utf-8")


def write_jsonl(path, entries):
    Path(path).write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")


def grade(sheet, f1="major", f2="nee", minors=(), extra=()):
    return {"sheet": sheet, "f1": f1, "f2": f2, "minors": list(minors), "extra": list(extra)}


def extra(key, voorstel="geldig"):
    return {"key": key, "voorstel": voorstel, "reden": "Synthetische reden."}


class DecisionRuleTest(ScoreBase):
    """Spec 1 and AC11 as pure functions: run_voldoet, model_oordeel and oordelen."""

    GOOD = {"f1": "major", "f2": "nee", "minors": [], "extra": []}

    def run_record(self, score=None, decisions=None, **over):
        return self.S.beoordeel_run(result_for("cfg-alfa", "synth-case-cfg-alfa-00000001", **over), score, decisions or {})

    def test_a_run_that_meets_every_condition_complies(self):
        self.assertTrue(self.S.run_voldoet(result_for("cfg-alfa", "r"), self.GOOD, {}))

    def test_three_of_three_is_a_candidate_two_of_three_is_doubt_and_one_of_three_falls_away(self):
        for runs, expected in ((3, "kandidaat"), (2, "twijfel"), (1, "valt af"), (0, "valt af")):
            with self.subTest(complying=runs):
                records = [self.run_record(self.GOOD if i < runs else {**self.GOOD, "f1": "minor"}) for i in range(3)]
                self.assertEqual([r["voldoet"] for r in records], [i < runs for i in range(3)])
                self.assertEqual(self.S.model_oordeel(records), expected)

    def test_a_run_that_is_missing_does_not_comply(self):
        missing = {"voldoet": False, "open": False}
        good = self.run_record(self.GOOD)
        self.assertEqual(self.S.model_oordeel([good, good, missing]), "twijfel")
        self.assertEqual(self.S.model_oordeel([good, missing, missing]), "valt af")
        self.assertEqual(self.S.model_oordeel([]), "valt af")

    def test_outcome_failed_with_no_go_does_not_comply(self):
        failed = result_for("cfg-alfa", "r")
        failed["result"]["outcome"] = "failed"
        self.assertEqual(failed["result"]["review"]["verdict"], "NO-GO")
        self.assertEqual(failed["status"], "beoordeeld")            # a failed outcome stays beoordeeld: the rule has to see it
        self.assertFalse(self.S.run_voldoet(failed, self.GOOD, {}))

    def test_every_other_missing_condition_fails_the_run(self):
        no_go_gone = result_for("cfg-alfa", "r")
        no_go_gone["result"]["review"]["verdict"] = "GO"
        cases = {
            "status limiet, with an accepted result still on it": result_for("cfg-alfa", "r", status="limiet"),
            "status resultaat_ongeldig": result_for("cfg-alfa", "r", status="resultaat_ongeldig"),
            "status benchfout": result_for("cfg-alfa", "r", "bench-result-benchfout.json"),
            "verdict GO": no_go_gone,
            "no result": result_for("cfg-alfa", "r", result=None),
        }
        for name, result in cases.items():
            with self.subTest(name):
                self.assertFalse(self.S.run_voldoet(result, self.GOOD, {}))
        for name, score in {"f1 minor": {**self.GOOD, "f1": "minor"}, "f1 nee": {**self.GOOD, "f1": "nee"}, "no score": None}.items():
            with self.subTest(name):
                self.assertFalse(self.S.run_voldoet(result_for("cfg-alfa", "r"), score, {}))

    def test_an_extra_decided_invalid_fails_every_run_with_that_key(self):
        decisions = {"x-verzonnen-api": "ongeldig", "x-echt": "geldig"}
        with_key = {**self.GOOD, "extra": [extra("x-verzonnen-api", "geldig")]}        # the decision is JP's, not the proposal
        other_key = {**self.GOOD, "extra": [extra("x-echt", "ongeldig")]}
        both = {**self.GOOD, "extra": [extra("x-echt"), extra("x-verzonnen-api")]}
        records = [self.run_record(score, decisions) for score in (with_key, with_key, other_key, both, self.GOOD)]
        self.assertEqual([r["voldoet"] for r in records], [False, False, True, False, True])
        self.assertEqual(self.S.model_oordeel(records[:2] + records[4:]), "valt af")        # the two with the key fail, one complies

    def test_an_extra_without_a_decision_gives_open(self):
        records = [self.run_record(self.GOOD), self.run_record(self.GOOD), self.run_record({**self.GOOD, "extra": [extra("x-nieuw")]})]
        self.assertEqual([r["open"] for r in records], [False, False, True])
        self.assertEqual(self.S.model_oordeel(records), "open")
        records = [self.run_record({**self.GOOD, "extra": [extra("x-nieuw")]}, {"x-nieuw": "geldig"})] + records[:2]
        self.assertEqual(self.S.model_oordeel(records), "kandidaat")          # decided: the run counts again

    def test_a_judged_run_without_a_score_is_open_not_a_failure(self):
        record = self.run_record(None)
        self.assertEqual((record["voldoet"], record["open"]), (False, True))
        self.assertEqual(self.S.model_oordeel([record]), "open")

    def test_neither_control_a_candidate_gives_every_model_onbeslist_runtime(self):
        good = {"voldoet": True, "open": False}
        bad = {"voldoet": False, "open": False}
        models = {SONNET: [good, good, bad], SOL: [bad, bad, bad], QWEN: [good, good, good], GLM: [bad, bad, bad]}
        self.assertEqual(set(self.S.oordelen(models).values()), {"onbeslist: runtime"})
        self.assertEqual(set(self.S.oordelen(models)), set(models))
        # one control a candidate: every model keeps its own verdict
        models[SOL] = [good, good, good]
        self.assertEqual(self.S.oordelen(models), {SONNET: "twijfel", SOL: "kandidaat", QWEN: "kandidaat", GLM: "valt af"})
        # a control that has no runs at all is no candidate either; an open control is none yet
        self.assertEqual(set(self.S.oordelen({QWEN: [good, good, good]}).values()), {"onbeslist: runtime"})
        self.assertEqual(set(self.S.oordelen({SONNET: [good, good, {"voldoet": False, "open": True}], QWEN: [good] * 3}).values()),
                         {"onbeslist: runtime"})

    def test_the_two_controls_are_the_two_of_the_spec(self):
        self.assertEqual(tuple(self.S.CONTROLS), (SONNET, SOL))


class MaskTest(ScoreBase):
    def test_every_configuration_every_openrouter_model_and_every_family_word_is_masked(self):
        for label, model in OPENROUTER.items():
            for text in (label, model, label.upper(), f"Config {label}, model {model}."):
                with self.subTest(text):
                    masked = self.S.mask_identity(text)
                    self.assertNotIn(label.lower(), masked.lower())
                    self.assertNotIn(model.lower(), masked.lower())
                    self.assertIn("[model]", masked)
        for word in FAMILY_WORDS:
            with self.subTest(word):
                self.assertEqual(self.S.mask_identity(f"een {word.upper()} hier"), "een [model] hier")

    def test_a_digit_or_a_dash_does_not_save_a_family_word_but_a_letter_does(self):
        mask = self.S.mask_identity
        self.assertEqual(mask("Qwen3 en GPT-6 en glm5"), "[model]3 en [model]-6 en [model]5")
        self.assertEqual(mask("de oplossing en de console, absoluut en isolatie"), "de oplossing en de console, absoluut en isolatie")
        self.assertEqual(mask("Claude review"), "[model] review")
        self.assertEqual(mask("anthropic/claude-sonnet-5.5"), "[model]")

    def test_a_letter_on_either_side_keeps_a_word_whole_on_both_sides(self):
        # the lookbehind and the lookahead each hold one of these: without the first parasol would become para[model],
        # without the second solution would become [model]ution
        mask = self.S.mask_identity
        for word in ("solution", "solid", "parasol", "console", "isolatie", "absolute", "gptx", "xgpt", "opusje", "reopus", "kimix", "codexen"):
            with self.subTest(word):
                self.assertEqual(mask(word), word)
                self.assertEqual(mask(f"een {word}."), f"een {word}.")
        for text, masked in (("(sol)", "([model])"), ("sol-or", "[model]-or"), ("a sol, b", "a [model], b"), ("SOL", "[model]"), ("Sol.", "[model].")):
            with self.subTest(text):
                self.assertEqual(mask(text), masked)

    def test_families_outside_the_eight_are_masked_too_as_whole_words_in_any_case(self):
        mask = self.S.mask_identity
        for word in ("opus", "haiku", "codex", "gemini", "kimi", "z.ai", "z-ai"):
            for text in (word, word.upper(), word.capitalize()):
                with self.subTest(text):
                    self.assertEqual(mask(f"een {text} hier"), "een [model] hier")
        self.assertEqual(mask("Codex CLI en Gemini-2 en Kimi3"), "[model] CLI en [model]-2 en [model]3")
        self.assertEqual(mask("Z.ai/GLM-5.3"), "[model]/[model]-5.3")
        self.assertEqual(mask("zxai en z_ai"), "zxai en z_ai")                  # the dot is a dot, not any character

    def test_the_longest_name_goes_first_so_nothing_of_it_is_left_behind(self):
        self.assertEqual(self.S.mask_identity("gpt-6.1-sol-or en gpt-6.1-sol"), "[model] en [model]-6.1-[model]")
        self.assertEqual(self.S.mask_identity("openai/gpt-6.1-sol"), "[model]")


class SheetTest(ScoreBase):
    def sheets(self, *flags):
        status, stdout, stderr = self.run_main("sheets", self.out, *flags)
        self.assertEqual(status, 0, stderr)
        return stdout

    def test_a_sheet_per_run_that_is_judged_and_the_key_apart(self):
        self.put(QWEN, 1)
        self.put(QWEN, 2, "bench-result-limiet.json")
        self.put(QWEN, 3, "bench-result-benchfout.json")
        self.put(SONNET, 1)
        self.put(SONNET, 2, "bench-result-ongeldig.json")
        self.sheets()
        files = sorted(p.name for p in (self.out / "sheets").iterdir())
        self.assertEqual(len(files), 2)
        for name in files:
            self.assertRegex(name, r"^[0-9a-f]{8}\.md$")
        key = json.loads((self.out / "sheets-key.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(f"{sheet}.md" for sheet in key), files)
        self.assertEqual(sorted(path.split("/")[:2] for path in key.values()), sorted([[QWEN, "r1"], [SONNET, "r1"]]))
        for path in key.values():           # a path under <out>: the run directories may be copied elsewhere
            self.assertTrue((self.out / path / "bench-result.json").is_file(), path)

    def test_a_sheet_holds_the_report_and_the_summary_and_no_more(self):
        directory = self.put(QWEN, 1)
        result = json.loads((directory / "bench-result.json").read_text(encoding="utf-8"))
        self.sheets()
        text = self.sheet_text(QWEN, 1)
        self.assertIn(result["result"]["report_markdown"].strip(), text)
        self.assertIn(result["result"]["summary"], text)
        text = text.replace(self.sheet_ids()[(QWEN, 1)], "")          # the id is 8 random hex characters: it may hold "91500"
        for secret in (QWEN, result["runId"], directory.name, str(self.out), str(self.tmp), "costUsd", "0.12", "91500", "NO-GO", "provider_reported"):
            self.assertNotIn(secret, text)

    def test_a_blind_sheet_has_no_configuration_name_no_label_and_no_model_name(self):
        # every report below names its own configuration and model, in two cases; the sheets are made all in one go
        for n, (label, model) in enumerate(OPENROUTER.items(), start=1):
            text = f"Ik ben {model} ({label.upper()}). Gedraaid als {label}, via {model.upper()}."
            self.put(label, 1, over={"result": {**fixture_json(BEOORDEELD)["result"], "report_markdown": f"# Rapport\n\n{text}\n", "summary": text}})
        self.sheets()
        ids = self.sheet_ids()
        self.assertEqual(len(ids), 8)
        for (label, _), sheet in ids.items():
            text = (self.out / "sheets" / f"{sheet}.md").read_text(encoding="utf-8")
            with self.subTest(label):
                for name in (*OPENROUTER, *OPENROUTER.values(), *FAMILY_WORDS):
                    self.assertFalse(in_words(name, text), f"{name} in the sheet of {label}")
                self.assertIn("[model]", text)

    def test_a_model_that_names_itself_stays_blind(self):
        self.put(SONNET, 1, "bench-result-identity.json")
        self.sheets()
        text = self.sheet_text(SONNET, 1)
        for word in FAMILY_WORDS:
            self.assertFalse(in_words(word, text), word)
        for name in (*OPENROUTER, *OPENROUTER.values()):
            self.assertNotIn(name.lower(), text.lower())
        self.assertIn("# [model] review", text)
        self.assertIn("geen oplossing en geen console-melding", text)          # words that only contain a family word stay

    def test_the_fields_to_fill_are_on_one_fixed_line_and_only_f1_asks_for_f1(self):
        self.put(QWEN, 1)
        self.sheets()
        sheet = self.sheet_ids()[(QWEN, 1)]
        lines = [l for l in self.sheet_text(QWEN, 1).splitlines() if l.startswith('{"sheet"')]
        self.assertEqual(lines, ['{"sheet": "%s", "f1": "major|minor|nee", "f2": "major|minor|nee", "minors": ["M1".."M6"], '
                                 '"extra": [{"key": "...", "voorstel": "geldig|ongeldig", "reden": "..."}]}' % sheet])
        self.sheets("--only-f1")                  # the same sheet is written again, for f1 only
        self.assertEqual(self.sheet_ids()[(QWEN, 1)], sheet)
        text = self.sheet_text(QWEN, 1)
        self.assertEqual([l for l in text.splitlines() if l.startswith('{"sheet"')], ['{"sheet": "%s", "f1": "major|minor|nee"}' % sheet])
        instruction = text.split("## ")[0].replace(sheet, "")      # the id is 8 random hex characters: it may hold "f2"
        for field in ("f2", "minors", '"extra"'):
            self.assertNotIn(field, instruction)                   # the instruction above the first heading asks for nothing else

    def test_two_fresh_calls_on_the_same_runs_give_different_ids(self):
        for n in (1, 2, 3):
            self.put(QWEN, n)
            self.put(SONNET, n)
        self.sheets()
        first = set(self.sheet_ids().values())
        shutil.rmtree(self.out / "sheets")
        (self.out / "sheets-key.json").unlink()
        self.sheets()
        second = set(self.sheet_ids().values())
        self.assertEqual((len(first), len(second)), (6, 6))
        self.assertEqual(first & second, set())                  # six random ids of 32 bits each: a clash is a 1 in 100 million

    def test_the_ids_are_made_after_the_runs_are_shuffled_not_in_the_order_of_the_directories(self):
        # fixed stand-ins: the shuffle reverses, and uuid4 counts. Unshuffled, the first id would belong to the first run in order.
        from unittest import mock

        class Reversing:
            def shuffle(self, items):
                items.reverse()

        counter = iter(range(1, 100))

        def counting():
            return type("Id", (), {"hex": f"{next(counter):08x}" + "0" * 24})()

        for n in (1, 2):
            self.put(SONNET, n)
            self.put(QWEN, n)
        with mock.patch.object(self.S.random, "SystemRandom", Reversing), mock.patch.object(self.S.uuid, "uuid4", counting):
            self.sheets()
        self.assertEqual({sheet: run for run, sheet in self.sheet_ids().items()},
                         {"00000001": (QWEN, 2), "00000002": (QWEN, 1), "00000003": (SONNET, 2), "00000004": (SONNET, 1)})

    def test_the_sheet_sends_the_scorer_to_the_rubric_by_its_path_in_the_repo(self):
        self.put(QWEN, 1)
        self.sheets()
        self.assertIn("llm-bench/review_bench/cases/macsearch-idea263-spec-r5/rubric.md", self.sheet_text(QWEN, 1))
        self.assertTrue((HERE.parent.parent / "llm-bench/review_bench/cases/macsearch-idea263-spec-r5/rubric.md").is_file())

    def test_a_second_call_keeps_the_ids_and_adds_a_sheet_for_a_new_run(self):
        self.put(QWEN, 1)
        self.sheets()
        before = self.sheet_ids()
        self.put(SONNET, 1)
        self.sheets()
        after = self.sheet_ids()
        self.assertEqual(after[(QWEN, 1)], before[(QWEN, 1)])
        self.assertEqual(len(after), 2)
        self.assertEqual(len(list((self.out / "sheets").iterdir())), 2)

    def test_the_result_that_counts_is_the_one_of_the_selection_rule(self):
        self.put(QWEN, 1, "bench-result-benchfout.json", mtime=2_000_000_000)          # newer, but a benchfout
        kept = self.put(QWEN, 1, mtime=1_000_000_000)
        self.sheets()
        key = json.loads((self.out / "sheets-key.json").read_text(encoding="utf-8"))
        self.assertEqual(list(key.values()), [f"{QWEN}/r1/{kept.name}"])

    def test_nothing_judged_makes_no_sheet_and_says_so(self):
        self.put(QWEN, 1, "bench-result-benchfout.json")
        stdout = self.sheets()
        self.assertIn("geen beoordeelde runs", stdout)
        self.assertFalse(list((self.out / "sheets").glob("*.md")) if (self.out / "sheets").exists() else [])


class SelectionTest(ScoreBase):
    def selected(self, label="cfg-alfa", n=1):
        return self.S.collect(self.out)[(label, n)]

    def test_a_result_with_a_model_status_beats_a_newer_benchfout(self):
        for status_template in ("bench-result-limiet.json", "bench-result-ongeldig.json", BEOORDEELD):
            with self.subTest(status_template):
                shutil.rmtree(self.out, ignore_errors=True)
                model = self.put("cfg-alfa", 1, status_template, mtime=1_000_000_000)
                self.put("cfg-alfa", 1, "bench-result-benchfout.json", mtime=2_000_000_000)
                self.assertEqual(self.selected().directory, model)

    def test_otherwise_the_newest_by_mtime_and_a_tie_by_name(self):
        old = self.put("cfg-alfa", 1, "bench-result-benchfout.json", mtime=1_000_000_000)
        new = self.put("cfg-alfa", 1, "bench-result-not-probed.json", mtime=2_000_000_000)
        self.assertEqual(self.selected().directory, new)
        self.assertNotEqual(old, new)
        shutil.rmtree(self.out)
        first = self.put("cfg-alfa", 1, "bench-result-benchfout.json", mtime=1_500_000_000)
        second = self.put("cfg-alfa", 1, "bench-result-not-probed.json", mtime=1_500_000_000)
        self.assertEqual(self.selected().directory, max(first, second, key=lambda p: p.name))

    def test_among_model_statuses_the_newest_wins_too(self):
        self.put("cfg-alfa", 1, "bench-result-limiet.json", mtime=1_000_000_000)
        newer = self.put("cfg-alfa", 1, BEOORDEELD, mtime=2_000_000_000)
        self.assertEqual(self.selected().directory, newer)

    def test_every_run_n_of_a_label_is_its_own_run(self):
        self.put("cfg-alfa", 1)
        self.put("cfg-alfa", 2, "bench-result-benchfout.json")
        self.put("cfg-beta", 1)
        self.assertEqual(sorted(self.S.collect(self.out)), [("cfg-alfa", 1), ("cfg-alfa", 2), ("cfg-beta", 1)])

    def test_what_is_no_result_of_that_label_is_not_read(self):
        self.put("cfg-alfa", 1)
        stray = self.put("cfg-alfa", 2, over={"label": "cfg-beta"})                       # a result of another label
        (self.out / "cfg-alfa" / "r3" / "leeg").mkdir(parents=True)                         # a run directory without a result
        (self.out / "cfg-alfa" / "r4").mkdir()
        (self.out / "cfg-alfa" / "r4" / "bench-result.json").write_text("{}", encoding="utf-8")          # a file where a run directory goes
        (self.out / "cfg-alfa" / "r5").write_text("een bestand", encoding="utf-8")
        (self.out / "cfg-alfa" / "rook").mkdir()
        (self.out / "sheets").mkdir()
        (self.out / "skipped.json").write_text("[]", encoding="utf-8")
        self.assertEqual(sorted(self.S.collect(self.out)), [("cfg-alfa", 1)])
        self.assertTrue(stray.is_dir())

    def test_an_out_that_is_no_directory_is_an_error(self):
        with self.assertRaises(self.S.ScoreError):
            self.S.collect(self.tmp / "niet-er")


class ScoresFileTest(ScoreBase):
    KEY = {"aaaa0001": "cfg-alfa/r1/x", "aaaa0002": "cfg-alfa/r2/y", "aaaa0003": "cfg-alfa/r3/z"}

    def lines(self, *entries, raw=()):
        path = self.tmp / "scores.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in entries) + "".join(r + "\n" for r in raw), encoding="utf-8")
        return path

    def test_the_fixture_is_read_as_it_is_written(self):
        scores = self.S.load_scores(SCORE_FIXTURES / "scores.jsonl", self.KEY)
        self.assertEqual(sorted(scores), ["aaaa0001", "aaaa0002", "aaaa0003"])
        self.assertEqual(scores["aaaa0001"], {"f1": "major", "f2": "minor", "minors": ["M1", "M3"], "extra": []})
        self.assertEqual(scores["aaaa0003"]["minors"], ["M2", "M6"])          # a finding counts once: M2 twice is M2
        self.assertEqual([e["key"] for e in scores["aaaa0003"]["extra"]], ["x-verzonnen-api", "x-nog-niet-beslist"])

    def test_a_smoke_file_has_f1_only_and_the_main_file_has_to_have_all_four(self):
        scores = self.S.load_scores(SCORE_FIXTURES / "scores-only-f1.jsonl", self.KEY, only_f1=True)
        self.assertEqual(scores, {"aaaa0001": {"f1": "major"}, "aaaa0002": {"f1": "nee"}})
        with self.assertRaises(self.S.ScoreError) as raised:
            self.S.load_scores(SCORE_FIXTURES / "scores-only-f1.jsonl", self.KEY)
        self.assertIn("line 1", str(raised.exception))
        self.assertIn("f2", str(raised.exception))

    def test_a_line_that_cannot_be_used_is_refused_with_its_number_and_never_quoted(self):
        bad = {
            "a sheet that is not in the key": [grade("ffff9999")],
            "the same sheet twice": [grade("aaaa0001"), grade("aaaa0001")],
            "f1 outside the three": [grade("aaaa0001", f1="blocker")],
            "f2 missing": [{"sheet": "aaaa0001", "f1": "major", "minors": [], "extra": []}],
            "a minor outside M1-M6": [grade("aaaa0001", minors=["M7"])],
            "minors that is no list": [{**grade("aaaa0001"), "minors": "M1"}],
            "an extra without a proposal": [grade("aaaa0001", extra=[{"key": "x-a", "reden": "r"}])],
            "an extra with a proposal of its own": [grade("aaaa0001", extra=[extra("x-a", "misschien")])],
            "an extra without a key": [grade("aaaa0001", extra=[{"voorstel": "geldig", "reden": "r"}])],
            "an extra that is no object": [grade("aaaa0001", extra=["x-a"])],
        }
        for name, entries in bad.items():
            with self.subTest(name):
                with self.assertRaises(self.S.ScoreError) as raised:
                    self.S.load_scores(self.lines(*entries), self.KEY)
                self.assertRegex(str(raised.exception), r"line [12]")
        with self.assertRaises(self.S.ScoreError) as raised:
            self.S.load_scores(self.lines(grade("aaaa0001"), raw=["dit is geen json geheim-0123456789"]), self.KEY)
        self.assertIn("line 2", str(raised.exception))
        self.assertNotIn("geheim", str(raised.exception))
        with self.assertRaises(self.S.ScoreError):
            self.S.load_scores(self.tmp / "niet-er.jsonl", self.KEY)

    def test_blank_lines_are_skipped_and_an_empty_file_is_no_scores(self):
        path = self.tmp / "scores.jsonl"
        path.write_text("\n" + json.dumps(grade("aaaa0001")) + "\n\n", encoding="utf-8")
        self.assertEqual(list(self.S.load_scores(path, self.KEY)), ["aaaa0001"])
        path.write_text("", encoding="utf-8")
        self.assertEqual(self.S.load_scores(path, self.KEY), {})

    def test_decisions_are_geldig_or_ongeldig_per_key(self):
        self.assertEqual(self.S.load_decisions(SCORE_FIXTURES / "decisions.json"), {"x-temp-path-race": "geldig", "x-verzonnen-api": "ongeldig"})
        for text in ('["x"]', '{"x-a": "misschien"}', '{"x-a": true}', "geen json"):
            with self.subTest(text):
                path = self.tmp / "decisions.json"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(self.S.ScoreError):
                    self.S.load_decisions(path)
        with self.assertRaises(self.S.ScoreError):
            self.S.load_decisions(self.tmp / "niet-er.json")


class TraceTest(ScoreBase):
    def count(self, trace="trace.jsonl", run_id=FIXTURE_RUN_ID):
        return self.S.count_sources_doc(SCORE_FIXTURES / trace, run_id)

    def test_three_read_file_calls_on_the_source_of_which_two_with_an_offset_give_3_and_2(self):
        self.assertEqual(self.count(), (3, 2))

    def test_the_path_is_normalised_so_the_same_file_in_another_spelling_counts(self):
        # ./sources/doc, sources//doc, sources/../sources/doc, an absolute path in the root of this run, and arguments that are an object;
        # not: another run's root, an absolute path without a root, another file in the root
        self.assertEqual(self.count("trace-path-forms.jsonl"), (5, 3))

    def test_the_root_in_an_absolute_path_is_that_of_the_run_in_question(self):
        self.assertEqual(self.count("trace-path-forms.jsonl", "an-other-run"), (5, 2))
        self.assertEqual(self.count("trace-path-forms.jsonl", "onbekende-run"), (4, 2))

    def count_calls(self, *calls):
        trace = self.tmp / "trace.jsonl"
        trace.write_text("".join(json.dumps({"type": "tool_call", "name": "read_file", "arguments": json.dumps(c)}) + "\n" for c in calls), encoding="utf-8")
        return self.S.count_sources_doc(trace, "r")

    def test_a_call_is_limited_only_when_offset_or_limit_is_a_number_as_the_harness_pages(self):
        # agent-harness src/worker/task-tools.ts: `typeof args.offset === 'number'`: a key with null in it pages nothing
        self.assertEqual(self.count_calls({"path": "sources/doc", "limit": 5}, {"path": "sources/doc", "offset": None},
                                          {"path": "sources/doc", "offset": 0}, {"path": "sources/doc"}), (4, 2))

    def test_a_number_is_an_int_or_a_float_and_nothing_else(self):
        limited = [{"offset": 3}, {"limit": 5}, {"offset": 1.5}, {"offset": 3, "limit": None}, {"offset": None, "limit": 20}, {"offset": 0, "limit": 0}]
        unlimited = [{"offset": True}, {"limit": False}, {"limit": "5"}, {"offset": [5]}, {"offset": {"n": 1}}, {"offset": None, "limit": None},
                     {"offset": "", "limit": True}, {}]
        self.assertEqual(self.count_calls(*({"path": "sources/doc", **c} for c in limited + unlimited)), (len(limited) + len(unlimited), len(limited)))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs mkfifo")
    def test_a_trace_that_is_a_named_pipe_is_no_trace_and_does_not_hang(self):
        pipe = self.tmp / "trace.jsonl"
        os.mkfifo(pipe)
        self.assertIsNone(self.S.count_sources_doc(pipe, "r"))

    def test_no_trace_is_no_count_and_an_empty_trace_is_zero(self):
        self.assertIsNone(self.S.count_sources_doc(self.tmp / "niet-er.jsonl", "r"))
        (self.tmp / "leeg.jsonl").write_text("", encoding="utf-8")
        self.assertEqual(self.S.count_sources_doc(self.tmp / "leeg.jsonl", "r"), (0, 0))


class SmokeTest(ScoreBase):
    """score.py smoke: the gate of P2. Both results have to exist, none is a benchfout, and the control found the known MAJOR."""

    def smoke(self, qwen=BEOORDEELD, sonnet=BEOORDEELD, *, f1="major", sonnet_over=None, skipped=None, score=True):
        """Run both smoke runs (None: the run is missing), score them, and call smoke. Returns (status, stdout, stderr)."""
        if qwen:
            self.put(QWEN, 1, qwen)
        if sonnet:
            self.put(SONNET, 1, sonnet, over=sonnet_over)
        if skipped is not None:
            (self.out / "skipped.json").parent.mkdir(parents=True, exist_ok=True)
            (self.out / "skipped.json").write_text(json.dumps(skipped), encoding="utf-8")
        self.out.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.run_main("sheets", self.out, "--only-f1")[0], 0)
        ids = self.sheet_ids() if (self.out / "sheets-key.json").exists() else {}
        entries = [{"sheet": sheet, "f1": f1 if label == SONNET else "nee"} for (label, _), sheet in ids.items()] if score else []
        self.write_scores(self.tmp / "scores.jsonl", entries)
        return self.run_main("smoke", self.out, "--scores", self.tmp / "scores.jsonl")

    def test_both_present_and_through(self):
        status, stdout, stderr = self.smoke()
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("rookproef: door", stdout)
        self.assertIn(f"{SONNET} r1: status=beoordeeld outcome=succeeded verdict=NO-GO f1=major", stdout)
        self.assertIn(f"{QWEN} r1: status=beoordeeld outcome=succeeded verdict=NO-GO f1=nee", stdout)

    def test_qwen_missing_after_a_rejected_preflight_is_a_stop(self):
        status, stdout, _ = self.smoke(qwen=None, skipped=[{"label": QWEN, "run": 1, "reason": "preflight afgewezen: HTTP 400: nee"}])
        self.assertEqual(status, 1)
        self.assertIn("rookproef: stop", stdout)
        self.assertNotIn("rookproef: door", stdout)
        self.assertIn(f"{QWEN}: geen resultaat", stdout)
        self.assertIn("preflight afgewezen", stdout)

    def test_sonnet_missing_is_a_stop(self):
        status, stdout, _ = self.smoke(sonnet=None)
        self.assertEqual(status, 1)
        self.assertIn("rookproef: stop", stdout)
        self.assertIn(f"{SONNET}: geen resultaat", stdout)

    def test_a_benchfout_of_either_is_a_stop(self):
        for qwen, sonnet in (("bench-result-benchfout.json", BEOORDEELD), (BEOORDEELD, "bench-result-benchfout.json"),
                             ("bench-result-not-probed.json", BEOORDEELD)):
            with self.subTest(qwen=qwen, sonnet=sonnet):
                shutil.rmtree(self.out, ignore_errors=True)
                status, stdout, _ = self.smoke(qwen, sonnet)
                self.assertEqual(status, 1)
                self.assertIn("rookproef: stop", stdout)
                self.assertIn("benchfout", stdout)

    def test_a_limit_or_an_invalid_result_of_qwen_is_model_behaviour_and_goes_through(self):
        for qwen in ("bench-result-limiet.json", "bench-result-ongeldig.json"):
            with self.subTest(qwen):
                shutil.rmtree(self.out, ignore_errors=True)
                status, stdout, _ = self.smoke(qwen)
                self.assertEqual(status, 0, stdout)
                self.assertIn("rookproef: door", stdout)

    def test_sonnet_has_to_be_judged_succeeded_no_go_and_f1_major(self):
        no_go_gone = {"result": {**fixture_json(BEOORDEELD)["result"], "review": {**fixture_json(BEOORDEELD)["result"]["review"], "verdict": "GO"}}}
        failed = {"result": {**fixture_json(BEOORDEELD)["result"], "outcome": "failed"}}
        cases = {"f1 minor": dict(f1="minor"), "f1 nee": dict(f1="nee"), "verdict GO": dict(sonnet_over=no_go_gone),
                 "outcome failed": dict(sonnet_over=failed), "status limiet": dict(sonnet="bench-result-limiet.json"),
                 "status resultaat_ongeldig": dict(sonnet="bench-result-ongeldig.json"), "f1 not scored": dict(score=False)}
        for name, kw in cases.items():
            with self.subTest(name):
                shutil.rmtree(self.out, ignore_errors=True)
                status, stdout, _ = self.smoke(**kw)
                self.assertEqual(status, 1, stdout)
                self.assertIn("rookproef: stop", stdout)

    def test_the_selection_rule_applies_a_model_status_beats_a_newer_benchfout(self):
        self.put(SONNET, 1, "bench-result-benchfout.json", mtime=2_000_000_000)
        self.put(SONNET, 1, mtime=1_000_000_000)
        status, stdout, _ = self.smoke(sonnet=None)         # qwen is put by smoke
        self.assertEqual(status, 0, stdout)

    def test_a_repeated_benchfout_next_to_the_result_that_counts_is_said_and_changes_no_gate(self):
        self.put(QWEN, 1, "bench-result-benchfout.json", mtime=1_000_000_000)
        self.put(SONNET, 1, "bench-result-not-probed.json", mtime=1_000_000_000)
        self.put(SONNET, 1, "bench-result-benchfout.json", mtime=1_100_000_000)
        self.put(SONNET, 1, "bench-result-limiet.json", mtime=900_000_000)          # an older model status is no benchfout: not counted
        status, stdout, _ = self.smoke()                  # the judged qwen counts over its benchfout; sonnet is judged too, over two
        self.assertEqual(status, 0, stdout)
        lines = stdout.splitlines()
        self.assertIn("rookproef: door", lines)
        qwen_line = lines.index(f"{QWEN} r1: status=beoordeeld outcome=succeeded verdict=NO-GO f1=nee")
        self.assertEqual(lines[qwen_line + 1], f"{QWEN} r1: nog 1 benchfout naast het resultaat dat telt")
        sonnet_line = lines.index(f"{SONNET} r1: status=beoordeeld outcome=succeeded verdict=NO-GO f1=major")
        self.assertEqual(lines[sonnet_line + 1], f"{SONNET} r1: nog 2 benchfouten naast het resultaat dat telt")
        self.assertEqual(sum("naast het resultaat dat telt" in l for l in lines), 2)

    def test_a_benchfout_that_counts_over_an_older_one_is_said_and_the_gate_still_stops(self):
        self.put(SONNET, 1, "bench-result-benchfout.json", mtime=1_000_000_000)
        self.put(SONNET, 1, "bench-result-benchfout.json", mtime=1_100_000_000)
        status, stdout, _ = self.smoke(sonnet=None)
        self.assertEqual(status, 1)
        self.assertIn(f"{SONNET} r1: nog 1 benchfout naast het resultaat dat telt", stdout.splitlines())
        self.assertTrue(stdout.rstrip().endswith("rookproef: stop"))

    def test_no_repeat_no_extra_line(self):
        status, stdout, _ = self.smoke()
        self.assertEqual(status, 0)
        self.assertNotIn("naast het resultaat dat telt", stdout)

    def test_without_a_judged_run_there_is_no_scores_file_and_smoke_is_a_stop_not_an_error(self):
        self.put(QWEN, 1, "bench-result-benchfout.json")
        self.put(SONNET, 1, "bench-result-limiet.json")
        self.assertEqual(self.run_main("sheets", self.out, "--only-f1")[0], 0)          # nothing judged: no sheet, no key
        self.assertFalse((self.out / "sheets-key.json").exists())
        status, stdout, stderr = self.run_main("smoke", self.out, "--scores", self.tmp / "niet-er.jsonl")
        self.assertEqual((status, stderr), (1, ""))
        self.assertIn(f"{QWEN} r1: status=benchfout", stdout)
        self.assertIn(f"{SONNET} r1: status=limiet", stdout)
        self.assertTrue(stdout.rstrip().endswith("rookproef: stop"), stdout)

    def test_no_results_and_no_scores_file_is_a_stop_too(self):
        self.out.mkdir()
        status, stdout, _ = self.run_main("smoke", self.out, "--scores", self.tmp / "niet-er.jsonl")
        self.assertEqual(status, 1)
        self.assertIn(f"{QWEN}: geen resultaat", stdout)
        self.assertTrue(stdout.rstrip().endswith("rookproef: stop"), stdout)

    def test_a_scores_file_that_is_there_but_garbled_stays_an_error(self):
        self.put(QWEN, 1)
        self.put(SONNET, 1)
        self.run_main("sheets", self.out, "--only-f1")
        (self.tmp / "scores.jsonl").write_text("dit is geen json\n", encoding="utf-8")
        status, stdout, stderr = self.run_main("smoke", self.out, "--scores", self.tmp / "scores.jsonl")
        self.assertEqual(status, 2)
        self.assertIn("line 1", stderr)
        self.assertNotIn("rookproef", stdout)
        (self.tmp / "scores.jsonl").unlink()
        (self.tmp / "scores.jsonl").mkdir()                                     # a directory is no file to treat as 'no scores'
        self.assertEqual(self.run_main("smoke", self.out, "--scores", self.tmp / "scores.jsonl")[0], 2)

    def test_a_judged_sonnet_without_a_scores_file_is_a_stop_on_f1(self):
        self.put(QWEN, 1)
        self.put(SONNET, 1)
        self.run_main("sheets", self.out, "--only-f1")
        status, stdout, _ = self.run_main("smoke", self.out, "--scores", self.tmp / "niet-er.jsonl")
        self.assertEqual(status, 1)
        self.assertIn("f1 ontbreekt", stdout)

    def test_a_scores_file_that_does_not_fit_the_key_is_an_error_not_a_stop(self):
        self.put(QWEN, 1)
        self.put(SONNET, 1)
        self.run_main("sheets", self.out, "--only-f1")
        self.write_scores(self.tmp / "scores.jsonl", [{"sheet": "ffff9999", "f1": "major"}])
        status, stdout, stderr = self.run_main("smoke", self.out, "--scores", self.tmp / "scores.jsonl")
        self.assertEqual(status, 2)
        self.assertNotIn("rookproef", stdout)


class ReportBase(ScoreBase):
    """score.py report over a directory of runs of the driver's layout. It holds no test."""

    DATE = "2026-10-20"

    def setUp(self):
        super().setUp()
        self.scores = self.tmp / "scores.jsonl"
        self.decisions = self.tmp / "decisions.json"
        self.decisions.write_text("{}", encoding="utf-8")
        self.ledger = self.tmp / "ledger.jsonl"
        self.ledger.write_text("", encoding="utf-8")
        self.preflight = self.tmp / "preflight.json"
        self.preflight.write_text("{}", encoding="utf-8")
        self.results = self.tmp / "results"

    def preflight_ok(self, *labels, rejected=None):
        entries = {label: {"ok": True, "reason": None} for label in labels}
        entries.update({label: {"ok": False, "reason": reason} for label, reason in (rejected or {}).items()})
        self.preflight.write_text(json.dumps(entries), encoding="utf-8")

    def score_runs(self, grades):
        """Make the sheets and write scores.jsonl: grades is {(label, n): grade fields}; a judged run that is not in it is left unscored."""
        self.assertEqual(self.run_main("sheets", self.out)[0], 0)
        ids = self.sheet_ids()
        self.write_scores(self.scores, [grade(ids[run], **fields) for run, fields in grades.items()])

    def report(self, models, *, runs=3, extra_args=(), date=None):
        """(status, stdout, stderr, the text of the report or None)."""
        status, stdout, stderr = self.run_main("report", self.out, "--scores", self.scores, "--decisions", self.decisions, "--ledger", self.ledger,
                                               "--date", date or self.DATE, "--preflight", self.preflight, "--models", *models, "--runs", runs,
                                               "--results-dir", self.results, *extra_args)
        path = self.results / f"review-bench-{date or self.DATE}.md"
        return status, stdout, stderr, path.read_text(encoding="utf-8") if path.exists() else None

    @staticmethod
    def section(text, heading):
        """The lines under '## heading' up to the next '## '."""
        lines = text.splitlines()
        start = lines.index(f"## {heading}")
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        return lines[start + 1:end]

    @staticmethod
    def rows(lines, label):
        return [l for l in lines if l.startswith(f"| {label}")]

    def cells(self, line):
        return [c.strip() for c in line.strip().strip("|").split("|")]


class ReportTest(ReportBase):
    def three(self, label, *templates, **kw):
        for n, template in enumerate(templates, start=1):
            if template:
                self.put(label, n, template, **kw)

    def populate_comparison(self):
        """sonnet 3/3, qwen 2/3, flash 1/3, as the grades below say; sol and glm are not run."""
        self.three(SONNET, BEOORDEELD, BEOORDEELD, BEOORDEELD)
        self.three(QWEN, BEOORDEELD, BEOORDEELD, BEOORDEELD)
        self.three(FLASH, BEOORDEELD, BEOORDEELD, BEOORDEELD)
        self.score_runs({
            (SONNET, 1): {}, (SONNET, 2): {}, (SONNET, 3): {},
            (QWEN, 1): {}, (QWEN, 2): {}, (QWEN, 3): dict(f1="minor", f2="major"),
            (FLASH, 1): {}, (FLASH, 2): dict(f1="nee"), (FLASH, 3): dict(f1="minor"),
        })
        self.preflight_ok(SONNET, QWEN, FLASH)

    def test_the_report_gives_every_model_its_verdict_and_the_runs_that_comply(self):
        self.populate_comparison()
        status, _, stderr, text = self.report([SONNET, QWEN, FLASH])
        self.assertEqual(status, 0, stderr)
        table = self.section(text, "Oordeel per model")
        sonnet, qwen, flash = (self.cells(self.rows(table, label)[0]) for label in (SONNET, QWEN, FLASH))
        self.assertEqual((sonnet[1], sonnet[2]), ("kandidaat", "3/3"))
        self.assertEqual((qwen[1], qwen[2]), ("twijfel", "2/3"))
        self.assertEqual((flash[1], flash[2]), ("valt af", "1/3"))
        self.assertEqual(qwen[4:6], ["major / major / minor", "nee / nee / major"])          # F1 and F2 per run
        self.assertEqual(qwen[3], "NO-GO / NO-GO / NO-GO")

    def test_neither_control_a_candidate_gives_every_row_onbeslist_runtime(self):
        self.populate_comparison()
        self.put(SOL, 1)
        self.score_runs({(SONNET, 1): dict(f1="minor"), (SONNET, 2): {}, (SONNET, 3): {}, (QWEN, 1): {}, (QWEN, 2): {}, (QWEN, 3): {},
                         (FLASH, 1): {}, (FLASH, 2): {}, (FLASH, 3): {}, (SOL, 1): {}})
        self.preflight_ok(SONNET, QWEN, FLASH, SOL)
        status, _, stderr, text = self.report([SONNET, SOL, QWEN, FLASH])
        self.assertEqual(status, 0, stderr)
        table = self.section(text, "Oordeel per model")
        for label in (SONNET, SOL, QWEN, FLASH):
            self.assertEqual(self.cells(self.rows(table, label)[0])[1], "onbeslist: runtime", label)
        self.assertIn("onbeslist: runtime", "\n".join(self.section(text, "Grenzen en vervolg")))

    def test_an_extra_without_a_decision_is_open_and_a_decision_closes_it(self):
        self.populate_comparison()
        ids = self.sheet_ids()
        self.write_scores(self.scores, [grade(ids[(label, n)], **({"extra": [extra("x-temp-path-race")]} if (label, n) == (QWEN, 2) else {}))
                                        for label in (SONNET, QWEN, FLASH) for n in (1, 2, 3)])
        status, _, stderr, text = self.report([SONNET, QWEN, FLASH])
        self.assertEqual(status, 0, stderr)
        row = self.cells(self.rows(self.section(text, "Oordeel per model"), QWEN)[0])
        self.assertEqual(row[1], "open")
        self.assertIn("x-temp-path-race (open)", row[-1])
        self.decisions.write_text(json.dumps({"x-temp-path-race": "ongeldig"}), encoding="utf-8")
        _, _, _, text = self.report([SONNET, QWEN, FLASH])
        row = self.cells(self.rows(self.section(text, "Oordeel per model"), QWEN)[0])
        self.assertEqual((row[1], row[2]), ("twijfel", "2/3"))          # run 2 fails on the invalid extra, the other two comply
        self.assertIn("x-temp-path-race (ongeldig)", row[-1])

    def test_an_expected_run_that_never_ran_still_has_a_row_and_does_not_comply(self):
        self.populate_comparison()
        status, _, _, text = self.report([SONNET, QWEN, FLASH, GLM])
        self.assertEqual(status, 0)
        glm = self.cells(self.rows(self.section(text, "Oordeel per model"), GLM)[0])
        self.assertEqual((glm[1], glm[2]), ("valt af (niet gedraaid: niet gestart)", "0/3"))          # the verdict word is still valt af

    def test_the_minors_are_the_mean_of_the_scored_runs_and_cost_is_mean_and_max_of_those_with_an_amount(self):
        for n, cost in enumerate((0.10, 0.20, None), start=1):
            usage = {k: v for k, v in fixture_json(BEOORDEELD)["usage"].items() if k != "costUsd"}
            if cost is not None:
                usage["costUsd"] = cost
            self.put(QWEN, n, over={"usage": usage, "peakInputTokens": 50000 + n * 1000, "durationMs": 10000 * n, "turns": 10 * n})
        self.score_runs({(QWEN, 1): dict(minors=["M1", "M2"]), (QWEN, 2): dict(minors=["M3"]), (QWEN, 3): dict(minors=[])})
        self.preflight_ok(QWEN)
        status, _, _, text = self.report([QWEN])
        self.assertEqual(status, 0)
        self.assertEqual(self.cells(self.rows(self.section(text, "Oordeel per model"), QWEN)[0])[6], "1,0")
        b = self.cells(self.rows(self.section(text, "Kosten, tokens, context en tijd"), QWEN)[0])
        self.assertEqual(b[1:3], ["$0,1500", "$0,2000"])           # a missing amount is no zero
        self.assertIn("53000 / 131072", b[4])                       # peakInputTokens next to the window
        self.assertEqual(b[5], "20,0 s")
        self.assertEqual(b[6], "20,0")

    def test_every_expected_run_that_is_not_judged_has_the_first_reason_that_fits(self):
        self.three("cfg-a", "bench-result-benchfout.json")                                             # preflight rejected: wins over the benchfout
        self.three("cfg-b", "bench-result-not-probed.json", over={"benchError": "CONFIGURATION_NOT_PROBED: geen aanvaarde probe voor cfg-b"})
        # ... r1 is not probed from its benchError, r2 and r3 from skipped.json
        self.three("cfg-c", "bench-result-benchfout.json", "bench-result-limiet.json", "bench-result-ongeldig.json")
        self.three("cfg-d")                                                                             # no result: budget, stop, nothing
        self.three("cfg-e", BEOORDEELD, BEOORDEELD, BEOORDEELD)
        (self.out / "skipped.json").write_text(json.dumps([
            {"label": "cfg-b", "run": 2, "reason": "niet geprobed: geen aanvaarde probe voor cfg-b"},
            {"label": "cfg-b", "run": 3, "reason": "niet geprobed: geen aanvaarde probe voor cfg-b"},
            {"label": "cfg-d", "run": 1, "reason": "budget bereikt"}, {"label": "cfg-d", "run": 2, "reason": "gestopt (stopvlag)"}]), encoding="utf-8")
        self.preflight_ok("cfg-b", "cfg-c", "cfg-d", "cfg-e", rejected={"cfg-a": "HTTP 400: model niet beschikbaar"})
        self.score_runs({("cfg-e", n): {} for n in (1, 2, 3)})
        status, _, stderr, text = self.report(["cfg-a", "cfg-b", "cfg-c", "cfg-d", "cfg-e"])
        self.assertEqual(status, 0, stderr)
        lines = self.section(text, "Runs zonder oordeel")
        reasons = {tuple(self.cells(l)[:2]): self.cells(l)[2] for l in lines if l.startswith("| cfg-")}
        self.assertEqual(len(reasons), 12)
        for n in (1, 2, 3):
            self.assertEqual(reasons[("cfg-a", str(n))], "preflight afgewezen: HTTP 400: model niet beschikbaar")
            self.assertTrue(reasons[("cfg-b", str(n))].startswith("niet geprobed: "), reasons[("cfg-b", str(n))])
        self.assertIn("geen aanvaarde probe voor cfg-b", reasons[("cfg-b", "1")])
        self.assertEqual(reasons[("cfg-c", "1")], "benchfout: MODEL_ERROR")
        self.assertEqual(reasons[("cfg-c", "2")], "limiet: COST_LIMIT_EXCEEDED")
        self.assertEqual(reasons[("cfg-c", "3")], "resultaat_ongeldig: REVIEW_RESULT_INVALID")
        self.assertEqual([reasons[("cfg-d", str(n))] for n in (1, 2, 3)], ["budget bereikt", "gestopt (stopvlag)", "niet gestart"])
        self.assertFalse([k for k in reasons if k[0] == "cfg-e"])
        self.assertIn("3 van 15 verwachte runs beoordeeld", text)

    def test_the_reason_from_skipped_json_is_used_when_the_preflight_file_has_no_word_about_it(self):
        self.out.mkdir(parents=True)                                # no run left a directory
        (self.out / "skipped.json").write_text(json.dumps([{"label": "cfg-a", "run": n, "reason": "preflight afgewezen: HTTP 429: te druk"}
                                                           for n in (1, 2, 3)]), encoding="utf-8")
        self.preflight_ok()
        self.write_scores(self.scores, [])
        status, _, stderr, text = self.report(["cfg-a"])
        self.assertEqual(status, 0, stderr)
        reasons = [self.cells(l)[2] for l in self.section(text, "Runs zonder oordeel") if l.startswith("| cfg-a")]
        self.assertEqual(reasons, ["preflight afgewezen: HTTP 429: te druk"] * 3)

    def test_a_result_with_a_model_status_is_not_called_a_rejected_preflight(self):
        self.three("cfg-a", "bench-result-limiet.json")
        self.preflight_ok(rejected={"cfg-a": "HTTP 400: later afgewezen"})
        self.write_scores(self.scores, [])
        _, _, _, text = self.report(["cfg-a"])
        reasons = [self.cells(l)[2] for l in self.section(text, "Runs zonder oordeel") if l.startswith("| cfg-a")]
        self.assertEqual(reasons[0], "limiet: COST_LIMIT_EXCEEDED")
        self.assertEqual(reasons[1:], ["preflight afgewezen: HTTP 400: later afgewezen"] * 2)

    def test_the_first_comparison_sets_the_open_models_against_the_controls(self):
        self.populate_comparison()          # sonnet 3 of 3, qwen 2 of 3, flash 1 of 3
        ids = self.sheet_ids()
        # qwen finds F1 as major in all three runs, but one of them has an extra that JP declares invalid: 2 of 3 comply, 3 of 3 hit
        self.write_scores(self.scores, [grade(ids[(label, n)], **({"extra": [extra("x-verzonnen-api")]} if (label, n) == (QWEN, 1) else {}))
                                        for label in (SONNET, QWEN) for n in (1, 2, 3)]
                          + [grade(ids[(FLASH, n)], f1=f1) for n, f1 in ((1, "major"), (2, "nee"), (3, "minor"))])
        self.decisions.write_text(json.dumps({"x-verzonnen-api": "ongeldig"}), encoding="utf-8")
        status, _, stderr, text = self.report([SONNET, QWEN, FLASH, GLM])
        self.assertEqual(status, 0, stderr)
        lines = self.section(text, "Eerste vergelijking: open modellen tegenover de harness-controles")
        rows = [self.cells(l) for l in lines if l.startswith("| ") and not l.startswith("| ---")]
        self.assertEqual(rows[0], ["Groep", "Model", "Oordeel", "Voldoet", "F1 als major gevonden"])
        self.assertEqual(rows[1:], [
            ["harness-controle", SONNET, "kandidaat", "3/3", "3/3"],
            ["open model", QWEN, "twijfel", "2/3", "3/3"],
            ["open model", FLASH, "valt af", "1/3", "1/3"],
            ["open model", GLM, "valt af (niet gedraaid: niet gestart)", "0/3", "0/3"]])
        joined = "\n".join(lines)
        self.assertIn("Geldigheid van de bench: in orde", joined)
        self.assertIn(f"Controle niet in --models: {SOL}.", joined)
        self.assertLess(text.index("## Oordeel per model"), text.index("## Eerste vergelijking: open modellen tegenover de harness-controles"))
        self.assertLess(text.index("## Eerste vergelijking: open modellen tegenover de harness-controles"), text.index("## Kosten, tokens, context en tijd"))

    def test_the_first_comparison_carries_the_runtime_verdict_and_the_validity_line(self):
        self.populate_comparison()
        self.put(SOL, 1)
        self.score_runs({(SONNET, 1): dict(f1="minor"), (SONNET, 2): {}, (SONNET, 3): {}, (QWEN, 1): {}, (QWEN, 2): {}, (QWEN, 3): {},
                         (FLASH, 1): {}, (FLASH, 2): {}, (FLASH, 3): {}, (SOL, 1): {}})
        self.preflight_ok(SONNET, QWEN, FLASH, SOL)
        _, _, _, text = self.report([SONNET, SOL, QWEN, FLASH])
        lines = self.section(text, "Eerste vergelijking: open modellen tegenover de harness-controles")
        self.assertEqual({self.cells(l)[2] for l in lines if l.startswith("| ") and not l.startswith("| ---") and self.cells(l)[0] != "Groep"},
                         {"onbeslist: runtime"})
        self.assertIn("niet aangetoond", "\n".join(lines))
        self.assertNotIn("Controle niet in --models", "\n".join(lines))

    def test_the_groups_of_the_comparison_are_a_fixed_mapping_of_the_eight_configurations(self):
        # spec 4.6, line 59: the five existing open models, gpt-6-luna as the proprietary one, and the two controls
        S = self.S
        self.assertEqual(S.OPEN_MODELS, (QWEN, FLASH, PRO, GLM, MINIMAX))
        self.assertEqual(S.PROPRIETARY, (LUNA,))
        self.assertEqual(tuple(S.CONTROLS), (SONNET, SOL))
        self.assertEqual({label: S.model_group(label) for label in OPENROUTER},
                         {QWEN: "open model", FLASH: "open model", PRO: "open model", GLM: "open model", MINIMAX: "open model",
                          LUNA: "propriëtair, geen controle", SONNET: "harness-controle", SOL: "harness-controle"})
        self.assertEqual(S.model_group("cfg-iets-anders"), "overig")

    def test_the_first_comparison_groups_open_proprietary_controls_and_others(self):
        models = [LUNA, "cfg-other", QWEN, SOL, MINIMAX, SONNET, PRO]               # not in the order of the groups
        self.out.mkdir()
        self.preflight_ok()
        self.write_scores(self.scores, [])
        status, _, stderr, text = self.report(models, runs=1)
        self.assertEqual(status, 0, stderr)
        rows = [self.cells(l)[:2] for l in self.section(text, "Eerste vergelijking: open modellen tegenover de harness-controles")
                if l.startswith("| ") and not l.startswith("| ---")]
        self.assertEqual(rows, [["Groep", "Model"],
                                ["harness-controle", SOL], ["harness-controle", SONNET],                       # within a group, the order of --models
                                ["open model", QWEN], ["open model", MINIMAX], ["open model", PRO],
                                ["propriëtair, geen controle", LUNA],
                                ["overig", "cfg-other"]])

    def test_a_model_that_never_ran_keeps_valt_af_and_the_main_table_says_why(self):
        self.three(SONNET, BEOORDEELD, BEOORDEELD, BEOORDEELD)
        self.three("cfg-ran", "bench-result-limiet.json", "bench-result-limiet.json", "bench-result-limiet.json")        # ran, to its limit
        self.three("cfg-bad", "bench-result-benchfout.json", "bench-result-benchfout.json", "bench-result-benchfout.json")      # ran, failed
        self.three("cfg-np", *["bench-result-not-probed.json"] * 3)               # a benchfout that never reached a model
        self.three("cfg-late", BEOORDEELD, None, None)                           # r2 and r3 never started
        (self.out / "skipped.json").write_text(json.dumps(
            [{"label": "cfg-budget", "run": n, "reason": "budget bereikt"} for n in (1, 2, 3)]
            + [{"label": "cfg-stop", "run": n, "reason": "gestopt na tweede benchfout op cfg-stop"} for n in (1, 2, 3)]), encoding="utf-8")
        self.preflight_ok(SONNET, "cfg-ran", "cfg-bad", "cfg-np", "cfg-late", "cfg-budget", "cfg-stop", rejected={"cfg-pre": "HTTP 400: nee"})
        self.score_runs({(SONNET, n): {} for n in (1, 2, 3)} | {("cfg-late", 1): dict(f1="nee")})
        status, _, stderr, text = self.report([SONNET, "cfg-ran", "cfg-bad", "cfg-np", "cfg-late", "cfg-budget", "cfg-stop", "cfg-pre", "cfg-none"])
        self.assertEqual(status, 0, stderr)
        verdicts = {self.cells(l)[0]: self.cells(l)[1:3] for l in self.section(text, "Oordeel per model") if l.startswith("| cfg-")}
        self.assertEqual(verdicts, {
            "cfg-ran": ["valt af", "0/3"], "cfg-bad": ["valt af", "0/3"], "cfg-late": ["valt af", "0/3"],              # these did run: no note
            "cfg-np": ["valt af (niet gedraaid: niet geprobed)", "0/3"],
            "cfg-budget": ["valt af (niet gedraaid: budget bereikt)", "0/3"],
            "cfg-stop": ["valt af (niet gedraaid: gestopt na tweede benchfout op cfg-stop)", "0/3"],
            "cfg-pre": ["valt af (niet gedraaid: preflight afgewezen)", "0/3"],
            "cfg-none": ["valt af (niet gedraaid: niet gestart)", "0/3"]})

    def test_a_note_on_a_never_ran_model_also_follows_the_runtime_verdict(self):
        self.three(QWEN, BEOORDEELD, BEOORDEELD, BEOORDEELD)
        self.score_runs({(QWEN, n): {} for n in (1, 2, 3)})
        self.preflight_ok(QWEN, rejected={FLASH: "HTTP 400: nee"})
        _, _, _, text = self.report([QWEN, FLASH])                  # no control at all: onbeslist: runtime for everyone
        cells = {self.cells(l)[0]: self.cells(l)[1] for l in self.section(text, "Oordeel per model") if l.startswith("| ")}
        self.assertEqual(cells[FLASH], "onbeslist: runtime (niet gedraaid: preflight afgewezen)")
        self.assertEqual(cells[QWEN], "onbeslist: runtime")

    def test_a_rejected_preflight_wins_over_not_probed_whichever_file_says_which(self):
        # a: the result is a not-probed benchfout and the preflight file rejects. b: nothing ran, skipped.json says niet geprobed and the
        # preflight file rejects. c: the result is not-probed and skipped.json says preflight afgewezen (the preflight file is ok).
        # d: nothing ran, skipped.json says niet geprobed and the preflight file is ok.
        self.three("cfg-a", "bench-result-not-probed.json", over={"benchError": "CONFIGURATION_NOT_PROBED: geen probe voor cfg-a"})
        self.three("cfg-c", "bench-result-not-probed.json", over={"benchError": "CONFIGURATION_NOT_PROBED: geen probe voor cfg-c"})
        (self.out / "skipped.json").write_text(json.dumps([
            {"label": "cfg-b", "run": 1, "reason": "niet geprobed: geen probe voor cfg-b"},
            {"label": "cfg-c", "run": 1, "reason": "preflight afgewezen: HTTP 429: uit skipped.json"},
            {"label": "cfg-d", "run": 1, "reason": "niet geprobed: geen probe voor cfg-d"}]), encoding="utf-8")
        self.preflight_ok("cfg-c", "cfg-d", rejected={"cfg-a": "HTTP 400: uit de preflight", "cfg-b": "HTTP 400: ook uit de preflight"})
        self.write_scores(self.scores, [])
        status, _, stderr, text = self.report(["cfg-a", "cfg-b", "cfg-c", "cfg-d"], runs=1)
        self.assertEqual(status, 0, stderr)
        reasons = {self.cells(l)[0]: self.cells(l)[2] for l in self.section(text, "Runs zonder oordeel") if l.startswith("| cfg-")}
        self.assertEqual(reasons, {
            "cfg-a": "preflight afgewezen: HTTP 400: uit de preflight",
            "cfg-b": "preflight afgewezen: HTTP 400: ook uit de preflight",
            "cfg-c": "preflight afgewezen: HTTP 429: uit skipped.json",
            "cfg-d": "niet geprobed: geen probe voor cfg-d"})

    def test_an_aborted_run_is_a_stop_not_a_bench_defect(self):
        # a run stopped by Ctrl-C: benchError afgebroken, and an error HARNESS_ERROR "aborted" (agent-harness src/run.ts)
        self.three(QWEN, "bench-result-benchfout.json", over={"benchError": "afgebroken", "error": {"code": "HARNESS_ERROR", "message": "aborted"}})
        self.three("cfg-b", "bench-result-benchfout.json", over={"error": {"code": "HARNESS_ERROR", "message": "kapot"}})      # a real harness error
        self.three("cfg-c", "bench-result-benchfout.json", over={"benchError": "afgebroken afgebroken"})                       # only starts like it
        self.preflight_ok(QWEN, "cfg-b", "cfg-c")
        self.write_scores(self.scores, [])
        status, _, stderr, text = self.report([QWEN, "cfg-b", "cfg-c"], runs=1)
        self.assertEqual(status, 0, stderr)
        reasons = {self.cells(l)[0]: self.cells(l)[2] for l in self.section(text, "Runs zonder oordeel") if l.startswith("| ")}
        self.assertEqual(reasons[QWEN], "gestopt (afgebroken)")
        self.assertEqual(reasons["cfg-b"], "benchfout: HARNESS_ERROR")
        self.assertEqual(reasons["cfg-c"], "benchfout: MODEL_ERROR")                  # a benchError that only starts like afgebroken

    def test_a_rejected_preflight_still_wins_over_an_aborted_run(self):
        self.three(QWEN, "bench-result-benchfout.json", over={"benchError": "afgebroken", "error": {"code": "HARNESS_ERROR", "message": "aborted"}})
        self.preflight_ok(rejected={QWEN: "HTTP 400: nee"})
        self.write_scores(self.scores, [])
        _, _, _, text = self.report([QWEN], runs=1)
        self.assertEqual([self.cells(l)[2] for l in self.section(text, "Runs zonder oordeel") if l.startswith(f"| {QWEN}")],
                         ["preflight afgewezen: HTTP 400: nee"])

    NOTES_SECTION = "Venster, probes en afwijkingen"

    def test_without_notes_the_section_is_there_and_says_it_is_not_filled_in_yet(self):
        self.populate_comparison()
        _, _, _, text = self.report([SONNET, QWEN, FLASH])
        lines = [l for l in self.section(text, self.NOTES_SECTION) if l.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn("nog niet ingevuld", lines[0])
        self.assertIn("--notes", lines[0])

    def test_notes_go_verbatim_into_the_section_between_the_ledger_and_the_limits(self):
        self.populate_comparison()
        notes = self.tmp / "notes.md"
        body = ("### Venster 1\n\nGedraaid op max2, 2026-10-21, tussen 10:00 en 11:30 | zonder lopende jobs.\n\n"
                "| Probe | Uitslag |\n| --- | --- |\n| qwen3.8-or-128k | aanvaard |\n\n- afwijking: één run opnieuw gedraaid (é, ≈, `code`)\n  - ingesprongen\n")
        notes.write_text(body, encoding="utf-8")
        status, _, stderr, text = self.report([SONNET, QWEN, FLASH], extra_args=("--notes", notes))
        self.assertEqual(status, 0, stderr)
        section = self.section(text, self.NOTES_SECTION)
        self.assertEqual("\n".join(section).strip("\n"), body.strip("\n"))
        self.assertNotIn("nog niet ingevuld", text)
        self.assertLess(text.index("## Grootboek"), text.index(f"## {self.NOTES_SECTION}"))
        self.assertLess(text.index(f"## {self.NOTES_SECTION}"), text.index("## Grenzen en vervolg"))

    def test_notes_that_cannot_be_used_are_exit_2_and_no_report(self):
        self.populate_comparison()
        unreadable = self.tmp / "kapot.md"
        unreadable.write_bytes(b"\xff\xfe geen utf-8 \x80")
        blank = self.tmp / "leeg.md"
        blank.write_text("  \n\n", encoding="utf-8")
        a_directory = self.tmp / "map.md"
        a_directory.mkdir()
        for name, path in (("missing", self.tmp / "niet-er.md"), ("not utf-8", unreadable), ("blank", blank), ("a directory", a_directory)):
            with self.subTest(name):
                status, _, stderr, text = self.report([SONNET, QWEN, FLASH], extra_args=("--notes", path))
                self.assertEqual(status, 2)
                self.assertIn("--notes", stderr)
                self.assertIsNone(text)
                self.assertFalse(self.results.exists())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs mkfifo")
    def test_notes_that_are_a_named_pipe_are_refused_without_a_read_that_hangs(self):
        pipe = self.tmp / "pipe.md"
        os.mkfifo(pipe)
        argv = [sys.executable, str(SCORE), "report", str(self.out), "--scores", "s", "--decisions", "d", "--ledger", "l", "--date", "2026-10-20",
                "--preflight", "p", "--models", QWEN, "--runs", "1", "--notes", str(pipe)]
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            self.fail("score.py report read a named pipe as the notes and hung")
        self.assertEqual(done.returncode, 2)
        self.assertIn("is not a file", done.stderr)

    def test_a_smoke_scores_file_that_is_not_there_is_refused_by_report_but_not_by_smoke(self):
        self.populate_comparison()
        smoke = self.tmp / "rook"
        self.put(QWEN, 1, "bench-result-benchfout.json", out=smoke)
        self.put(SONNET, 1, "bench-result-benchfout.json", out=smoke)
        missing = self.tmp / "niet-er.jsonl"
        status, _, stderr, text = self.report([SONNET, QWEN, FLASH], extra_args=("--smoke-dir", smoke, "--smoke-scores", missing))
        self.assertEqual(status, 2)
        self.assertIn("--smoke-scores", stderr)
        self.assertIsNone(text)
        self.assertFalse(self.results.exists())
        self.assertEqual(self.run_main("smoke", smoke, "--scores", missing)[0], 1)          # the subcommand keeps its meaning: no scores, a stop
        missing.write_text("", encoding="utf-8")                                              # an empty file is the way to say there is no sheet
        status, _, stderr, text = self.report([SONNET, QWEN, FLASH], extra_args=("--smoke-dir", smoke, "--smoke-scores", missing))
        self.assertEqual(status, 0, stderr)
        self.assertIn("rookproef: stop", "\n".join(self.section(text, "Rookproef")))

    def test_a_result_that_is_dropped_is_named_in_the_warnings_by_its_path_under_out(self):
        self.three(QWEN, BEOORDEELD, BEOORDEELD, BEOORDEELD)
        garbled = self.put(QWEN, 1)
        (garbled / "bench-result.json").write_text("{ niet af", encoding="utf-8")
        mislabelled = self.put(QWEN, 2, over={"label": "cfg-beta"})
        no_status = self.put(QWEN, 3, over={"status": "kapot"})
        a_directory = self.out / QWEN / "r3" / "synth-case-zonder-bestand"
        (a_directory / "bench-result.json").mkdir(parents=True)
        empty = self.out / QWEN / "r3" / "synth-case-leeg"
        empty.mkdir()
        self.score_runs({(QWEN, n): {} for n in (1, 2, 3)})
        status, _, stderr, text = self.report([QWEN])
        self.assertEqual(status, 0, stderr)
        warnings = "\n".join(self.section(text, "Waarschuwingen"))
        for directory in (garbled, mislabelled, no_status, a_directory):
            relative = f"{directory.relative_to(self.out).as_posix()}/bench-result.json"
            self.assertIn(relative, warnings)
            self.assertIn(relative, stderr)
        self.assertNotIn(empty.name, warnings)                                   # a run directory without the file is nothing that was dropped
        self.assertNotIn(str(self.out), warnings + stderr)                      # relative to <out>, not absolute
        sheets = self.run_main("sheets", self.out)
        self.assertNotIn("bench-result.json", sheets[1] + sheets[2])           # whoever scores sees no word of it

    def test_no_dropped_result_no_warning_section(self):
        self.populate_comparison()
        _, _, stderr, text = self.report([SONNET, QWEN, FLASH])
        self.assertNotIn("## Waarschuwingen", text)
        self.assertEqual(stderr, "")

    def test_the_count_of_runs_without_an_amount_has_its_singular_and_its_plural(self):
        def without_amount(n):
            usage = {k: v for k, v in fixture_json(BEOORDEELD)["usage"].items() if k != "costUsd"}
            self.put(QWEN, n, over={"usage": usage})
        for missing, expected in ((0, "0 runs hebben er geen"), (1, "1 run heeft er geen"), (2, "2 runs hebben er geen")):
            with self.subTest(missing=missing):
                shutil.rmtree(self.out, ignore_errors=True)
                for n in (1, 2, 3):
                    if n <= missing:
                        without_amount(n)
                    else:
                        self.put(QWEN, n)
                self.score_runs({(QWEN, n): {} for n in (1, 2, 3)})
                self.preflight_ok(QWEN)
                _, _, _, text = self.report([QWEN])
                self.assertIn(f"({expected})", text)

    def test_the_read_file_counts_of_each_run_come_from_its_trace(self):
        self.put(QWEN, 1, trace="trace.jsonl")
        self.put(QWEN, 2)                                       # no trace file at all
        self.put(QWEN, 3, "bench-result-benchfout.json")
        self.score_runs({(QWEN, 1): {}, (QWEN, 2): {}})
        self.preflight_ok(QWEN)
        _, _, _, text = self.report([QWEN])
        rows = {self.cells(l)[1]: self.cells(l) for l in self.rows(self.section(text, "Per run"), QWEN)}
        self.assertEqual(rows["1"][-2:], ["3", "2"])
        self.assertEqual(rows["2"][-2:], ["-", "-"])
        self.assertEqual(rows["3"][2], "benchfout")

    def test_the_preflight_section_has_the_outcome_the_reason_and_the_amount_of_the_ledger(self):
        self.three("cfg-alfa", BEOORDEELD)
        self.score_runs({("cfg-alfa", 1): {}})
        shutil.copy(SCORE_FIXTURES / "ledger.jsonl", self.ledger)
        shutil.copy(SCORE_FIXTURES / "preflight.json", self.preflight)
        status, _, stderr, text = self.report(["cfg-alfa", "cfg-beta", "cfg-gamma"], runs=1)
        self.assertEqual(status, 0, stderr)
        rows = {self.cells(l)[0]: self.cells(l) for l in self.section(text, "Preflight") if l.startswith("| cfg-")}
        self.assertEqual(rows["cfg-alfa"][1:3], ["afgewezen", "HTTP 400: model niet beschikbaar"])
        self.assertEqual(rows["cfg-alfa"][3], "onbekend")                       # the ledger holds null for it
        self.assertEqual(rows["cfg-beta"][1:4], ["ok", "-", "$0,0021"])           # two preflights of beta: the last one is the amount
        self.assertEqual(rows["cfg-gamma"][1], "geen preflight")

    def test_the_ledger_is_a_list_of_rows_ids_that_repeat_do_not_merge_them(self):
        self.three(QWEN, BEOORDEELD)
        self.score_runs({(QWEN, 1): {}})
        self.preflight_ok(QWEN)
        shutil.copy(SCORE_FIXTURES / "ledger.jsonl", self.ledger)
        _, _, _, text = self.report([QWEN], runs=1)
        lines = self.section(text, "Grootboek")
        rows = [l for l in lines if l.startswith("| ") and "synth-case" in l]
        self.assertEqual(len(rows), 3)                                  # two of them share one id
        self.assertEqual(sum("synth-case-cfg-beta-0a0b0c0d" in l for l in rows), 2)
        total = "\n".join(lines)
        self.assertIn("$0,4321", total)                                 # 0.01 + 0.0021 + 0.12 + 0.3, a missing amount as 0
        self.assertIn("2 zonder bedrag", total)

    def test_the_context_rows_name_the_two_production_runs(self):
        self.populate_comparison()
        _, _, _, text = self.report([SONNET, QWEN, FLASH])
        context = "\n".join(self.section(text, "Context: productieruns"))
        for expected in ("1a78c1b8", "Claude Code", "$0,39", "7146cbe9", "Codex CLI", "≈ $0,10"):
            self.assertIn(expected, context)

    def test_the_window_is_named_next_to_the_peak_and_the_report_says_what_it_does_not_cover(self):
        self.populate_comparison()
        _, _, _, text = self.report([SONNET, QWEN, FLASH])
        self.assertIn("61000 / 131072", "\n".join(self.section(text, "Kosten, tokens, context en tijd")))
        limits = "\n".join(self.section(text, "Grenzen en vervolg"))
        self.assertIn("één case", limits)
        self.assertIn("alleen een document", limits)

    def test_the_report_goes_to_results_dir_under_the_name_of_the_date(self):
        self.populate_comparison()
        status, stdout, _, text = self.report([SONNET, QWEN, FLASH], date="2026-11-03")
        self.assertEqual(status, 0)
        self.assertTrue((self.results / "review-bench-2026-11-03.md").is_file())
        self.assertIn(str(self.results / "review-bench-2026-11-03.md"), stdout)
        self.assertTrue(text.startswith("# Review-bench 2026-11-03"))

    def test_without_results_dir_the_report_goes_to_llm_bench_results(self):
        self.assertEqual(self.S.DEFAULT_RESULTS_DIR, HERE.parent / "results")
        ap = self.S.build_parser()
        args = ap.parse_args(["report", str(self.out), "--scores", "s", "--decisions", "d", "--ledger", "l", "--date", "2026-10-20",
                              "--preflight", "p", "--models", "a", "--runs", "3"])
        self.assertEqual(Path(args.results_dir), HERE.parent / "results")

    def test_the_smoke_flags_come_in_a_pair(self):
        self.populate_comparison()
        for extra_args in (("--smoke-dir", self.tmp / "rook"), ("--smoke-scores", self.tmp / "s.jsonl")):
            with self.subTest(extra_args):
                status, _, stderr, text = self.report([SONNET, QWEN, FLASH], extra_args=extra_args)
                self.assertEqual(status, 2)
                self.assertIn("--smoke", stderr)
        self.assertFalse(self.results.exists())

    def test_the_smoke_section_has_the_gate_and_the_runs_of_the_smoke_dir(self):
        self.populate_comparison()
        smoke = self.tmp / "rook"
        self.put(QWEN, 1, out=smoke)
        self.put(SONNET, 1, out=smoke)
        self.assertEqual(self.run_main("sheets", smoke, "--only-f1")[0], 0)
        ids = self.sheet_ids(smoke)
        self.write_scores(self.tmp / "rook-scores.jsonl", [{"sheet": ids[(QWEN, 1)], "f1": "nee"}, {"sheet": ids[(SONNET, 1)], "f1": "major"}])
        status, _, stderr, text = self.report([SONNET, QWEN, FLASH], extra_args=("--smoke-dir", smoke, "--smoke-scores", self.tmp / "rook-scores.jsonl"))
        self.assertEqual(status, 0, stderr)
        lines = self.section(text, "Rookproef")
        joined = "\n".join(lines)
        self.assertIn("rookproef: door", joined)
        self.assertEqual(self.cells(self.rows(lines, SONNET)[0])[1:], ["1", "beoordeeld", "succeeded", "NO-GO", "major"])
        self.assertEqual(self.cells(self.rows(lines, QWEN)[0])[1:], ["1", "beoordeeld", "succeeded", "NO-GO", "nee"])
        # without the smoke flags the section says it was not given
        _, _, _, text = self.report([SONNET, QWEN, FLASH])
        self.assertIn("niet meegegeven", "\n".join(self.section(text, "Rookproef")))

    def test_a_smoke_that_stopped_is_in_the_report_as_a_stop(self):
        self.populate_comparison()
        smoke = self.tmp / "rook"
        self.put(SONNET, 1, "bench-result-benchfout.json", out=smoke)
        self.run_main("sheets", smoke, "--only-f1")
        self.write_scores(self.tmp / "rook-scores.jsonl", [])
        status, _, stderr, text = self.report([SONNET, QWEN, FLASH], extra_args=("--smoke-dir", smoke, "--smoke-scores", self.tmp / "rook-scores.jsonl"))
        self.assertEqual(status, 0, stderr)               # the report is made; the gate is only told
        self.assertIn("rookproef: stop", "\n".join(self.section(text, "Rookproef")))


class ReportInputTest(ReportBase):
    """What the report refuses: a verdict from incomplete or unreadable input would be a wrong one."""

    def setUp(self):
        super().setUp()
        for n in (1, 2, 3):
            self.put(QWEN, n)
        self.preflight_ok(QWEN)

    def refused(self, *, models=(QWEN,), runs=3, date=None, extra_args=()):
        status, stdout, stderr, text = self.report(list(models), runs=runs, date=date, extra_args=extra_args)
        self.assertEqual(status, 2, stdout)
        self.assertIsNone(text)
        return stderr

    def test_a_judged_run_without_a_score_is_refused_and_the_message_names_sheets_only(self):
        self.score_runs({(QWEN, 1): {}, (QWEN, 2): {}})
        stderr = self.refused()
        missing = self.sheet_ids()[(QWEN, 3)]
        self.assertIn(missing, stderr)
        self.assertIn("1 beoordeelde run heeft nog geen score", stderr)
        self.assertNotIn(QWEN, stderr)                      # the message must not link a sheet to a configuration

    def test_two_judged_runs_without_a_score_are_said_in_the_plural(self):
        self.score_runs({(QWEN, 1): {}})
        self.assertIn("2 beoordeelde runs hebben nog geen score", self.refused())

    def test_a_judged_run_without_a_sheet_is_refused_too(self):
        self.score_runs({(QWEN, n): {} for n in (1, 2, 3)})
        self.put(QWEN, 4)
        stderr = self.refused(runs=4)
        self.assertIn("geen blad", stderr)
        self.assertIn("1 beoordeelde run heeft geen blad", stderr)

    def test_a_score_for_a_sheet_that_is_not_in_the_key_is_refused(self):
        self.score_runs({(QWEN, n): {} for n in (1, 2, 3)})
        self.write_scores(self.scores, [*[json.loads(l) for l in self.scores.read_text(encoding="utf-8").splitlines()], grade("ffff9999")])
        self.assertIn("line 4", self.refused())

    def test_a_missing_sheets_key_is_refused_with_the_way_out(self):
        self.write_scores(self.scores, [grade("aaaa0001")])
        self.assertIn("score.py sheets", self.refused())

    def test_a_score_for_a_run_that_is_not_expected_is_ignored_with_a_warning(self):
        self.score_runs({(QWEN, n): {} for n in (1, 2, 3)})
        self.put(SONNET, 1)                                       # not in --models
        self.run_main("sheets", self.out)
        ids = self.sheet_ids()
        self.write_scores(self.scores, [grade(ids[(QWEN, n)]) for n in (1, 2, 3)] + [grade(ids[(SONNET, 1)])])
        status, _, stderr, text = self.report([QWEN])
        self.assertEqual(status, 0, stderr)
        self.assertIn("## Waarschuwingen", text)
        self.assertIn("buiten --models", stderr)

    def test_results_outside_models_and_runs_are_named_in_a_warning(self):
        self.score_runs({(QWEN, n): {} for n in (1, 2, 3)})
        self.put(QWEN, 4)                                         # beyond --runs
        self.put("cfg-typo", 1)                                   # a label that --models does not name
        status, _, stderr, text = self.report([QWEN])
        self.assertEqual(status, 0, stderr)
        self.assertIn(f"resultaten buiten --models en --runs genegeerd: cfg-typo r1, {QWEN} r4", stderr)
        self.assertIn("cfg-typo r1", "\n".join(self.section(text, "Waarschuwingen")))

    def test_the_arguments_of_the_call_are_checked(self):
        self.score_runs({(QWEN, n): {} for n in (1, 2, 3)})
        self.assertIn("--date", self.refused(date="20-10-2026"))
        self.assertIn("--date", self.refused(date="2026-13-40"))
        self.assertIn("more than once", self.refused(models=(QWEN, QWEN)))
        self.assertFalse(self.results.exists())

    def test_a_ledger_a_preflight_or_decisions_that_are_not_there_are_refused(self):
        self.score_runs({(QWEN, n): {} for n in (1, 2, 3)})
        for attribute, needle in (("ledger", "--ledger"), ("preflight", "--preflight"), ("decisions", "--decisions")):
            with self.subTest(attribute):
                original = getattr(self, attribute)
                setattr(self, attribute, self.tmp / "niet-er")
                try:
                    self.assertIn(needle, self.refused())
                finally:
                    setattr(self, attribute, original)

    def test_a_preflight_entry_that_is_no_object_with_ok_is_refused(self):
        self.score_runs({(QWEN, n): {} for n in (1, 2, 3)})
        self.preflight.write_text(json.dumps({QWEN: "ok"}), encoding="utf-8")
        self.assertIn(QWEN, self.refused())


class ScoreUsageTest(ScoreBase):
    def test_no_subcommand_and_an_unknown_one_are_usage_errors(self):
        self.assertEqual(self.run_main()[0], 2)
        self.assertEqual(self.run_main("foo")[0], 2)

    def test_a_directory_that_is_not_there_is_an_error_not_a_traceback(self):
        for argv in (("sheets", self.tmp / "niet-er"), ("smoke", self.tmp / "niet-er", "--scores", self.tmp / "s.jsonl")):
            with self.subTest(argv[0]):
                status, _, stderr = self.run_main(*argv)
                self.assertEqual(status, 2)
                self.assertIn("score.py:", stderr)


class StdlibOnlyScoreTest(unittest.TestCase):
    @unittest.skipUnless(hasattr(sys, "stdlib_module_names"), "needs Python 3.10")
    def test_score_imports_nothing_outside_the_standard_library(self):
        tree = ast.parse(SCORE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = ([a.name for a in node.names] if isinstance(node, ast.Import)
                       else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
            for module in modules:
                with self.subTest(module=module):
                    self.assertIn(module.split(".")[0], sys.stdlib_module_names)

    def test_score_runs_as_a_script_and_is_executable(self):
        self.assertTrue(os.access(SCORE, os.X_OK))
        done = subprocess.run([sys.executable, str(SCORE), "--help"], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        for word in ("sheets", "smoke", "report"):
            self.assertIn(word, done.stdout)


class EndToEndTest(DriverBase):
    """P2, P3 and P4 of the plan, in its layout: the preflight in R, the smoke in R/rook, the main runs in R/runs, each with
    --preflight-file R/preflight.json. Four configurations with --runs 3: one is rejected by the preflight, one gives CONFIGURATION_NOT_PROBED."""

    REJECTED, UNPROBED = FLASH, GLM

    def setUp(self):
        super().setUp()
        self.labels = [QWEN, SONNET, self.REJECTED, self.UNPROBED]
        self.R = self.tmp / "R"
        write_harness_json(self.config_file, self.litellm.base_url,
                           {label: {"costMode": "hosted", "contextTokens": 131072} for label in self.labels})
        self.litellm.answer(self.REJECTED, (400, {"error": {"message": "model niet beschikbaar"}}))

    def drive_in(self, models, out, runs, *flags, config=None):
        return self.drive(models, runs=runs, out=out, args=("--preflight-file", self.R / "preflight.json", *flags), config=config)

    def score_py(self, *argv):
        return subprocess.run([sys.executable, str(SCORE), *map(str, argv)], capture_output=True, text=True, cwd=self.tmp, timeout=120,
                              env=clean_env())

    def ids(self, out):
        key = json.loads((Path(out) / "sheets-key.json").read_text(encoding="utf-8"))
        return {(path.split("/")[0], int(path.split("/")[1][1:])): sheet for sheet, path in key.items()}

    def test_the_whole_road_from_preflight_to_report(self):
        R = self.R
        # P2: the preflight in R, then the smoke in R/rook
        done = self.drive(self.labels, out=R, ready=False, args=("--preflight", "--preflight-file", R / "preflight.json"))
        self.assertEqual(done.returncode, 0, done.stderr)
        fake = {"default": {"cost": 0.05, "duration_ms": 2000},
                "labels": {self.UNPROBED: {"status": "benchfout", "benchError": "CONFIGURATION_NOT_PROBED: geen aanvaarde probe voor glm-5.3-or"}}}
        done = self.drive_in([QWEN, SONNET], R / "rook", 1, config=fake)
        self.assertEqual(done.returncode, 0, done.stderr)
        done = self.score_py("sheets", R / "rook", "--only-f1")
        self.assertEqual(done.returncode, 0, done.stderr)
        smoke_ids = self.ids(R / "rook")
        self.assertEqual(sorted(label for label, _ in smoke_ids), sorted([QWEN, SONNET]))
        write_jsonl(R / "rook" / "scores.jsonl", [{"sheet": sheet, "f1": "major"} for sheet in smoke_ids.values()])
        done = self.score_py("smoke", R / "rook", "--scores", R / "rook" / "scores.jsonl")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("rookproef: door", done.stdout)
        # P3: the main runs; the rejected configuration is skipped by the driver, the unprobed one is called once
        done = self.drive_in(self.labels, R / "runs", 3, config=fake)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.ran()), 2 + 3 + 3 + 1)                     # smoke 2, qwen 3, sonnet 3, the unprobed one once
        trace = next((R / "runs" / QWEN / "r1").glob("synth-case-*/trace.jsonl"))
        shutil.copy(SCORE_FIXTURES / "trace.jsonl", trace)
        # P4: sheets, scores by hand, decisions, report
        done = self.score_py("sheets", R / "runs")
        self.assertEqual(done.returncode, 0, done.stderr)
        ids = self.ids(R / "runs")
        self.assertEqual(len(ids), 6)
        grades = {(QWEN, 1): "major", (QWEN, 2): "major", (QWEN, 3): "minor", **{(SONNET, n): "major" for n in (1, 2, 3)}}
        write_jsonl(R / "runs" / "scores.jsonl", [grade(ids[run], f1=f1) for run, f1 in grades.items()])
        (R / "decisions.json").write_text("{}", encoding="utf-8")
        done = self.score_py("report", R / "runs", "--scores", R / "runs" / "scores.jsonl", "--decisions", R / "decisions.json", "--ledger", self.ledger,
                             "--date", "2026-10-20", "--preflight", R / "preflight.json", "--models", *self.labels, "--runs", 3,
                             "--smoke-dir", R / "rook", "--smoke-scores", R / "rook" / "scores.jsonl", "--results-dir", R / "results")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        text = (R / "results" / "review-bench-2026-10-20.md").read_text(encoding="utf-8")
        reasons = ReportBase.section(text, "Runs zonder oordeel")
        rejected = [l for l in reasons if l.startswith(f"| {self.REJECTED}")]
        unprobed = [l for l in reasons if l.startswith(f"| {self.UNPROBED}")]
        self.assertEqual(len(rejected), 3)
        self.assertTrue(all("preflight afgewezen" in l and "model niet beschikbaar" in l for l in rejected), rejected)
        self.assertEqual(len(unprobed), 3)
        self.assertTrue(all("niet geprobed" in l for l in unprobed), unprobed)
        self.assertFalse([l for l in reasons if "benchfout" in l or "niet gestart" in l])
        self.assertIn("6 van 12 verwachte runs beoordeeld", text)
        table = ReportBase.section(text, "Oordeel per model")
        by_label = {l.split("|")[1].strip().split(" (")[0]: [c.strip() for c in l.strip().strip("|").split("|")] for l in table if l.startswith("| ")}
        self.assertEqual(by_label[SONNET][1:3], ["kandidaat", "3/3"])
        self.assertEqual(by_label[QWEN][1:3], ["twijfel", "2/3"])
        self.assertEqual(by_label[self.REJECTED][1:3], ["valt af (niet gedraaid: preflight afgewezen)", "0/3"])
        self.assertEqual(by_label[self.UNPROBED][1:3], ["valt af (niet gedraaid: niet geprobed)", "0/3"])
        comparison = [[c.strip() for c in l.strip().strip("|").split("|")] for l in ReportBase.section(text, "Eerste vergelijking: open modellen tegenover de harness-controles")
                      if l.startswith("| ") and not l.startswith("| ---")]
        self.assertEqual(comparison, [
            ["Groep", "Model", "Oordeel", "Voldoet", "F1 als major gevonden"],
            ["harness-controle", SONNET, "kandidaat", "3/3", "3/3"],
            ["open model", QWEN, "twijfel", "2/3", "2/3"],
            ["open model", self.REJECTED, "valt af (niet gedraaid: preflight afgewezen)", "0/3", "0/3"],
            ["open model", self.UNPROBED, "valt af (niet gedraaid: niet geprobed)", "0/3", "0/3"]])
        preflight = ReportBase.section(text, "Preflight")
        self.assertTrue(any(l.startswith(f"| {self.REJECTED} | afgewezen") for l in preflight), preflight)
        self.assertTrue(any(l.startswith(f"| {QWEN} | ok") for l in preflight), preflight)
        smoke = "\n".join(ReportBase.section(text, "Rookproef"))
        self.assertIn("rookproef: door", smoke)
        self.assertIn(f"| {SONNET} | 1 | beoordeeld | succeeded | NO-GO | major |", smoke)
        read_row = next(l for l in ReportBase.section(text, "Per run") if l.startswith(f"| {QWEN} | 1 |"))
        self.assertTrue(read_row.rstrip().endswith("| 3 | 2 |"), read_row)
        self.assertIn(f"| preflight | {self.REJECTED} |", "\n".join(ReportBase.section(text, "Grootboek")))
        for sheet in ids.values():                                                        # the sheets of the main runs name no configuration
            sheet_text = (R / "runs" / "sheets" / f"{sheet}.md").read_text(encoding="utf-8")
            for label in self.labels:
                self.assertNotIn(label, sheet_text)


if __name__ == "__main__":
    unittest.main()
