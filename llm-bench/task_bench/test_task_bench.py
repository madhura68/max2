"""Tests for the task-bench driver and scorer (M7, Task 7): run.py and score.py against fake_task_bench.py. No model, no
network, no real key: the harness is a stand-in, the endpoint list is a function the tests replace, the key is a dummy.

  python3 -m unittest discover -s llm-bench/task_bench -p 'test_*.py'

fixtures/real-harness/ holds unchanged copies of what the real harness and the real driver steps wrote in the practice run of
2026-10-03 (the first task, the hosted model, the 16-bit route): the probe, the bench result of the run, the public endpoint list,
the model config, the extra body, the case and the ledger. The parsers are tested on them, and the stand-in is held to their shapes.
"""
import ast
import contextlib
import csv
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fake_task_bench  # noqa: E402
import run  # noqa: E402
import score  # noqa: E402

FAKE = HERE / "fake_task_bench.py"
CHECK_KEY = HERE.parent / "refiner" / "check_key.py"
REAL = HERE / "fixtures" / "real-harness"
TASK_CONFIG = HERE / "task-config.json"
DUMMY_KEY = "dummy-value-not-a-key-0f4a9c1e"       # a test lends a child process this and nothing real
KEY_VARIABLE = "OPENROUTER_API_KEY"                  # the name; a test lends the variable DUMMY_KEY and nothing else
HOSTED, LOCAL = "qwen3.8-openrouter", "gsq-lokaal"
HOSTED_MODEL, LOCAL_MODEL = "qwen/qwen3.8-27b", "qwen3.8-gsq-rco:27b-iq3_s-text"
STAMP = r"\d{8}T\d{6}Z"                              # <ts> of the names: UTC, as in the ledger of the practice run
CASES_12 = [f"AH-{n:02d}" for n in range(1, 7)] + [f"SM-{n:02d}" for n in range(1, 7)]       # 6 per repo, as the set will be


def clean_env(**extra):
    """The environment for a child process: ours without an OPENROUTER_API_KEY (a test never lends a real key), plus extra."""
    env = {k: v for k, v in os.environ.items() if k != KEY_VARIABLE}
    env.update(extra)
    return env


def real_json(*parts):
    return json.loads(REAL.joinpath(*parts).read_text(encoding="utf-8"))


def case_lines(*ids):
    """The text of a cases.jsonl: one case per id, each the real case of the practice run (AH-01) under another id."""
    base = real_json("case-AH-01.json")
    return "".join(json.dumps({**base, "id": case_id}, ensure_ascii=False) + "\n" for case_id in ids)


def shipped_models():
    return json.loads((HERE / "models.json").read_text(encoding="utf-8"))


def read_summary(directory):
    """The rows of the summary.csv score.py wrote in directory."""
    with (Path(directory) / "summary.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def probe_amounts(probe):
    """The five usage.costUsd of a probe.json, in the order of the stand-in's costs: a_plain, b_single_tool, the two turns of
    c_two_tools, d_nonexistent_tool."""
    steps = probe["steps"]
    return [steps["a_plain"]["raw"]["usage"]["costUsd"], steps["b_single_tool"]["raw"]["usage"]["costUsd"],
            steps["c_two_tools"]["raw"]["turn1"]["usage"]["costUsd"], steps["c_two_tools"]["raw"]["turn2"]["usage"]["costUsd"],
            steps["d_nonexistent_tool"]["raw"]["usage"]["costUsd"]]


# ---------------------------------------------------------------------------------------------------------------------
# verdict: the decision rule of spec §1
# ---------------------------------------------------------------------------------------------------------------------

class VerdictTest(unittest.TestCase):
    def test_the_count_over_all_169_pairs_is_the_count_of_both_reviewers(self):
        counts = {}
        for h in range(13):
            for g in range(13):
                counts[score.verdict(h, g)] = counts.get(score.verdict(h, g), 0) + 1
        self.assertEqual(counts, {"gezakt": 104, "onbeslist": 33, "meerwaarde": 23, "max2 volstaat": 9})

    def test_the_named_cases(self):
        for (h, g), expected in {(8, 0): "onbeslist", (9, 9): "onbeslist", (12, 9): "onbeslist", (12, 8): "onbeslist",
                                 (12, 7): "meerwaarde", (10, 6): "meerwaarde", (10, 7): "onbeslist",
                                 (11, 11): "max2 volstaat", (7, 0): "gezakt"}.items():
            with self.subTest(hosted=h, gsq=g):
                self.assertEqual(score.verdict(h, g), expected)

    def test_the_threshold_is_nine_of_twelve(self):
        self.assertEqual(score.THRESHOLD, 9)


# ---------------------------------------------------------------------------------------------------------------------
# models.json and load_models
# ---------------------------------------------------------------------------------------------------------------------

class ModelsFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def hosted(self, **over):
        return {**shipped_models()[HOSTED], **over}

    def load(self, models, labels=(HOSTED,)):
        path = self.tmp / "models.json"
        path.write_text(json.dumps(models), encoding="utf-8")
        return run.load_models(path, list(labels))

    def refused(self, models, labels=(HOSTED,)):
        with self.assertRaises(run.RunError) as raised:
            self.load(models, labels)
        return str(raised.exception)

    def test_the_hosted_label_pins_the_16_bit_route_and_the_privacy_flags(self):
        cfg = shipped_models()[HOSTED]
        self.assertEqual((cfg["base_url"], cfg["name"]), ("https://openrouter.ai/api/v1", HOSTED_MODEL))
        self.assertEqual(cfg["extraBody"]["provider"],
                         {"data_collection": "deny", "require_parameters": True, "quantizations": ["bf16", "fp16"]})
        self.assertEqual(cfg["extraBody"]["reasoning"], {"effort": "medium"})
        self.assertEqual(cfg["api_key_env"], "OPENROUTER_API_KEY")
        self.assertIs(cfg["retry_transient"], True)

    def test_the_local_label_has_no_key_no_extra_settings_and_no_retry(self):
        cfg = shipped_models()[LOCAL]
        self.assertEqual((cfg["base_url"], cfg["name"]), ("http://127.0.0.1:11434/v1", LOCAL_MODEL))
        self.assertNotIn("api_key_env", cfg)
        self.assertNotIn("extraBody", cfg)
        self.assertIs(cfg["retry_transient"], False)

    def test_there_are_these_two_labels_and_no_other(self):
        self.assertEqual(sorted(shipped_models()), sorted([HOSTED, LOCAL]))

    def test_load_models_gives_the_labels_asked_for_in_that_order(self):
        loaded = run.load_models(HERE / "models.json", [HOSTED, LOCAL])
        self.assertEqual(list(loaded), [HOSTED, LOCAL])
        self.assertEqual(loaded[HOSTED], shipped_models()[HOSTED])

    def test_a_hosted_label_without_the_provider_block_is_refused(self):
        no_provider = self.hosted()
        del no_provider["extraBody"]["provider"]
        no_extra_body = self.hosted()
        del no_extra_body["extraBody"]
        for what, cfg in (("no provider", no_provider), ("no extraBody", no_extra_body),
                          ("a provider that is no object", self.hosted(extraBody={"provider": "deny"}))):
            with self.subTest(what):
                message = self.refused({HOSTED: cfg})
                self.assertIn(HOSTED, message)
                self.assertIn("provider", message)

    def test_other_quantizations_are_refused(self):
        for what, quantizations in (("missing", None), ("a lower precision", ["fp8"]), ("one of the two", ["bf16"]),
                                    ("one more", ["bf16", "fp16", "fp8"]), ("another order", ["fp16", "bf16"]),
                                    ("a string", "bf16"), ("empty", [])):
            with self.subTest(what):
                provider = {"data_collection": "deny", "require_parameters": True}
                if quantizations is not None:
                    provider["quantizations"] = quantizations
                message = self.refused({HOSTED: self.hosted(extraBody={"provider": provider})})
                self.assertIn(HOSTED, message)
                self.assertIn("quantizations", message)

    def test_the_privacy_flags_are_required_too(self):
        good = shipped_models()[HOSTED]["extraBody"]["provider"]
        for what, provider in (("data collection allowed", {**good, "data_collection": "allow"}),
                               ("data collection not said", {k: v for k, v in good.items() if k != "data_collection"}),
                               ("require_parameters false", {**good, "require_parameters": False}),
                               ("require_parameters a string", {**good, "require_parameters": "true"}),
                               ("require_parameters not said", {k: v for k, v in good.items() if k != "require_parameters"})):
            with self.subTest(what):
                self.refused({HOSTED: self.hosted(extraBody={"provider": provider})})

    def test_the_guard_goes_by_the_host_of_the_url(self):
        no_provider = {k: v for k, v in self.hosted().items() if k != "extraBody"}
        self.load({"elders": {**no_provider, "base_url": "https://example.org/openrouter.ai/api/v1"}}, ["elders"])
        self.refused({"sub": {**no_provider, "base_url": "https://eu.openrouter.ai/api/v1"}}, ["sub"])

    def test_a_label_needs_a_base_url_and_a_name(self):
        for field in ("base_url", "name"):
            with self.subTest(field):
                cfg = self.hosted()
                del cfg[field]
                self.assertIn(field, self.refused({HOSTED: cfg}))

    def test_api_key_env_is_the_name_of_a_variable_and_a_value_is_never_quoted_back(self):
        pasted = "sk-or-v1-" + "0123456789abcdef"
        message = self.refused({HOSTED: self.hosted(api_key_env=pasted)})
        self.assertIn("api_key_env", message)
        self.assertNotIn(pasted, message)

    def test_retry_transient_has_to_be_said_as_true_or_false(self):
        no_retry = self.hosted()
        del no_retry["retry_transient"]
        for what, cfg in (("missing", no_retry), ("a string", self.hosted(retry_transient="yes")), ("a number", self.hosted(retry_transient=1))):
            with self.subTest(what):
                self.assertIn("retry_transient", self.refused({HOSTED: cfg}))

    def test_a_label_is_one_plain_path_segment(self):
        for label in ("../x", "a/b", "", ".hidden", "x" * 65):
            with self.subTest(label):
                self.refused({label: shipped_models()[LOCAL]}, [label])

    def test_unknown_labels_and_unreadable_files_are_refused(self):
        self.assertIn("nope", self.refused({HOSTED: self.hosted()}, ["nope"]))
        with self.assertRaises(run.RunError):
            run.load_models(self.tmp / "missing.json", [HOSTED])
        (self.tmp / "list.json").write_text("[]", encoding="utf-8")
        with self.assertRaises(run.RunError):
            run.load_models(self.tmp / "list.json", [HOSTED])
        (self.tmp / "broken.json").write_text("{", encoding="utf-8")
        with self.assertRaises(run.RunError):
            run.load_models(self.tmp / "broken.json", [HOSTED])

    def test_task_config_is_the_task_block_of_the_worker_config(self):
        config = json.loads(TASK_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config["limits"], {"maxTurns": 40, "maxOutputTokens": 80000, "maxWallSeconds": 2400,
                                            "maxToolErrors": 8, "contextTokens": 65536})
        self.assertEqual((config["image"], config["uid"], config["gid"], config["npmCacheDir"]),
                         ("node:24-bookworm", 1000, 1000, "/var/lib/agent-harness/npm-cache"))
        self.assertNotIn("maxVerifyRepairs", config)      # not set on max2, so the standard 3 holds
        self.assertEqual([r["repoUrl"] for r in config["recipes"]],
                         ["https://git.jp-visser.nl/janpeter/agent-harness.git", "https://git.jp-visser.nl/janpeter/scrum4me-mcp.git"])


# ---------------------------------------------------------------------------------------------------------------------
# the small parsers, on real output
# ---------------------------------------------------------------------------------------------------------------------

class ParsersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_the_cost_of_the_real_probe_is_the_sum_of_its_five_amounts(self):
        probe = real_json("probe-qwen-qwen3.8-27b", "probe.json")
        amounts = probe_amounts(probe)
        self.assertEqual(len(set(amounts)), 5)
        self.assertTrue(all(a > 0 for a in amounts))
        self.assertEqual(run.probe_cost(probe), 0.00077981)         # the sum of the practice run, to the last digit
        self.assertEqual(run.probe_cost(probe), math.fsum(amounts))

    def test_every_amount_counts_also_the_two_turns_of_c_two_tools(self):
        probe = {"steps": {
            "a_plain": {"pass": True, "reason": "x", "raw": {"usage": {"costUsd": 0.001}}},
            "b_single_tool": {"pass": True, "reason": "x", "raw": {"usage": {"costUsd": 0.002}}},
            "c_two_tools": {"pass": True, "reason": "x", "raw": {"turn1": {"usage": {"costUsd": 0.004}},
                                                                   "turn2": {"usage": {"costUsd": 0.008}}}},
            "d_nonexistent_tool": {"pass": True, "reason": "x", "raw": {"usage": {"costUsd": 0.016}}}}}
        self.assertAlmostEqual(run.probe_cost(probe), 0.031, places=12)
        without_turns = json.loads(json.dumps(probe))
        without_turns["steps"]["c_two_tools"]["raw"] = {"turn1": {"usage": {"costUsd": 0.004}}}      # a turn 2 that never came
        self.assertAlmostEqual(run.probe_cost(without_turns), 0.023, places=12)

    def test_a_probe_without_any_amount_costs_null_and_a_step_that_threw_adds_nothing(self):
        silent = {"steps": {"a_plain": {"pass": True, "reason": "x", "raw": {"usage": {"source": "missing"}}},
                            "b_single_tool": {"pass": False, "reason": "model HTTP 502", "raw": None}}}
        self.assertIsNone(run.probe_cost(silent))
        self.assertIsNone(run.probe_cost({"steps": {}}))
        self.assertIsNone(run.probe_cost({}))
        partly = {"steps": {"a_plain": {"pass": True, "reason": "x", "raw": {"usage": {"costUsd": 0.5}}},
                            "b_single_tool": {"pass": False, "reason": "model HTTP 502", "raw": None}}}
        self.assertEqual(run.probe_cost(partly), 0.5)                # a lower bound, as the plan says

    def test_a_cost_of_zero_is_a_cost_and_what_is_no_amount_is_not(self):
        zero = {"steps": {"a_plain": {"raw": {"usage": {"costUsd": 0}}}}}
        self.assertEqual(run.probe_cost(zero), 0.0)
        for bad in (True, "0.5", None, -0.5, math.nan, math.inf, [0.5]):
            with self.subTest(bad=bad):
                self.assertIsNone(run.amount(bad))
                self.assertIsNone(run.probe_cost({"steps": {"a_plain": {"raw": {"usage": {"costUsd": bad}}}}}))
        self.assertEqual((run.amount(0), run.amount(2), run.amount(0.25)), (0.0, 2.0, 0.25))

    def test_the_endpoint_list_of_the_practice_run_has_one_16_bit_provider_with_tools(self):
        listing = real_json("endpoints-qwen3.8-27b.json")
        by_name = {e["provider_name"]: e for e in listing["data"]["endpoints"]}
        self.assertEqual(by_name["Cerebras"]["quantization"], "fp16")            # 16-bit, but ...
        self.assertNotIn("tools", by_name["Cerebras"]["supported_parameters"])  # ... without tools
        self.assertEqual(run.sixteen_bit_with_tools(listing), ["DeepInfra"])

    def test_without_a_16_bit_endpoint_with_tools_the_list_is_empty(self):
        listing = real_json("endpoints-qwen3.8-27b.json")
        listing["data"]["endpoints"] = [e for e in listing["data"]["endpoints"] if e["provider_name"] != "DeepInfra"]
        self.assertEqual(run.sixteen_bit_with_tools(listing), [])
        for odd in (None, [], {}, {"data": None}, {"data": {"endpoints": "x"}}, {"data": {"endpoints": [None, 3]}}):
            with self.subTest(odd=odd):
                self.assertEqual(run.sixteen_bit_with_tools(odd), [])

    def test_the_real_result_is_read_and_a_result_of_another_case_or_label_is_not(self):
        path = REAL / "AH-01-qwen3.8-openrouter-d6c19fec" / "bench-result.json"
        result = run.read_bench_result(path, "AH-01", HOSTED)
        self.assertEqual((result["status"], result["usage"]["costUsd"]), ("geslaagd", 0.065849775))
        self.assertIsNone(run.read_bench_result(path, "AH-02", HOSTED))
        self.assertIsNone(run.read_bench_result(path, "AH-01", LOCAL))

    def test_a_result_that_is_absent_unreadable_or_no_result_is_none(self):
        def put(text):
            path = self.tmp / "bench-result.json"
            path.write_text(text, encoding="utf-8")
            return path
        good = real_json("AH-01-qwen3.8-openrouter-d6c19fec", "bench-result.json")
        self.assertIsNone(run.read_bench_result(self.tmp / "absent.json", "AH-01", HOSTED))
        for what, text in (("not JSON", "{"), ("a list", "[]"), ("no status", json.dumps({**good, "status": None})),
                           ("an unknown status", json.dumps({**good, "status": "gelukt"})), ("empty", "")):
            with self.subTest(what):
                self.assertIsNone(run.read_bench_result(put(text), "AH-01", HOSTED))
        path = self.tmp / "bytes.json"
        path.write_bytes(b"\xff\xfe\x00")
        self.assertIsNone(run.read_bench_result(path, "AH-01", HOSTED))
        self.assertIsNone(run.read_bench_result(self.tmp, "AH-01", HOSTED))     # a directory is no result

    def test_the_five_model_statuses_and_the_benchfout(self):
        self.assertEqual(run.MODEL_STATUSES, ("geslaagd", "verborgen_tests_rood", "verify_rood", "limiet", "geen_wijzigingen"))
        for status in (*run.MODEL_STATUSES, "benchfout"):
            result = fake_task_bench.bench_result("AH-01", HOSTED, f"AH-01-{HOSTED}-00000000", status)
            path = self.tmp / f"{status}.json"
            path.write_text(json.dumps(result), encoding="utf-8")
            self.assertEqual(run.read_bench_result(path, "AH-01", HOSTED)["status"], status)


class LedgerHelpersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = self.tmp / "sub" / "ledger.jsonl"

    def test_an_entry_is_one_json_line_in_the_order_of_the_practice_ledger(self):
        run.append_ledger(self.path, {"id": "probe-x-1", "kind": "probe", "label": "x", "cost_usd": None})
        run.append_ledger(self.path, {"id": "AH-01-x-0123abcd", "kind": "run", "label": "x", "case": "AH-01", "cost_usd": 0.5})
        self.assertEqual(self.path.read_text(encoding="utf-8").splitlines(),
                         ['{"id": "probe-x-1", "kind": "probe", "label": "x", "cost_usd": null}',
                          '{"id": "AH-01-x-0123abcd", "kind": "run", "label": "x", "case": "AH-01", "cost_usd": 0.5}'])

    def test_the_ledger_of_the_practice_run_reads_and_adds_up(self):
        entries = run.read_ledger(REAL / "ledger.jsonl")
        self.assertEqual([e["kind"] for e in entries], ["probe", "run"])
        self.assertEqual(run.ledger_total(entries), math.fsum([0.00077981, 0.065849775]))
        self.assertEqual(run.ledger_unknown(entries), 0)

    def test_a_missing_amount_counts_as_zero_in_the_total_and_is_counted(self):
        entries = [{"cost_usd": 0.25}, {"cost_usd": None}, {"cost_usd": 0.75}, {"cost_usd": None}]
        self.assertEqual((run.ledger_total(entries), run.ledger_unknown(entries)), (1.0, 2))
        self.assertEqual(run.ledger_total([]), 0.0)

    def test_the_total_is_an_exact_sum(self):
        entries = [{"cost_usd": 0.1}] * 10
        self.assertEqual(run.ledger_total(entries), 1.0)        # sum() would give 0.9999999999999999

    def test_no_ledger_yet_is_an_empty_ledger(self):
        self.assertEqual(run.read_ledger(self.path), [])

    def test_blank_lines_are_skipped_and_a_bad_line_is_refused_without_quoting_it(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"cost_usd": 1.0}\n\n  \n{"cost_usd": 2.0}\n', encoding="utf-8")
        self.assertEqual(len(run.read_ledger(self.path)), 2)
        for what, text in (("not JSON", "secret-looking-line\n"), ("a list", "[1]\n"), ("a string amount", '{"cost_usd": "1"}\n'),
                           ("a negative amount", '{"cost_usd": -1}\n'), ("a true", '{"cost_usd": true}\n')):
            with self.subTest(what):
                self.path.write_text('{"cost_usd": 1.0}\n' + text, encoding="utf-8")
                with self.assertRaises(run.RunError) as raised:
                    run.read_ledger(self.path)
                self.assertIn("line 2", str(raised.exception))
                self.assertNotIn("secret-looking-line", str(raised.exception))


class StdlibOnlyTest(unittest.TestCase):
    @unittest.skipUnless(hasattr(sys, "stdlib_module_names"), "needs Python 3.10")
    def test_run_score_and_the_stand_in_import_nothing_outside_the_standard_library(self):
        own = {"run", "score", "fake_task_bench"}
        for name in ("run.py", "score.py", "fake_task_bench.py"):
            tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = ([a.name for a in node.names] if isinstance(node, ast.Import)
                           else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
                for module in modules:
                    top = module.split(".")[0]
                    with self.subTest(file=name, module=module):
                        self.assertTrue(top in sys.stdlib_module_names or top in own, top)


# ---------------------------------------------------------------------------------------------------------------------
# the stand-in itself: held to the real CLI and to the real files
# ---------------------------------------------------------------------------------------------------------------------

class FakeHarnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "case.json").write_text(case_lines("AH-01"), encoding="utf-8")
        (self.tmp / "model.json").write_text(json.dumps({"baseUrl": "https://openrouter.ai/api/v1", "name": HOSTED_MODEL}),
                                             encoding="utf-8")

    def fake(self, *args, **env):
        return subprocess.run([sys.executable, str(FAKE), *map(str, args)], capture_output=True, text=True,
                              env=clean_env(**env), timeout=60)

    def task_bench(self, *extra, model=None, **env):
        if model is not None:
            (self.tmp / "model.json").write_text(json.dumps(model), encoding="utf-8")
        return self.fake("task-bench", "--case", self.tmp / "case.json", "--model-config", self.tmp / "model.json",
                         "--task-config", TASK_CONFIG, "--label", HOSTED, "--out", self.tmp / "runs", *extra, **env)

    def test_a_result_has_the_keys_and_the_order_of_the_real_one(self):
        real = real_json("AH-01-qwen3.8-openrouter-d6c19fec", "bench-result.json")
        made = fake_task_bench.bench_result("AH-01", HOSTED, real["runId"], "geslaagd", 0.065849775)
        self.assertEqual(list(made), list(real))
        self.assertEqual(list(made["usage"]), list(real["usage"]))
        self.assertEqual(list(made["hidden"]), list(real["hidden"]))
        self.assertEqual(list(made["hidden"]["files"][0]), list(real["hidden"]["files"][0]))
        self.assertEqual(list(made["model"]), list(real["model"]))

    def test_the_optional_fields_are_where_the_real_bench_puts_them(self):
        benchfout = fake_task_bench.bench_result("AH-01", HOSTED, "AH-01-x-00000000", "benchfout", None, bench_error="clone faalde")
        self.assertEqual((benchfout["runStatus"], benchfout["benchError"]), ("not_run", "clone faalde"))
        self.assertNotIn("costUsd", benchfout["usage"])
        self.assertNotIn("hidden", benchfout)
        failed = fake_task_bench.bench_result("AH-01", HOSTED, "AH-01-x-00000000", "verify_rood", 0.1)
        self.assertEqual(failed["error"]["code"], "VERIFY_FAILED")
        self.assertNotIn("benchError", failed)

    def test_a_probe_has_the_keys_and_the_step_shapes_of_the_real_one(self):
        real = real_json("probe-qwen-qwen3.8-27b", "probe.json")
        costs = probe_amounts(real)
        done = self.fake("probe", "--base-url", real["baseUrl"], "--model", real["model"], "--out", self.tmp / "p",
                         FAKE_TASK_BENCH_CONFIG=str(self.write_config({"probe": {"costs": costs}})))
        self.assertEqual(done.returncode, 0, done.stderr)
        made = json.loads((self.tmp / "p" / "probe-qwen-qwen3.8-27b" / "probe.json").read_text(encoding="utf-8"))
        self.assertEqual(list(made), list(real))
        self.assertEqual(list(made["steps"]), list(real["steps"]))
        self.assertEqual(list(made["steps"]["c_two_tools"]["raw"]), ["turn1", "turn2"])
        self.assertEqual(run.probe_cost(made), run.probe_cost(real))

    def write_config(self, config):
        path = self.tmp / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def results(self):
        return list((self.tmp / "runs").glob("*/bench-result.json")) if (self.tmp / "runs").exists() else []

    def test_the_cli_is_as_strict_as_the_real_one(self):
        good = {"baseUrl": "https://openrouter.ai/api/v1", "name": HOSTED_MODEL}
        done = self.task_bench(model=good)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.results()), 1)
        shutil.rmtree(self.tmp / "runs")
        (self.tmp / "e.json").write_text("{}", encoding="utf-8")
        refused = {"a typo such as extra_body in the model config": dict(model={**good, "extra_body": {}}),
                   "a key in the model config": dict(model={**good, "apiKey": "x"}),
                   "an extra body file": dict(model=good, extra=("--extra-body-file", self.tmp / "e.json")),
                   "an unset key variable": dict(model=good, extra=("--api-key-env", "FAKE_UNSET_VARIABLE"))}
        for what, kw in refused.items():
            with self.subTest(what):
                done = self.task_bench(*kw.get("extra", ()), model=kw["model"])
                self.assertEqual(done.returncode, 1, done.stdout)
                self.assertEqual(self.results(), [])

    def test_a_label_and_a_case_id_are_held_to_the_real_patterns(self):
        done = self.fake("task-bench", "--case", self.tmp / "case.json", "--model-config", self.tmp / "model.json",
                         "--task-config", TASK_CONFIG, "--label", "../x", "--out", self.tmp / "runs")
        self.assertEqual(done.returncode, 1)
        (self.tmp / "case.json").write_text(case_lines("ah-1"), encoding="utf-8")
        self.assertEqual(self.task_bench().returncode, 1)


# ---------------------------------------------------------------------------------------------------------------------
# the driver, as a process
# ---------------------------------------------------------------------------------------------------------------------

# What a test runs instead of `run.py`: the same main(), but with fetch_endpoints replaced by a function that answers from a file
# (no network) and logs that it was called, in the log the stand-in writes to, so the order of the calls is visible.
WRAPPER = '''
import json, os, sys
sys.path.insert(0, %r)
import run
spec = json.load(open(os.environ.pop("TASK_BENCH_TEST_ENDPOINTS")))
log = os.environ.pop("TASK_BENCH_TEST_LOG")
def fetch(base_url, model):
    with open(log, "a") as f:
        f.write(json.dumps({"command": "fetch", "args": [base_url, model]}) + "\\n")
    if spec.get("error"):
        raise OSError("the network is down")
    return spec["listing"]
run.fetch_endpoints = fetch
sys.exit(run.main(sys.argv[1:]))
''' % str(HERE)


def without_deepinfra(listing):
    """The practice run's endpoint list without its only 16-bit provider that has tools: Cerebras (fp16, no tools) is left."""
    listing = json.loads(json.dumps(listing))
    listing["data"]["endpoints"] = [e for e in listing["data"]["endpoints"] if e["provider_name"] != "DeepInfra"]
    return listing


class DriverBase(unittest.TestCase):
    """run.py with fake_task_bench.py as the harness. It holds no test, so a subclass does not repeat any."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()         # resolved: the driver resolves --out, and /var is /private/var
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = self.tmp / "out"                            # run.py creates it
        self.ledger = self.tmp / "ledger.jsonl"
        self.log = self.tmp / "calls.jsonl"
        self.harness = f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKE))}"
        self.listing = real_json("endpoints-qwen3.8-27b.json")
        self.counter = 0

    # --- running it -----------------------------------------------------------------------------------------------------

    def command(self, models, *, config=None, ids=("AH-01", "AH-02", "AH-03"), args=(), env=None, listing=None,
                fetch_error=False, harness=None, cases=None):
        """(argv, environment) of the driver for the labels in models."""
        (self.tmp / "fake.json").write_text(json.dumps(config or {}), encoding="utf-8")
        (self.tmp / "endpoints.json").write_text(json.dumps({"listing": listing or self.listing, "error": fetch_error}), encoding="utf-8")
        if cases is None:
            cases = self.tmp / "cases.jsonl"
            cases.write_text(case_lines(*ids), encoding="utf-8")
        argv = [sys.executable, "-c", WRAPPER, "--harness", harness or self.harness, "--models", *models, "--cases", str(cases),
                "--task-config", str(TASK_CONFIG), "--out", str(self.out), "--ledger", str(self.ledger), *map(str, args)]
        environment = clean_env(FAKE_TASK_BENCH_CONFIG=str(self.tmp / "fake.json"), FAKE_TASK_BENCH_LOG=str(self.log),
                                FAKE_TASK_BENCH_LEDGER=str(self.ledger), TASK_BENCH_TEST_ENDPOINTS=str(self.tmp / "endpoints.json"),
                                TASK_BENCH_TEST_LOG=str(self.log), **(env or {}))
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

    def calls(self, command=None):
        """What the stand-in (and the replaced endpoint function) logged, in order."""
        if not self.log.exists():
            return []
        rows = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [row for row in rows if command is None or row["command"] == command]

    def ran(self):
        """[(label, case)] of every task-bench call, in order."""
        return [(row["label"], row["case"]) for row in self.calls("task-bench")]

    def ledger_rows(self):
        if not self.ledger.exists():
            return []
        return [json.loads(line) for line in self.ledger.read_text(encoding="utf-8").splitlines() if line.strip()]

    def run_dirs(self, label, case):
        directory = self.out / label
        return sorted(p for p in directory.glob(f"{case}-{label}-*") if p.is_dir()) if directory.exists() else []

    # --- preparing a state to resume from -------------------------------------------------------------------------------

    def seed(self, label, case, status, *, cost=None, bench_error=None, over=None):
        """A finished run in <out>/<label>/ as the harness leaves it: <case>-<label>-<8 hex>/bench-result.json; over replaces fields."""
        self.counter += 1
        run_id = f"{case}-{label}-{self.counter:08x}"
        directory = self.out / label / run_id
        directory.mkdir(parents=True)
        result = {**fake_task_bench.bench_result(case, label, run_id, status, cost, bench_error=bench_error), **(over or {})}
        (directory / "bench-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return directory

    def preload(self, *amounts):
        """A ledger that holds these amounts already (None: an unknown one), as of an earlier window."""
        self.ledger.write_text("".join(json.dumps({"id": f"x{n}", "kind": "run", "label": HOSTED, "case": "AH-01", "cost_usd": a}) + "\n"
                                       for n, a in enumerate(amounts)), encoding="utf-8")


class UsageTest(DriverBase):
    """Exit 2: the call or the configuration is wrong, and nothing has started."""

    def assert_nothing_started(self):
        self.assertFalse(self.log.exists(), "the harness was called")
        self.assertFalse(self.out.exists(), "something was written under --out")
        self.assertFalse(self.ledger.exists())

    def test_a_missing_key_variable_is_a_usage_error_before_anything_starts(self):
        for what, env in (("not set", {}), ("empty", {KEY_VARIABLE: ""}), ("blank", {KEY_VARIABLE: "   "})):
            with self.subTest(what):
                self.reset()
                done = self.drive([HOSTED], env=env)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn(KEY_VARIABLE, done.stderr)
                self.assert_nothing_started()

    def test_the_key_is_wanted_for_a_label_that_is_asked_for_and_only_then(self):
        done = self.drive([LOCAL])                       # the local label needs no key, and the hosted one is not asked for
        self.assertEqual(done.returncode, 0, done.stderr)
        self.reset()
        done = self.drive([LOCAL, HOSTED])               # one label that needs the key makes the whole call need it
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assert_nothing_started()

    def test_unknown_and_repeated_labels_are_refused(self):
        done = self.drive(["nope"])
        self.assertEqual(done.returncode, 2)
        self.assertIn("nope", done.stderr)
        done = self.drive([LOCAL, LOCAL])
        self.assertEqual(done.returncode, 2)
        self.assertIn(LOCAL, done.stderr)
        self.assert_nothing_started()

    def test_the_models_file_can_be_another_and_a_hosted_label_in_it_still_needs_the_provider_block(self):
        cfg = {k: v for k, v in shipped_models()[HOSTED].items() if k != "extraBody"}
        (self.tmp / "m.json").write_text(json.dumps({HOSTED: cfg}), encoding="utf-8")
        done = self.drive([HOSTED], args=("--models-file", self.tmp / "m.json"), env={KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("provider", done.stderr)
        self.assert_nothing_started()

    def test_problems_with_the_cases_are_refused(self):
        bad = {"missing file": None, "empty": "", "no JSON": "{\n", "no object": "[1]\n", "no id": '{"x": 1}\n',
               "an id that is not a path segment": case_lines("../x"),
               "a duplicate id": case_lines("AH-01", "AH-02", "AH-01")}
        for what, text in bad.items():
            with self.subTest(what):
                self.reset()
                path = self.tmp / "bad-cases.jsonl"
                if text is not None:
                    path.write_text(text, encoding="utf-8")
                done = self.drive([LOCAL], cases=path if text is not None else self.tmp / "nothing.jsonl")
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assert_nothing_started()

    def test_a_missing_or_broken_task_config_is_refused(self):
        argv, environment = self.command([LOCAL])
        for what, content in (("missing", None), ("not JSON", "{"), ("not an object", "[]")):
            with self.subTest(what):
                path = self.tmp / "task.json"
                if content is not None:
                    path.write_text(content, encoding="utf-8")
                else:
                    path.unlink(missing_ok=True)
                changed = [str(path) if a == str(TASK_CONFIG) else a for a in argv]
                done = subprocess.run(changed, capture_output=True, text=True, env=environment, cwd=self.tmp, timeout=60)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assert_nothing_started()

    def test_the_budget_stop_has_to_be_a_positive_amount(self):
        for value in ("0", "-1", "nan", "inf", "abc"):
            with self.subTest(value):
                done = self.drive([LOCAL], args=("--budget-stop", value))
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assert_nothing_started()

    def test_missing_arguments_are_a_usage_error_with_the_same_status(self):
        done = subprocess.run([sys.executable, str(HERE / "run.py")], capture_output=True, text=True, env=clean_env(), timeout=60)
        self.assertEqual(done.returncode, 2)
        for flag in ("--harness", "--models", "--cases", "--task-config", "--out", "--ledger"):
            self.assertIn(flag, done.stderr)

    def test_a_harness_that_cannot_be_started_is_a_usage_error(self):
        done = self.drive([LOCAL], harness=str(self.tmp / "no-such-harness"))
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("harness", done.stderr)
        self.assertFalse(self.ledger.exists())
        done = self.drive([LOCAL], harness="   ")
        self.assertEqual(done.returncode, 2, done.stderr)

    def test_a_ledger_that_cannot_be_read_is_refused_before_anything_starts(self):
        self.ledger.write_text('{"cost_usd": 1.0}\nthis is no entry\n', encoding="utf-8")
        done = self.drive([LOCAL])
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("line 2", done.stderr)
        self.assertFalse(self.log.exists())

    def test_an_out_that_is_a_file_is_refused(self):
        self.out.write_text("not a directory", encoding="utf-8")
        done = self.drive([LOCAL])
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertFalse(self.log.exists())


class FlowTest(DriverBase):
    """What a normal run does, call by call and file by file."""

    def task_bench_argv(self, label, case_id, key=False, retry=False):
        argv = ["task-bench", "--case", str(self.out / "cases" / f"{case_id}.json"), "--model-config", str(self.out / f"model-{label}.json"),
                "--task-config", str(TASK_CONFIG.resolve()), "--label", label, "--out", str(self.out / label)]
        return argv + (["--api-key-env", KEY_VARIABLE] if key else []) + (["--retry-transient"] if retry else [])

    def test_the_local_label_is_probed_and_then_every_case_runs_in_the_order_of_the_file(self):
        done = self.drive([LOCAL])
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self.calls()
        self.assertEqual([c["command"] for c in calls], ["probe", "task-bench", "task-bench", "task-bench"])
        self.assertEqual([c["case"] for c in calls[1:]], ["AH-01", "AH-02", "AH-03"])
        probe = calls[0]["argv"]
        self.assertEqual(probe[:6], ["probe", "--base-url", "http://127.0.0.1:11434/v1", "--model", LOCAL_MODEL, "--out"])
        self.assertRegex(probe[6], rf"^{re.escape(str(self.out / 'probes'))}/{re.escape(LOCAL)}-{STAMP}$")
        self.assertEqual(len(probe), 7, "a local label has no key and no extra body to hand over")
        for call in calls[1:]:
            self.assertEqual(call["argv"], self.task_bench_argv(LOCAL, call["case"]))      # no key, no retry
            self.assertFalse(call["retry_transient"])
            self.assertFalse(call["key_env_set"])

    def test_the_files_the_driver_writes_for_the_harness(self):
        self.assertEqual(self.drive([LOCAL]).returncode, 0)
        self.assertEqual(json.loads((self.out / f"model-{LOCAL}.json").read_text(encoding="utf-8")),
                         {"baseUrl": "http://127.0.0.1:11434/v1", "name": LOCAL_MODEL})       # no extraBody: the label has none
        self.assertFalse((self.out / f"extra-body-{LOCAL}.json").exists())
        cases = [json.loads(line) for line in (self.tmp / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
        for case in cases:
            self.assertEqual(json.loads((self.out / "cases" / f"{case['id']}.json").read_text(encoding="utf-8")), case)

    def test_the_hosted_label_gets_the_endpoint_list_the_key_variable_the_extra_body_and_the_retry(self):
        done = self.drive([HOSTED], env={KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self.calls()
        self.assertEqual([c["command"] for c in calls], ["fetch", "probe", "task-bench", "task-bench", "task-bench"])
        self.assertEqual(calls[0]["args"], ["https://openrouter.ai/api/v1", HOSTED_MODEL])
        evidence = sorted(self.out.glob(f"endpoints-{HOSTED}-*.json"))
        self.assertEqual(len(evidence), 1)
        self.assertRegex(evidence[0].name, rf"^endpoints-{re.escape(HOSTED)}-{STAMP}\.json$")
        self.assertEqual(json.loads(evidence[0].read_text(encoding="utf-8")), self.listing)
        stamp = evidence[0].name[len(f"endpoints-{HOSTED}-"):-len(".json")]
        extra_body = self.out / f"extra-body-{HOSTED}.json"
        probe = calls[1]["argv"]
        self.assertEqual(probe[:6], ["probe", "--base-url", "https://openrouter.ai/api/v1", "--model", HOSTED_MODEL, "--out"])
        self.assertEqual(probe[6], str(self.out / "probes" / f"{HOSTED}-{stamp}"))        # one stamp for the evidence, the dir and the id
        self.assertEqual(probe[7:], ["--api-key-env", KEY_VARIABLE, "--extra-body-file", str(extra_body)])
        self.assertTrue((self.out / "probes" / f"{HOSTED}-{stamp}" / "probe-qwen-qwen3.8-27b" / "probe.json").is_file())
        self.assertEqual(json.loads(extra_body.read_text(encoding="utf-8")), real_json("extra-body-qwen3.8-openrouter.json"))
        self.assertEqual(calls[1]["extra_body"], real_json("extra-body-qwen3.8-openrouter.json"))
        # the model config is the one of the practice run: baseUrl, name and extraBody, and no key
        self.assertEqual(json.loads((self.out / f"model-{HOSTED}.json").read_text(encoding="utf-8")),
                         real_json("model-qwen3.8-openrouter.json"))
        for call in calls[2:]:
            self.assertEqual(call["argv"], self.task_bench_argv(HOSTED, call["case"], key=True, retry=True))
            self.assertTrue(call["retry_transient"])
            self.assertTrue(call["key_env_set"])
        self.assertEqual(self.ledger_rows()[0]["id"], f"probe-{HOSTED}-{stamp}")

    def test_the_endpoint_list_is_for_a_hosted_label_only_and_comes_once_per_label(self):
        done = self.drive([LOCAL, HOSTED], env={KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([c["command"] for c in self.calls()],
                         ["probe", "task-bench", "task-bench", "task-bench", "fetch", "probe", "task-bench", "task-bench", "task-bench"])
        self.assertEqual(self.ran(), [(LOCAL, c) for c in ("AH-01", "AH-02", "AH-03")] + [(HOSTED, c) for c in ("AH-01", "AH-02", "AH-03")])
        self.assertEqual(len(self.calls("fetch")), 1)

    def test_the_results_land_in_a_directory_per_label_under_out(self):
        self.assertEqual(self.drive([LOCAL]).returncode, 0)
        for case in ("AH-01", "AH-02", "AH-03"):
            [directory] = self.run_dirs(LOCAL, case)
            self.assertRegex(directory.name, rf"^{case}-{re.escape(LOCAL)}-[0-9a-f]{{8}}$")
            self.assertTrue((directory / "bench-result.json").is_file())

    def test_the_driver_says_what_it_does_and_ends_with_the_ledger(self):
        done = self.drive([LOCAL])
        self.assertEqual(done.returncode, 0, done.stderr)
        for case in ("AH-01", "AH-02", "AH-03"):
            self.assertRegex(done.stdout, rf"{LOCAL} {case}: geslaagd")
        self.assertIn("ledger", done.stdout.lower())
        self.assertEqual(done.stderr, "")

    def test_a_second_run_over_a_finished_set_probes_and_runs_nothing(self):
        self.assertEqual(self.drive([LOCAL]).returncode, 0)
        first = len(self.ran())
        self.assertEqual(self.drive([LOCAL]).returncode, 0)
        self.assertEqual(len(self.ran()), first)
        self.assertEqual(len(self.calls("probe")), 2)           # every window starts with its own probe

    def test_the_ledger_directory_is_made_when_it_is_not_there(self):
        self.ledger = self.tmp / "deeper" / "still" / "ledger.jsonl"
        self.assertEqual(self.drive([LOCAL]).returncode, 0)
        self.assertEqual(len(self.ledger_rows()), 4)


class StampTest(unittest.TestCase):
    """The <ts> of a label: UTC, whole seconds, and never one that an earlier probe or endpoint list has used already."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        real = run.datetime

        class Frozen(real):
            @classmethod
            def now(cls, tz=None):
                return real(2026, 10, 3, 8, 17, 26, 987654, tzinfo=tz)       # the second of the practice run's probe, and then some

        patcher = mock.patch.object(run, "datetime", Frozen)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.driver = run.Driver(None, self.tmp, self.tmp / "ledger.jsonl", 14.0, {}, [], self.tmp / "task.json", run.StopFlag())

    def test_the_stamp_is_the_utc_second(self):
        self.assertEqual(self.driver.free_stamp(HOSTED), "20261003T081726Z")

    def test_a_second_that_a_probe_directory_has_is_skipped(self):
        (self.tmp / "probes" / f"{HOSTED}-20261003T081726Z").mkdir(parents=True)
        self.assertEqual(self.driver.free_stamp(HOSTED), "20261003T081727Z")

    def test_a_second_that_an_endpoint_list_has_is_skipped(self):
        (self.tmp / f"endpoints-{HOSTED}-20261003T081726Z.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.driver.free_stamp(HOSTED), "20261003T081727Z")

    def test_taken_seconds_are_skipped_one_by_one_and_only_for_the_same_label(self):
        (self.tmp / "probes" / f"{HOSTED}-20261003T081726Z").mkdir(parents=True)
        (self.tmp / "probes" / f"{HOSTED}-20261003T081727Z").mkdir()
        (self.tmp / "probes" / f"{LOCAL}-20261003T081728Z").mkdir()
        self.assertEqual(self.driver.free_stamp(HOSTED), "20261003T081728Z")
        self.assertEqual(self.driver.free_stamp(LOCAL), "20261003T081726Z")


class ResumeTest(DriverBase):
    def test_a_case_with_a_result_of_a_model_status_does_not_run_again(self):
        ids = ("AH-01", "AH-02", "AH-03", "AH-04", "AH-05", "AH-06")
        for case, status in zip(ids, run.MODEL_STATUSES):
            self.seed(LOCAL, case, status)
        done = self.drive([LOCAL], ids=ids)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, "AH-06")])
        for case in ids[:5]:
            self.assertEqual(len(self.run_dirs(LOCAL, case)), 1)

    def test_the_real_result_of_the_practice_run_counts(self):
        shutil.copytree(REAL / "AH-01-qwen3.8-openrouter-d6c19fec", self.out / HOSTED / "AH-01-qwen3.8-openrouter-d6c19fec")
        done = self.drive([HOSTED], env={KEY_VARIABLE: DUMMY_KEY}, ids=("AH-01", "AH-02"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(HOSTED, "AH-02")])

    def test_a_result_of_another_label_does_not_count(self):
        self.seed(HOSTED, "AH-01", "geslaagd")
        self.assertEqual(self.drive([LOCAL], ids=("AH-01",)).returncode, 0)
        self.assertEqual(self.ran(), [(LOCAL, "AH-01")])

    def test_what_is_no_valid_result_of_this_case_and_label_does_not_count(self):
        directory = self.out / LOCAL
        cases = {"AH-01": "a result of another case", "AH-02": "a result of another label", "AH-03": "a result that is not JSON",
                 "AH-04": "a result with an unknown status", "AH-05": "a run directory without a result",
                 "AH-06": "a directory whose name is not a run id"}
        self.seed(LOCAL, "AH-01", "geslaagd", over={"caseId": "AH-09"})
        self.seed(LOCAL, "AH-02", "geslaagd", over={"label": "another"})
        broken = self.seed(LOCAL, "AH-03", "geslaagd")
        (broken / "bench-result.json").write_text("{", encoding="utf-8")
        self.seed(LOCAL, "AH-04", "geslaagd", over={"status": "gelukt"})
        (directory / f"AH-05-{LOCAL}-0badc0de").mkdir(parents=True)
        misnamed = self.seed(LOCAL, "AH-06", "geslaagd")
        misnamed.rename(directory / f"AH-06-{LOCAL}-notahex")
        done = self.drive([LOCAL], ids=tuple(cases))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, c) for c in cases])

    def test_a_case_with_one_benchfout_on_disk_runs_once_more(self):
        self.seed(LOCAL, "AH-01", "benchfout", bench_error="clone faalde")
        done = self.drive([LOCAL], ids=("AH-01", "AH-02"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, "AH-01"), (LOCAL, "AH-02")])

    def test_that_one_more_run_is_the_last_one(self):
        self.seed(LOCAL, "AH-01", "benchfout", bench_error="clone faalde")
        done = self.drive([LOCAL], ids=("AH-01", "AH-02"), config={"default": {"status": "benchfout"}})
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertIn("AH-01", done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, "AH-01")])

    def test_two_benchfouten_on_disk_stop_the_driver_without_a_new_run(self):
        self.seed(LOCAL, "AH-01", "geslaagd")
        self.seed(LOCAL, "AH-02", "benchfout", bench_error="clone faalde")
        self.seed(LOCAL, "AH-02", "benchfout")                        # a benchfout with no benchError counts too
        done = self.drive([LOCAL], ids=("AH-01", "AH-02", "AH-03"))
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertIn("AH-02", done.stderr)
        self.assertEqual(self.ran(), [])

    def test_a_result_that_was_aborted_does_not_count_as_a_benchfout(self):
        for _ in range(3):
            self.seed(LOCAL, "AH-01", "benchfout", bench_error="afgebroken")
        done = self.drive([LOCAL], ids=("AH-01", "AH-02"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, "AH-01"), (LOCAL, "AH-02")])

    def test_an_aborted_result_next_to_a_benchfout_leaves_one_more_run(self):
        self.seed(LOCAL, "AH-01", "benchfout", bench_error="afgebroken")
        self.seed(LOCAL, "AH-01", "benchfout", bench_error="clone faalde")
        done = self.drive([LOCAL], ids=("AH-01",))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, "AH-01")])

    def test_benchfouten_do_not_matter_once_the_case_has_a_result_of_a_model_status(self):
        self.seed(LOCAL, "AH-01", "benchfout")
        self.seed(LOCAL, "AH-01", "benchfout")
        self.seed(LOCAL, "AH-01", "verborgen_tests_rood")
        done = self.drive([LOCAL], ids=("AH-01", "AH-02"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, "AH-02")])


class BenchfoutTest(DriverBase):
    def test_a_first_benchfout_runs_once_more_and_the_set_goes_on(self):
        config = {"cases": {"AH-02": [{"status": "benchfout", "benchError": "clone faalde", "cost": 0.01},
                                       {"status": "geslaagd", "cost": 0.02}]}}
        done = self.drive([LOCAL], config=config)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, c) for c in ("AH-01", "AH-02", "AH-02", "AH-03")])
        self.assertEqual([r["cost_usd"] for r in self.ledger_rows() if r.get("case") == "AH-02"], [0.01, 0.02])
        self.assertEqual(len(self.run_dirs(LOCAL, "AH-02")), 2)

    def test_every_case_has_a_repeat_of_its_own(self):
        config = {"default": {"cost": 0.01}, "cases": {c: [{"status": "benchfout"}, {"status": "geslaagd"}] for c in ("AH-01", "AH-02", "AH-03")}}
        done = self.drive([LOCAL], config=config)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.ran()), 6)

    def test_a_second_benchfout_on_the_same_case_stops_the_driver_with_3(self):
        config = {"default": {"cost": 0.01}, "cases": {"AH-02": {"status": "benchfout", "benchError": "clone faalde"}}}
        done = self.drive([LOCAL], config=config)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertIn("AH-02", done.stderr)
        self.assertNotIn("AH-03", done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, "AH-01"), (LOCAL, "AH-02"), (LOCAL, "AH-02")])       # AH-03 never started
        self.assertEqual([r["cost_usd"] for r in self.ledger_rows() if r.get("case") == "AH-02"], [0.01, 0.01])   # both attempts booked

    def test_the_stop_names_the_reason_of_the_benchfout(self):
        config = {"cases": {"AH-01": {"status": "benchfout", "benchError": "clone faalde: git exit 128"}}}
        done = self.drive([LOCAL], config=config)
        self.assertEqual(done.returncode, 3)
        self.assertIn("clone faalde: git exit 128", done.stdout + done.stderr)

    def test_it_stops_also_when_the_first_case_fails_twice_and_the_other_label_never_starts(self):
        config = {"cases": {"AH-01": {"status": "benchfout"}}}
        done = self.drive([LOCAL, HOSTED], config=config, env={KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual({label for label, _ in self.ran()}, {LOCAL})
        self.assertEqual(self.calls("fetch"), [])

    def test_a_run_without_a_usable_result_is_a_benchfout_without_an_amount_and_counts_for_the_rule(self):
        broken = {"a harness that wrote no result and no directory": ({"no_result": True}, r"^AH-01-%s-geen-resultaat-%s$" % (LOCAL, STAMP)),
                  "a harness that left an empty run directory": ({"no_result": True, "make_dir": True}, None),
                  "a result that is not JSON": ({"result_text": "{"}, None),
                  "a result of another case": ({"result_case": "AH-09"}, None),
                  "a result of another label": ({"result_label": "elders"}, None),
                  "a result without a valid status": ({"result_text": json.dumps({"caseId": "AH-01", "label": LOCAL, "status": "gelukt"})}, None),
                  "two new run directories": ({"extra_runs": 1}, r"^AH-01-%s-geen-resultaat-%s$" % (LOCAL, STAMP))}
        for what, (attempt, id_pattern) in broken.items():
            with self.subTest(what):
                self.reset()
                done = self.drive([LOCAL], config={"cases": {"AH-01": {"cost": 0.5, **attempt}}}, ids=("AH-01", "AH-02"))
                self.assertEqual(done.returncode, 3, done.stderr)             # twice in a row: the second is the stop
                self.assertIn("AH-01", done.stderr)
                rows = [r for r in self.ledger_rows() if r["kind"] == "run"]
                self.assertEqual(len(rows), 2)
                for row in rows:
                    self.assertIsNone(row["cost_usd"])                          # the amount is unknown, whatever the stand-in wrote
                    self.assertRegex(row["id"], id_pattern or rf"^AH-01-{re.escape(LOCAL)}-[0-9a-f]{{8}}$")
                    self.assertEqual((row["kind"], row["label"], row["case"]), ("run", LOCAL, "AH-01"))
                self.assertEqual(self.ran(), [(LOCAL, "AH-01"), (LOCAL, "AH-01")])

    def test_the_id_of_a_run_without_a_usable_result_is_the_name_of_its_directory_when_there_is_one(self):
        done = self.drive([LOCAL], config={"cases": {"AH-01": {"result_text": "{"}}}, ids=("AH-01",))
        self.assertEqual(done.returncode, 3)
        names = sorted(p.name for p in self.run_dirs(LOCAL, "AH-01"))
        self.assertEqual(sorted(r["id"] for r in self.ledger_rows() if r["kind"] == "run"), names)

    def test_one_bad_run_followed_by_a_good_one_is_just_a_repeat(self):
        config = {"cases": {"AH-01": [{"no_result": True, "stderr": "docker: no daemon"}, {"status": "limiet", "cost": 0.3}]}}
        done = self.drive([LOCAL], config=config, ids=("AH-01", "AH-02"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("docker: no daemon", done.stdout + done.stderr)             # what the harness said is not lost
        self.assertEqual([r["cost_usd"] for r in self.ledger_rows() if r.get("case") == "AH-01"], [None, 0.3])

    def test_a_result_that_is_there_counts_whatever_the_exit_status_says(self):
        done = self.drive([LOCAL], config={"cases": {"AH-01": {"status": "geslaagd", "exit": 1}}}, ids=("AH-01", "AH-02"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, "AH-01"), (LOCAL, "AH-02")])

    def test_each_status_of_a_model_ends_the_case_at_once(self):
        for status in run.MODEL_STATUSES:
            with self.subTest(status):
                self.reset()
                done = self.drive([LOCAL], config={"default": {"status": status}}, ids=("AH-01", "AH-02"))
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(len(self.ran()), 2)


class LedgerTest(DriverBase):
    def test_every_run_and_every_probe_is_a_line_in_the_ledger(self):
        config = {"default": {"cost": 0.25}}
        done = self.drive([LOCAL], config=config)
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = self.ledger_rows()
        self.assertEqual([r["kind"] for r in rows], ["probe", "run", "run", "run"])
        probe, runs = rows[0], rows[1:]
        self.assertEqual(list(probe), ["id", "kind", "label", "cost_usd"])
        self.assertRegex(probe["id"], rf"^probe-{re.escape(LOCAL)}-{STAMP}$")
        self.assertEqual(probe["label"], LOCAL)
        for row, case in zip(runs, ("AH-01", "AH-02", "AH-03")):
            self.assertEqual(list(row), ["id", "kind", "label", "case", "cost_usd"])
            self.assertEqual((row["label"], row["case"], row["cost_usd"]), (LOCAL, case, 0.25))
            self.assertEqual(row["id"], self.run_dirs(LOCAL, case)[0].name)

    def test_a_probe_is_booked_before_the_first_run_and_each_run_before_the_next_paid_call(self):
        done = self.drive([LOCAL, HOSTED], env={KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(done.returncode, 0, done.stderr)
        paid = [c for c in self.calls() if c["command"] != "fetch"]
        self.assertEqual([c["ledger_lines"] for c in paid], list(range(8)))       # at call n the n calls before it are booked

    def test_a_missing_amount_is_null_in_the_ledger(self):
        self.assertEqual(self.drive([LOCAL]).returncode, 0)
        text = self.ledger.read_text(encoding="utf-8")
        self.assertEqual(text.count('"cost_usd": null'), 4)        # the probe and the three runs of a local model: no amount
        self.assertEqual([r["cost_usd"] for r in self.ledger_rows()], [None] * 4)

    def test_the_cost_of_a_probe_is_the_sum_of_every_amount_in_it(self):
        amounts = probe_amounts(real_json("probe-qwen-qwen3.8-27b", "probe.json"))        # five different amounts above 0
        self.assertEqual(len(set(amounts)), 5)
        done = self.drive([HOSTED], config={"probe": {"costs": amounts}}, env={KEY_VARIABLE: DUMMY_KEY}, ids=("AH-01",))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ledger_rows()[0]["cost_usd"], 0.00077981)
        self.reset()
        synthetic = [0.001, 0.002, 0.004, 0.008, 0.016]
        self.assertEqual(self.drive([HOSTED], config={"probe": {"costs": synthetic}}, env={KEY_VARIABLE: DUMMY_KEY}, ids=("AH-01",)).returncode, 0)
        self.assertEqual(self.ledger_rows()[0]["cost_usd"], math.fsum(synthetic))

    def test_a_probe_without_any_amount_is_null(self):
        self.assertEqual(self.drive([HOSTED], env={KEY_VARIABLE: DUMMY_KEY}, ids=("AH-01",)).returncode, 0)
        self.assertIsNone(self.ledger_rows()[0]["cost_usd"])

    def test_the_ledger_is_added_to_never_rewritten(self):
        shutil.copy(REAL / "ledger.jsonl", self.ledger)
        before = self.ledger.read_text(encoding="utf-8")
        self.assertEqual(self.drive([HOSTED], env={KEY_VARIABLE: DUMMY_KEY}, ids=("AH-02",)).returncode, 0)
        self.assertTrue(self.ledger.read_text(encoding="utf-8").startswith(before))
        self.assertEqual(len(self.ledger_rows()), 4)

    # --- the stop at the budget ---------------------------------------------------------------------------------------

    def test_a_total_of_14_dollars_or_more_starts_no_run(self):
        for total in (14.0, 14.5):
            with self.subTest(total=total):
                self.reset()
                self.preload(total)
                done = self.drive([LOCAL])
                self.assertEqual(done.returncode, 4, done.stderr)
                self.assertEqual(self.ran(), [])
                self.assertIn("14", done.stderr)

    def test_a_total_under_14_dollars_does_not_stop_it(self):
        self.preload(13.99)
        done = self.drive([LOCAL])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.ran()), 3)

    def test_the_ledger_of_the_practice_run_counts(self):
        shutil.copy(REAL / "ledger.jsonl", self.ledger)                       # 0.0666 in it
        with self.ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "x", "kind": "run", "label": HOSTED, "case": "AH-09", "cost_usd": 13.95}) + "\n")
        done = self.drive([LOCAL])                                            # 13.95 alone is under 14, with the practice run it is not
        self.assertEqual(done.returncode, 4, done.stderr)
        self.assertEqual(self.ran(), [])

    def test_a_missing_amount_counts_as_zero_in_the_total(self):
        self.preload(13.5, None, None, 0.25)
        done = self.drive([LOCAL])
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_total_is_an_exact_sum(self):
        self.preload(*[0.1] * 10)                      # added up one by one that is 0.9999999999999999, summed exactly 1.0
        done = self.drive([LOCAL], args=("--budget-stop", "1"))
        self.assertEqual(done.returncode, 4, done.stderr)

    def test_a_run_that_takes_the_total_over_the_line_is_the_last_one(self):
        self.preload(13.9)
        done = self.drive([LOCAL], config={"default": {"cost": 0.2}})
        self.assertEqual(done.returncode, 4, done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, "AH-01")])
        self.assertEqual(self.ledger_rows()[-1]["cost_usd"], 0.2)             # that run is booked

    def test_the_repeat_of_a_benchfout_looks_at_the_budget_too(self):
        self.preload(13.6)
        done = self.drive([LOCAL], config={"cases": {"AH-01": {"status": "benchfout", "cost": 0.5}}})
        self.assertEqual(done.returncode, 4, done.stderr)                     # not 3: the second attempt never started
        self.assertEqual(self.ran(), [(LOCAL, "AH-01")])

    def test_the_stop_can_be_set(self):
        self.preload(5.0)
        done = self.drive([LOCAL], args=("--budget-stop", "5"))
        self.assertEqual(done.returncode, 4, done.stderr)
        self.reset()
        self.preload(5.0)
        self.assertEqual(self.drive([LOCAL], args=("--budget-stop", "5.01")).returncode, 0)

    def test_the_budget_is_the_ledger_not_the_label(self):
        self.preload(14.0)
        done = self.drive([LOCAL, HOSTED], env={KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(done.returncode, 4, done.stderr)
        self.assertEqual(self.ran(), [])


class ProbeEndpointsTest(DriverBase):
    def test_a_probe_that_is_not_reliable_stops_the_driver_with_5(self):
        for verdict in ("unreliable", "none"):
            with self.subTest(verdict):
                self.reset()
                done = self.drive([LOCAL], config={"probe": {"verdict": verdict, "costs": [0.001, 0.002, 0.004, 0.008, 0.016]}})
                self.assertEqual(done.returncode, 5, done.stderr)
                self.assertIn(verdict, done.stderr)
                self.assertEqual(self.ran(), [])
                [row] = self.ledger_rows()                          # what the probe cost is booked all the same
                self.assertEqual(row["kind"], "probe")
                self.assertGreater(row["cost_usd"], 0)

    def test_a_probe_that_wrote_no_probe_json_is_a_stop_with_5_and_an_unknown_cost(self):
        done = self.drive([LOCAL], config={"probe": {"crash": "connection refused"}})
        self.assertEqual(done.returncode, 5, done.stderr)
        self.assertIn("connection refused", done.stdout + done.stderr)
        self.assertEqual(self.ran(), [])
        [row] = self.ledger_rows()
        self.assertEqual((row["kind"], row["label"], row["cost_usd"]), ("probe", LOCAL, None))

    def test_a_probe_json_without_a_verdict_is_not_reliable(self):
        # the stand-in writes what it is told; here the verdict is a word the harness does not use
        done = self.drive([LOCAL], config={"probe": {"verdict": "zeker"}})
        self.assertEqual(done.returncode, 5, done.stderr)
        self.assertEqual(self.ran(), [])

    def test_a_later_label_is_not_probed_once_an_earlier_one_stops_the_driver(self):
        config = {"probe_by_model": {LOCAL_MODEL: {"verdict": "unreliable"}}}
        done = self.drive([LOCAL, HOSTED], config=config, env={KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(done.returncode, 5, done.stderr)
        self.assertEqual([c["command"] for c in self.calls()], ["probe"])

    def test_the_hosted_probe_failing_comes_after_the_local_cases_that_ran(self):
        config = {"probe_by_model": {HOSTED_MODEL: {"verdict": "unreliable"}}}
        done = self.drive([LOCAL, HOSTED], config=config, env={KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(done.returncode, 5, done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, c) for c in ("AH-01", "AH-02", "AH-03")])

    def test_without_a_16_bit_endpoint_with_tools_the_driver_stops_with_5_and_keeps_the_evidence(self):
        listing = without_deepinfra(self.listing)
        done = self.drive([HOSTED], listing=listing, env={KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(done.returncode, 5, done.stderr)
        self.assertIn("16-bit", done.stderr)
        self.assertEqual([c["command"] for c in self.calls()], ["fetch"])           # no probe, no run
        [evidence] = sorted(self.out.glob(f"endpoints-{HOSTED}-*.json"))
        self.assertEqual(json.loads(evidence.read_text(encoding="utf-8")), listing)
        self.assertEqual(self.ledger_rows(), [])

    def test_an_endpoint_list_that_cannot_be_fetched_is_a_stop_with_5(self):
        done = self.drive([HOSTED], fetch_error=True, env={KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(done.returncode, 5, done.stderr)
        self.assertIn("endpoint", done.stderr)
        self.assertIn("OSError", done.stderr)                   # the kind of error, not its text
        self.assertEqual([c["command"] for c in self.calls()], ["fetch"])

    def test_the_endpoint_list_is_fetched_from_the_public_models_url_without_a_key(self):
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, *args):
                return json.dumps({"data": {"endpoints": []}}).encode()

        def urlopen(request, timeout=None):
            captured["url"], captured["headers"], captured["timeout"] = request.full_url, dict(request.header_items()), timeout
            return Response()

        original = run.urllib.request.urlopen
        run.urllib.request.urlopen = urlopen
        self.addCleanup(setattr, run.urllib.request, "urlopen", original)
        listing = run.fetch_endpoints("https://openrouter.ai/api/v1", HOSTED_MODEL)
        self.assertEqual(listing, {"data": {"endpoints": []}})
        self.assertEqual(captured["url"], "https://openrouter.ai/api/v1/models/qwen/qwen3.8-27b/endpoints")
        self.assertFalse({"Authorization", "authorization"} & set(captured["headers"]))
        self.assertEqual(captured["headers"].get("User-agent"), "llm-bench-task-bench/1")      # urllib capitalizes the name so
        self.assertGreater(captured["timeout"], 0)


class KeyTest(DriverBase):
    def run_hosted(self, **kw):
        done = self.drive([HOSTED, LOCAL], env={KEY_VARIABLE: DUMMY_KEY}, **kw)
        return done

    def test_the_value_of_the_key_is_nowhere_and_only_the_name_is_handed_over(self):
        done = self.run_hosted(config={"default": {"cost": 0.1}, "probe": {"costs": [0.001] * 5}})
        self.assertEqual(done.returncode, 0, done.stderr)
        for where, text in (("stdout", done.stdout), ("stderr", done.stderr), ("the ledger", self.ledger.read_text(encoding="utf-8")),
                            ("the calls", self.log.read_text(encoding="utf-8"))):
            with self.subTest(where):
                self.assertNotIn(DUMMY_KEY, text)
        hosted = [c for c in self.calls() if c["command"] in ("probe", "task-bench") and (c.get("label") == HOSTED or c.get("model") == HOSTED_MODEL)]
        self.assertEqual(len(hosted), 4)
        for call in hosted:
            argv = call["argv"]
            self.assertEqual(argv[argv.index("--api-key-env") + 1], KEY_VARIABLE)
            self.assertEqual(argv.count("--api-key-env"), 1)
            self.assertTrue(call["key_env_set"])                      # the value travelled in the environment
        local = [c for c in self.calls() if c.get("label") == LOCAL or c.get("model") == LOCAL_MODEL]
        self.assertTrue(local and all("--api-key-env" not in c["argv"] for c in local))
        files = [p for p in self.out.rglob("*") if p.is_file()]
        self.assertGreater(len(files), 10)
        for path in files:
            self.assertNotIn(DUMMY_KEY, path.read_text(encoding="utf-8"), path.name)

    def test_check_key_finds_nothing_under_out(self):
        self.assertEqual(self.run_hosted().returncode, 0)
        checked = subprocess.run([sys.executable, str(CHECK_KEY), "--env", KEY_VARIABLE, str(self.out)], capture_output=True, text=True,
                                 env=clean_env(**{KEY_VARIABLE: DUMMY_KEY}), timeout=60)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertRegex(checked.stdout, r"files_scanned=[1-9]\d* unreadable=0 with_key=0")

    def test_check_key_does_find_a_key_when_one_is_there(self):
        # the check has teeth: the same call over a directory with the value in a file does not pass
        self.assertEqual(self.run_hosted().returncode, 0)
        (self.out / "planted.txt").write_text(f"x {DUMMY_KEY} y", encoding="utf-8")
        checked = subprocess.run([sys.executable, str(CHECK_KEY), "--env", KEY_VARIABLE, str(self.out)], capture_output=True, text=True,
                                 env=clean_env(**{KEY_VARIABLE: DUMMY_KEY}), timeout=60)
        self.assertEqual(checked.returncode, 1)

    def test_what_the_harness_says_is_masked_when_it_is_quoted(self):
        echo = f"boom: the server echoed {DUMMY_KEY} and {DUMMY_KEY.strip()} back"
        config = {"cases": {"AH-01": {"no_result": True, "stderr": echo}}}
        done = self.drive([HOSTED], env={KEY_VARIABLE: DUMMY_KEY}, config=config, ids=("AH-01",))
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertIn("boom", done.stdout + done.stderr)             # it is quoted ...
        self.assertNotIn(DUMMY_KEY, done.stdout + done.stderr)       # ... without the key
        self.assertIn("<redacted>", done.stdout + done.stderr)
        self.assertNotIn(DUMMY_KEY, self.ledger.read_text(encoding="utf-8"))

    def test_mask_secrets_masks_the_value_and_its_trimmed_form_and_cuts_after_the_masking(self):
        self.assertEqual(run.mask_secrets("a secret and short", ["secret"]), "a secret and short")      # a placeholder is left alone
        self.assertEqual(run.mask_secrets(f"a {DUMMY_KEY} b", [DUMMY_KEY]), "a <redacted> b")
        self.assertEqual(run.mask_secrets(f"a {DUMMY_KEY} b", [f" {DUMMY_KEY}\n"]), "a <redacted> b")      # the trimmed form too
        self.assertEqual(run.excerpt(f"{'x' * 295}{DUMMY_KEY} more", [DUMMY_KEY]).count(DUMMY_KEY[:6]), 0)    # masked before the cut


class StopTest(DriverBase):
    """SIGINT and SIGTERM: the driver sets a flag and waits for the bench, as `pkill -s` in the window needs it to."""

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
        config = {"cases": {"AH-01": [{"wait_for_signal": True, "marker": str(marker), "cost": 0.25}, {"status": "geslaagd", "cost": 0.5}]},
                  "default": {"cost": 0.5}}
        proc = self.start([LOCAL], config=config)
        self.wait_for(marker, proc)
        os.killpg(proc.pid, signum)             # to the group, as pkill -s does: the driver and the bench both get it
        stdout, stderr = proc.communicate(timeout=60)
        return proc.returncode, stdout, stderr

    def check_aborted_run(self, status, stderr):
        self.assertEqual(status, 6, stderr)
        [directory] = self.run_dirs(LOCAL, "AH-01")
        result = json.loads((directory / "bench-result.json").read_text(encoding="utf-8"))   # the bench was left to write it
        self.assertEqual((result["status"], result["benchError"]), ("benchfout", "afgebroken"))
        rows = self.ledger_rows()
        self.assertEqual([r["kind"] for r in rows], ["probe", "run"])
        self.assertEqual((rows[1]["case"], rows[1]["cost_usd"], rows[1]["id"]), ("AH-01", 0.25, directory.name))   # its cost is booked
        self.assertEqual(self.ran(), [(LOCAL, "AH-01")])                         # AH-02 did not start

    def test_sigint_to_the_group_lets_the_running_bench_finish_and_stops_with_6(self):
        status, stdout, stderr = self.stop_during_a_run(signal.SIGINT)
        self.check_aborted_run(status, stderr)

    def test_sigterm_to_the_group_does_the_same(self):
        status, stdout, stderr = self.stop_during_a_run(signal.SIGTERM)
        self.check_aborted_run(status, stderr)

    def test_the_aborted_run_is_run_again_when_the_driver_resumes_and_is_no_benchfout(self):
        status, stdout, stderr = self.stop_during_a_run(signal.SIGINT)
        self.check_aborted_run(status, stderr)
        done = self.drive([LOCAL], config={"cases": {"AH-01": {"status": "geslaagd", "cost": 0.5}}, "default": {"cost": 0.5}})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, c) for c in ("AH-01", "AH-01", "AH-02", "AH-03")])
        self.assertEqual(len(self.run_dirs(LOCAL, "AH-01")), 2)             # the aborted evidence stays, next to the new run

    def test_a_signal_during_the_probe_stops_before_the_first_run(self):
        done = self.drive([LOCAL], config={"probe": {"sigint_parent": True, "costs": [0.001] * 5}})
        self.assertEqual(done.returncode, 6, done.stderr)
        self.assertEqual([c["command"] for c in self.calls()], ["probe"])
        [row] = self.ledger_rows()
        self.assertEqual((row["kind"], row["cost_usd"]), ("probe", math.fsum([0.001] * 5)))       # the probe is booked

    def test_a_signal_during_a_run_that_ends_normally_stops_before_the_next_case(self):
        done = self.drive([LOCAL], config={"cases": {"AH-01": {"sigint_parent": True, "status": "geslaagd", "cost": 0.1}}})
        self.assertEqual(done.returncode, 6, done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, "AH-01")])
        self.assertEqual([r["cost_usd"] for r in self.ledger_rows() if r["kind"] == "run"], [0.1])

    def test_the_repeat_of_a_benchfout_does_not_start_after_a_signal(self):
        done = self.drive([LOCAL], config={"cases": {"AH-01": {"sigint_parent": True, "status": "benchfout", "cost": 0.1}}})
        self.assertEqual(done.returncode, 6, done.stderr)               # not 3 and not a second attempt
        self.assertEqual(self.ran(), [(LOCAL, "AH-01")])

    def test_a_signal_during_the_last_run_of_a_label_stops_before_the_next_label(self):
        done = self.drive([LOCAL, HOSTED], env={KEY_VARIABLE: DUMMY_KEY},
                          config={"cases": {f"{LOCAL}/AH-03": {"sigint_parent": True, "status": "geslaagd"}}})
        self.assertEqual(done.returncode, 6, done.stderr)
        self.assertEqual([label for label, _ in self.ran()], [LOCAL] * 3)
        self.assertEqual(self.calls("fetch"), [])                         # no endpoint list, no probe for the next label
        self.assertEqual(len(self.calls("probe")), 1)

    def test_a_signal_is_a_stop_even_when_nothing_is_left_to_do(self):
        done = self.drive([LOCAL], ids=("AH-01",), config={"cases": {"AH-01": {"sigint_parent": True}}})
        self.assertEqual(done.returncode, 6, done.stderr)
        self.assertEqual(len(self.ledger_rows()), 2)

    def test_a_bench_that_reports_itself_aborted_stops_the_driver_even_without_a_signal(self):
        # somebody stopped only the bench (pkill on the node process): the driver neither repeats it nor goes on to the next case
        done = self.drive([LOCAL], config={"cases": {"AH-01": {"status": "benchfout", "benchError": "afgebroken", "cost": 0.4}}})
        self.assertEqual(done.returncode, 6, done.stderr)
        self.assertEqual(self.ran(), [(LOCAL, "AH-01")])
        self.assertEqual(self.ledger_rows()[-1]["cost_usd"], 0.4)


class NamedPipeTest(DriverBase):
    """The work trees of the real bench (ws/, ws-deps/) can hold a named pipe, and opening one hangs: nothing may read them."""

    def test_the_driver_reads_only_bench_result_json_of_a_run(self):
        done = self.drive([LOCAL], config={"default": {"fifo": True}}, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        pipes = list(self.out.glob(f"{LOCAL}/*/ws/fifo"))
        self.assertEqual(len(pipes), 3)
        again = self.drive([LOCAL], config={"default": {"fifo": True}}, timeout=60)         # resuming looks at the run directories
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(len(self.ran()), 3)


# ---------------------------------------------------------------------------------------------------------------------
# the scorer
# ---------------------------------------------------------------------------------------------------------------------

class ScoreBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.counter = 0
        self.clock = 1_700_000_000

    def put(self, root, label, case, status, *, cost=None, mtime=None, bench_error=None, over=None):
        """A finished run at <root>/<label>/<case>-<label>-<8 hex>/bench-result.json; mtime in seconds (default: each one later);
        over replaces fields of the result."""
        self.counter += 1
        run_id = f"{case}-{label}-{self.counter:08x}"
        directory = Path(root) / label / run_id
        directory.mkdir(parents=True)
        result = {**fake_task_bench.bench_result(case, label, run_id, status, cost, bench_error=bench_error), **(over or {})}
        path = directory / "bench-result.json"
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        self.clock += 10
        stamp = (self.clock if mtime is None else mtime) * 10**9
        os.utime(path, ns=(stamp, stamp))
        return directory

    def full_set(self, root, label, geslaagd, cases=CASES_12, other="verify_rood"):
        """12 runs of label, the first `geslaagd` of them geslaagd and the rest of another model status."""
        for n, case in enumerate(cases):
            self.put(root, label, case, "geslaagd" if n < geslaagd else other, cost=0.05)

    def score(self, root, *models, args=(), timeout=60):
        return subprocess.run([sys.executable, str(HERE / "score.py"), str(root), "--models", *models, *map(str, args)],
                              capture_output=True, text=True, env=clean_env(), timeout=timeout)

    def summary(self, root):
        return read_summary(root)


class ScoreTest(ScoreBase):
    def test_a_complete_set_gets_a_table_the_counts_the_verdict_and_a_summary(self):
        self.full_set(self.tmp, HOSTED, 10)
        self.full_set(self.tmp, LOCAL, 4)
        done = self.score(self.tmp, HOSTED, LOCAL)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Oordeel: meerwaarde", done.stdout)
        self.assertRegex(done.stdout, rf"{re.escape(HOSTED)}\D+10 van 12")
        self.assertRegex(done.stdout, rf"{re.escape(LOCAL)}\D+4 van 12")
        for case in CASES_12:
            self.assertRegex(done.stdout, rf"\|\s*{case}\s*\|")
        rows = self.summary(self.tmp)
        self.assertEqual(len(rows), 24)
        self.assertEqual({r["label"] for r in rows}, {HOSTED, LOCAL})
        self.assertEqual(sorted({r["case"] for r in rows}), sorted(CASES_12))
        self.assertEqual(sum(r["status"] == "geslaagd" for r in rows if r["label"] == HOSTED), 10)

    def test_the_first_label_is_the_hosted_one_in_the_verdict(self):
        self.full_set(self.tmp, HOSTED, 12)
        self.full_set(self.tmp, LOCAL, 2)
        self.assertIn("Oordeel: meerwaarde", self.score(self.tmp, HOSTED, LOCAL).stdout)
        self.assertIn("Oordeel: gezakt", self.score(self.tmp, LOCAL, HOSTED).stdout)       # hosted 2, gsq 12

    def test_a_verdict_on_the_edge_is_onbeslist(self):
        self.full_set(self.tmp, HOSTED, 9)
        self.full_set(self.tmp, LOCAL, 3)
        self.assertIn("Oordeel: onbeslist", self.score(self.tmp, HOSTED, LOCAL).stdout)

    def test_the_real_result_is_read_into_the_summary(self):
        shutil.copytree(REAL / "AH-01-qwen3.8-openrouter-d6c19fec", self.tmp / HOSTED / "AH-01-qwen3.8-openrouter-d6c19fec")
        self.full_set(self.tmp, HOSTED, 11, cases=CASES_12[1:])
        self.full_set(self.tmp, LOCAL, 3)
        self.assertEqual(self.score(self.tmp, HOSTED, LOCAL).returncode, 0)
        [row] = [r for r in self.summary(self.tmp) if (r["label"], r["case"]) == (HOSTED, "AH-01")]
        self.assertEqual(row["status"], "geslaagd")
        self.assertEqual(row["run_id"], "AH-01-qwen3.8-openrouter-d6c19fec")
        self.assertEqual(float(row["cost_usd"]), 0.065849775)
        self.assertEqual((row["model_turns"], row["tool_calls"], row["tool_errors"]), ("12", "17", "0"))
        self.assertEqual((row["input_tokens"], row["output_tokens"]), ("279211", "12783"))
        self.assertEqual(float(row["duration_s"]), 1030.562)
        self.assertEqual((row["providers"], row["retries"], row["attempts"]), ("DeepInfra", "0", "1"))

    def test_a_missing_amount_is_an_empty_cell(self):
        self.put(self.tmp, HOSTED, "AH-01", "geslaagd", cost=None)
        for case in CASES_12[1:]:
            self.put(self.tmp, HOSTED, case, "geslaagd", cost=0.05)
        self.full_set(self.tmp, LOCAL, 3)
        self.assertEqual(self.score(self.tmp, HOSTED, LOCAL).returncode, 0)
        [row] = [r for r in self.summary(self.tmp) if (r["label"], r["case"]) == (HOSTED, "AH-01")]
        self.assertEqual(row["cost_usd"], "")

    def test_results_in_other_directories_of_the_tree_are_found_too(self):
        self.full_set(self.tmp / "gehost", HOSTED, 10)
        self.full_set(self.tmp / "gsq", LOCAL, 4)
        done = self.score(self.tmp, HOSTED, LOCAL)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Oordeel: meerwaarde", done.stdout)

    def test_a_run_outside_a_directory_named_after_its_label_is_not_the_drivers_and_does_not_count(self):
        # the practice run sits in proef/<run>, with no label directory; its case is not one of these 12, so counting it makes 13
        cases = CASES_12[1:] + ["SM-07"]
        self.full_set(self.tmp / "gehost", HOSTED, 10, cases=cases)
        self.full_set(self.tmp / "gsq", LOCAL, 4, cases=cases)
        shutil.copytree(REAL / "AH-01-qwen3.8-openrouter-d6c19fec", self.tmp / "proef" / "AH-01-qwen3.8-openrouter-d6c19fec")
        done = self.score(self.tmp, HOSTED, LOCAL)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.summary(self.tmp)), 24)
        self.assertNotIn("AH-01", {r["case"] for r in self.summary(self.tmp)})

    def test_the_last_result_of_a_case_counts_by_the_mtime_of_its_file(self):
        self.full_set(self.tmp, LOCAL, 4)
        self.full_set(self.tmp, HOSTED, 10, cases=CASES_12[1:])
        self.put(self.tmp, HOSTED, "AH-01", "benchfout", bench_error="clone faalde", mtime=1_700_000_100)     # older
        self.put(self.tmp, HOSTED, "AH-01", "geslaagd", mtime=1_700_000_200)                                    # newer: the repeat
        done = self.score(self.tmp, HOSTED, LOCAL)
        self.assertEqual(done.returncode, 0, done.stderr)
        [row] = [r for r in self.summary(self.tmp) if (r["label"], r["case"]) == (HOSTED, "AH-01")]
        self.assertEqual((row["status"], row["attempts"]), ("geslaagd", "2"))

    def test_a_benchfout_as_the_last_status_is_refused_even_after_a_valid_result(self):
        self.full_set(self.tmp, LOCAL, 4)
        self.full_set(self.tmp, HOSTED, 10, cases=CASES_12[1:])
        self.put(self.tmp, HOSTED, "AH-01", "geslaagd", mtime=1_700_000_100)
        self.put(self.tmp, HOSTED, "AH-01", "benchfout", bench_error="clone faalde", mtime=1_700_000_200)
        done = self.score(self.tmp, HOSTED, LOCAL)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("AH-01", done.stderr)
        self.assertIn("benchfout", done.stderr)
        self.assertFalse((self.tmp / "summary.csv").exists())
        self.assertNotIn("Oordeel", done.stdout)

    def test_an_aborted_run_as_the_last_status_is_refused(self):
        self.full_set(self.tmp, LOCAL, 4)
        self.full_set(self.tmp, HOSTED, 10, cases=CASES_12[1:])
        self.put(self.tmp, HOSTED, "AH-01", "benchfout", bench_error="afgebroken")
        self.assertEqual(self.score(self.tmp, HOSTED, LOCAL).returncode, 2)

    def test_equal_mtimes_leave_no_doubt_in_favour_of_a_verdict(self):
        self.full_set(self.tmp, LOCAL, 4)
        self.full_set(self.tmp, HOSTED, 10, cases=CASES_12[1:])
        self.put(self.tmp, HOSTED, "AH-01", "geslaagd", mtime=1_700_000_100)
        self.put(self.tmp, HOSTED, "AH-01", "benchfout", mtime=1_700_000_100)
        done = self.score(self.tmp, HOSTED, LOCAL)
        self.assertEqual(done.returncode, 2, done.stderr)        # which one is last cannot be told: no verdict

    def test_fewer_than_12_cases_with_a_result_is_refused(self):
        self.full_set(self.tmp, LOCAL, 4)
        self.full_set(self.tmp, HOSTED, 10, cases=CASES_12[:11])
        done = self.score(self.tmp, HOSTED, LOCAL)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(HOSTED, done.stderr)
        self.assertIn("11", done.stderr)
        self.assertFalse((self.tmp / "summary.csv").exists())

    def test_more_than_12_cases_is_refused_too(self):
        self.full_set(self.tmp, LOCAL, 4)
        self.full_set(self.tmp, HOSTED, 10)
        self.put(self.tmp, HOSTED, "SM-07", "geslaagd")
        done = self.score(self.tmp, HOSTED, LOCAL)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("13", done.stderr)

    def test_a_label_without_any_result_is_refused(self):
        self.full_set(self.tmp, HOSTED, 10)
        done = self.score(self.tmp, HOSTED, LOCAL)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(LOCAL, done.stderr)

    def test_two_labels_with_different_cases_are_refused(self):
        self.full_set(self.tmp, HOSTED, 10)
        self.full_set(self.tmp, LOCAL, 4, cases=CASES_12[:11] + ["SM-09"])
        done = self.score(self.tmp, HOSTED, LOCAL)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("SM-09", done.stderr)
        self.assertIn("SM-06", done.stderr)

    def test_one_case_twice_does_not_make_two_cases(self):
        self.full_set(self.tmp, LOCAL, 4)
        self.full_set(self.tmp, HOSTED, 10, cases=CASES_12[:11])
        self.put(self.tmp, HOSTED, "AH-01", "geslaagd")
        self.assertEqual(self.score(self.tmp, HOSTED, LOCAL).returncode, 2)       # 11 different cases, one of them twice

    def test_a_run_whose_result_says_another_label_or_case_than_its_place_does_not_count(self):
        self.full_set(self.tmp, LOCAL, 4)
        self.full_set(self.tmp, HOSTED, 10, cases=CASES_12[1:])
        self.put(self.tmp, HOSTED, "AH-01", "geslaagd", over={"label": "elders"})
        broken = self.put(self.tmp, HOSTED, "AH-01", "geslaagd")
        (broken / "bench-result.json").write_text("{", encoding="utf-8")
        self.assertEqual(self.score(self.tmp, HOSTED, LOCAL).returncode, 2)

    def test_usage_problems_exit_2(self):
        self.full_set(self.tmp, HOSTED, 10)
        self.full_set(self.tmp, LOCAL, 4)
        self.assertEqual(self.score(self.tmp / "nothing", HOSTED, LOCAL).returncode, 2)         # no such directory
        self.assertEqual(self.score(self.tmp, HOSTED, HOSTED).returncode, 2)                   # one label twice
        done = subprocess.run([sys.executable, str(HERE / "score.py"), str(self.tmp), "--models", HOSTED],
                              capture_output=True, text=True, env=clean_env(), timeout=60)
        self.assertEqual(done.returncode, 2)                                                    # two labels are needed
        done = subprocess.run([sys.executable, str(HERE / "score.py"), str(self.tmp)], capture_output=True, text=True,
                              env=clean_env(), timeout=60)
        self.assertEqual(done.returncode, 2)

    # --- the ledger (R30) -------------------------------------------------------------------------------------------

    def ledger(self, *amounts):
        path = self.tmp / "ledger.jsonl"
        path.write_text("".join(json.dumps({"id": f"x{n}", "kind": "run", "label": HOSTED, "case": "AH-01", "cost_usd": a}) + "\n"
                                for n, a in enumerate(amounts)), encoding="utf-8")
        return path

    def test_with_a_ledger_the_total_and_the_number_of_missing_amounts_are_printed(self):
        self.full_set(self.tmp, HOSTED, 10)
        self.full_set(self.tmp, LOCAL, 4)
        ledger = self.ledger(1.25, None, 0.25, None, None)
        done = self.score(self.tmp, HOSTED, LOCAL, args=("--ledger", ledger))
        self.assertEqual(done.returncode, 0, done.stderr)
        line = next(l for l in done.stdout.splitlines() if l.startswith("Grootboek"))
        self.assertIn("$1.5000", line)
        self.assertRegex(line, r"3\D+zonder bedrag")
        self.assertIn("5 regels", line)

    def test_without_a_ledger_there_are_no_budget_lines(self):
        self.full_set(self.tmp, HOSTED, 10)
        self.full_set(self.tmp, LOCAL, 4)
        done = self.score(self.tmp, HOSTED, LOCAL)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Oordeel", done.stdout)
        self.assertNotIn("Grootboek", done.stdout)

    def test_a_ledger_that_cannot_be_read_is_refused(self):
        self.full_set(self.tmp, HOSTED, 10)
        self.full_set(self.tmp, LOCAL, 4)
        bad = self.tmp / "bad.jsonl"
        bad.write_text("no entry\n", encoding="utf-8")
        self.assertEqual(self.score(self.tmp, HOSTED, LOCAL, args=("--ledger", bad)).returncode, 2)

    def test_the_ledger_of_the_practice_run_adds_up_in_the_report(self):
        self.full_set(self.tmp, HOSTED, 10)
        self.full_set(self.tmp, LOCAL, 4)
        done = self.score(self.tmp, HOSTED, LOCAL, args=("--ledger", REAL / "ledger.jsonl"))
        self.assertIn("$0.0666", done.stdout)

    # --- the named pipe ------------------------------------------------------------------------------------------

    def test_the_work_trees_of_a_run_are_never_opened_or_walked(self):
        self.full_set(self.tmp, HOSTED, 10)
        self.full_set(self.tmp, LOCAL, 4)
        for directory in list((self.tmp / HOSTED).iterdir()) + list((self.tmp / LOCAL).iterdir()):
            (directory / "ws").mkdir()
            os.mkfifo(directory / "ws" / "fifo")                # opening it for reading blocks for ever
            (directory / "ws-deps").mkdir()
            os.mkfifo(directory / "ws-deps" / "fifo")
        os.mkfifo(self.tmp / HOSTED / "stray-pipe")             # even a pipe where a run directory should be
        done = self.score(self.tmp, HOSTED, LOCAL, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_bench_result_that_is_a_named_pipe_is_no_result(self):
        self.full_set(self.tmp, LOCAL, 4)
        self.full_set(self.tmp, HOSTED, 10, cases=CASES_12[1:])
        directory = self.tmp / HOSTED / f"AH-01-{HOSTED}-0000ffff"
        directory.mkdir()
        os.mkfifo(directory / "bench-result.json")
        done = self.score(self.tmp, HOSTED, LOCAL, timeout=60)
        self.assertEqual(done.returncode, 2, done.stderr)


# ---------------------------------------------------------------------------------------------------------------------
# the driver and the scorer on each other's files
# ---------------------------------------------------------------------------------------------------------------------

class PipelineTest(DriverBase):
    """What run.py leaves is what score.py reads: the layout is the seam between them, and each is otherwise tested on its own."""

    def answers(self, hosted_geslaagd, gsq_geslaagd):
        """A fake-harness config for 12 cases: the first hosted_geslaagd of them geslaagd for the hosted label and the first
        gsq_geslaagd for the other; the rest verify_rood for the hosted label and limiet for gsq."""
        cases = {}
        for n, case in enumerate(CASES_12):
            cases[f"{HOSTED}/{case}"] = {"status": "geslaagd" if n < hosted_geslaagd else "verify_rood", "cost": 0.05}
            cases[f"{LOCAL}/{case}"] = {"status": "geslaagd" if n < gsq_geslaagd else "limiet"}
        return cases

    def score(self, directory, *extra):
        return subprocess.run([sys.executable, str(HERE / "score.py"), str(directory), "--models", HOSTED, LOCAL, *map(str, extra)],
                              capture_output=True, text=True, env=clean_env(), timeout=60)

    def test_one_window_for_both_labels_is_scored_from_its_out(self):
        cases = self.answers(10, 4)
        cases[f"{HOSTED}/AH-02"] = [{"status": "benchfout", "benchError": "clone faalde", "cost": 0.01}, {"status": "geslaagd", "cost": 0.05}]
        done = self.drive([HOSTED, LOCAL], config={"cases": cases}, ids=tuple(CASES_12), env={KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(done.returncode, 0, done.stderr)
        scored = self.score(self.out, "--ledger", self.ledger)
        self.assertEqual(scored.returncode, 0, scored.stderr)
        self.assertIn("Oordeel: meerwaarde", scored.stdout)                   # 10 and 4
        entries = run.read_ledger(self.ledger)
        self.assertIn(f"${run.ledger_total(entries):.4f}", scored.stdout)
        self.assertIn(f"{len(entries)} regels", scored.stdout)
        rows = {(r["label"], r["case"]): r for r in read_summary(self.out)}
        self.assertEqual(len(rows), 24)
        self.assertEqual((rows[HOSTED, "AH-02"]["status"], rows[HOSTED, "AH-02"]["attempts"]), ("geslaagd", "2"))   # the repeat counts
        self.assertEqual(rows[LOCAL, "AH-01"]["cost_usd"], "")                                                      # a local model: no amount
        self.assertEqual(float(rows[HOSTED, "AH-01"]["cost_usd"]), 0.05)

    def test_two_windows_with_an_out_each_and_a_practice_run_beside_them_are_scored_from_their_parent(self):
        windows = self.tmp / "R"
        cases = self.answers(11, 11)
        self.out = windows / "gehost"
        done = self.drive([HOSTED], config={"cases": cases}, ids=tuple(CASES_12), env={KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.out = windows / "gsq"
        done = self.drive([LOCAL], config={"cases": cases}, ids=tuple(CASES_12))
        self.assertEqual(done.returncode, 0, done.stderr)
        shutil.copytree(REAL / "AH-01-qwen3.8-openrouter-d6c19fec", windows / "proef" / "AH-01-qwen3.8-openrouter-d6c19fec")
        scored = self.score(windows, "--ledger", self.ledger)
        self.assertEqual(scored.returncode, 0, scored.stderr)
        self.assertIn("Oordeel: max2 volstaat", scored.stdout)                 # 11 and 11
        rows = read_summary(windows)
        self.assertEqual(len(rows), 24)
        self.assertEqual({r["attempts"] for r in rows}, {"1"})                  # the practice run is not the driver's: not an attempt

    def test_a_set_the_driver_stopped_in_is_not_scored(self):
        cases = self.answers(10, 4)
        cases[f"{LOCAL}/SM-03"] = {"status": "benchfout"}
        done = self.drive([HOSTED, LOCAL], config={"cases": cases}, ids=tuple(CASES_12), env={KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(done.returncode, 3, done.stderr)
        scored = self.score(self.out)
        self.assertEqual(scored.returncode, 2, scored.stderr)
        self.assertIn("SM-03", scored.stderr)
        self.assertFalse((self.out / "summary.csv").exists())


if __name__ == "__main__":
    unittest.main()
