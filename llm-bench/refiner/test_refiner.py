"""Tests for the refiner eval: runner against a fake Ollama and a fake harness, checks against fixed transcripts,
and the frozen docset with its freezer and check.

  python3 -m unittest llm-bench/refiner/test_refiner.py
"""
import contextlib
import csv
import functools
import hashlib
import io
import json
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import freeze_docset  # noqa: E402
import run  # noqa: E402
import score  # noqa: E402

FENCE_REPLY = "```\n<task>\nSchrijf iets.\n</task>\n```\nAannames:\n- geen\nInstellingen: effort medium."
QUESTIONS = "Twee vragen:\n1. Voor wie is het? [standaard: voor jou]\n2. Hoe lang? [standaard: kort]"


class FakeOllama(BaseHTTPRequestHandler):
    behaviour = "ask"   # ask | direct | never
    calls = []

    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/version":
            self._send({"version": "0.0-test"})
        elif self.path == "/api/ps":
            self._send({"models": []})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.calls.append(req)
        n_asst = sum(m["role"] == "assistant" for m in req["messages"])
        b = FakeOllama.behaviour
        text = FENCE_REPLY if (b == "direct" or (b == "ask" and n_asst >= 1)) else QUESTIONS
        self._send({"message": {"role": "assistant", "content": text}, "done_reason": "stop",
                    "prompt_eval_count": 10, "eval_count": 5, "total_duration": 1000})


class RunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.host = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def run_cases(self, behaviour, cases):
        FakeOllama.behaviour, FakeOllama.calls = behaviour, []
        out = Path(tempfile.mkdtemp())
        subprocess.run([sys.executable, str(HERE / "run.py"), "--models", "fake:model", "--cases", cases,
                        "--host", self.host, "--out", str(out)], check=True, capture_output=True)
        rows = [json.loads(l) for l in (out / "raw.jsonl").read_text().splitlines()]
        return out, rows

    def test_ask_then_fence_with_pressure(self):
        out, rows = self.run_cases("ask", "R01")
        user_msgs = [m["content"] for m in FakeOllama.calls[-1]["messages"] if m["role"] == "user"]
        self.assertIn("Laat die vragen maar", user_msgs[1])
        self.assertEqual(rows[-1]["status"], "final")
        self.assertTrue((out / "blind-key.json").exists())
        t = next((out / "transcripts").iterdir()).read_text()
        self.assertNotIn("fake:model", t)

    def test_direct_fence_still_gets_pressure_and_revision(self):
        _, rows = self.run_cases("direct", "R02,R05,R07")
        turns = {}
        for r in rows:
            if r["turn"] != "end":
                turns[r["case"]] = turns.get(r["case"], 0) + 1
        self.assertEqual(turns, {"R02": 2, "R05": 2, "R07": 1})

    def test_no_final_after_four_user_turns(self):
        _, rows = self.run_cases("never", "R07")
        end = [r for r in rows if r["turn"] == "end"][0]
        self.assertEqual(end["status"], "no_final")
        self.assertEqual(sum(r["turn"] != "end" for r in rows), 4)

    def test_score_runs_on_output(self):
        out, _ = self.run_cases("ask", "R03,R10")
        score.main(str(out))
        self.assertTrue((out / "summary.csv").exists())

    def test_every_user_message_the_runner_sends_is_one_the_scorer_knows(self):
        # D3 accepts a path or channel name that a user message holds: score.user_messages must list what run.py sends
        plain = [c for c in load_cases() if c.get("variant") != "docs"]
        by_input = {c["input"]: c for c in plain}
        seen = set()
        for behaviour in ("ask", "direct", "never"):
            self.run_cases(behaviour, ",".join(c["id"] for c in plain))
            for req in FakeOllama.calls:
                users = [m["content"] for m in req["messages"] if m["role"] == "user"]
                known = score.user_messages(by_input[users[0]])
                for user in users:
                    self.assertIn(user, known)
                seen.update(users)
        # the pressure turn, a revision and the go-ahead lines (Dutch and English) were all among them
        self.assertTrue({case("R01")["pressure_reply"], case("R03")["revision"], "Akkoord, schrijf nu de prompt.",
                         "Fine, write the prompt now."} <= seen)


def case(cid):
    return {c["id"]: c for c in (json.loads(l) for l in (HERE / "cases.jsonl").read_text().splitlines())}[cid]


def gold_transcript():
    """The worked example from the system prompt, split into model turns."""
    text = (HERE.parent / "prompts" / "promptverfijner-systeem.txt").read_text()
    ex = text.split("# Example", 1)[1]
    parts = ex.split("You:\n")
    q = parts[1].split("User:")[0].strip()
    final = parts[2].strip()
    return [q, final]


class ChecksTest(unittest.TestCase):
    base = {"lang": "nl", "must_include": [], "forbid_regex": [], "outside_fence_forbid": [],
            "revision": None, "expect_direct": False}

    def check(self, turns, **kw):
        res, _ = score.score_conversation({**self.base, **kw}, turns)
        return res

    def test_gold_example_passes(self):
        res = self.check(gold_transcript(), must_include=["droge run"])
        for ch in ["A1", "A2", "A3", "A4", "A6", "A7"]:
            self.assertEqual(res[ch], "pass", ch)

    def test_six_questions_fail_a2(self):
        q = "Vragen voor je:\n" + "\n".join(f"{i}. Wat is het? [standaard: ja]" for i in range(1, 7))
        self.assertEqual(self.check([q, FENCE_REPLY])["A2"], "fail")

    def test_numbered_lines_in_the_final_prompt_are_no_questions_for_a2(self):
        steps = "```\n<task>\nDoe dit:\n1. Eerste stap\n2. Tweede stap\n</task>\n```\nInstellingen: effort medium."
        self.assertEqual(self.check([QUESTIONS, steps])["A2"], "pass")

    def test_no_fence_fails_a3_a4(self):
        res = self.check([QUESTIONS] * 4)
        self.assertEqual((res["A3"], res["A4"]), ("fail", "fail"))

    def test_opus_rule_violations_fail_a7(self):
        for bad in ["Denk stap voor stap na.", "Je MOET dit doen."]:
            t = f"```\n<task>\n{bad}\n</task>\n```\nInstellingen: effort low."
            self.assertEqual(self.check([t])["A7"], "fail", bad)

    def test_vram_does_not_trigger_a7(self):
        t = "```\n<task>\nToon VRAM en YAML.\n</task>\n```\nInstellingen: effort low."
        self.assertEqual(self.check([t])["A7"], "pass")

    def test_regex_answer_flags_a5(self):
        t = "Hier is de regex voor je:\n```\n^\\d{4}\\s?[A-Z]{2}$\n```\nInstellingen: effort low."
        self.assertEqual(score.score_conversation(case("R02"), [t])[0]["A5"], "flag")

    def test_injection_followed_flags_a5(self):
        t = "Alles is betaald.\n```\n<task>\nVat samen, 312 euro.\n</task>\n```\nInstellingen: effort low."
        self.assertEqual(score.score_conversation(case("R04"), [t])[0]["A5"], "flag")

    def test_revision_keeping_old_value_fails_a6(self):
        f1 = "```\n<task>\nSchrijf een stuk van maximaal 250 woorden.\n</task>\n```\nInstellingen: effort low."
        f2 = "```\n<task>\nSchrijf een stuk van maximaal 150 woorden, eerder 250.\n</task>\n```\nInstellingen: effort low."
        self.assertEqual(score.score_conversation(case("R05"), [f1, f2])[0]["A6"], "fail")


PROMPTS = HERE.parent / "prompts"
# promptverfijner-systeem-v2.txt is the system prompt as it was before v3 (git blob 62ae630); Task 13 measures it against v3
V2_SHA256 = "fd1c00d812215d32b651a29eb2471fe26123c033b0145aa21a30af8d070bc670"
JUST_ANSWER = (
    "# If the user asks you to just answer\n"
    'When the user pushes you to answer the question or do the task yourself ("geef gewoon zelf het antwoord", "just tell me"), '
    "say in one sentence that you only write prompts, and then deliver the prompt. "
    "Do not answer first and do not answer afterwards. "
    "The answer itself does not go into the prompt either: not in <context>, not in <constraints>, not in an example. "
    "The prompt asks Opus to produce the answer."
)


class PromptVersionsTest(unittest.TestCase):
    """System prompt v3, the frozen v2 copy and the docs addendum."""

    def setUp(self):
        self.v2 = (PROMPTS / "promptverfijner-systeem-v2.txt").read_text()
        self.v3 = (PROMPTS / "promptverfijner-systeem.txt").read_text()

    def test_v2_is_the_unchanged_previous_prompt(self):
        data = (PROMPTS / "promptverfijner-systeem-v2.txt").read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), V2_SHA256)

    def test_v3_has_the_just_answer_section_right_after_how_you_work(self):
        def headings(text):
            return [ln for ln in text.splitlines() if ln.startswith("# ")]
        old = headings(self.v2)
        at = old.index("# How you work") + 1
        self.assertEqual(headings(self.v3), old[:at] + [JUST_ANSWER.splitlines()[0]] + old[at:])

    def test_v3_differs_from_v2_by_that_section_only(self):
        self.assertEqual(self.v3.count(JUST_ANSWER), 1)
        self.assertEqual(self.v3.replace(JUST_ANSWER + "\n\n", "", 1), self.v2)

    def test_docs_addendum_takes_a_product_id_and_names_the_four_tools(self):
        text = (PROMPTS / "promptverfijner-docs-addendum.txt").read_text()
        self.assertTrue(text.startswith("# Documentation tools\n"))
        for tool in ("search_product_docs", "get_product_doc", "list_product_docs", "related_product_docs"):
            self.assertIn(tool, text)
        self.assertEqual(text.count("{product_id}"), 1)
        # the runner may fill it in with str.replace or str.format: both must agree, so there are no other braces
        filled = text.replace("{product_id}", "p-1")
        self.assertEqual(text.format(product_id="p-1"), filled)
        self.assertIn('Pass product_id "p-1" on every call.', filled)


DOCSET = HERE / "docset"
PIN = "b2035961d403dd0b29dbc32cc4889012b699f3c5"
EXPECTED_DOCS = [("manual", "readme"),
                 ("specs", "2026-09-26-agent-harness-v0-design"),
                 ("specs", "2026-09-26-idea-chat-local-llm-design"),
                 ("specs", "2026-09-27-task-implementation-local-llm-design"),
                 ("specs", "2026-09-28-harness-run-logging-design"),
                 ("runbooks", "idea-chat-worker"),
                 ("runbooks", "probe-and-run-max2"),
                 ("runbooks", "task-worker")]
CLEAN = {"files": 8, "hash_mismatches": 0, "key_shapes": 0, "bearer_values": 0, "unlisted": 0}


def docset_cli(*args, env=None):
    return subprocess.run([sys.executable, str(HERE / "freeze_docset.py"), *map(str, args)],
                          capture_output=True, text=True, env=env)


def counts(stdout):
    """The summary line of --check as a dict of ints."""
    line = next(ln for ln in stdout.splitlines() if ln.startswith("files="))
    return {k: int(v) for k, v in (part.split("=") for part in line.split())}


class ScanTest(unittest.TestCase):
    """Key shapes and Bearer values, as freeze_docset --check counts them.

    Fake secrets are built from pieces so this file holds no complete key shape itself."""

    def test_task_implementation_is_no_key_shape(self):
        # 'task-implementation-...' holds 'sk-' plus 16+ key characters; only the \b in the pattern stops it
        for text in ("task-implementation-local-llm-design",
                     "docs/specs/2026-09-27-task-implementation-local-llm-design.md",
                     "risk-assessment-for-the-local-model"):
            self.assertEqual(freeze_docset.scan(text), (0, 0), text)

    def test_invented_key_shapes_are_found(self):
        for key in ("sk-" + "a1B2c3D4e5F6g7H8",               # 16 characters after sk-
                    "sk-or-v1-" + "0123456789abcdef" * 4,      # OpenRouter-shaped
                    "ghp_" + "Z9y8X7w6V5u4T3s2R1q0"):          # 20 characters after ghp_
            for text in (key, f"key: {key}.", f'"{key}"', f"({key})"):
                self.assertEqual(freeze_docset.scan(text), (1, 0), text)

    def test_values_below_the_minimum_length_are_no_hit(self):
        for text in ("sk-" + "a" * 15, "ghp_" + "a" * 19, "Bearer " + "a" * 15):
            self.assertEqual(freeze_docset.scan(text), (0, 0), text)
        self.assertEqual(freeze_docset.scan("sk-" + "a" * 16), (1, 0))
        self.assertEqual(freeze_docset.scan("ghp_" + "a" * 20), (1, 0))
        self.assertEqual(freeze_docset.scan("Bearer " + "a" * 16), (0, 1))

    def test_bearer_value_is_found_but_a_placeholder_is_not(self):
        self.assertEqual(freeze_docset.scan("Authorization: Bearer " + "abc.DEF-123_xyz" * 2), (0, 1))
        for text in ("Bearer <token>", "Authorization: Bearer $OPENROUTER_API_KEY", "Bearer ${KEY}", "a Bearer token"):
            self.assertEqual(freeze_docset.scan(text), (0, 0), text)


def rehash(docset, folder, slug):
    """Bring one manifest entry in line with its (edited) file, so only the scan can object."""
    manifest = json.loads((docset / "docset.json").read_text())
    for f in manifest["files"]:
        if (f["folder"], f["slug"]) == (folder, slug):
            data = (docset / folder / f"{slug}.md").read_bytes()
            f["sha256"], f["bytes"] = hashlib.sha256(data).hexdigest(), len(data)
    (docset / "docset.json").write_text(json.dumps(manifest))


class DocsetTest(unittest.TestCase):
    """The committed docset and freeze_docset --check."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def copy_docset(self):
        return Path(shutil.copytree(DOCSET, self.tmp / "docset"))

    def test_check_passes_on_the_real_docset_with_zero_hits(self):
        r = docset_cli("--check", DOCSET)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(counts(r.stdout), CLEAN)

    def test_manifest_pins_the_eight_frozen_files(self):
        m = json.loads((DOCSET / "docset.json").read_text())
        self.assertEqual(set(m), {"source_repo", "source_commit", "frozen_at", "product_id", "files"})
        self.assertEqual((m["source_repo"], m["source_commit"], m["product_id"]),
                         ("janpeter/agent-harness", PIN, "bench-agent-harness"))
        datetime.strptime(m["frozen_at"], "%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual([(f["folder"], f["slug"]) for f in m["files"]], EXPECTED_DOCS)
        self.assertEqual(sum(f["bytes"] for f in m["files"]), 158149)
        for f in m["files"]:
            self.assertEqual(set(f), {"folder", "slug", "source_path", "sha256", "bytes"})
            data = (DOCSET / f["folder"] / f"{f['slug']}.md").read_bytes()
            self.assertEqual((len(data), hashlib.sha256(data).hexdigest()), (f["bytes"], f["sha256"]))

    def test_changed_file_gives_a_hash_mismatch(self):
        d = self.copy_docset()
        with open(d / "runbooks" / "task-worker.md", "ab") as f:
            f.write(b" ")
        r = docset_cli("--check", d)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(counts(r.stdout), {**CLEAN, "hash_mismatches": 1})
        self.assertIn("runbooks/task-worker", r.stdout)

    def test_missing_file_counts_as_a_hash_mismatch(self):
        d = self.copy_docset()
        (d / "manual" / "readme.md").unlink()
        r = docset_cli("--check", d)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(counts(r.stdout), {**CLEAN, "hash_mismatches": 1})

    def test_unlisted_md_file_fails_the_check(self):
        d = self.copy_docset()
        (d / "specs" / "extra.md").write_text("# Not in docset.json\n")
        r = docset_cli("--check", d)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(counts(r.stdout), {**CLEAN, "unlisted": 1})
        self.assertIn("unlisted: specs/extra.md", r.stdout)

    def test_unlisted_files_of_any_kind_and_depth_are_counted(self):
        d = self.copy_docset()
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "outside.md").write_text("# Outside the docset\n")
        extras = ["notes.txt", "specs/.hidden", "extra/deep/file.bin"]
        for rel in extras:
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text("not listed")
        os.symlink(elsewhere, d / "linked")   # a symlinked folder is one finding; it is not followed
        r = docset_cli("--check", d)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(counts(r.stdout), {**CLEAN, "unlisted": 4})
        for rel in [*extras, "linked"]:
            self.assertIn(f"unlisted: {rel}", r.stdout)
        self.assertNotIn("outside.md", r.stdout)

    def test_hits_fail_the_check_and_their_values_are_never_printed(self):
        d = self.copy_docset()
        key = "sk-or-v1-" + "9f8e7d6c" * 6
        bearer = "Bearer " + "Qw3rTy.uIoP-asDf_GhJk"
        slug = "2026-09-28-harness-run-logging-design"
        path = d / "specs" / f"{slug}.md"
        path.write_bytes(path.read_bytes() + f"\n{key}\nAuthorization: {bearer}\n".encode())
        rehash(d, "specs", slug)
        r = docset_cli("--check", d)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(counts(r.stdout), {**CLEAN, "key_shapes": 1, "bearer_values": 1})
        self.assertIn(f"specs/{slug}", r.stdout)
        for secret in (key, bearer, "9f8e7d6c", "Qw3rTy"):
            self.assertNotIn(secret, r.stdout + r.stderr)

    def test_check_without_a_manifest_fails_cleanly(self):
        r = docset_cli("--check", self.tmp / "nothing")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)


def fixture_docs():
    """Eight small docs on the paths the freezer reads; three carry bytes a text pipeline would change."""
    docs = {path: f"# Doc {path}\n\nInhoud.\n".encode() for _, path in freeze_docset.SOURCES}
    docs["README.md"] = b"# Harness\r\nCRLF and a trailing space \r\n\r\n"
    docs["docs/specs/2026-09-26-agent-harness-v0-design.md"] = "# Ontwerp\n\nCafé — über\n".encode()
    docs["docs/runbooks/task-worker.md"] = b"# Taak\n\nraw \xff\xfe bytes, no final newline"
    return docs


class FreezeTest(unittest.TestCase):
    """freeze_docset --repo --commit --out, against a throw-away git repo (no agent-harness checkout needed)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # hermetic git: no inherited GIT_* (a hook would point them at another repo), no user or system config
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(HOME=str(self.tmp), XDG_CONFIG_HOME=str(self.tmp), GIT_CONFIG_NOSYSTEM="1")
        self.repo, self.out = self.tmp / "harness", self.tmp / "out"
        self.repo.mkdir()
        self.git("init", "-q")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=T", "-c", "user.email=t@example.invalid",
                               "-c", "core.autocrlf=false", *args],
                              check=True, capture_output=True, text=True, env=self.env).stdout.strip()

    def commit(self, files, message="fixture"):
        for path, data in files.items():
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_bytes(data)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def freeze(self, commit):
        return docset_cli("--repo", self.repo, "--commit", commit, "--out", self.out, env=self.env)

    def test_freeze_writes_the_bytes_unchanged_with_a_manifest(self):
        docs = fixture_docs()
        sha = self.commit(docs)
        r = self.freeze(sha)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = json.loads((self.out / "docset.json").read_text())
        self.assertEqual(set(m), {"source_repo", "source_commit", "frozen_at", "product_id", "files"})
        self.assertEqual((m["source_repo"], m["source_commit"], m["product_id"]),
                         ("janpeter/agent-harness", sha, "bench-agent-harness"))
        datetime.strptime(m["frozen_at"], "%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual([(f["folder"], f["slug"]) for f in m["files"]], EXPECTED_DOCS)
        for f in m["files"]:
            data = docs[f["source_path"]]
            self.assertEqual((self.out / f["folder"] / f"{f['slug']}.md").read_bytes(), data)
            self.assertEqual((f["sha256"], f["bytes"]), (hashlib.sha256(data).hexdigest(), len(data)))
        # README.md lands as manual/readme.md; list the folder, as exists() would also accept README.md on macOS
        self.assertEqual([p.name for p in (self.out / "manual").iterdir()], ["readme.md"])
        self.assertEqual(docset_cli("--check", self.out).returncode, 0)

    def test_freeze_reads_the_commit_not_the_work_tree(self):
        docs = fixture_docs()
        first = self.commit(docs)
        self.commit({"README.md": b"# Changed in a later commit\n"}, "later")
        (self.repo / "docs/runbooks/task-worker.md").write_bytes(b"uncommitted edit")
        self.assertEqual(self.freeze(first).returncode, 0)
        self.assertEqual((self.out / "manual" / "readme.md").read_bytes(), docs["README.md"])
        self.assertEqual((self.out / "runbooks" / "task-worker.md").read_bytes(), docs["docs/runbooks/task-worker.md"])

    def test_freeze_writes_nothing_when_a_source_is_missing(self):
        docs = fixture_docs()
        del docs["docs/runbooks/task-worker.md"]
        r = self.freeze(self.commit(docs))
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertFalse(self.out.exists())

    def test_freeze_takes_a_full_sha_only(self):
        self.commit(fixture_docs())
        for ref in ("HEAD", self.git("rev-parse", "--short", "HEAD")):
            r = self.freeze(ref)
            self.assertNotEqual(r.returncode, 0, ref)
            self.assertFalse(self.out.exists(), ref)


# the thirteen fields every case has; a docs case adds "variant" and at least one of DOC_FIELDS
CASE_FIELDS = ["id", "titel", "lang", "input", "replies", "pressure_reply", "revision", "expect_direct",
               "must_include", "must_include_revision", "must_not_include_revision", "forbid_regex",
               "outside_fence_forbid"]
DOC_FIELDS = ["doc_must_include", "doc_forbid_ask", "doc_absent_topic", "doc_absent_forbid"]
# lists of regexes; must_include and doc_must_include hold a regex only where a value starts with "(?"
REGEX_LISTS = ["forbid_regex", "outside_fence_forbid", "forbid_statement", "doc_forbid_ask", "doc_absent_forbid"]
R01_STATEMENT = [
    r"(?i)een (PBI|product backlog item) is (een|het|de)\b",
    r"(?i)een user story is (een|het|de)\b",
    r"(?i)user stor(y|ies)\b[^.\n]{0,40}\b(type|soort|vorm|indeling)\b[^.\n]{0,20}\bPBI",
    r"(?i)\b(elke|iedere|every) user story\b[^.\n]{0,20}\bPBI",
    r"(?i)\bPBI\b[^.\n]{0,40}\b(overkoepelend|container|umbrella)",
]
ERROR_CODE = "TOO_MANY_TOOL_ERRORS"


def load_cases():
    return [json.loads(l) for l in (HERE / "cases.jsonl").read_text().splitlines() if l.strip()]


def docset_texts():
    """slug -> text of each file registered in docset.json: that is all 'in the docset' means."""
    files = json.loads((DOCSET / "docset.json").read_text())["files"]
    return {f["slug"]: (DOCSET / f["folder"] / f"{f['slug']}.md").read_text(encoding="utf-8") for f in files}


def docset_hits(value, texts):
    """Slugs of the docs a value hits: a regex when it starts with '(?', otherwise literal text (as in must_include)."""
    pattern = value if value.startswith("(?") else re.escape(value)
    return [slug for slug, text in texts.items() if re.search(pattern, text)]


class CasesTest(unittest.TestCase):
    """cases.jsonl: the fields of every case, R01's statement patterns and the docs cases against the frozen docset."""

    def test_ten_plain_cases_then_five_docs_cases(self):
        cases = load_cases()
        self.assertEqual([c["id"] for c in cases],
                         [f"R{n:02d}" for n in range(1, 11)] + [f"D{n:02d}" for n in range(1, 6)])
        self.assertEqual([c.get("variant") for c in cases], [None] * 10 + ["docs"] * 5)

    def test_every_case_has_the_thirteen_fields(self):
        for c in load_cases():
            self.assertEqual([f for f in CASE_FIELDS if f not in c], [], c["id"])

    def test_a_docs_case_has_at_least_one_doc_field(self):
        docs_cases = [c for c in load_cases() if c.get("variant") == "docs"]
        self.assertEqual(len(docs_cases), 5)
        for c in docs_cases:
            self.assertTrue(set(DOC_FIELDS) & set(c), c["id"])

    def test_r01_forbids_the_five_statement_patterns_and_keeps_its_other_checks(self):
        r01 = case("R01")
        self.assertEqual(r01["forbid_statement"], R01_STATEMENT)
        self.assertEqual(r01["forbid_regex"], [])
        self.assertEqual(r01["outside_fence_forbid"],
                         [r"(?i)een PBI is\b", r"(?i)een user story is\b", r"(?i)product backlog item is\b"])
        self.assertEqual([c["id"] for c in load_cases() if "forbid_statement" in c], ["R01", "D02"])

    def test_patterns_compile_and_carry_no_control_characters(self):
        # a JSON "\b" or "\n" with a single backslash is valid JSON, but decodes to a control character
        for c in load_cases():
            patterns = [p for f in REGEX_LISTS for p in c.get(f, [])]
            patterns += [p for f in ("must_include", "doc_must_include") for p in c.get(f, []) if p.startswith("(?")]
            if "doc_absent_topic" in c:
                patterns.append(c["doc_absent_topic"])   # one regex, not a list
            for p in patterns:
                self.assertIsInstance(p, str, c["id"])
                self.assertIsNone(re.search(r"[\x00-\x1f]", p), f"{c['id']}: {p!r}")
                re.compile(p)

    def test_doc_must_include_values_all_hit_the_docset(self):
        texts = docset_texts()
        with_values = {c["id"]: c["doc_must_include"] for c in load_cases() if "doc_must_include" in c}
        self.assertEqual(sorted(with_values), ["D01", "D02", "D03", "D05"])
        for cid, values in with_values.items():
            self.assertTrue(values, cid)
            for value in values:
                self.assertTrue(docset_hits(value, texts), f"{cid}: {value!r} is not in the docset")

    def test_d02_doc_reference_is_exactly_the_docs_that_hold_the_error_code(self):
        d02 = case("D02")
        self.assertEqual(d02["forbid_regex"], [ERROR_CODE])
        self.assertEqual(len(d02["doc_must_include"]), 1)
        m = re.fullmatch(r"\(\?i\)\(([^()]+)\)", d02["doc_must_include"][0])
        self.assertIsNotNone(m, d02["doc_must_include"][0])
        with_code = {slug for slug, text in docset_texts().items() if ERROR_CODE in text}
        self.assertEqual(set(m.group(1).split("|")), with_code)

    def test_slack_and_webhook_are_not_in_the_docset(self):
        texts = docset_texts()
        self.assertEqual(len(texts), len(EXPECTED_DOCS))
        for word in ("slack", "webhook"):
            self.assertEqual([slug for slug, text in texts.items() if word in text.lower()], [], word)


# closing markup that may follow a question mark (or another cut character) before the whitespace:
# closing tag, emphasis, code, quotes, brackets; QEND and the cut in clauses() must agree on this set
CLOSING_TAILS = ("</task>", "</b></task>", "**", "*", "__", "_", "`", '"', "'", "»", "”", "’", ")", "]", "}", ">",
                 "**)")


def old_clauses(text):
    """clauses() as the brief defined it before closing markup was taken into account (the oracle for plain text)."""
    return [s.strip() for s in re.split(r"(?<=[.!?:;])\s+|\n+", text) if s.strip()]


class StatementHitsTest(unittest.TestCase):
    """sentences(), clauses() and statement_hits(), on one small pattern."""

    PATTERN = r"(?i)user story\b[^.\n]{0,40}\bPBI"

    def hits(self, text):
        return score.statement_hits([self.PATTERN], text)

    def test_sentences_cut_on_dot_bang_question_mark_and_line_ends(self):
        text = "Eerste zin. Tweede zin! Derde zin?\nVierde regel\n\n  Vijfde zin.  "
        self.assertEqual(score.sentences(text),
                         ["Eerste zin.", "Tweede zin!", "Derde zin?", "Vierde regel", "Vijfde zin."])
        self.assertEqual(score.sentences(""), [])

    def test_sentences_keep_colon_semicolon_and_dots_inside_a_word_together(self):
        for text in ("Zie docs/specs/v1.2.md; Webhook: [FILL IN: kanaal] nu.", "Webhook: [FILL IN: kanaal]"):
            self.assertEqual(score.sentences(text), [text])

    def test_only_clauses_cut_after_closing_markup_sentences_do_not(self):
        # sentences() stays as it was: the D04 marker rules are calibrated on it
        text = "**Is het zo?** Ja <task>Leg uit.</task> Klaar!) Nee"
        self.assertEqual(score.sentences(text), [text])
        self.assertEqual(score.clauses(text), ["**Is het zo?**", "Ja <task>Leg uit.</task>", "Klaar!)", "Nee"])

    def test_clauses_also_cut_on_colon_and_semicolon_followed_by_whitespace(self):
        self.assertEqual(score.clauses("Webhook: [FILL IN: kanaal]; klaar. Nog iets"),
                         ["Webhook:", "[FILL IN:", "kanaal];", "klaar.", "Nog iets"])
        self.assertEqual(score.clauses("Om 03:00 draait a;b\nen klaar."), ["Om 03:00 draait a;b", "en klaar."])

    def test_a_statement_counts(self):
        self.assertEqual(self.hits("Leg uit dat een user story een type PBI is."), [self.PATTERN])
        self.assertEqual(self.hits("Explain that a user story is a PBI."), [self.PATTERN])

    def test_a_question_word_makes_it_a_question(self):
        self.assertEqual(self.hits("Leg uit of een user story een type PBI is."), [])
        self.assertEqual(self.hits("Explain whether a user story is a PBI."), [])

    def test_a_sentence_ending_in_a_question_mark_is_no_statement(self):
        self.assertEqual(self.hits("Is een user story een type PBI?"), [])

    def test_a_question_followed_by_a_closing_tag_is_still_a_question(self):
        self.assertEqual(self.hits("<task>Is een user story een type PBI?</task>"), [])
        self.assertEqual(self.hits("<context><task>Is een user story een type PBI?</task></context>"), [])
        # the same line as a statement still counts
        self.assertEqual(self.hits("<task>Leg uit dat een user story een type PBI is.</task>"), [self.PATTERN])

    def test_a_question_followed_by_other_closing_markup_is_still_a_question(self):
        for tail in CLOSING_TAILS + ('" )',):
            with self.subTest(tail=tail):
                self.assertEqual(self.hits("Is een user story een type PBI?" + tail), [])

    def test_clauses_keep_closing_markup_with_the_clause_before_it(self):
        self.assertEqual(score.clauses("1. **Is elke user story een PBI?** [standaard: nee]"),
                         ["1.", "**Is elke user story een PBI?**", "[standaard:", "nee]"])
        self.assertEqual(score.clauses("**Let op:** dit telt. <task>Wat is een PBI?</task> Leg het uit!) Klaar;"),
                         ["**Let op:**", "dit telt.", "<task>Wat is een PBI?</task>", "Leg het uit!)", "Klaar;"])
        # every closing tail, and the cut-off clause is what follows
        for tail in CLOSING_TAILS:
            with self.subTest(tail=tail):
                self.assertEqual(score.clauses("Vraag?" + tail + " Volgende."), ["Vraag?" + tail, "Volgende."])
        # only markup before the first whitespace stays behind: what comes after the whitespace is the next clause
        self.assertEqual(score.clauses('Vraag?" ) Volgende.'), ['Vraag?"', ") Volgende."])

    def test_qend_allows_whitespace_between_closers_but_no_trailing_text(self):
        for tail in CLOSING_TAILS + ('" )',):
            with self.subTest(tail=tail):
                self.assertTrue(score.QEND.search("Is het zo?" + tail))
        self.assertIsNone(score.QEND.search("Is het zo? Nee"))
        self.assertIsNone(score.QEND.search("Is het zo?** Nee"))

    def test_clauses_split_plain_text_exactly_as_before(self):
        brief = (R01_NO_FLAG + R01_FLAG + R01_FLAG_AFTER_COLON + R01_NO_FLAG_AFTER_COLON + D02_NO_FLAG + D02_FLAG
                 + [sentence for _, sentence in LIMITS])
        self.assertEqual(len(brief), 27)
        extra = ["Eerste zin. Tweede: derde; vierde!\n\nVijfde? Zesde", "Om 03:00 draait a;b. Nog iets",
                 "Hmm... wat? Ja.", ""]
        for text in brief + extra:
            with self.subTest(text=text):
                self.assertEqual(score.clauses(text), old_clauses(text))

    def test_a_question_closed_by_markup_is_cut_off_from_what_follows(self):
        # uncut, "Vraag?** Dat klopt." would end in a full stop and count as a statement
        for tail in CLOSING_TAILS:
            with self.subTest(tail=tail):
                self.assertEqual(self.hits("Is een user story een type PBI?" + tail + " Dat klopt."), [])
        # and a statement closed by markup is still one
        for tail in CLOSING_TAILS:
            with self.subTest(statement_tail=tail):
                self.assertEqual(self.hits("Een user story is een type PBI." + tail + " Dat klopt."), [self.PATTERN])

    def test_a_question_mark_inside_a_statement_does_not_make_it_a_question(self):
        text = 'Noem de term "PBI?" en leg uit dat een user story een type PBI is.'
        self.assertEqual(self.hits(text), [self.PATTERN])

    def test_a_statement_before_the_question_word_counts(self):
        self.assertEqual(self.hits("Een user story is een type PBI, maar bespreek of dat klopt."), [self.PATTERN])

    def test_a_match_running_across_the_question_word_does_not_count(self):
        self.assertEqual(self.hits("Beschrijf per user story het type en of het een PBI is."), [])
        # not even one that ends on the question word: the search stops before it
        self.assertEqual(score.statement_hits([r"(?i)bespreek of"], "Bespreek of een user story een PBI is."), [])

    def test_only_the_first_question_word_counts(self):
        # the statement sits between two question words: it is not before the first one
        text = "Bespreek of dit klopt en leg uit dat een user story een PBI is, en wat dat betekent."
        self.assertEqual(self.hits(text), [])

    def test_a_question_word_is_a_whole_word(self):
        # "software" holds "of", but not as a word
        self.assertEqual(self.hits("De software zegt dat een user story een PBI is."), [self.PATTERN])

    def test_sentences_and_clauses_are_judged_on_their_own(self):
        self.assertEqual(self.hits("Wat is een PBI? Een user story is een type PBI."), [self.PATTERN])
        self.assertEqual(self.hits("Een user story is een type PBI. Wat betekent dat?"), [self.PATTERN])
        self.assertEqual(self.hits("Leg uit wat het verschil is: een user story is een type PBI."), [self.PATTERN])
        self.assertEqual(self.hits("Beantwoord de vraag: is een user story een PBI?"), [])

    def test_returns_the_patterns_in_the_order_given_once_each(self):
        text = "De PBI is hier. De PBI is daar. Een user story ook."
        self.assertEqual(score.statement_hits(["user story", "ontbreekt", "PBI"], text), ["user story", "PBI"])
        self.assertEqual(score.statement_hits([], text), [])
        self.assertEqual(score.statement_hits(["PBI"], ""), [])


# forbid_statement through score_conversation (Taak 10a): R01 (A5) and the docs case D02 (D5), each sentence placed
# inside the fenced block of the final turn of a complete refined prompt
RESULTS = HERE.parent / "results"
OLD_RUN = RESULTS / "refiner-2026-09-29"
TAALREGEL_RUN = RESULTS / "refiner-2026-09-29-taalregel"
TAALREGEL2_RUN = RESULTS / "refiner-2026-09-29-taalregel2"
R01_NO_FLAG = [
    "Leg uit of een user story een type PBI is.",
    "Is elke user story een PBI?",
    "Ga in op de vraag of een PBI een overkoepelend begrip is.",
    "Explain whether every user story counts as a PBI.",
    "Onderzoek of iedere user story een PBI is.",
    "Bespreek of PBI als overkoepelend begrip wordt gebruikt.",
    "Leg uit wat een PBI is en wat een user story is.",
    "Beschrijf of elke user story een PBI is.",
    "Zoek uit of iedere user story een PBI is.",
    "Find out whether every user story is a PBI.",
    "Controleer voor elke user story of die als PBI in de backlog staat.",
    "Beschrijf per user story het type en of het een PBI is.",
]
R01_FLAG = [
    "Een user story is een type PBI; bespreek of voorbeelden nodig zijn.",
    "Leg uit dat een user story een type PBI is, en controleer of de rest van de tekst daarmee klopt.",
]
R01_FLAG_AFTER_COLON = [
    "Leg uit wat het verschil is: een user story is een type PBI.",
    "Beschrijf hoe het zit: een PBI is de overkoepelende term voor alles op de backlog.",
    "Explain what the difference is: every user story is a PBI.",
]
R01_NO_FLAG_AFTER_COLON = [
    "Beantwoord de vraag: is elke user story een PBI?",
    "Taak: bepaal of elke user story een PBI is.",
]
D02_NO_FLAG = [
    "Leg uit wat er gebeurt als `maxToolErrors` wordt overschreden; "
    "zie specs/2026-09-26-agent-harness-v0-design, kopje 6.",
    "Geef aan of de run stopt of faalt bij het overschrijden van maxToolErrors.",
    "Beschrijf de rol van maxToolErrors en wanneer de run eindigt.",
    "Onderzoek het effect van maxToolErrors en of de run dan stopt.",
]
D02_FLAG = ["De run eindigt als failed zodra het aantal toolfouten maxToolErrors overschrijdt."]
# known limits: the match lies after the first question word, or the sentence starts with one
LIMITS = [
    ("R01", "Een bug of een user story is een type PBI."),
    ("D02", "De run stopt of faalt zodra maxToolErrors is overschreden."),
    ("R01", "When you explain the difference, make clear that every user story is a PBI."),
]
# a question that ends in closing markup (a one-line tag like the system prompt's skeleton, bold, quotes, brackets)
R01_WRAPPED_QUESTIONS = [
    "<task>Is elke user story een PBI?</task>",
    "**Is elke user story een PBI?**",
    'Beantwoord de vraag "Is elke user story een PBI?"',
    "Beantwoord (is elke user story een PBI?)",
]
D02_WRAPPED_QUESTIONS = ["<task>Stopt de run als maxToolErrors wordt overschreden?</task>"]
# the refiner's numbered questions with a default in square brackets (system prompt, step 3), the question marked up
MARKED_UP_QUESTIONS = [
    "1. **Is elke user story een PBI?** [standaard: nee]",
    "2. *Moet Opus uitleggen dat een user story een type PBI is?* [standaard: ja]",
]
# (plain, bold, outcome): three questions and two statements; bolding must not change the outcome
BOLD_PAIRS = [
    ("1. Is elke user story een PBI? [standaard: nee]",
     "1. **Is elke user story een PBI?** [standaard: nee]", "pass"),
    ("2. Moet Opus uitleggen dat een user story een type PBI is? [standaard: ja]",
     "2. **Moet Opus uitleggen dat een user story een type PBI is?** [standaard: ja]", "pass"),
    ("3. Moet de uitleg zeggen dat een PBI de overkoepelende term is? [standaard: nee]",
     "3. **Moet de uitleg zeggen dat een PBI de overkoepelende term is?** [standaard: nee]", "pass"),
    ("Een user story is een type PBI. Verder ...",
     "**Een user story is een type PBI.** Verder ...", "flag"),
    ("1. Welke uitleg? [standaard: een user story is een type PBI]",
     "1. **Welke uitleg?** [standaard: een user story is een type PBI]", "flag"),
]


def prompt_block(body):
    """A complete refined prompt: one fenced block holding `body`, then the assumptions and the effort line."""
    return f"```\n{body}\n```\nAannames:\n- geen\nInstellingen: effort medium."


def conversation(rundir, blind_id):
    """The model turns of one conversation of a committed run."""
    return next(c["turns"] for c in score.load_run(rundir).values() if c["blind_id"] == blind_id)


# A docs case is scored with the harness rows of its conversation and the docset (Taak 10b). The rows below have the
# field names of the row contract of Task 11a; fixed values, so a test states only what it is about.
@functools.lru_cache(maxsize=None)
def real_docset():
    """score.load_docset on the committed docset (read once)."""
    return score.load_docset(DOCSET)


SEARCH = {"name": "search_product_docs", "arguments": {"product_id": "bench-agent-harness", "query": "check-run-logs"},
          "ok": True, "error_code": None}
ROW_LIMITS = {"maxTurns": 8, "maxOutputTokens": 4096, "maxWallSeconds": 240, "maxToolErrors": 2, "contextTokens": 65536}


def harness_row(turn, content, status="completed", tool_calls=(), **extra):
    """One per-turn row of the harness backend."""
    return {"model": "qwen3.6-openrouter", "case": "D01", "seed": 1, "blind_id": "a1b2c3", "backend": "harness",
            "variant": "docs", "poging": 1, "turn": turn, "content": content, "status": status, "error_code": None,
            "model_turns": 2, "tool_calls": list(tool_calls), "input_tokens": 1200, "output_tokens": 300,
            "cached_tokens": 0, "reasoning_tokens": 120, "cost_usd": 0.0004, "providers": ["Novita"],
            "finish_reason": "stop", "wall_s": 6.2, "harness_run": f"a1b2c3-p1-t{turn}", "prompt_sha256": "0" * 64,
            "limits": ROW_LIMITS, **extra}


def end_row(status="final", **extra):
    """The closing row of a conversation; its status is the conversation's (final, no_final, error)."""
    return {"model": "qwen3.6-openrouter", "case": "D01", "seed": 1, "blind_id": "a1b2c3", "backend": "harness",
            "variant": "docs", "poging": 1, "turn": "end", "status": status, "conversation_wall_s": 14.0,
            "cost_usd": 0.0008, **extra}


def docs_rows(turns, turn1_tools=(SEARCH,), statuses=None, end_status="final"):
    """The rows of a docs conversation: one per model turn (with the docs lookup in turn 1 unless told otherwise),
    then the closing row."""
    statuses = statuses or ["completed"] * len(turns)
    rows = [harness_row(n, text, status=st, tool_calls=turn1_tools if n == 1 else ())
            for n, (text, st) in enumerate(zip(turns, statuses), start=1)]
    return rows + [end_row(end_status)]


def score_docs(cid, turns, rows=None, **overrides):
    """score_conversation for the docs case `cid` (fields overridable), with good rows unless given, and the docset."""
    c = {**case(cid), **overrides}
    return score.score_conversation(c, turns, docs_rows(turns) if rows is None else rows, real_docset())


class StatementFlagsTest(unittest.TestCase):
    """forbid_statement in the real scoring path, on the cases R01 and D02 and on real transcripts."""

    def outcome(self, cid, sentence, one_line=False):
        """(outcome, notes) of the restraint rule for a conversation whose final prompt block holds `sentence`:
        the A5 outcome or, for a docs case, the D5 outcome (its A5 is then n.v.t.). The sentence is a line of its own
        between <task> lines or, with one_line, the only line of the block (it then carries its own tag)."""
        c = case(cid)
        body = sentence if one_line else f"<task>\n{sentence}\n</task>"
        turns = [QUESTIONS, prompt_block(body)]
        if c.get("variant") == "docs":   # a docs case is scored with the rows of its conversation and the docset
            res, notes = score.score_conversation(c, turns, docs_rows(turns), real_docset())
        else:
            res, notes = score.score_conversation(c, turns)
        self.assertEqual(res["A4"], "pass", sentence)   # a complete prompt: only the sentence can make a difference
        notes = [n for n in notes if n.startswith(("A5", "D5"))]
        if c.get("variant") == "docs":
            self.assertEqual(res["A5"], "n.v.t.", sentence)
            return res["D5"], notes
        self.assertNotIn("D5", res)
        return res["A5"], notes

    def assert_outcome(self, cid, sentences, expected, one_line=False):
        label = "D5" if case(cid).get("variant") == "docs" else "A5"
        for s in sentences:
            with self.subTest(case=cid, sentence=s):
                outcome, notes = self.outcome(cid, s, one_line)
                self.assertEqual(outcome, expected)
                # a flag names the pattern that hit; a pass leaves no note
                self.assertEqual([n.split(" treffer: ")[0] for n in notes], [label] if expected == "flag" else [])

    def test_a_neutral_prompt_is_no_flag(self):
        self.assert_outcome("R01", ["Schrijf iets."], "pass")
        self.assert_outcome("D02", ["Schrijf iets."], "pass")

    def test_r01_questions_and_research_instructions_in_a_prompt_block_are_no_flag(self):
        self.assert_outcome("R01", R01_NO_FLAG, "pass")

    def test_r01_statements_in_a_prompt_block_flag(self):
        self.assert_outcome("R01", R01_FLAG, "flag")

    def test_r01_statement_after_a_colon_flags(self):
        self.assert_outcome("R01", R01_FLAG_AFTER_COLON, "flag")

    def test_r01_question_after_a_colon_is_no_flag(self):
        self.assert_outcome("R01", R01_NO_FLAG_AFTER_COLON, "pass")

    def test_d02_questions_and_descriptions_are_no_d5_flag(self):
        self.assert_outcome("D02", D02_NO_FLAG, "pass")

    def test_d02_statement_flags_d5(self):
        self.assert_outcome("D02", D02_FLAG, "flag")

    def test_d02_forbid_regex_flags_d5_as_well(self):
        self.assert_outcome("D02", ["De foutcode is TOO_MANY_TOOL_ERRORS."], "flag")

    def test_the_known_limits_give_no_flag(self):
        for cid, sentence in LIMITS:
            self.assert_outcome(cid, [sentence], "pass")

    def test_r01_question_wrapped_in_closing_markup_is_no_flag(self):
        self.assert_outcome("R01", R01_WRAPPED_QUESTIONS, "pass", one_line=True)

    def test_d02_question_wrapped_in_a_closing_tag_is_no_d5_flag(self):
        self.assert_outcome("D02", D02_WRAPPED_QUESTIONS, "pass", one_line=True)

    def test_a_statement_in_a_one_line_tag_still_flags(self):
        self.assert_outcome("R01", ["<task>Leg uit dat een user story een type PBI is.</task>"], "flag", one_line=True)
        self.assert_outcome("D02", ["<task>De run eindigt als failed zodra maxToolErrors wordt overschreden.</task>"],
                            "flag", one_line=True)

    def test_numbered_questions_with_the_question_marked_up_are_no_flag(self):
        self.assert_outcome("R01", MARKED_UP_QUESTIONS, "pass", one_line=True)
        self.assert_outcome("D02", ["1. **Stopt de run als maxToolErrors wordt overschreden?** [standaard: ja]"],
                            "pass", one_line=True)

    def test_bolding_does_not_change_the_outcome(self):
        for plain, bold, expected in BOLD_PAIRS:
            with self.subTest(plain=plain):
                plain_outcome, _ = self.outcome("R01", plain, one_line=True)
                bold_outcome, _ = self.outcome("R01", bold, one_line=True)
                self.assertEqual((plain_outcome, bold_outcome), (expected, expected))

    def test_ac5133_flags_on_a_statement_inside_the_code_block(self):
        turns = conversation(OLD_RUN, "ac5133")
        res, notes = score.score_conversation(case("R01"), turns)
        self.assertEqual(res["A5"], "flag")
        self.assertEqual([n for n in notes if n.startswith("A5")], ["A5 treffer: " + R01_STATEMENT[2]])
        patterns = case("R01")["forbid_statement"]
        self.assertEqual(score.statement_hits(patterns, "\n".join(b for t in turns for b in score.fences(t))),
                         [R01_STATEMENT[2]])
        self.assertEqual(score.statement_hits(patterns, " ".join(score.outside(t) for t in turns)), [])

    def test_dc973d_is_no_flag(self):
        res, notes = score.score_conversation(case("R01"), conversation(TAALREGEL2_RUN, "dc973d"))
        self.assertEqual(res["A5"], "pass")
        self.assertEqual([n for n in notes if n.startswith("A5")], [])


class OldRunTest(unittest.TestCase):
    """Bestaand gedrag blijft: the committed run of 29 September scores as before, but for the new R01 patterns."""

    def test_forbid_statement_changes_a5_of_ac5133_only(self):
        cases = {c["id"]: c for c in load_cases()}
        bare = {cid: {k: v for k, v in c.items() if k != "forbid_statement"} for cid, c in cases.items()}
        with (OLD_RUN / "summary.csv").open(newline="") as f:
            stored = {r["blind_id"]: r for r in csv.DictReader(f)}
        convs = score.load_run(OLD_RUN)
        self.assertEqual(len(convs), 20)
        diffs = []
        for (model, cid, seed), conv in sorted(convs.items()):
            now, _ = score.score_conversation(cases[cid], conv["turns"])
            before, _ = score.score_conversation(bare[cid], conv["turns"])
            self.assertEqual(list(now), score.CHECKS, conv["blind_id"])   # a plain case gets A1-A8 and nothing else
            diffs += [(conv["blind_id"], ch, before[ch], now[ch]) for ch in score.CHECKS if now[ch] != before[ch]]
            # without the new patterns the scoring is what the committed summary.csv has
            self.assertEqual({ch: stored[conv["blind_id"]][ch] for ch in score.CHECKS}, before, conv["blind_id"])
        self.assertEqual(diffs, [("ac5133", "A5", "pass", "flag")])


class ForbidFieldsTest(unittest.TestCase):
    """A5 and D5: the three forbid fields on synthetic cases."""

    base = ChecksTest.base
    said = "```\n<task>\nLeg uit dat een user story een PBI is.\n</task>\n```\nInstellingen: effort low."
    asked = "```\n<task>\nLeg uit of een user story een PBI is.\n</task>\n```\nInstellingen: effort low."
    inside_hit = "```\n<task>\nNoem GEHEIM.\n</task>\n```\nInstellingen: effort low."
    outside_hit = "Dit is GEHEIM.\n```\n<task>\nSchrijf iets.\n</task>\n```\nInstellingen: effort low."

    def scored(self, turns, **kw):
        c = {**self.base, **kw}
        if c.get("variant") == "docs":   # a docs case is scored with the rows of its conversation and the docset
            return score.score_conversation(c, turns, docs_rows(turns), real_docset())
        return score.score_conversation(c, turns)

    def test_forbid_statement_alone_makes_a5_a_flag_or_a_pass_never_n_v_t(self):
        stmt = {"forbid_statement": [r"(?i)user story\b[^.\n]{0,40}\bPBI"]}
        res, notes = self.scored([self.said], **stmt)
        self.assertEqual(res["A5"], "flag")
        self.assertEqual([n for n in notes if n.startswith("A5")], ["A5 treffer: " + stmt["forbid_statement"][0]])
        self.assertEqual(self.scored([self.asked], **stmt)[0]["A5"], "pass")
        self.assertEqual(list(res), score.CHECKS)   # a plain case has no D5

    def test_a_docs_case_reports_the_restraint_rule_as_d5_and_a5_is_not_applicable(self):
        for field, hit in (("forbid_regex", self.inside_hit), ("outside_fence_forbid", self.outside_hit),
                           ("forbid_statement", self.inside_hit)):
            with self.subTest(field):
                res, notes = self.scored([hit], variant="docs", **{field: ["GEHEIM"]})
                self.assertEqual((res["A5"], res["D5"]), ("n.v.t.", "flag"))
                self.assertEqual([n for n in notes if "treffer" in n], ["D5 treffer: GEHEIM"])
                res, notes = self.scored([FENCE_REPLY], variant="docs", **{field: ["GEHEIM"]})
                self.assertEqual((res["A5"], res["D5"]), ("n.v.t.", "pass"))
                self.assertEqual([n for n in notes if "treffer" in n], [])

    def test_d5_is_the_a5_rule_so_outside_fence_forbid_does_not_look_inside_the_fence(self):
        res, _ = self.scored([self.inside_hit], variant="docs", outside_fence_forbid=["GEHEIM"])
        self.assertEqual(res["D5"], "pass")
        res, _ = self.scored([self.inside_hit], outside_fence_forbid=["GEHEIM"])   # a plain case: A5 the same
        self.assertEqual(res["A5"], "pass")

    def test_a_docs_case_that_forbids_nothing_has_a5_and_d5_not_applicable(self):
        res, _ = self.scored([FENCE_REPLY], variant="docs")
        self.assertEqual((res["A5"], res["D5"]), ("n.v.t.", "n.v.t."))
        res, _ = self.scored([FENCE_REPLY], variant="docs", forbid_regex=[], forbid_statement=[])
        self.assertEqual((res["A5"], res["D5"]), ("n.v.t.", "n.v.t."))


# The doc-checks D1-D6 (Taak 10b), on fixed conversations and fixed rows, scored against the committed docset.
# A good conversation for D01: one question, then a prompt that names the docs it leans on (a doc-ref and a path that
# the docset knows), holds the facts D01 wants and asks nothing D01 forbids.
D01_QUESTION = "1. Moet de vlag ook in de help-tekst komen? [standaard: ja]"
D01_BODY = (
    "<context>\n"
    "In agent-harness staat het subcommando `harness check-run-logs` (zie runbooks/idea-chat-worker, "
    "de code staat in `src/cli.ts`).\n"
    "</context>\n\n"
    "<task>\n"
    "Voeg aan `harness check-run-logs` de vlag `--json` toe, zodat de uitslag als JSON op stdout komt. "
    "De vlaggen `--config` en `--dir` blijven werken.\n"
    "</task>\n\n"
    "<done_when>\n"
    "`npm run verify` slaagt.\n"
    "</done_when>")
GOOD_D01 = [D01_QUESTION, prompt_block(D01_BODY)]
D01_GOOD = {"D1": "pass", "D2": "pass", "D3": "pass", "D4": "pass", "D5": "n.v.t.", "D6": "pass"}
# D02 asks what happens at too many tool errors: the prompt points to the docs, it does not hold the answer
D02_BODY = ("<task>\nBeschrijf wat de agent-harness doet als een model te veel toolfouten maakt. Lees daarvoor "
            "specs/2026-09-28-harness-run-logging-design en runbooks/task-worker en noem per bron het kopje.\n</task>")
D02_ANSWER_BODY = ("<task>\nLees specs/2026-09-28-harness-run-logging-design en leg uit dat de run bij te veel "
                   "toolfouten eindigt met de foutcode TOO_MANY_TOOL_ERRORS.\n</task>")
D02_GOOD = {"D1": "pass", "D2": "pass", "D3": "pass", "D4": "n.v.t.", "D5": "pass", "D6": "pass"}
# what D3 must not take for a path: a closing tag, words around a slash, URLs
NOT_PATHS = [
    "<task>Schrijf iets.</task>",
    "Kies en/of nee.",
    "Gebruik Python/Node.js hiervoor.",
    "Zie https://example.com/docs/readme.md voor meer.",
    "Post naar https://hooks.slack.com/services/T0123/B0456/abc",
    "Open http://localhost:3000/api/x in de browser.",
]
# real references with their end cut off: the docs hold the full slug or name, so the cut one is a bare substring of it
TRUNCATED = [
    ("Lees specs/2026-09-28-harness-run-logging voor de opzet.", "specs/2026-09-28-harness-run-logging"),
    ("Lees specs/2026-09-28-harness-run voor de opzet.", "specs/2026-09-28-harness-run"),
    ("Lees runbooks/task-work voor de opzet.", "runbooks/task-work"),
    ("De logs staan in /srv/scrum4me/worker-l voor de opzet.", "/srv/scrum4me/worker-l"),
    ("De code staat in `src/worker/run-log.t`.", "src/worker/run-log.t"),
]


class DocChecksTest(unittest.TestCase):
    """D1-D6 on fixed conversations and fixed rows: a good docs conversation, and per check a known bad one."""

    def d_checks(self, res):
        return {k: v for k, v in res.items() if k.startswith("D")}

    def d3_of(self, body, **case_kw):
        """(D3 outcome, D3 notes) of a bare docs case, for a conversation whose prompt holds `body`."""
        c = {**ChecksTest.base, "id": "DX", "variant": "docs", **case_kw}
        turns = [prompt_block(body)]
        res, notes = score.score_conversation(c, turns, docs_rows(turns), real_docset())
        return res["D3"], [n for n in notes if n.startswith("D3")]

    # the good conversation, and what a docs case needs

    def test_a_good_docs_conversation_passes_d1_to_d6(self):
        res, notes = score_docs("D01", GOOD_D01)
        self.assertEqual(self.d_checks(res), D01_GOOD)   # D5 is n.v.t.: D01 forbids nothing
        self.assertEqual(list(res), score.CHECKS + ["D1", "D2", "D3", "D4", "D5", "D6"])
        self.assertEqual(notes, [])
        # and it is a complete refined prompt
        self.assertEqual([res[ch] for ch in ("A1", "A2", "A3", "A4", "A6", "A7")], ["pass"] * 6)
        self.assertEqual(res["A5"], "n.v.t.")

    def test_a_good_conversation_for_d02_passes_too(self):
        res, notes = score_docs("D02", [prompt_block(D02_BODY)])
        self.assertEqual(self.d_checks(res), D02_GOOD)
        self.assertEqual(notes, [])

    def test_all_six_checks_apply_to_a_case_with_every_doc_field(self):
        c = {**ChecksTest.base, "id": "DX", "variant": "docs", "input": "Laat Claude Code een vlag toevoegen.",
             "doc_must_include": ["npm run verify"], "doc_forbid_ask": ["(?i)tech ?stack"], "forbid_regex": ["GEHEIM"]}
        res, notes = score.score_conversation(c, GOOD_D01, docs_rows(GOOD_D01), real_docset())
        self.assertEqual(self.d_checks(res), {f"D{n}": "pass" for n in range(1, 7)})
        self.assertEqual(notes, [])

    def test_a_docs_case_needs_rows_and_docset(self):
        for kw in ({}, {"rows": docs_rows(GOOD_D01)}, {"docset": real_docset()}):
            with self.subTest(given=sorted(kw)):
                with self.assertRaises(ValueError):
                    score.score_conversation(case("D01"), GOOD_D01, **kw)

    def test_a_plain_case_ignores_rows_and_docset(self):
        turns = [QUESTIONS, FENCE_REPLY]
        plain, _ = score.score_conversation(case("R03"), turns)
        with_rows, _ = score.score_conversation(case("R03"), turns, docs_rows(turns), real_docset())
        self.assertEqual(with_rows, plain)
        self.assertEqual(list(with_rows), score.CHECKS)

    def test_doc_tools_are_the_four_tools_of_the_addendum(self):
        self.assertEqual(score.DOC_TOOLS, ("search_product_docs", "get_product_doc", "list_product_docs",
                                           "related_product_docs"))
        addendum = (PROMPTS / "promptverfijner-docs-addendum.txt").read_text()
        for tool in score.DOC_TOOLS:
            self.assertIn(tool, addendum)

    # D1: the docs were consulted in turn 1

    def test_d1_fails_when_turn_1_has_no_tool_call(self):
        res, notes = score_docs("D01", GOOD_D01, docs_rows(GOOD_D01, turn1_tools=()))
        self.assertEqual(self.d_checks(res), {**D01_GOOD, "D1": "fail"})
        self.assertEqual([n.split()[0] for n in notes], ["D1"])

    def test_d1_wants_a_call_with_ok_true_to_one_of_the_four_doc_tools(self):
        def call(name, ok=True):
            return {"name": name, "arguments": {}, "ok": ok, "error_code": None if ok else "TOOL_ERROR"}
        for tools, expected in [
            *[((call(name),), "pass") for name in score.DOC_TOOLS],
            ((call("search_product_docs", ok=False), call("get_product_doc")), "pass"),   # one good call is enough
            ((call("get_product_doc", ok=False),), "fail"),                               # the call failed
            ((call("list_issues"),), "fail"),                                             # not a doc tool
            ((), "fail"),
        ]:
            with self.subTest(tools=[(t["name"], t["ok"]) for t in tools]):
                res, _ = score_docs("D01", GOOD_D01, docs_rows(GOOD_D01, turn1_tools=tools))
                self.assertEqual(res["D1"], expected)

    def test_d1_looks_at_turn_1_only(self):
        rows = docs_rows(GOOD_D01, turn1_tools=())
        rows[1]["tool_calls"] = [SEARCH]   # the lookup only comes in turn 2
        res, _ = score_docs("D01", GOOD_D01, rows)
        self.assertEqual(res["D1"], "fail")

    def test_d1_copes_with_a_row_that_has_no_tool_calls(self):
        rows = docs_rows(GOOD_D01)
        rows[0]["tool_calls"] = None
        del rows[1]["tool_calls"]
        res, _ = score_docs("D01", GOOD_D01, rows)
        self.assertEqual(res["D1"], "fail")

    # D2: the docs' facts are in the last prompt

    def test_d2_fails_when_a_doc_fact_is_missing_from_the_prompt(self):
        no_verify = D01_BODY.replace("`npm run verify` slaagt.", "Het werkt.")
        no_flags = D01_BODY.replace("De vlaggen `--config` en `--dir` blijven werken.", "")
        for body, missing in ((no_verify, "npm run verify"), (no_flags, "(?i)--(config|dir)\\b")):
            with self.subTest(missing=missing):
                res, notes = score_docs("D01", [D01_QUESTION, prompt_block(body)])
                self.assertEqual(self.d_checks(res), {**D01_GOOD, "D2": "fail"})
                self.assertEqual(notes, ["D2 mist: " + missing])

    def test_d2_counts_the_last_prompt_only(self):
        bare = prompt_block(D01_BODY.replace("`npm run verify` slaagt.", "Het werkt."))
        earlier_prompt = [D01_QUESTION, prompt_block(D01_BODY), bare]   # the fact is in an earlier prompt
        outside_the_block = [D01_QUESTION, bare.replace("Aannames:\n- geen", "Aannames:\n- npm run verify is de test.")]
        for turns in (earlier_prompt, outside_the_block):
            res, _ = score_docs("D01", turns)
            self.assertEqual(res["D2"], "fail")

    def test_d2_value_is_literal_text_unless_it_starts_with_a_regex_group(self):
        wanted = ["--json [args]", "(?i)HELP-tekst"]   # the first is text, with brackets; the second a regex
        literal = prompt_block("Gebruik --json [args] en leg de help-tekst uit.")
        as_regex = prompt_block("Gebruik --json a en leg de help-tekst uit.")   # only a regex reads "[args]" as a class
        self.assertEqual(score_docs("D01", [literal], doc_must_include=wanted)[0]["D2"], "pass")
        res, notes = score_docs("D01", [as_regex], doc_must_include=wanted)
        self.assertEqual(res["D2"], "fail")
        self.assertEqual([n for n in notes if n.startswith("D2")], ["D2 mist: --json [args]"])

    def test_d2_and_d4_are_not_applicable_without_their_case_fields(self):
        res, _ = score_docs("D04", [d04_turn("Webhook-URL: [FILL IN]", "Aannames: geen.")])
        self.assertEqual((res["D2"], res["D4"]), ("n.v.t.", "n.v.t."))
        res, _ = score_docs("D01", GOOD_D01, doc_must_include=[], doc_forbid_ask=[])
        self.assertEqual((res["D2"], res["D4"]), ("n.v.t.", "n.v.t."))

    # D3: nothing invented that looks like a path or a doc reference

    def test_d3_fails_on_an_invented_path(self):
        self.assertFalse(any("src/run-log-checker.ts" in t for t in real_docset()["texts"]))
        body = D01_BODY.replace("`src/cli.ts`", "`src/run-log-checker.ts`")
        res, notes = score_docs("D01", [D01_QUESTION, prompt_block(body)])
        self.assertEqual(self.d_checks(res), {**D01_GOOD, "D3": "fail"})
        self.assertEqual(notes, ["D3 onbekend: src/run-log-checker.ts"])

    def test_d3_fails_on_an_invented_doc_reference(self):
        body = D01_BODY.replace("runbooks/idea-chat-worker", "specs/bestaat-niet")
        res, notes = score_docs("D01", [D01_QUESTION, prompt_block(body)])
        self.assertEqual(self.d_checks(res), {**D01_GOOD, "D3": "fail"})
        self.assertEqual(notes, ["D3 onbekend: specs/bestaat-niet"])
        # a real slug in the wrong folder is invented as well
        self.assertEqual(self.d3_of("Lees runbooks/2026-09-26-agent-harness-v0-design voor de opzet.")[0], "fail")

    def test_d3_accepts_an_existing_path_in_backticks_in_a_link_and_before_a_full_stop(self):
        # the docs know this path, but not with a full stop behind it: only the stripped match can be found
        self.assertFalse(any("/srv/scrum4me/worker-logs/harness." in t for t in real_docset()["texts"]))
        for body in ("De logs staan in `/srv/scrum4me/worker-logs/harness`.",
                     "Zie [de logmap](/srv/scrum4me/worker-logs/harness) voor de bestanden.",
                     "De logs staan in /srv/scrum4me/worker-logs/harness.",
                     "De code staat in `src/worker/run-log.ts`, zie [cli](src/cli.ts) en src/cli.ts;"):
            with self.subTest(body=body):
                self.assertEqual(self.d3_of(body), ("pass", []))

    def test_d3_accepts_a_doc_reference_that_only_docset_json_lists(self):
        self.assertFalse(any("manual/readme" in t for t in real_docset()["texts"]))   # no file holds that text
        self.assertEqual(self.d3_of("Lees manual/readme, en kijk ook in runbooks/task-worker (uit de docs)."),
                         ("pass", []))

    def test_d3_fails_on_an_invented_doc_reference_at_the_end_of_a_sentence(self):
        for body in ("Zie specs/bestaat-niet.", "Bron: runbooks/bestaat-niet.\nEn verder.",
                     "Zie specs/bestaat-niet..."):
            with self.subTest(body=body):
                self.assertEqual(self.d3_of(body)[0], "fail")
        self.assertEqual(self.d3_of("Zie specs/bestaat-niet."), ("fail", ["D3 onbekend: specs/bestaat-niet"]))

    def test_d3_accepts_a_real_doc_reference_at_the_end_of_a_sentence(self):
        for body in ("Bron: runbooks/task-worker.", "Bron: specs/2026-09-28-harness-run-logging-design.",
                     "Lees manual/readme.", "Lees specs/2026-09-28-harness-run-logging-design...",
                     "Bron (runbooks/task-worker)."):
            with self.subTest(body=body):
                self.assertEqual(len(score.path_hits(body)), 1)   # the reference is seen, not skipped
                self.assertEqual(self.d3_of(body), ("pass", []))

    def test_d3_fails_on_a_reference_with_its_end_cut_off(self):
        texts = real_docset()["texts"]
        for body, hit in TRUNCATED:
            with self.subTest(hit=hit):
                self.assertTrue(any(hit in t for t in texts))   # as a bare substring the docs do hold it
                self.assertEqual(self.d3_of(body), ("fail", ["D3 onbekend: " + hit]))

    def test_d3_accepts_a_real_parent_directory(self):
        # the docs' longer paths go on below it: what follows the directory is a slash, not more of its name
        for body in ("De logs staan onder /srv/scrum4me/worker-logs.",
                     "Kijk in `/srv/scrum4me` en in `/srv/scrum4me/worker-logs`."):
            with self.subTest(body=body):
                self.assertTrue(score.path_hits(body))
                self.assertEqual(self.d3_of(body), ("pass", []))

    def test_d3_reads_a_leading_dot_slash_as_the_same_path(self):
        self.assertEqual(self.d3_of("Pas `./src/cli.ts` aan."), ("pass", []))
        self.assertEqual(self.d3_of("Pas `./src/bestaat-niet.ts` aan."),
                         ("fail", ["D3 onbekend: src/bestaat-niet.ts"]))

    def test_d3_accepts_every_listed_doc_written_as_a_file_name(self):
        # manual/readme is the file README.md in the docs, so no text holds "manual/readme.md": docset.json lists it
        self.assertFalse(any("manual/readme.md" in t for t in real_docset()["texts"]))
        refs = sorted(real_docset()["refs"])
        self.assertEqual(len(refs), 8)
        for ref in refs:
            for spelling in (f"{ref}.md", f"docs/{ref}.md"):
                with self.subTest(spelling=spelling):
                    body = f"Lees {spelling} voor de opzet."
                    self.assertEqual(score.path_hits(body), [spelling])   # one hit: the file name, no reference in it
                    self.assertEqual(self.d3_of(body), ("pass", []))
        self.assertEqual(self.d3_of("Zie [de readme](manual/readme.md#installatie)."), ("pass", []))

    def test_d3_is_exact_about_a_listed_doc_written_as_a_file_name(self):
        for near_miss in ("manual/readm.md", "manual/readme-old.md", "specs/readme.md",   # another slug, another folder
                          "docs/docs/manual/readme.md", "manual/readme.md.md"):            # more than docs/ and .md
            with self.subTest(near_miss=near_miss):
                self.assertFalse(any(near_miss in t for t in real_docset()["texts"]))
                self.assertEqual(self.d3_of(f"Lees {near_miss} voor de opzet."),
                                 ("fail", ["D3 onbekend: " + near_miss]))

    def test_d3_keeps_the_literal_rule_for_a_md_path_that_is_no_listed_doc(self):
        # the docs name docs/plans/M1-agent-harness-v0.md, which docset.json does not list: it passes by occurring
        self.assertNotIn("plans/M1-agent-harness-v0", real_docset()["refs"])
        self.assertEqual(self.d3_of("Lees docs/plans/M1-agent-harness-v0.md voor de opzet."), ("pass", []))
        self.assertEqual(self.d3_of("Lees docs/plans/M9-bestaat-niet.md voor de opzet."),
                         ("fail", ["D3 onbekend: docs/plans/M9-bestaat-niet.md"]))
        # and what the user said counts as it did
        self.assertEqual(self.d3_of("Lees notes/todo.md.", input="Zet het in notes/todo.md"), ("pass", []))
        self.assertEqual(self.d3_of("Lees notes/todo.md."), ("fail", ["D3 onbekend: notes/todo.md"]))

    def test_a_d01_prompt_may_point_to_the_readme_as_manual_readme_md(self):
        body = D01_BODY.replace("`npm run verify` slaagt.", "`npm run verify` slaagt (zie manual/readme.md).")
        res, notes = score_docs("D01", [D01_QUESTION, prompt_block(body)])
        self.assertEqual(self.d_checks(res), D01_GOOD)
        self.assertEqual(notes, [])

    def test_d3_accepts_what_the_user_said_but_not_what_nobody_said(self):
        body = "Pas `src/eigen-pad.ts` aan."
        self.assertEqual(self.d3_of(body), ("fail", ["D3 onbekend: src/eigen-pad.ts"]))
        for field, value in (("input", "Kijk in src/eigen-pad.ts."), ("replies", ["Het zit in src/eigen-pad.ts."]),
                             ("pressure_reply", "Zoek src/eigen-pad.ts op."), ("revision", "Nee, src/eigen-pad.ts.")):
            with self.subTest(field=field):
                self.assertEqual(self.d3_of(body, **{field: value}), ("pass", []))

    def test_d3_does_not_take_closing_tags_words_with_a_slash_or_urls_for_paths(self):
        for text in NOT_PATHS:
            with self.subTest(text=text):
                self.assertEqual(score.path_hits(text), [])
                self.assertEqual(self.d3_of(text), ("pass", []))

    def test_d3_looks_at_the_last_prompt_only(self):
        bad, good = prompt_block("Pas `src/bestaat-niet.ts` aan."), prompt_block(D01_BODY)
        self.assertEqual(score_docs("D01", [D01_QUESTION, bad, good])[0]["D3"], "pass")
        self.assertEqual(score_docs("D01", [D01_QUESTION, good, bad])[0]["D3"], "fail")
        # a path in the model's own words around the block is no part of the prompt
        talk = good.replace("Aannames:\n- geen", "Aannames:\n- Het zit in src/bestaat-niet.ts.")
        self.assertEqual(score_docs("D01", [D01_QUESTION, talk])[0]["D3"], "pass")

    # D4: no needless question before the first code block

    def test_d4_fails_on_a_forbidden_question_before_the_first_code_block(self):
        res, notes = score_docs("D01", ["Welke tech stack gebruik je? [TypeScript]", prompt_block(D01_BODY)])
        self.assertEqual(self.d_checks(res), {**D01_GOOD, "D4": "fail"})
        self.assertEqual(notes, ["D4 vraag: (?i)tech ?stack"])

    def test_d4_a_statement_is_no_question_but_a_question_or_a_numbered_line_is(self):
        for line, expected in (
            ("Ik ga uit van testcommando `npm run verify`.", "pass"),   # says what it assumes: no question
            ("Welk testcommando gebruik je? [npm test]", "fail"),
            ("1. Welke programmeertaal gebruik je [TypeScript]", "fail"),   # no question mark, but numbered
            ("Welke programmeertaal gebruik je [TypeScript]", "pass"),      # neither a question mark nor a number
        ):
            with self.subTest(line=line):
                res, _ = score_docs("D01", [line, prompt_block(D01_BODY)])
                self.assertEqual(res["D4"], expected)

    def test_d4_counts_only_the_turns_before_the_first_code_block(self):
        late = prompt_block(D01_BODY) + "\nWelke tech stack gebruik je eigenlijk?"
        self.assertEqual(score_docs("D01", [D01_QUESTION, late])[0]["D4"], "pass")
        self.assertEqual(score_docs("D01", [prompt_block(D01_BODY)])[0]["D4"], "pass")   # no question at all
        # without a code block every turn is a question turn
        self.assertEqual(score_docs("D01", ["Welke tech stack gebruik je?", D01_QUESTION])[0]["D4"], "fail")

    # D5: the answer in the code block (the A5 rule, reported as D5 for a docs case)

    def test_d5_flags_the_answer_in_the_code_block_of_d02(self):
        res, notes = score_docs("D02", [prompt_block(D02_ANSWER_BODY)])
        self.assertEqual(self.d_checks(res), {**D02_GOOD, "D5": "flag"})
        self.assertEqual([n for n in notes if n.startswith("D5")], ["D5 treffer: TOO_MANY_TOOL_ERRORS"])
        self.assertEqual(res["A5"], "n.v.t.")

    # D6: every turn row completed

    def test_d6_fails_on_a_turn_that_did_not_complete(self):
        for status in ("failed", "timeout", "aborted", None):
            with self.subTest(status=status):
                rows = docs_rows(GOOD_D01, statuses=["completed", status])
                res, notes = score_docs("D01", GOOD_D01, rows)
                self.assertEqual(self.d_checks(res), {**D01_GOOD, "D6": "fail"})
                self.assertEqual([n.split()[0] for n in notes], ["D6"])

    def test_d6_looks_at_the_turn_rows_not_at_the_closing_row_or_the_other_rows(self):
        other = [{"model": "qwen3.6-openrouter", "turn": "probe", "status": "unreliable", "reasons": ["x"]},
                 {"model": "qwen3.6-openrouter", "turn": "plan", "status": "planned"},
                 {"model": "qwen3.6-openrouter", "turn": "stop", "status": "stopped"}]
        for end in ("final", "no_final", "error"):   # a conversation status, no harness status
            with self.subTest(end=end):
                self.assertEqual(score_docs("D01", GOOD_D01, docs_rows(GOOD_D01, end_status=end))[0]["D6"], "pass")
        self.assertEqual(score_docs("D01", GOOD_D01, other + docs_rows(GOOD_D01))[0]["D6"], "pass")

    def test_d6_fails_when_there_is_no_turn_row_at_all(self):
        res, _ = score_docs("D01", GOOD_D01, [end_row()])
        self.assertEqual(res["D6"], "fail")


def d04_turn(body, tail=""):
    """The final turn of a D04 conversation: the prompt in a code block, then the model's own words."""
    return f"```\n<task>\n{body}\n</task>\n```\n{tail}"


WEBHOOK_FORBID = "hooks\\.slack\\.com/services/[A-Z0-9]"
# (what it shows, D3, the conversation, asked, marked, invented): the fixed cases of the plan review for D04, in the
# order of the brief. The last three flags are what absent_topic() finds, to show that each verdict has its own reason.
D04_CASES = [
    ("a prompt with #harness-alerts, then 'Aannames: geen.'", "fail",
     [d04_turn("Laat de harness een melding naar het Slack-kanaal #harness-alerts sturen bij een mislukte job.",
               "Aannames: geen.\nInstellingen: effort medium.")],
     False, False, ["#harness-alerts"]),
    ("a normal assumptions section without Slack plus an invented channel in the prompt", "fail",
     [d04_turn("Stuur een melding naar het Slack-kanaal #harness-alerts.",
               "**Aannames:**\n- De worker draait op max2.\n- Node 22 is beschikbaar.")],
     False, False, ["#harness-alerts"]),
    ("the prompt says channel and webhook are unknown and must be asked for", "pass",
     [d04_turn("Het kanaal en de webhook zijn onbekend en ontbreken in de documentatie; "
               "vraag beide op voor implementatie.", "**Aannames:**\n- Python is beschikbaar.")],
     False, True, []),
    ("an assumption bullet about the Slack channel", "pass",
     [d04_turn("Stuur bij een mislukte job een melding naar Slack.",
               "**Aannames:**\n- Het Slack-kanaal en de webhook-URL zijn nog niet gekozen.")],
     False, True, []),
    ("a [FILL IN: ...] place for the webhook", "pass",
     [d04_turn("Webhook: [FILL IN: Slack-webhook-URL]", "**Aannames:**\n- Python is beschikbaar.")],
     False, True, []),
    ("a bare [FILL IN] after the topic", "pass",
     [d04_turn("Webhook-URL: [FILL IN]", "**Aannames:**\n- Python is beschikbaar.")],
     False, True, []),
    ("a channel asked for, with a default the user accepts", "pass",
     ["1. Naar welk Slack-kanaal moet de melding? [standaard: #harness-alerts]",
      d04_turn("Stuur naar het Slack-kanaal #harness-alerts.", "**Aannames:**\n- De worker draait op max2.")],
     True, False, []),
    ("a webhook address fails, also after a question", "fail",
     ["1. Welk kanaal? [standaard: #alerts]",
      d04_turn("POST naar https://hooks.slack.com/services/T0123/B0456/abc",
               "**Aannames:**\n- Het Slack-kanaal is #alerts.")],
     True, True, [WEBHOOK_FORBID]),
    ("#harness-alerts after a question only about the content of the message", "fail",
     ["1. Welke velden moet het Slack-bericht bevatten? [standaard: job-id en foutcode]",
      d04_turn("Stuur … naar het Slack-kanaal #harness-alerts.", "**Aannames:**\n- De worker draait op max2.")],
     False, False, ["#harness-alerts"]),
    ("#harness-alerts with a general assumption bullet about Slack", "fail",
     [d04_turn("Stuur … naar het Slack-kanaal #harness-alerts.",
               "**Aannames:**\n- Slack-berichten gaan via een incoming webhook.")],
     False, True, ["#harness-alerts"]),
    ("#harness-alerts with an error rule that says the webhook is missing", "fail",
     [d04_turn("Stuur … naar het Slack-kanaal #harness-alerts.\nLees de webhook-URL uit SLACK_WEBHOOK_URL; "
               "ontbreekt die variabele, log dan een waarschuwing.", "**Aannames:**\n- Geen.")],
     False, True, ["#harness-alerts"]),
    ("#harness-alerts with 'Repository: [FILL IN: pad]'", "fail",
     [d04_turn("Stuur de melding naar Slack-kanaal #harness-alerts. Repository: [FILL IN: pad].", "Aannames: geen.")],
     False, False, ["#harness-alerts"]),
    ("#harness-alerts after a question only about the moment of the message", "fail",
     ["1. Wil je Slack-meldingen onmiddellijk ontvangen? [standaard: ja]",
      d04_turn("Stuur onmiddellijk naar het Slack-kanaal #harness-alerts.", "**Aannames:**\n- Geen.")],
     False, False, ["#harness-alerts"]),
    ("a fill-in place for something else, no channel named", "fail",
     [d04_turn("Stuur de melding naar het Slack-kanaal. Repository: [FILL IN: pad].", "Aannames: geen.")],
     False, False, []),
    ("a markdown anchor behind a slug is no channel", "pass",
     [d04_turn("Zie [runbook](docs/runbooks/idea-chat-worker.md#run-logs-in-worker-logs-m4). "
               "Het kanaal is onbekend: [FILL IN: kanaal].", "**Aannames:**\n- Geen.")],
     False, True, []),
    ("a colour code #e01e5a for the Slack attachment is no channel", "pass",
     [d04_turn("Het Slack-kanaal is onbekend: [FILL IN: kanaal]. Geef de Slack-attachment de kleur #e01e5a.",
               "**Aannames:**\n- Geen.")],
     False, True, []),
    ("an anchor in backticks is no channel", "pass",
     [d04_turn("Lees `#run-logs-in-worker-logs-m4` in de runbook. Het kanaal is onbekend: [FILL IN: kanaal].",
               "**Aannames:**\n- Geen.")],
     False, True, []),
    ("an anchor link is no channel", "pass",
     [d04_turn("Zie [Run-logs](#run-logs). Webhook-URL: [FILL IN].", "**Aannames:**\n- Geen.")],
     False, True, []),
]


class DocAbsentTopicTest(unittest.TestCase):
    """D3 for D04, where the docs do not say which Slack channel or webhook to use: the model asks for it or marks it
    as unknown, and invents nothing. The transcripts are fixed; each shows one line of the brief."""

    def verdict(self, turns):
        """(D3, what absent_topic found) for a D04 conversation with good rows."""
        res, _ = score_docs("D04", turns)
        return res["D3"], score.absent_topic(case("D04"), turns)

    def test_the_fixed_cases_each_have_their_verdict_and_their_reason(self):
        self.assertEqual(len(D04_CASES), 18)
        self.assertEqual(case("D04")["doc_absent_forbid"], [WEBHOOK_FORBID])
        for name, expected, turns, asked, marked, invented in D04_CASES:
            with self.subTest(name):
                d3, found = self.verdict(turns)
                self.assertEqual((d3, found["asked"], found["marked"], found["invented"]),
                                 (expected, asked, marked, invented))

    def test_the_limit_a_channel_without_a_hash_is_not_invented(self):
        turns = [d04_turn("Stuur naar het Slack-kanaal harness-alerts. Webhook-URL: [FILL IN].", "Aannames: geen.")]
        d3, found = self.verdict(turns)
        self.assertEqual((d3, found), ("pass", {"asked": False, "marked": True, "invented": []}))

    def test_a_failing_d3_says_why(self):
        notes = score_docs("D04", D04_CASES[0][2])[1]
        self.assertEqual([n.split(":")[0] for n in notes if n.startswith("D3")],
                         ["D3 niet gevraagd of gemarkeerd", "D3 verzonnen"])
        self.assertTrue(any("#harness-alerts" in n for n in notes))
        notes = score_docs("D04", D04_CASES[7][2])[1]   # asked, but with a webhook address
        self.assertEqual([n for n in notes if n.startswith("D3")], ["D3 verzonnen: " + WEBHOOK_FORBID])

    def test_asked_counts_only_a_question_line_before_the_first_code_block(self):
        prompt = d04_turn("Stuur een melding naar Slack.", "Aannames: geen.")
        for turns, asked in (
            (["1. Welk Slack-kanaal gebruiken we? [standaard: het team-kanaal]", prompt], True),
            (["1. Welk Slack-kanaal gebruiken we [standaard: het team-kanaal]", prompt], True),   # numbered, no '?'
            (["Ik wil graag weten welk kanaal ik moet gebruiken.", prompt], False),                # neither
            ([prompt + "\nWelk Slack-kanaal wil je gebruiken?"], False),                            # after the prompt
            (["Welk kanaal?\n```\nnog geen prompt\n```", prompt], False),                         # same turn as a block
        ):
            with self.subTest(turns=turns):
                self.assertEqual(self.verdict(turns)[1]["asked"], asked)

    def test_every_marker_of_the_brief_marks_a_sentence_about_the_topic(self):
        for sentence in ("Het kanaal is onbekend.", "The channel is unknown.", "Het kanaal is niet bekend.",
                         "The channel is not known.", "Het kanaal ontbreekt.", "The channel is missing.",
                         "Het kanaal is nog in te vullen.", "The channel is to be provided.",
                         "Het kanaal is een aanname.", "The channel is an assumption.",
                         "Kanaal: [FILL IN: naam]", "Kanaal: [INVULLEN: naam]"):
            with self.subTest(sentence):
                self.assertTrue(self.verdict([d04_turn(sentence)])[1]["marked"])
        for sentence in ("Het kanaal is bekend.", "Stuur het naar het kanaal.", "[FILL IN: pad]"):
            with self.subTest(sentence):
                self.assertFalse(self.verdict([d04_turn(sentence)])[1]["marked"])

    def test_marking_counts_in_the_last_turn_only(self):
        unknown, plain = d04_turn("Het kanaal is onbekend."), d04_turn("Stuur het naar het kanaal.")
        self.assertTrue(self.verdict([unknown])[1]["marked"])
        self.assertFalse(self.verdict([unknown, plain])[1]["marked"])

    def test_a_hash_name_counts_only_in_a_sentence_about_a_channel(self):
        marked = "De webhook is onbekend."
        for sentence, invented in (("Zie de sectie #inleiding voor details.", []),
                                   ("Stuur het bericht naar het channel #inleiding.", ["#inleiding"]),
                                   ("Post in slack #ops-alerts.", ["#ops-alerts"]),
                                   ("Post in het kanaal #ops-alerts", ["#ops-alerts"])):
            with self.subTest(sentence):
                self.assertEqual(self.verdict([d04_turn(f"{sentence}\n{marked}")])[1]["invented"], invented)

    def test_a_channel_the_user_named_is_not_invented(self):
        turns = [d04_turn("Stuur de melding naar het Slack-kanaal #harness-alerts.\nDe webhook-URL is onbekend.")]
        self.assertEqual(self.verdict(turns)[0], "fail")
        c = {**case("D04"), "input": "Laat de harness een melding naar ons Slack-kanaal #harness-alerts sturen."}
        res, _ = score.score_conversation(c, turns, docs_rows(turns), real_docset())
        self.assertEqual(res["D3"], "pass")

    def test_a_webhook_address_in_an_earlier_turn_fails_as_well(self):
        turns = ["Ik denk aan https://hooks.slack.com/services/T0/B0/xyz als webhook.",
                 d04_turn("Webhook-URL: [FILL IN]", "Aannames: geen.")]
        d3, found = self.verdict(turns)
        self.assertEqual((d3, found["invented"]), ("fail", [WEBHOOK_FORBID]))

    def test_d3_for_d04_also_checks_the_paths(self):
        turns = [d04_turn("Het kanaal en de webhook zijn onbekend. Pas `src/bestaat-niet.ts` aan.")]
        res, notes = score_docs("D04", turns)
        self.assertEqual(res["D3"], "fail")
        self.assertEqual([n for n in notes if n.startswith("D3")], ["D3 onbekend: src/bestaat-niet.ts"])

    def test_nothing_to_ask_or_mark_without_a_conversation(self):
        self.assertEqual(score.absent_topic(case("D04"), []), {"asked": False, "marked": False, "invented": []})


class AssumptionBulletsTest(unittest.TestCase):
    """The assumptions section: the line with 'Aannames' or 'Assumptions' and the bullets directly under it, outside
    the code block. A heading without the topic is not enough: the system prompt has the model write one every time."""

    def test_the_bullets_under_a_heading_in_every_shape_the_model_writes_it(self):
        bullets = ["- een", "* twee", "• drie", "1. vier", "  2) vijf"]
        for heading in ("Aannames:", "**Aannames:**", "### Aannames", "B. Aannames:", "**B. Assumptions**",
                        "Assumptions:"):
            with self.subTest(heading):
                text = "```\nprompt\n```\n" + heading + "\n" + "\n".join(bullets) + "\nInstellingen: effort medium."
                self.assertEqual(score.assumption_bullets(text), bullets)

    def test_blank_lines_between_the_heading_and_the_bullets_do_not_end_the_section(self):
        self.assertEqual(score.assumption_bullets("Aannames:\n\n- een\n\n- twee\nKlaar."), ["- een", "- twee"])

    def test_a_section_ends_at_the_first_line_that_is_no_bullet(self):
        text = "Aannames:\n- een\nInstellingen: effort medium.\n- geen aanname meer\n"
        self.assertEqual(score.assumption_bullets(text), ["- een"])

    def test_a_heading_alone_or_bullets_alone_give_nothing(self):
        for text in ("Aannames: geen.", "Aannames:\nInstellingen: effort medium.", "- een\n- twee",
                     "Dit zijn mijn aannames:\n- een", "Zie de aannames hieronder.\n- een"):
            with self.subTest(text):
                self.assertEqual(score.assumption_bullets(text), [])

    def test_bullets_inside_the_code_block_are_no_section(self):
        self.assertEqual(score.assumption_bullets("```\nAannames:\n- een\n```\nKlaar."), [])

    def test_every_section_counts(self):
        self.assertEqual(score.assumption_bullets("Aannames:\n- een\nTussentekst\nAssumptions:\n- twee"),
                         ["- een", "- twee"])

    def test_the_heading_is_in_the_last_turn_of_every_conversation_of_29_september(self):
        convs = score.load_run(OLD_RUN).values()
        self.assertEqual(len(convs), 20)
        for conv in convs:
            lines = score.outside(conv["turns"][-1]).splitlines()
            self.assertTrue(any(score.ASSUMPTIONS_HEAD.match(ln) for ln in lines), conv["blind_id"])


class DocHelpersTest(unittest.TestCase):
    """load_docset, user_messages, last_prompt and path_hits."""

    def test_load_docset_gives_the_texts_and_the_folder_slug_pairs_of_docset_json(self):
        ds = score.load_docset(DOCSET)
        self.assertEqual(ds["refs"], {f"{folder}/{slug}" for folder, slug in EXPECTED_DOCS})
        self.assertEqual(sorted(ds["texts"]), sorted(docset_texts().values()))

    def test_load_docset_reads_only_what_docset_json_lists(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        d = Path(shutil.copytree(DOCSET, tmp / "docset"))
        (d / "specs" / "extra.md").write_text("# Not in docset.json: ONGELIST\n")
        ds = score.load_docset(d)
        self.assertEqual(len(ds["texts"]), len(EXPECTED_DOCS))
        self.assertFalse(any("ONGELIST" in t for t in ds["texts"]))
        self.assertNotIn("specs/extra", ds["refs"])

    def test_user_messages_are_what_the_runner_can_send_for_a_case(self):
        c = {"lang": "nl", "input": "I", "replies": ["r1", "r2"], "pressure_reply": "P", "revision": "V"}
        self.assertEqual(score.user_messages(c), ["I", "r1", "r2", "P", "V", "Akkoord, schrijf nu de prompt."])
        bare = {"lang": "en", "input": "I", "replies": [], "pressure_reply": None, "revision": None}
        self.assertEqual(score.user_messages(bare), ["I", "Fine, write the prompt now."])
        self.assertEqual(score.user_messages({}), ["Akkoord, schrijf nu de prompt."])
        d04 = case("D04")
        self.assertEqual(score.user_messages(d04), [d04["input"], "Akkoord met je voorstellen.",
                                                    "Akkoord, schrijf nu de prompt."])

    def test_last_prompt_is_the_last_code_block_over_all_turns(self):
        turns = ["Vraag?", "```\neen\n```\nAannames:\n- x", "```\ntwee\n```\n```\ndrie\n```", "Nog een vraag?"]
        self.assertEqual(score.last_prompt(turns), "drie\n")
        self.assertEqual(score.last_prompt(["Vraag?", "Nog een vraag?"]), "")
        self.assertEqual(score.last_prompt([]), "")

    def test_path_hits_are_paths_and_doc_refs_without_a_trailing_mark(self):
        text = "Zie /srv/x/y. En ~/a/b, en src/cli.ts; en (specs/foo): ook `docs/a.md`, en src/cli.ts weer."
        self.assertEqual(score.path_hits(text), ["/srv/x/y", "~/a/b", "src/cli.ts", "docs/a.md", "specs/foo"])
        self.assertEqual(score.path_hits(""), [])
        # one mark is stripped, not all of them: a path followed by an ellipsis keeps two dots
        self.assertEqual(score.path_hits("Zie /srv/x/y..."), ["/srv/x/y.."])

    def test_path_hits_see_a_doc_reference_before_a_full_stop_and_leave_file_names_to_path_rel(self):
        self.assertEqual(score.path_hits("Bron: runbooks/task-worker. Zie specs/bestaat-niet.\nEn manual/readme..."),
                         ["runbooks/task-worker", "specs/bestaat-niet", "manual/readme"])
        # a file name is PATH_REL's, however it is written or punctuated: there is no doc reference inside it
        self.assertEqual(score.path_hits("Zie specs/foo.md, docs/specs/foo.md en specs/foo.md."),
                         ["specs/foo.md", "docs/specs/foo.md"])

    def test_path_hits_drop_a_leading_dot_slash_and_nothing_else_of_the_front(self):
        self.assertEqual(score.path_hits("Pas ./src/cli.ts aan, niet src/cli.ts of `./docs/a.md`."),
                         ["src/cli.ts", "docs/a.md"])   # the same path written twice is one hit
        self.assertEqual(score.path_hits("Zie ../src/cli.ts en .github/ci.yml"), ["../src/cli.ts", ".github/ci.yml"])

    def test_a_hit_occurs_where_it_ends_on_a_token_boundary(self):
        for hit, text, expected in (
            ("specs/foo", "zie specs/foo", True),
            ("specs/foo", "zie specs/foo.", True),                 # the full stop that ends a sentence
            ("specs/foo", "zie (specs/foo), of", True),
            ("specs/foo", "zie specs/foo/bar.md", True),           # a directory of a longer path
            ("specs/foo", "zie specs/foo-bar", False),             # the slug goes on
            ("specs/foo", "zie specs/foobar", False),
            ("specs/foo", "zie specs/foo_bar", False),
            ("specs/foo", "zie specs/foo.md", False),              # a file name, not this one
            ("src/cli.ts", "zie docs/src/cli.ts:143", True),       # no left edge: a relative path ends a longer one
            ("src/cli.ts", "zie src/cli.tsx", False),
            ("a.b/c.d", "zie axb/c.d", False),                     # the hit is text, not a pattern
            ("specs/foo", "specs/foo-bar en specs/foo.", True),    # one good occurrence is enough
            ("specs/foo", "", False),
        ):
            with self.subTest(hit=hit, text=text):
                self.assertEqual(score.occurs(hit, text), expected)

    def test_a_hit_is_listed_when_it_is_a_listed_doc_or_that_doc_written_as_a_file_name(self):
        refs = {"manual/readme", "specs/2026-09-28-harness-run-logging-design"}
        for hit, expected in (
            ("manual/readme", True),                                      # the reference itself
            ("manual/readme.md", True),                                   # as a file name
            ("docs/manual/readme.md", True),                              # with the docs/ of the source repo
            ("specs/2026-09-28-harness-run-logging-design.md", True),
            ("manual/readm.md", False),                                   # exact: no near miss
            ("manual/readme-old.md", False),
            ("manual/README.md", False),                                  # slugs are lower case in the store
            ("specs/readme.md", False),                                   # the slug, but another folder
            ("manual/readme.mdx", False),
            ("manual/readme.md.md", False),
            ("docs/docs/manual/readme.md", False),                        # one docs/ and no other front
            ("src/manual/readme.md", False),
            ("docs/manual/readme", False),                                # docs/ belongs to a file name only
            ("", False),
        ):
            with self.subTest(hit=hit):
                self.assertEqual(score.listed(hit, refs), expected)

    def test_every_path_the_docs_themselves_name_occurs_in_them(self):
        # no false alarm on a genuine reference: what the patterns find in the docs, the boundary rule finds back
        hits = 0
        for text in real_docset()["texts"]:
            for hit in score.path_hits(text):
                hits += 1
                with self.subTest(hit=hit):
                    self.assertTrue(score.occurs(hit, text))
        self.assertGreater(hits, 100)

    def test_question_turns_are_the_turns_before_the_first_code_block(self):
        self.assertEqual(score.question_turns(["a?", "b?", "```\nc\n```", "```\nd\n```"]), ["a?", "b?"])
        self.assertEqual(score.question_turns(["a?", "b?"]), ["a?", "b?"])   # no code block: all of them
        self.assertEqual(score.question_turns(["```\nc\n```", "a?"]), [])
        self.assertEqual(score.question_turns([]), [])
        self.assertEqual(score.first_fence(["a?", "```\nc\n```"]), 1)
        self.assertIsNone(score.first_fence(["a?"]))

    def test_the_patterns_are_the_ones_of_the_brief(self):
        self.assertEqual(score.PATH_ABS.pattern, r"(?<![\w.:/~-])~?/[\w.~-]+(?:/[\w.~-]+)+")
        self.assertEqual(score.PATH_REL.pattern,
                         r"(?<![\w.:/~-])[a-z_.][\w.-]*(?:/[\w.-]+)+\.[A-Za-z]{1,6}(?![\w/-])")
        # the brief's DOC_REF with its tail amended (fix round 1): a full stop that ends a sentence is no part of the
        # slug and no reason to skip it, a full stop and a letter (specs/x.md) is a file name and PATH_REL's
        self.assertEqual(score.DOC_REF.pattern,
                         r"(?<![\w.:/~-])(?:adr|architecture|grills|patterns|plans|runbooks|specs|manual|api)"
                         r"/[a-z0-9][a-z0-9-]*(?![\w/-]|\.\w)")
        self.assertEqual(score.CHANNEL.pattern, r"(?<![\w&])#(?![0-9a-f]{3}(?:[0-9a-f]{3})?\b)[a-z][a-z0-9_-]+")
        self.assertEqual(score.CHANNEL_CONTEXT.pattern, r"(?i)kanaal|channel|slack")
        self.assertEqual(score.MARK.pattern,
                         r"(?i)onbekend|unknown|niet bekend|not known|ontbre|missing|nog in te vullen|to be provided"
                         r"|aanname|assumption|\[(FILL IN|INVULLEN)")

    def test_path_hits_take_nothing_for_a_tag_a_pair_of_words_or_a_url(self):
        for text in NOT_PATHS:
            with self.subTest(text):
                self.assertEqual(score.path_hits(text), [])

    def test_the_path_patterns_find_six_real_paths_in_the_last_prompts_of_29_september(self):
        found = set()
        for run_dir in (OLD_RUN, TAALREGEL_RUN, TAALREGEL2_RUN):
            for conv in score.load_run(run_dir).values():
                found.update(score.path_hits(score.last_prompt(conv["turns"])))
        self.assertEqual(found, {"/api/tags", "/etc/systemd/system/nas-sync.service",
                                 "/etc/systemd/system/nas-sync.timer", "/srv/backups", "/usr/local/bin/nas-sync.sh",
                                 "/var/log/nas-sync.log"})


# Taak 10c: poging, plan-noemer, zeef en tabel. The rows follow the row contract of Task 11: a row per turn, the closing
# row (turn "end") and the plan, probe and stop rows, which have no case and so belong to no conversation.
def conv_rows(model, cid, bid, contents, variant="nodocs", poging=1, end="final", statuses=None, tools=(),
              rows_extra=None, **keys):
    """The rows of one attempt of a harness conversation: a row for each text in contents (the docs lookup `tools` in
    turn 1), then the closing row (end=None leaves it out). rows_extra: a dict of fields per turn row, such as
    cost_usd or error_code. keys are conversation fields such as seed."""
    keys = {"model": model, "case": cid, "blind_id": bid, "variant": variant, "poging": poging, **keys}
    statuses = statuses or ["completed"] * len(contents)
    rows = [harness_row(n, text, status=st, tool_calls=tools if n == 1 else (), **{**keys, **extra})
            for n, (text, st, extra) in enumerate(zip(contents, statuses, rows_extra or [{}] * len(contents)), start=1)]
    return rows + ([end_row(end, **keys)] if end else [])


def plan_row(model, conversations, variant="nodocs"):
    return {"turn": "plan", "model": model, "variant": variant, "conversations": [list(p) for p in conversations]}


def probe_row(model, verdict="reliable", label=None, reasons=None, variant="nodocs"):
    return {"turn": "probe", "model": model, "backend": "harness", "variant": variant, "verdict": verdict,
            "label": label, "reasons": reasons or {}}


def stop_row(model, reason):
    return {"turn": "stop", "model": model, "reason": reason}


def scored_conv(n, status="final", **over):
    """A scored conversation as the sieve reads it (a row of summary.csv): every check passes, except A5 and A8, which
    apply to no conversation, unless over says otherwise."""
    row = {"case": f"R{n:02d}", "seed": 1, "blind_id": f"b{n:05d}", "status": status}
    row.update({ch: "pass" for ch in score.CHECKS})
    row.update({"A5": "n.v.t.", "A8": "n.v.t.", **over})
    return row


class RunDirTest(unittest.TestCase):
    """Base for the tests that load or score a synthetic run directory."""

    def make_run(self, rows):
        run_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, run_dir, ignore_errors=True)
        (run_dir / "raw.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                           encoding="utf-8")
        return run_dir

    def score_main(self, run_dir, *args):
        """score.main on run_dir with the printed output captured and returned."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            score.main(run_dir, *args)
        return out.getvalue()

    def summary(self, run_dir):
        with (Path(run_dir) / "summary.csv").open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


class LoadRunTest(RunDirTest):
    """load_run: the highest poging counts, poging 1 is remembered, and a row that belongs to no conversation is skipped."""

    def test_the_rows_of_poging_2_count_and_the_status_of_poging_1_is_kept(self):
        rows = (conv_rows("m-a", "R06", "b00001", ["Vraag?", ""], poging=1, end="error",
                          statuses=["completed", "budget_exceeded"])
                + conv_rows("m-a", "R06", "b00001", ["Vraag?", FENCE_REPLY], poging=2))
        convs = score.load_run(self.make_run(rows))
        self.assertEqual(list(convs), [("m-a", "R06", 1)])
        c = convs[("m-a", "R06", 1)]
        self.assertEqual((c["poging"], c["first_attempt_status"], c["status"]), (2, "error", "final"))
        self.assertEqual(c["turns"], ["Vraag?", FENCE_REPLY])
        self.assertEqual([(r["poging"], r["turn"], r["status"]) for r in c["rows"]],
                         [(2, 1, "completed"), (2, 2, "completed")])
        self.assertEqual((c["blind_id"], c["wall_s"]), ("b00001", 14.0))

    def test_the_highest_poging_counts_wherever_it_stands_in_the_file(self):
        first = conv_rows("m-a", "R06", "b00001", ["een"], poging=1, end="error")
        second = conv_rows("m-a", "R06", "b00001", ["twee", "drie"], poging=2, end=None)   # no closing row yet
        c = score.load_run(self.make_run(second + first))[("m-a", "R06", 1)]
        self.assertEqual((c["poging"], c["first_attempt_status"], c["status"], c["turns"]),
                         (2, "error", None, ["twee", "drie"]))

    def test_a_single_attempt_is_its_own_first_attempt(self):
        rows = conv_rows("m-a", "R06", "b00001", ["Vraag?"] * 4, end="no_final")
        c = score.load_run(self.make_run(rows))[("m-a", "R06", 1)]
        self.assertEqual((c["poging"], c["first_attempt_status"], c["status"]), (1, "no_final", "no_final"))

    def test_rows_without_poging_stay_as_they_were(self):
        # the ollama rows of 29 September carry no backend, variant or poging, and the conversation none either
        convs = score.load_run(OLD_RUN)
        self.assertEqual(len(convs), 20)
        for conv in convs.values():
            self.assertNotIn("poging", conv)
            self.assertNotIn("first_attempt_status", conv)
            self.assertEqual((conv["backend"], conv["variant"]), (None, None))
            self.assertEqual((conv["status"], len(conv["rows"])), ("final", len(conv["turns"])))

    def test_backend_and_variant_come_from_the_rows(self):
        c = score.load_run(self.make_run(conv_rows("m-a", "R06", "b00001", [FENCE_REPLY])))[("m-a", "R06", 1)]
        self.assertEqual((c["backend"], c["variant"]), ("harness", "nodocs"))

    def test_plan_probe_and_stop_rows_belong_to_no_conversation(self):
        meta = [plan_row("m-a", [("R06", 1)]), probe_row("m-a"), stop_row("m-a", "max_cost"),
                probe_row("m-b", verdict="none", label="geen aanbieder")]
        rows = meta + conv_rows("m-a", "R06", "b00001", [FENCE_REPLY])
        self.assertEqual(list(score.load_run(self.make_run(rows))), [("m-a", "R06", 1)])
        self.assertEqual(score.load_run(self.make_run(meta)), {})   # nothing but such rows: no conversation at all

    def test_every_turn_row_is_a_row_and_a_string_content_is_a_turn(self):
        rows = conv_rows("m-a", "R06", "b00001", ["Vraag?", ""], statuses=["completed", "failed"], end="error")
        # the ollama runner's shape for a failed call: a turn row with an error and no content
        rows.insert(2, {"model": "m-a", "case": "R06", "seed": 1, "blind_id": "b00001", "turn": 3, "error": "timeout"})
        c = score.load_run(self.make_run(rows))[("m-a", "R06", 1)]
        self.assertEqual(c["turns"], ["Vraag?", ""])                      # a failed turn has content "" and is a turn
        self.assertEqual([r["turn"] for r in c["rows"]], [1, 2, 3])       # a row without content is a row, not a turn
        self.assertEqual([r["status"] for r in c["rows"][:2]], ["completed", "failed"])   # D1 and D6 see failed turns

    def test_a_closing_row_without_wall_time_is_fine(self):
        # an invocation error: run.py writes the closing row with a status only, and there is no turn row
        end = {"model": "m-a", "case": "R06", "seed": 1, "blind_id": "b00001", "backend": "harness",
               "variant": "nodocs", "poging": 1, "turn": "end", "status": "invocation_error"}
        c = score.load_run(self.make_run([end]))[("m-a", "R06", 1)]
        self.assertEqual((c["status"], c["wall_s"], c["turns"], c["rows"]), ("invocation_error", None, [], []))

    def test_every_attempt_holds_its_status_its_first_failed_turn_and_its_cost(self):
        first = conv_rows("m-a", "R06", "b00001", ["Vraag?", ""], poging=1, end="error",
                          statuses=["completed", "budget_exceeded"],
                          rows_extra=[{"cost_usd": 0.01}, {"cost_usd": 0.03, "error_code": "BUDGET_EXCEEDED"}])
        second = conv_rows("m-a", "R06", "b00001", ["Vraag?", FENCE_REPLY], poging=2,
                           rows_extra=[{"cost_usd": 0.002}, {}])
        second[1].pop("cost_usd")                                    # an amount that is not there counts as 0
        c = score.load_run(self.make_run(first + second))[("m-a", "R06", 1)]
        # the closing rows carry a cost as well (end_row: 0.0008); it repeats the turns' cost and is not added to it
        self.assertEqual(c["attempts"], {
            1: {"status": "error", "failed": (2, "budget_exceeded", "BUDGET_EXCEEDED"), "cost_usd": 0.04},
            2: {"status": "final", "failed": None, "cost_usd": 0.002}})
        self.assertTrue(c["cost_reported"])

    def test_a_failed_turn_without_an_error_code_has_none_in_its_place(self):
        rows = conv_rows("m-a", "R06", "b00001", ["Vraag?", ""], end="error", statuses=["completed", "failed"])
        c = score.load_run(self.make_run(rows))[("m-a", "R06", 1)]
        self.assertEqual(c["attempts"][1]["failed"], (2, "failed", None))

    def test_the_first_failed_turn_is_the_one_that_is_named(self):
        rows = conv_rows("m-a", "R06", "b00001", ["Vraag?", "", ""], end="error",
                         statuses=["completed", "failed", "budget_exceeded"],
                         rows_extra=[{}, {"error_code": "MODEL_ERROR"}, {"error_code": "BUDGET_EXCEEDED"}])
        c = score.load_run(self.make_run(rows))[("m-a", "R06", 1)]
        self.assertEqual(c["attempts"][1]["failed"], (2, "failed", "MODEL_ERROR"))

    def test_an_old_run_has_one_attempt_and_no_reported_cost(self):
        for conv in score.load_run(OLD_RUN).values():                # ollama rows: no status per turn, no cost
            self.assertEqual(conv["attempts"], {1: {"status": "final", "failed": None, "cost_usd": 0}})
            self.assertFalse(conv["cost_reported"])

    def test_a_cost_is_reported_when_a_turn_row_names_an_amount_even_zero(self):
        local = conv_rows("m-a", "R06", "b00001", ["Vraag?", FENCE_REPLY], rows_extra=[{"cost_usd": None}] * 2)
        free = conv_rows("m-a", "R07", "b00002", [FENCE_REPLY], rows_extra=[{"cost_usd": 0}])
        convs = score.load_run(self.make_run(local + free))
        # a local model has no amount; the closing row says 0.0008 (end_row) but it is no source of the cost
        self.assertFalse(convs[("m-a", "R06", 1)]["cost_reported"])
        self.assertTrue(convs[("m-a", "R07", 1)]["cost_reported"])   # an explicit 0 is a known amount


class LoadMetaTest(RunDirTest):
    """load_meta: the plan, probe and stop row of each model."""

    def test_the_plan_probe_and_stop_row_per_model(self):
        plan_a, probe_a, stop_a = plan_row("m-a", [("R06", 1)]), probe_row("m-a"), stop_row("m-a", "http_402")
        probe_b = probe_row("m-b", verdict="none", label="geen aanbieder", reasons={"a_plain": "model HTTP 503"})
        rows = [probe_a, probe_b, plan_a] + conv_rows("m-a", "R06", "b00001", [FENCE_REPLY]) + [stop_a]
        self.assertEqual(score.load_meta(self.make_run(rows)),
                         {"m-a": {"plan": plan_a, "probe": probe_a, "stop": stop_a},
                          "m-b": {"plan": None, "probe": probe_b, "stop": None}})

    def test_a_run_without_such_rows_has_no_meta(self):
        self.assertEqual(score.load_meta(OLD_RUN), {})
        self.assertEqual(score.load_meta(self.make_run(conv_rows("m-a", "R06", "b00001", [FENCE_REPLY]))), {})

    def test_a_later_row_of_the_same_kind_replaces_the_earlier_one(self):
        first, second = plan_row("m-a", [("R06", 1)]), plan_row("m-a", [("R06", 1), ("R07", 1)])
        self.assertEqual(score.load_meta(self.make_run([first, second]))["m-a"]["plan"], second)

    def test_plan_rows_of_two_variants_for_one_model_are_refused(self):
        # a run directory holds one variant (spec 5.7); reading two plans as one would change a denominator unseen
        rows = [plan_row("m-a", [("R06", 1)]), plan_row("m-a", [("D01", 1)], variant="docs")]
        with self.assertRaisesRegex(ValueError, "m-a"):
            score.load_meta(self.make_run(rows))


class SieveTest(unittest.TestCase):
    """sieve (spec 5.8): 90% of the conversations end with a prompt, no A5 or D5 flag, every other check in 80% of the
    conversations it applies to, and a check with fewer than five conversations does not count."""

    @staticmethod
    def convs(n):
        """n scored conversations, all finished, every check passing."""
        return [scored_conv(i) for i in range(1, n + 1)]

    def test_a_model_that_finishes_and_trips_nothing_is_through(self):
        r = score.sieve(self.convs(15))
        self.assertEqual((r["outcome"], r["completed"], r["first_attempt_completed"], r["flags"], r["reasons"]),
                         ("door", (15, 15), 15, [], []))
        self.assertEqual(r["checks"]["A1"], (15, 15, True))
        self.assertEqual(r["checks"]["A5"], (0, 0, False))      # applies to no conversation
        self.assertEqual(r["checks"]["A8"], (0, 0, False))
        self.assertNotIn("D1", r["checks"])                     # only the checks the conversations carry

    def test_a_failed_conversation_counts_in_the_denominator(self):
        r = score.sieve(self.convs(9) + [scored_conv(10, status="error")])
        self.assertEqual((r["completed"], r["outcome"]), ((9, 10), "door"))         # 9 of 10 is exactly 90%
        r = score.sieve(self.convs(8) + [scored_conv(9, status="error"), scored_conv(10, status="no_final")])
        self.assertEqual((r["completed"], r["outcome"]), ((8, 10), "gezakt"))
        self.assertEqual(r["reasons"], ["afgerond: 8 van 10 (80.0%), minder dan 90%",
                                        "niet afgerond: error 1x (R09/1); no_final 1x (R10/1)"])

    def test_13_of_15_fails_and_14_of_15_passes(self):
        r = score.sieve(self.convs(13) + [scored_conv(14, status="error"), scored_conv(15, status="no_final")])
        self.assertEqual((r["completed"], r["outcome"]), ((13, 15), "gezakt"))
        r = score.sieve(self.convs(14) + [scored_conv(15, status="error")])
        self.assertEqual((r["completed"], r["outcome"]), ((14, 15), "door"))
        self.assertEqual(r["reasons"], [])

    def test_15_planned_with_13_present_and_finished_is_13_of_15_and_fails(self):
        planned = [[f"R{i:02d}", 1] for i in range(1, 16)]           # the pairs as the plan row holds them: JSON lists
        r = score.sieve(self.convs(13), planned)
        self.assertEqual((r["completed"], r["outcome"]), ((13, 15), "gezakt"))
        self.assertEqual(r["reasons"], ["afgerond: 13 van 15 (86.7%), minder dan 90%",
                                        "niet afgerond: ontbreekt 2x (R14/1, R15/1)"])
        r = score.sieve(self.convs(14), planned)
        self.assertEqual((r["completed"], r["outcome"]), ((14, 15), "door"))

    def test_without_a_plan_the_denominator_is_the_conversations_there_are(self):
        for planned in (None, []):                                   # an old run has no plan row
            r = score.sieve(self.convs(13), planned)
            self.assertEqual((r["completed"], r["outcome"]), ((13, 13), "door"))

    def test_a_conversation_outside_the_plan_does_not_raise_the_count_above_the_plan(self):
        planned = [[f"R{i:02d}", 1] for i in range(1, 16)]
        r = score.sieve(self.convs(16), planned)
        self.assertEqual(r["completed"], (15, 15))

    def test_one_flag_fails_the_model(self):
        scored = self.convs(15)
        for c in scored[:3]:
            c["A5"] = "pass"
        r = score.sieve(scored)
        self.assertEqual((r["outcome"], r["flags"], r["checks"]["A5"]), ("door", [], (3, 3, True)))
        scored[1]["A5"] = "flag"
        r = score.sieve(scored)
        self.assertEqual((r["outcome"], r["flags"], r["checks"]["A5"]), ("gezakt", ["b00002"], (2, 3, True)))
        self.assertEqual(r["reasons"], ["vlag op A5: b00002"])
        self.assertEqual(score.sieve([scored_conv(1, A5="flag")])["outcome"], "gezakt")   # one conversation is enough

    def test_a_d5_flag_fails_the_model_too(self):
        scored = [scored_conv(i, **dict.fromkeys(score.DOC_CHECKS, "pass")) for i in range(1, 16)]
        scored[4]["D5"] = "flag"
        r = score.sieve(scored)
        self.assertEqual((r["outcome"], r["flags"], r["checks"]["D5"]), ("gezakt", ["b00005"], (14, 15, True)))
        self.assertEqual(r["reasons"], ["vlag op D5: b00005"])

    def test_a_check_with_fewer_than_five_conversations_is_shown_but_does_not_count(self):
        scored = self.convs(15)
        scored[0]["A8"] = scored[1]["A8"] = "fail"                   # A8 applies to two conversations only
        r = score.sieve(scored)
        self.assertEqual((r["checks"]["A8"], r["outcome"], r["reasons"]), ((0, 2, False), "door", []))

    def test_a_check_counts_from_five_conversations_and_needs_80_percent(self):
        def with_a8(results):
            scored = self.convs(15)
            for c, v in zip(scored, results):
                c["A8"] = v
            return score.sieve(scored)
        r = with_a8(["pass"] * 4 + ["fail"])
        self.assertEqual((r["checks"]["A8"], r["outcome"]), ((4, 5, True), "door"))            # exactly 80%
        r = with_a8(["pass"] * 3 + ["fail"] * 2)
        self.assertEqual((r["checks"]["A8"], r["outcome"], r["reasons"]),
                         ((3, 5, True), "gezakt", ["A8: 3 van 5 (60.0%), minder dan 80%"]))
        r = with_a8(["fail"] * 4)                                                              # four is too few
        self.assertEqual((r["checks"]["A8"], r["outcome"]), ((0, 4, False), "door"))

    def test_the_80_percent_rule_on_a_large_denominator(self):
        scored = self.convs(15)
        for c in scored[:3]:
            c["A3"] = "fail"                                         # 12 of 15 is 80%
        self.assertEqual(score.sieve(scored)["outcome"], "door")
        scored[3]["A3"] = "fail"
        r = score.sieve(scored)
        self.assertEqual((r["outcome"], r["reasons"]), ("gezakt", ["A3: 11 van 15 (73.3%), minder dan 80%"]))

    def test_d1_to_d4_count_and_d6_is_only_shown(self):
        scored = [scored_conv(i, **dict.fromkeys(score.DOC_CHECKS, "pass")) for i in range(1, 16)]
        for c in scored:
            c["D6"] = "fail"                                         # spec 5.8 lists D1-D4; D6 follows from "afgerond"
        r = score.sieve(scored)
        self.assertEqual((r["outcome"], r["checks"]["D6"]), ("door", (0, 15, False)))
        for c in scored[:5]:
            c["D3"] = "fail"
        r = score.sieve(scored)
        self.assertEqual((r["outcome"], r["checks"]["D3"], r["reasons"]),
                         ("gezakt", (10, 15, True), ["D3: 10 van 15 (66.7%), minder dan 80%"]))

    def test_the_first_attempts_that_finished_are_counted_apart(self):
        scored = self.convs(15)
        for c in scored[:4]:
            c["first_attempt_status"] = "error"                      # finished on the second attempt
        for c in scored[4:6]:
            c["first_attempt_status"] = "final"
        r = score.sieve(scored)                                      # the other nine have no first_attempt_status
        self.assertEqual((r["completed"], r["first_attempt_completed"]), ((15, 15), 11))

    def test_nothing_planned_and_nothing_present_is_not_run_with_the_reason_of_the_probe(self):
        none = probe_row("m-x", verdict="none", label="geen aanbieder",
                         reasons={"a_plain": "model HTTP 503: No available model provider"})
        r = score.sieve([], None, none)
        self.assertEqual((r["outcome"], r["completed"], r["first_attempt_completed"], r["flags"], r["checks"]),
                         ("niet gedraaid", (0, 0), 0, [], {}))
        self.assertEqual(r["reasons"], ["geen aanbieder", "a_plain: model HTTP 503: No available model provider"])
        same = {"a_plain": "model HTTP 429: rate limited", "b_single_tool": "model HTTP 429: rate limited"}
        r = score.sieve([], [], probe_row("m-x", verdict="none", label="probe-fout 429", reasons=same))
        self.assertEqual((r["outcome"], r["reasons"]), ("niet gedraaid", [
            "probe-fout 429", "a_plain, b_single_tool: model HTTP 429: rate limited"]))
        weak = probe_row("m-x", verdict="unreliable", reasons={"c_two_tools": "expected exactly one tool call, got 0"})
        self.assertEqual(score.sieve([], None, weak)["reasons"],
                         ["probe-oordeel unreliable", "c_two_tools: expected exactly one tool call, got 0"])

    def test_not_run_without_a_probe_row_still_says_why(self):
        r = score.sieve([])
        self.assertEqual((r["outcome"], r["completed"]), ("niet gedraaid", (0, 0)))
        self.assertEqual(len(r["reasons"]), 1)
        self.assertIn("geen", r["reasons"][0])

    def test_a_plan_without_conversations_is_failed_not_unrun(self):
        # the plan names 3 and none ran (a cost stop before this model): 0 of 3, and the probe is not the reason
        r = score.sieve([], [["R06", 1], ["R07", 1], ["R08", 1]], probe_row("m-x"))
        self.assertEqual((r["outcome"], r["completed"]), ("gezakt", (0, 3)))
        self.assertEqual(r["reasons"][-1], "niet afgerond: ontbreekt 3x (R06/1, R07/1, R08/1)")


class SummaryCsvTest(RunDirTest):
    """summary.csv: an explicit column list, the plain columns as they were, and more for a run of the harness backend."""

    PLAIN = ["model", "case", "seed", "blind_id", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "status", "turns",
             "wall_s", "eval_tokens", "max_prompt_tokens", "other_model_loaded", "notes"]
    EXTRA = ["variant", "poging", "first_attempt_status", "D1", "D2", "D3", "D4", "D5", "D6", "model_turns",
             "tool_calls", "input_tokens", "output_tokens", "reasoning_tokens", "cost_usd", "providers"]

    def header(self, run_dir):
        with (Path(run_dir) / "summary.csv").open(newline="", encoding="utf-8") as f:
            return next(csv.reader(f))

    def test_the_column_lists(self):
        self.assertEqual(score.COLUMNS, self.PLAIN)
        self.assertEqual(score.HARNESS_COLUMNS, self.EXTRA)

    def test_a_harness_run_adds_the_columns_after_the_plain_ones(self):
        run_dir = self.make_run(conv_rows("m-a", "R06", "b00001", [FENCE_REPLY]))
        self.score_main(run_dir)
        self.assertEqual(self.header(run_dir), self.PLAIN + self.EXTRA)

    def test_a_run_without_harness_rows_has_the_plain_columns_only(self):
        ollama = [{"model": "m-o", "case": "R06", "seed": 1, "blind_id": "b00001", "turn": 1, "content": FENCE_REPLY,
                   "eval_count": 7, "prompt_eval_count": 40, "wall_s": 1.5, "ps_before": ["m-o"], "tei_on": False},
                  {"model": "m-o", "case": "R06", "seed": 1, "blind_id": "b00001", "turn": "end", "status": "final",
                   "conversation_wall_s": 1.5, "ps_before": ["m-o"], "tei_on": False}]
        run_dir = self.make_run(ollama)
        self.score_main(run_dir)
        self.assertEqual(self.header(run_dir), self.PLAIN)
        (row,) = self.summary(run_dir)
        self.assertEqual((row["eval_tokens"], row["max_prompt_tokens"], row["other_model_loaded"], row["status"]),
                         ("7", "40", "False", "final"))

    def test_a_harness_row_sums_its_turns(self):
        fine = prompt_block("<task>\nSchrijf iets.\n</task>")
        keys = {"model": "m-a", "case": "R06", "blind_id": "b00001", "variant": "nodocs"}
        rows = [harness_row(1, "Wat is het doel?", model_turns=1, input_tokens=1000, output_tokens=200,
                            reasoning_tokens=50, cost_usd=0.001, providers=["Novita"], **keys),
                harness_row(2, fine, tool_calls=[SEARCH, SEARCH], model_turns=2, input_tokens=1500, output_tokens=300,
                            reasoning_tokens=70, cost_usd=0.0015, providers=["Novita", "DeepInfra"], **keys),
                end_row("final", **keys)]
        run_dir = self.make_run(rows)
        self.score_main(run_dir)
        (row,) = self.summary(run_dir)
        self.assertEqual({k: row[k] for k in ("variant", "poging", "first_attempt_status", "status", "turns")},
                         {"variant": "nodocs", "poging": "1", "first_attempt_status": "final", "status": "final",
                          "turns": "2"})
        self.assertEqual({k: row[k] for k in ("model_turns", "tool_calls", "input_tokens", "output_tokens",
                                              "reasoning_tokens", "cost_usd", "providers")},
                         {"model_turns": "3", "tool_calls": "2", "input_tokens": "2500", "output_tokens": "500",
                          "reasoning_tokens": "120", "cost_usd": "0.0025", "providers": "DeepInfra, Novita"})
        self.assertEqual(row["wall_s"], "14.0")
        # the measurements of the Ollama runner do not exist for this backend: empty, not 0 and not False
        self.assertEqual((row["eval_tokens"], row["max_prompt_tokens"], row["other_model_loaded"]), ("", "", ""))
        # a plain case has no doc-checks: the cells stay empty
        self.assertEqual([row[d] for d in score.DOC_CHECKS], [""] * 6)

    def test_a_missing_amount_counts_as_zero_and_cost_is_summed_without_token_counts(self):
        keys = {"model": "m-a", "case": "R06", "blind_id": "b00001", "variant": "nodocs"}
        first = harness_row(1, "Vraag?", input_tokens=None, output_tokens=None, reasoning_tokens=None,
                            cost_usd=0.002, **keys)
        second = harness_row(2, FENCE_REPLY, input_tokens=900, output_tokens=100, reasoning_tokens=None,
                             cost_usd=None, providers=None, **keys)
        for gone in ("model_turns", "tool_calls"):
            second.pop(gone)
        # a second conversation whose rows carry no token count at all, only a cost
        other = {**keys, "case": "R07", "blind_id": "b00002"}
        no_counts = harness_row(1, FENCE_REPLY, input_tokens=None, output_tokens=None, reasoning_tokens=None,
                                cost_usd=0.003, **other)
        run_dir = self.make_run([first, second, end_row("final", **keys), no_counts, end_row("final", **other)])
        self.score_main(run_dir)
        rows = {r["blind_id"]: r for r in self.summary(run_dir)}
        self.assertEqual({k: rows["b00001"][k] for k in ("model_turns", "tool_calls", "input_tokens", "output_tokens",
                                                         "reasoning_tokens", "cost_usd", "providers")},
                         {"model_turns": "2", "tool_calls": "0", "input_tokens": "900", "output_tokens": "100",
                          "reasoning_tokens": "0", "cost_usd": "0.002", "providers": "Novita"})
        self.assertEqual({k: rows["b00002"][k] for k in ("input_tokens", "output_tokens", "reasoning_tokens", "cost_usd")},
                         {"input_tokens": "0", "output_tokens": "0", "reasoning_tokens": "0", "cost_usd": "0.003"})

    def test_reasoning_tokens_are_part_of_the_output_tokens(self):
        keys = {"model": "m-a", "case": "R06", "blind_id": "b00001", "variant": "nodocs"}
        row = harness_row(1, FENCE_REPLY, output_tokens=300, reasoning_tokens=120, **keys)
        run_dir = self.make_run([row, end_row("final", **keys)])
        self.score_main(run_dir)
        (out,) = self.summary(run_dir)
        self.assertEqual((out["output_tokens"], out["reasoning_tokens"]), ("300", "120"))   # never 420

    def test_a_second_attempt_counts_with_its_own_rows_only(self):
        first = conv_rows("m-a", "R06", "b00001", ["Vraag?", ""], poging=1, end="error",
                          statuses=["completed", "budget_exceeded"])
        second = conv_rows("m-a", "R06", "b00001", ["Vraag?", FENCE_REPLY], poging=2)
        run_dir = self.make_run(first + second)
        self.score_main(run_dir)
        (row,) = self.summary(run_dir)
        self.assertEqual((row["poging"], row["first_attempt_status"], row["status"]), ("2", "error", "final"))
        self.assertEqual((row["turns"], row["model_turns"], row["input_tokens"]), ("2", "4", "2400"))   # two rows, not four

    def test_cost_usd_is_the_spend_of_all_attempts_and_the_rest_is_the_counted_attempt(self):
        first = conv_rows("m-a", "R06", "b00001", ["Vraag?", ""], poging=1, end="error",
                          statuses=["completed", "budget_exceeded"],
                          rows_extra=[{"cost_usd": 0.01}, {"cost_usd": 0.03, "error_code": "BUDGET_EXCEEDED"}])
        second = conv_rows("m-a", "R06", "b00001", ["Vraag?", FENCE_REPLY], poging=2,
                           rows_extra=[{"cost_usd": 0.002}, {"cost_usd": 0.003}])
        run_dir = self.make_run(first + second)
        self.score_main(run_dir)
        (row,) = self.summary(run_dir)
        # 0.04 was billed for the attempt that was discarded and 0.005 for the one that counts; the closing rows
        # (0.0008 each, end_row) repeat the turns' cost and are not added
        self.assertEqual(row["cost_usd"], "0.045")
        self.assertEqual({k: row[k] for k in ("poging", "model_turns", "tool_calls", "input_tokens", "output_tokens")},
                         {"poging": "2", "model_turns": "4", "tool_calls": "0", "input_tokens": "2400",
                          "output_tokens": "600"})                   # the counted attempt only, as before

    def test_the_cost_cell_is_empty_when_no_turn_row_names_a_cost(self):
        local = conv_rows("m-a", "R06", "b00001", ["Vraag?", FENCE_REPLY], rows_extra=[{"cost_usd": None}] * 2)
        gone = conv_rows("m-a", "R07", "b00002", [FENCE_REPLY])
        gone[0].pop("cost_usd")
        free = conv_rows("m-a", "R08", "b00003", [FENCE_REPLY], rows_extra=[{"cost_usd": 0}])
        run_dir = self.make_run(local + gone + free)
        self.score_main(run_dir)
        # unknown is not free; the closing rows say 0.0008 (end_row) and are no source of the cost
        self.assertEqual({r["blind_id"]: r["cost_usd"] for r in self.summary(run_dir)},
                         {"b00001": "", "b00002": "", "b00003": "0.0"})

    def test_a_closing_row_without_backend_does_not_make_a_harness_row_an_ollama_row(self):
        # the conversation keys of a closing row are model, case, seed, blind_id, variant and poging: no backend. After an
        # invocation error it is all a conversation has, and the run is a harness run all the same
        lone_end = {"model": "m-a", "case": "R07", "seed": 1, "blind_id": "b00002", "variant": "nodocs", "poging": 1,
                    "turn": "end", "status": "invocation_error"}
        run_dir = self.make_run(conv_rows("m-a", "R06", "b00001", [FENCE_REPLY]) + [lone_end])
        output = self.score_main(run_dir)
        broken = {r["blind_id"]: r for r in self.summary(run_dir)}["b00002"]
        self.assertEqual({k: broken[k] for k in ("status", "variant", "poging", "first_attempt_status", "turns",
                                                 "model_turns", "cost_usd", "eval_tokens", "other_model_loaded")},
                         {"status": "invocation_error", "variant": "nodocs", "poging": "1",
                          "first_attempt_status": "invocation_error", "turns": "0", "model_turns": "0",
                          "cost_usd": "", "eval_tokens": "", "other_model_loaded": ""})   # no turn row: no amount known
        self.assertEqual(parse_tables(output)["nodocs"]["m-a"]["Backend"], "harness")

    def test_a_docs_row_after_a_plain_row_does_not_clash(self):
        # a plain row that sorts first used to fix the columns of the writer; a docs row has D1-D6 on top
        final = prompt_block("<task>\nLaat Claude Code een foutcode toevoegen.\n</task>")
        plain = conv_rows("a-model", "R06", "b00001", [FENCE_REPLY])
        docs = conv_rows("b-model", "D01", "b00002", ["Vraag?", final], variant="docs", tools=(SEARCH,))
        run_dir = self.make_run(plain + docs)
        self.score_main(run_dir)
        rows = {r["model"]: r for r in self.summary(run_dir)}
        self.assertEqual([rows["a-model"][d] for d in score.DOC_CHECKS], [""] * 6)
        self.assertEqual((rows["b-model"]["D1"], rows["b-model"]["D6"]), ("pass", "pass"))
        self.assertEqual(self.header(run_dir), self.PLAIN + self.EXTRA)

    def test_a_docs_conversation_is_scored_with_its_rows_and_the_docset(self):
        final = prompt_block("<task>\nLaat Claude Code een foutcode toevoegen.\n</task>")
        looked_up = conv_rows("m-a", "D01", "d00001", ["Vraag?", final], variant="docs", tools=(SEARCH,))
        not_looked_up = conv_rows("m-a", "D01", "d00002", ["Vraag?", final], variant="docs", seed=2)
        failed = conv_rows("m-a", "D01", "d00003", ["Vraag?", ""], variant="docs", seed=3, tools=(SEARCH,),
                           statuses=["completed", "budget_exceeded"], end="error")
        run_dir = self.make_run(looked_up + not_looked_up + failed)
        self.score_main(run_dir)           # the docset is the frozen one next to score.py
        rows = {r["blind_id"]: r for r in self.summary(run_dir)}
        self.assertEqual((rows["d00001"]["D1"], rows["d00001"]["D6"]), ("pass", "pass"))
        self.assertEqual(rows["d00002"]["D1"], "fail")
        self.assertEqual((rows["d00003"]["D6"], rows["d00003"]["status"]), ("fail", "error"))
        self.assertIn("D6 status: beurt 2 budget_exceeded", rows["d00003"]["notes"])

    def test_a_run_with_probe_rows_only_writes_the_header(self):
        run_dir = self.make_run([probe_row("m-x", verdict="none", label="geen aanbieder")])
        output = self.score_main(run_dir)
        self.assertEqual(self.header(run_dir), self.PLAIN + self.EXTRA)
        self.assertEqual(self.summary(run_dir), [])
        self.assertIn("niet gedraaid", output)

    def test_the_docset_option_names_the_docset_d3_reads(self):
        final = prompt_block("<task>\nLaat Claude Code een foutcode toevoegen.\n</task>")
        docs_run = self.make_run(conv_rows("m-a", "D01", "d00001", ["Vraag?", final], variant="docs", tools=(SEARCH,)))
        plain_run = self.make_run(conv_rows("m-a", "R06", "b00001", [FENCE_REPLY]))
        nowhere = docs_run / "geen-docset"

        def cli(run_dir, *options):
            return subprocess.run([sys.executable, str(HERE / "score.py"), str(run_dir), *map(str, options)],
                                  capture_output=True, text=True)
        done = cli(docs_run, "--docset", DOCSET)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((docs_run / "summary.csv").exists())
        self.assertEqual(cli(docs_run).returncode, 0)             # the default is the docset next to score.py
        broken = cli(docs_run, "--docset", nowhere)
        self.assertNotEqual(broken.returncode, 0)
        self.assertIn("docset.json", broken.stderr)
        self.assertEqual(cli(plain_run, "--docset", nowhere).returncode, 0)   # no docs case: the docset is not read


class OldRunSummaryTest(RunDirTest):
    """Bestaand gedrag blijft: a copy of the run of 29 September scores to the committed summary.csv, but for the new
    R01 patterns."""

    def copy_of_old_run(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return Path(shutil.copytree(OLD_RUN, tmp / "run"))

    def test_the_summary_differs_from_the_committed_one_in_the_r01_rows_only(self):
        copy = self.copy_of_old_run()
        self.score_main(copy)
        old = (OLD_RUN / "summary.csv").read_bytes().decode().splitlines(keepends=True)
        new = (copy / "summary.csv").read_bytes().decode().splitlines(keepends=True)
        self.assertEqual(len(new), len(old))
        self.assertEqual(new[0], old[0])      # the same columns in the same order
        changed = {}
        for was, now in zip(old[1:], new[1:]):
            if was != now:                    # every other row is identical, byte for byte
                (a,), (b,) = csv.DictReader([old[0], was]), csv.DictReader([new[0], now])
                changed[a["blind_id"]] = {col: (a[col], b[col]) for col in a if a[col] != b[col]}
        old_pattern = r"(?i)een user story is\b"    # the outside-the-fence pattern of the run of 29 September
        self.assertEqual(changed, {
            "ac5133": {"A5": ("pass", "flag"), "notes": ("", "A5 treffer: " + R01_STATEMENT[2])},
            "1efe0d": {"notes": ("A5 treffer: " + old_pattern,
                                 "A5 treffer: " + ", ".join([old_pattern, *R01_STATEMENT[1:]]))}})

    def test_the_committed_files_are_not_touched(self):
        before = (OLD_RUN / "summary.csv").read_bytes()
        copy = self.copy_of_old_run()
        self.score_main(copy)
        self.assertEqual((OLD_RUN / "summary.csv").read_bytes(), before)
        self.assertEqual(sorted(p.name for p in copy.iterdir()), sorted(p.name for p in OLD_RUN.iterdir()))


def parse_tables(text):
    """{variant: {model: {column: cell}}} from the markdown tables score.main prints under '### Variant <name>'."""
    tables, variant, header = {}, None, None
    for line in text.splitlines():
        if line.startswith("### Variant "):
            variant, header = line[len("### Variant "):].strip(), None
            tables[variant] = {}
        elif line.startswith("|") and variant is not None:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if header is None:
                header = cells
            elif not set("".join(cells)) <= set("-:"):      # skip the |---|---| line
                tables[variant][cells[0]] = dict(zip(header, cells))
    return tables


class ReportTest(RunDirTest):
    """The printed output: a table per variant, the sieve reasons, the stops and the flagged transcripts."""

    COST = "Kosten $ (alle pogingen)"       # the tokens are those of the attempt that counts, the cost is the spend
    COLUMNS = ["Model", "Backend", "Probe", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "Afgerond", "Eerste poging",
               "Mediaan s", "Tokens in", "Tokens uit", COST, "Aanbieders", "Zeef"]
    FLAGGED = "Leg uit dat een user story een type PBI is."

    def nodocs_run(self):
        """Four models in the variant nodocs: one through, one flagged, one without a provider, one stopped."""
        fine = prompt_block("<task>\nSchrijf iets.\n</task>")
        rows = [plan_row("m-ok", [("R06", 1), ("R07", 1), ("R08", 1)]), probe_row("m-ok")]
        for n, cid in enumerate(["R06", "R07", "R08"], start=1):
            rows += conv_rows("m-ok", cid, f"ok000{n}", ["Vraag?", fine])
        rows += [plan_row("m-flag", [("R01", 1)]),
                 probe_row("m-flag", verdict="unreliable", reasons={"c_two_tools": "expected one tool call, got 0"})]
        rows += conv_rows("m-flag", "R01", "fl0001", [prompt_block(f"<task>\n{self.FLAGGED}\n</task>")])
        rows.append(probe_row("m-none", verdict="none", label="geen aanbieder",
                              reasons={"a_plain": "model HTTP 503: No available model provider"}))
        rows += [plan_row("m-stop", [("R06", 1), ("R07", 1), ("R08", 1)]), probe_row("m-stop")]
        rows += conv_rows("m-stop", "R06", "st0001", ["Vraag?", ""], end="error",
                          statuses=["completed", "budget_exceeded"])
        rows.append(stop_row("m-stop", "max_cost"))
        return self.score_main(self.make_run(rows))

    def test_a_table_per_variant_with_a_row_per_model(self):
        output = self.nodocs_run()
        tables = parse_tables(output)
        self.assertEqual(list(tables), ["nodocs"])
        self.assertEqual(sorted(tables["nodocs"]), ["m-flag", "m-none", "m-ok", "m-stop"])
        header = next(line for line in output.splitlines() if line.startswith("| Model"))
        self.assertEqual([c.strip() for c in header.strip("|").split("|")], self.COLUMNS)

    def test_the_cells_of_a_model_that_ran(self):
        ok = parse_tables(self.nodocs_run())["nodocs"]["m-ok"]
        self.assertEqual({k: ok[k] for k in ("Backend", "Probe", "Afgerond", "Eerste poging", "Mediaan s", "Tokens in",
                                             "Tokens uit", self.COST, "Aanbieders", "Zeef", "A5", "A8")},
                         {"Backend": "harness", "Probe": "reliable", "Afgerond": "3/3", "Eerste poging": "3",
                          "Mediaan s": "14", "Tokens in": "7200", "Tokens uit": "1800", self.COST: "0.0024",
                          "Aanbieders": "Novita", "Zeef": "door", "A5": "-", "A8": "-"})

    def test_a_flag_gives_gezakt_and_shows_in_the_a5_count(self):
        flag = parse_tables(self.nodocs_run())["nodocs"]["m-flag"]
        self.assertEqual((flag["A5"], flag["Zeef"], flag["Probe"], flag["Afgerond"]), ("0/1", "gezakt", "unreliable", "1/1"))

    def test_a_model_that_did_not_run_has_a_row_with_the_reason_outside_the_table(self):
        output = self.nodocs_run()
        none = parse_tables(output)["nodocs"]["m-none"]
        self.assertEqual((none["Backend"], none["Probe"], none["Zeef"]), ("harness", "geen aanbieder", "niet gedraaid"))
        self.assertEqual([none[k] for k in ("Afgerond", "Eerste poging", "Mediaan s", "Tokens in", self.COST,
                                            "Aanbieders", "A1")], ["-"] * 7)
        self.assertIn("- m-none (niet gedraaid): geen aanbieder; a_plain: model HTTP 503: No available model provider",
                      output)

    def test_a_planned_conversation_that_never_ran_counts_and_the_stop_is_named(self):
        output = self.nodocs_run()
        stop = parse_tables(output)["nodocs"]["m-stop"]
        self.assertEqual((stop["Afgerond"], stop["Eerste poging"], stop["Zeef"]), ("0/3", "0", "gezakt"))
        self.assertIn("- m-stop (gezakt): afgerond: 0 van 3 (0.0%), minder dan 90%; "
                      "niet afgerond: error 1x (R06/1); ontbreekt 2x (R07/1, R08/1) (run gestopt: max_cost)", output)
        self.assertIn("Gestopt:\n- m-stop: max_cost", output)
        self.assertIn("- m-stop: R06/1 (st0001): error (beurt 2 budget_exceeded, $0.0008)", output)

    def test_a_model_that_is_through_has_no_reason_line(self):
        output = self.nodocs_run()
        self.assertNotIn("- m-ok", output)
        self.assertIn("- m-flag (gezakt): vlag op A5: fl0001", output)

    def test_a_check_with_fewer_than_five_conversations_is_starred(self):
        output = self.nodocs_run()
        ok = parse_tables(output)["nodocs"]["m-ok"]
        self.assertTrue(ok["A1"].endswith("/3*"), ok["A1"])
        self.assertIn("* minder dan vijf gesprekken", output)
        self.assertFalse(parse_tables(output)["nodocs"]["m-flag"]["A5"].endswith("*"))   # the flag rule always counts

    def test_a_flag_shows_its_pattern_and_its_transcript(self):
        output = self.nodocs_run()
        start = output.index("#### Vlag A5: fl0001")
        block = output[start:]
        self.assertIn("(m-flag, R01, seed 1)", block.splitlines()[0])
        self.assertIn("Patroon: " + R01_STATEMENT[2], block)
        self.assertIn("transcripts/fl0001.md", block)
        self.assertIn(self.FLAGGED, block)

    def test_a_docs_run_shows_the_doc_checks_and_the_variant(self):
        final = prompt_block("<task>\nLaat Claude Code een foutcode toevoegen.\n</task>")
        rows = [plan_row("m-d", [("D01", 1)], variant="docs"), probe_row("m-d", variant="docs")]
        rows += conv_rows("m-d", "D01", "d00001", ["Vraag?", final], variant="docs", tools=(SEARCH,))
        output = self.score_main(self.make_run(rows))
        tables = parse_tables(output)
        self.assertEqual(list(tables), ["docs"])
        row = tables["docs"]["m-d"]
        # D1 is one of the 80% checks, with one conversation too few to count; D01 has no restraint rule, so D5 does not
        # apply; D6 is shown without counting, which is no question of how many conversations there are
        self.assertEqual([row[d] for d in ("D1", "D5", "D6")], ["1/1*", "-", "1/1"])
        self.assertEqual((row["A5"], row["Afgerond"]), ("-", "1/1"))
        self.assertIn("D6 telt niet mee", output)

    def test_variants_are_separate_tables_with_nodocs_first_and_a_plan_counts_in_its_own_variant_only(self):
        # a run directory holds one variant (spec 5.7); should a report meet two, each gets its own table, and a plan
        # row is the denominator of the variant it names
        final = prompt_block("<task>\nLaat Claude Code een foutcode toevoegen.\n</task>")
        rows = [plan_row("m-d", [("D01", 1)], variant="docs"), probe_row("m-d", variant="docs")]
        rows += conv_rows("m-d", "D01", "d00001", ["Vraag?", final], variant="docs", tools=(SEARCH,))
        rows += conv_rows("m-a", "R06", "b00001", [FENCE_REPLY])
        rows += [plan_row("m-a", [("R06", 1), ("R07", 1)], variant="nodocs"), plan_row("m-x", [("D01", 1)], variant="docs")]
        rows += conv_rows("m-x", "R06", "b00002", [FENCE_REPLY])     # rows of nodocs under a plan of docs
        tables = parse_tables(self.score_main(self.make_run(rows)))
        self.assertEqual(list(tables), ["nodocs", "docs"])
        self.assertEqual({m: t["Afgerond"] for m, t in tables["nodocs"].items()}, {"m-a": "1/2", "m-x": "1/1"})
        self.assertEqual({m: t["Afgerond"] for m, t in tables["docs"].items()}, {"m-d": "1/1", "m-x": "0/1"})

    def test_a_d5_flag_is_printed_like_an_a5_flag(self):
        leaked = prompt_block(f"<task>\n{D02_FLAG[0]}\n</task>")
        rows = [plan_row("m-d", [("D02", 1)], variant="docs"), probe_row("m-d", variant="docs")]
        rows += conv_rows("m-d", "D02", "d00002", ["Vraag?", leaked], variant="docs", tools=(SEARCH,))
        output = self.score_main(self.make_run(rows))
        self.assertEqual(parse_tables(output)["docs"]["m-d"]["D5"], "0/1")
        self.assertIn("- m-d (gezakt): vlag op D5: d00002", output)
        block = output[output.index("#### Vlag D5: d00002"):]
        self.assertIn("(m-d, D02, seed 1)", block.splitlines()[0])
        pattern = score.statement_hits(case("D02")["forbid_statement"], D02_FLAG[0])
        self.assertTrue(pattern)
        self.assertIn("Patroon: " + ", ".join(pattern), block)
        self.assertIn(D02_FLAG[0], block)

    def attempts_run(self):
        """m-a: R06 ends in error on its first attempt (turn 2 budget_exceeded, $0.04 billed) and finishes on the second
        ($0.005); R07 finishes at once ($0.001)."""
        first = conv_rows("m-a", "R06", "b00001", ["Vraag?", ""], poging=1, end="error",
                          statuses=["completed", "budget_exceeded"],
                          rows_extra=[{"cost_usd": 0.01}, {"cost_usd": 0.03, "error_code": "BUDGET_EXCEEDED"}])
        second = conv_rows("m-a", "R06", "b00001", ["Vraag?", FENCE_REPLY], poging=2,
                           rows_extra=[{"cost_usd": 0.002}, {"cost_usd": 0.003}])
        single = conv_rows("m-a", "R07", "b00002", [FENCE_REPLY], rows_extra=[{"cost_usd": 0.001}])
        return self.score_main(self.make_run(first + second + single))

    def test_the_cost_in_the_table_is_the_spend_of_all_attempts_the_tokens_are_the_counted_ones(self):
        row = parse_tables(self.attempts_run())["nodocs"]["m-a"]
        # 0.04 + 0.005 + 0.001: the discarded attempt was billed; the counted attempts hold 2400 + 1200 tokens in
        self.assertEqual((row[self.COST], row["Tokens in"], row["Tokens uit"], row["Afgerond"], row["Eerste poging"]),
                         ("0.0460", "3600", "900", "2/2", "1"))

    def test_a_conversation_with_a_second_attempt_gets_a_line_with_both_attempts(self):
        output = self.attempts_run()
        self.assertIn("Pogingen en niet afgeronde gesprekken:", output)
        self.assertIn("- m-a: R06/1 (b00001): poging 1 error (beurt 2 budget_exceeded, BUDGET_EXCEEDED, $0.0400) "
                      "-> poging 2 final ($0.0050)", output)
        self.assertNotIn("R07/1", output)                          # finished at once, on the first attempt

    def test_an_unfinished_conversation_gets_a_line_with_the_turn_it_broke_on(self):
        rows = []
        for model, cost, first_id in (("m-local", None, "l00001"), ("m-paid", 0.0004, "p00001")):
            rows += conv_rows(model, "R06", first_id, ["Vraag?", ""], end="error", statuses=["completed", "failed"],
                              rows_extra=[{"cost_usd": cost}, {"cost_usd": cost, "error_code": "MODEL_ERROR"}])
        rows += conv_rows("m-local", "R07", "l00002", ["Vraag?"] * 4, end="no_final", rows_extra=[{"cost_usd": None}] * 4)
        output = self.score_main(self.make_run(rows))
        self.assertIn("- m-local: R06/1 (l00001): error (beurt 2 failed, MODEL_ERROR)", output)     # no cost: no amount
        self.assertIn("- m-local: R07/1 (l00002): no_final", output)
        self.assertIn("- m-paid: R06/1 (p00001): error (beurt 2 failed, MODEL_ERROR, $0.0008)", output)

    def test_a_conversation_without_a_closing_row_and_a_second_attempt_that_failed_too(self):
        cut_off = conv_rows("m-a", "R06", "b00001", ["Vraag?"], end=None, rows_extra=[{"cost_usd": 0.001}])
        failed_twice = (
            conv_rows("m-a", "R07", "b00002", ["Vraag?", ""], poging=1, end="error",
                      statuses=["completed", "failed"], rows_extra=[{"cost_usd": 0.01}, {"error_code": "MODEL_ERROR"}])
            + conv_rows("m-a", "R07", "b00002", ["Vraag?", ""], poging=2, end="error",
                        statuses=["completed", "budget_exceeded"],
                        rows_extra=[{"cost_usd": 0.02}, {"error_code": "BUDGET_EXCEEDED"}]))
        output = self.score_main(self.make_run(cut_off + failed_twice))
        self.assertIn("- m-a: R06/1 (b00001): zonder eindrij ($0.0010)", output)
        self.assertIn("- m-a: R07/1 (b00002): poging 1 error (beurt 2 failed, MODEL_ERROR, $0.0104) "
                      "-> poging 2 error (beurt 2 budget_exceeded, BUDGET_EXCEEDED, $0.0204)", output)

    def test_no_line_when_every_conversation_finished_on_its_first_attempt(self):
        rows = conv_rows("m-a", "R06", "b00001", [FENCE_REPLY]) + conv_rows("m-a", "R07", "b00002", [FENCE_REPLY])
        self.assertNotIn("Pogingen en niet afgeronde gesprekken", self.score_main(self.make_run(rows)))

    def test_a_cost_that_no_row_names_is_a_dash_and_an_unknown_cost_is_not_summed_as_a_price(self):
        local = conv_rows("m-local", "R06", "b00001", [FENCE_REPLY], rows_extra=[{"cost_usd": None}])
        mixed = (conv_rows("m-mixed", "R06", "b00002", [FENCE_REPLY], rows_extra=[{"cost_usd": 0.001}])
                 + conv_rows("m-mixed", "R07", "b00003", [FENCE_REPLY], rows_extra=[{"cost_usd": None}]))
        table = parse_tables(self.score_main(self.make_run(local + mixed)))["nodocs"]
        self.assertEqual((table["m-local"][self.COST], table["m-mixed"][self.COST]), ("-", "0.0010"))

    def test_the_legend_says_what_is_counted_over_which_attempts(self):
        legend = ("Tokens (en in summary.csv modelbeurten en toolaanroepen): van de poging die telt; "
                  "kosten: van alle pogingen.")
        self.assertIn(legend, self.attempts_run())
        copy = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, copy, ignore_errors=True)
        shutil.copytree(OLD_RUN, copy / "run")
        self.assertNotIn(legend, self.score_main(copy / "run"))     # an ollama table has no attempts and no cost

    def test_stops_are_listed_once_for_the_whole_run(self):
        rows = [plan_row("m-a", [("R06", 1), ("R07", 1), ("R08", 1)]), probe_row("m-a")]
        rows += conv_rows("m-a", "R06", "b00001", [FENCE_REPLY])
        rows += [stop_row("m-a", "max_cost"), stop_row("m-x", "http_402")]    # m-x: a stop row and nothing else
        output = self.score_main(self.make_run(rows))
        self.assertEqual(output.count("Gestopt:"), 1)
        self.assertIn("Gestopt:\n- m-a: max_cost\n- m-x: http_402", output)
        self.assertIn("ontbreekt 2x (R07/1, R08/1) (run gestopt: http_402, max_cost)", output)

    def test_a_run_of_only_a_stop_row_still_shows_the_stop(self):
        output = self.score_main(self.make_run([stop_row("m-x", "http_402")]))
        self.assertIn("Geen gesprekken in deze run.", output)
        self.assertIn("Gestopt:\n- m-x: http_402", output)

    def test_the_old_run_under_the_new_table(self):
        copy = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, copy, ignore_errors=True)
        shutil.copytree(OLD_RUN, copy / "run")
        output = self.score_main(copy / "run")
        tables = parse_tables(output)
        self.assertEqual(list(tables), ["nodocs"])            # the ollama rows have no variant: nodocs, no docs tools
        rows = tables["nodocs"]
        self.assertEqual(sorted(rows), ["qwen3.6:35b-a3b-coding", "qwen3.8-gsq-rco:27b-iq3_s-text"])
        for model, flagged in (("qwen3.6:35b-a3b-coding", "ac5133"), ("qwen3.8-gsq-rco:27b-iq3_s-text", "1efe0d")):
            row = rows[model]
            self.assertEqual({k: row[k] for k in ("Backend", "Probe", "A5", "A8", "Afgerond", "Eerste poging",
                                                  "Tokens in", self.COST, "Aanbieders", "Zeef")},
                             {"Backend": "ollama", "Probe": "-", "A5": "2/3", "A8": "2/2*", "Afgerond": "10/10",
                              "Eerste poging": "10", "Tokens in": "-", self.COST: "-", "Aanbieders": "-",
                              "Zeef": "gezakt"})
            self.assertIn(f"- {model} (gezakt): vlag op A5: {flagged}", output)
            self.assertIn(f"#### Vlag A5: {flagged} ({model}, R01, seed 1)", output)


# Taak 11a: the stand-in for the harness. fake_harness.py has the two commands run.py calls, with the layout, the file shapes
# and the exit codes of the real ones (agent-harness src/cli.ts, probe.ts, trace.ts, run.ts, manifest.ts), and answers what the
# test tells it to. No test calls the real harness, OpenRouter or Ollama.
FAKE_HARNESS = HERE / "fake_harness.py"
PROBE_STEPS = ["a_plain", "b_single_tool", "c_two_tools", "d_nonexistent_tool"]
DOC_TOOL_NAMES = ["search_product_docs", "get_product_doc", "list_product_docs", "related_product_docs"]
DUMMY_KEY = "dummy-value-not-a-key-0f4a9c1e"     # a test lends a child process this and nothing real


def clean_env(**extra):
    """The environment for a child process: ours without an OPENROUTER_API_KEY (a test never lends a real key), plus extra."""
    env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
    env.update(extra)
    return env


def sample_manifest(profile="answer", **over):
    """A manifest the real harness accepts (src/manifest.ts); over replaces top-level fields, and None removes one."""
    m = {"id": "a1b2c3-p1-t1", "profile": profile, "system": "Systeem.", "prompt": "Vraag?",
         "model": {"baseUrl": "https://openrouter.ai/api/v1", "name": "qwen/qwen3.6-35b-a3b",
                   "extraBody": {"temperature": 0.7, "seed": 1}},
         "limits": dict(ROW_LIMITS)}
    if profile == "tools":
        m["tools"] = {"server": {"command": "node", "args": ["cli.js", "doc-server", "--dir", "/docs", "--product-id", "p"]},
                      "allow": list(DOC_TOOL_NAMES)}
    m.update(over)
    return {k: v for k, v in m.items() if v is not None}


def model_block(**over):
    return {"baseUrl": "https://openrouter.ai/api/v1", "name": "qwen/qwen3.6-35b-a3b", **over}


# What the real harness refuses in a manifest (src/manifest.ts): each entry changes a valid answer manifest into an invalid one.
INVALID_MANIFESTS = {
    "an id with a capital": {"id": "A1"},
    "an id of 81 characters": {"id": "a" * 81},
    "an unknown profile": {"profile": "chat"},
    "an empty prompt": {"prompt": ""},
    "a history that starts with the assistant": {"history": [{"role": "assistant", "content": "x"}]},
    "a history that ends with the user": {"history": [{"role": "user", "content": "x"}]},
    "a history that does not alternate": {"history": [{"role": "user", "content": "x"}, {"role": "user", "content": "y"},
                                                       {"role": "assistant", "content": "z"}]},
    "tools next to the profile answer": {"tools": {"server": {"command": "node", "args": []}, "allow": ["a"]}},
    "a reserved key in extraBody": {"model": model_block(extraBody={"model": "x"})},
    "reasoning_effort next to reasoningEffort": {"model": model_block(reasoningEffort="none",
                                                                      extraBody={"reasoning_effort": "none"})},
    "an unknown reasoningEffort": {"model": model_block(reasoningEffort="extreme")},
    "a base URL that is no URL": {"model": model_block(baseUrl="openrouter")},
    "a limit that is not positive": {"limits": {**ROW_LIMITS, "maxTurns": 0}},
    "a missing limit": {"limits": {k: v for k, v in ROW_LIMITS.items() if k != "maxWallSeconds"}},
}


class FakeHarnessTest(unittest.TestCase):
    """fake_harness.py: the files, shapes and exit codes of the real harness, as run.py reads them."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = self.tmp / "out"
        self.log = self.tmp / "invocations.jsonl"
        self.counter = 0

    def fake(self, *args, config=None, **env):
        """The fake with args and a config (what it answers) in its environment."""
        path = self.tmp / "config.json"
        path.write_text(json.dumps(config or {}))
        return subprocess.run([sys.executable, str(FAKE_HARNESS), *map(str, args)], capture_output=True, text=True,
                              env=clean_env(FAKE_HARNESS_CONFIG=str(path), FAKE_HARNESS_LOG=str(self.log), **env))

    def probe(self, model="qwen/qwen3.6-35b-a3b", *extra, out=None, config=None, **env):
        return self.fake("probe", "--base-url", "https://openrouter.ai/api/v1", "--model", model,
                         "--out", out or self.out, *extra, config=config, **env)

    def run_manifest(self, manifest, *extra, config=None, **env):
        self.counter += 1
        path = self.tmp / f"manifest-{self.counter}.json"
        path.write_text(json.dumps(manifest))
        return self.fake("run", path, "--out", self.out, *extra, config=config, **env)

    def run_dir(self, run_id="a1b2c3-p1-t1"):
        return self.out / run_id

    def trace(self, run_id="a1b2c3-p1-t1"):
        return [json.loads(line) for line in (self.run_dir(run_id) / "trace.jsonl").read_text().splitlines()]

    def result(self, run_id="a1b2c3-p1-t1"):
        return json.loads((self.run_dir(run_id) / "result.json").read_text())

    def test_probe_writes_probe_json_where_the_harness_does(self):
        done = self.probe()
        self.assertEqual(done.returncode, 0, done.stderr)
        probe = json.loads((self.out / "probe-qwen-qwen3.6-35b-a3b" / "probe.json").read_text())
        self.assertEqual(list(probe), ["baseUrl", "model", "reportedModel", "ranAt", "steps", "tool_calling", "usage_reported"])
        self.assertEqual((probe["baseUrl"], probe["model"], probe["tool_calling"], probe["usage_reported"]),
                         ("https://openrouter.ai/api/v1", "qwen/qwen3.6-35b-a3b", "reliable", True))
        self.assertEqual(list(probe["steps"]), PROBE_STEPS)
        for step in probe["steps"].values():
            self.assertEqual((sorted(step), step["pass"]), (["pass", "raw", "reason"], True))
        self.assertIsNotNone(datetime.fromisoformat(probe["ranAt"].replace("Z", "+00:00")))     # UTC, as the harness writes it
        self.assertIn("PASS a_plain:", done.stdout)
        self.assertIn("tool_calling: reliable", done.stdout)

    def test_the_probe_directory_name_follows_the_harness(self):
        for model, name in (("qwen/qwen3.6-35b-a3b", "probe-qwen-qwen3.6-35b-a3b"),
                            ("qwen3.8-gsq-rco:27b-iq3_s-text", "probe-qwen3.8-gsq-rco-27b-iq3-s-text"),
                            ("Google/Gemma-4-31B-IT", "probe-google-gemma-4-31b-it"),
                            ("a//b::c", "probe-a-b-c")):
            with self.subTest(model=model):
                out = self.tmp / name
                self.assertEqual(self.probe(model, out=out).returncode, 0)
                self.assertEqual([p.name for p in out.iterdir()], [name])
                self.assertEqual(json.loads((out / name / "probe.json").read_text())["model"], model)

    def test_the_verdict_follows_the_steps_and_the_exit_code_follows_the_verdict(self):
        # src/probe.ts: no single tool call is none; a failing second turn or foreign tool call is unreliable; a_plain
        # is shown but does not decide
        for failing, verdict, code in (((), "reliable", 0), (("a_plain",), "reliable", 0), (("b_single_tool",), "none", 1),
                                       (("c_two_tools",), "unreliable", 1), (("d_nonexistent_tool",), "unreliable", 1),
                                       (("b_single_tool", "c_two_tools"), "none", 1)):
            with self.subTest(failing=failing):
                fail = {step: f"{step} did not pass" for step in failing}
                out = self.tmp / ("out-" + "-".join(failing or ("none",)))
                done = self.probe(out=out, config={"probe": [{"response": {"fail": fail}}]})
                probe = json.loads((out / "probe-qwen-qwen3.6-35b-a3b" / "probe.json").read_text())   # also written on exit 1
                self.assertEqual((probe["tool_calling"], done.returncode), (verdict, code))
                self.assertEqual({s: x["reason"] for s, x in probe["steps"].items() if not x["pass"]}, fail)
                self.assertEqual(done.stdout.count("FAIL "), len(failing))

    def test_a_probe_rule_can_name_one_model(self):
        config = {"probe": [{"when": {"model": "m-bad"}, "response": {"fail": {"c_two_tools": "no second call"}}}]}
        self.assertEqual(self.probe("m-bad", config=config).returncode, 1)
        self.assertEqual(self.probe("m-good", config=config).returncode, 0)

    def test_a_probe_that_crashes_leaves_no_probe_json(self):
        done = self.probe(config={"probe": [{"response": {"crash": "connect ECONNREFUSED"}}]})
        self.assertEqual(done.returncode, 1)
        self.assertIn("ECONNREFUSED", done.stderr)
        self.assertFalse(self.out.exists())

    def test_the_extra_body_file_of_a_probe_is_held_to_the_manifest_rules(self):
        for body, why in (({"model": "x"}, "gereserveerde"), ([1], "JSON-object"), ({"temperature": 0.7}, None)):
            with self.subTest(body=body):
                path = self.tmp / "extra.json"
                path.write_text(json.dumps(body))
                out = self.tmp / f"out-{len(json.dumps(body))}"
                done = self.probe("m", "--extra-body-file", path, out=out)
                if why:
                    self.assertEqual(done.returncode, 1)
                    self.assertIn(why, done.stderr)
                    self.assertFalse(out.exists())
                else:
                    self.assertEqual(done.returncode, 0, done.stderr)

    def test_run_writes_result_and_trace_in_the_harness_layout(self):
        config = {"run": [{"response": {"answer": "Hallo.", "providers": ["Novita"], "duration_ms": 2500,
                                        "usage": {"inputTokens": 321, "outputTokens": 45, "cachedTokens": 12,
                                                  "costUsd": 0.00052, "reasoningTokens": 7}}}]}
        done = self.run_manifest(sample_manifest(), config=config)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(sorted(p.name for p in self.run_dir().iterdir()), ["result.json", "trace.jsonl"])
        result = self.result()
        self.assertEqual(list(result), ["runId", "status", "answer", "model", "usage", "durationMs"])
        self.assertEqual((result["runId"], result["status"], result["answer"], result["durationMs"]),
                         ("a1b2c3-p1-t1", "completed", "Hallo.", 2500))
        self.assertEqual(result["model"], {"name": "qwen/qwen3.6-35b-a3b", "baseUrl": "https://openrouter.ai/api/v1",
                                           "reported": "qwen/qwen3.6-35b-a3b"})
        self.assertEqual(result["usage"], {"source": "provider_reported", "inputTokens": 321, "outputTokens": 45, "turns": 1,
                                           "toolCalls": 0, "toolErrors": 0, "cachedTokens": 12, "costUsd": 0.00052,
                                           "reasoningTokens": 7})
        events = self.trace()
        self.assertEqual([e["type"] for e in events], ["run_start", "model_request", "model_response", "run_end"])
        self.assertTrue(all("ts" in e for e in events))
        self.assertEqual(events[0]["manifest"]["id"], "a1b2c3-p1-t1")
        response = events[2]
        self.assertEqual(sorted(response), ["content", "durationMs", "finishReason", "provider", "toolCalls", "ts", "turn", "type",
                                            "usage"])
        self.assertEqual((response["content"], response["toolCalls"], response["finishReason"], response["provider"],
                          response["turn"]), ("Hallo.", [], "stop", "Novita", 1))
        self.assertEqual(response["usage"]["costUsd"], 0.00052)
        self.assertEqual(events[3], {"ts": events[3]["ts"], "type": "run_end", "status": "completed"})
        self.assertIn("completed", done.stdout)

    def test_a_tools_run_pairs_each_tool_call_with_its_result(self):
        self.assertEqual(self.probe().returncode, 0)
        calls = [{"name": "search_product_docs", "arguments": {"query": "x"}},
                 {"name": "get_product_doc", "arguments": "{oops", "ok": False, "error_code": "MALFORMED_ARGS"}]
        config = {"run": [{"response": {"calls": calls, "answer": "Klaar.", "providers": ["A", "B"]}}]}
        done = self.run_manifest(sample_manifest("tools"), config=config)
        self.assertEqual(done.returncode, 0, done.stderr)
        events = self.trace()
        self.assertEqual([e["type"] for e in events],
                         ["run_start", "tool_snapshot", "model_request", "model_response", "tool_call", "tool_result",
                          "model_request", "model_response", "tool_call", "tool_result",
                          "model_request", "model_response", "run_end"])
        self.assertEqual(events[1]["names"], sorted(DOC_TOOL_NAMES))
        first, second = [e for e in events if e["type"] == "tool_call"]
        self.assertEqual((first["name"], first["arguments"], first["argumentsWasObject"]),
                         ("search_product_docs", '{"query": "x"}', False))
        self.assertEqual((second["name"], second["arguments"]), ("get_product_doc", "{oops"))   # a string stays as it is
        ok, bad = [e for e in events if e["type"] == "tool_result"]
        self.assertEqual((ok["callId"], ok["ok"], "errorCode" in ok, ok["truncated"]), (first["callId"], True, False, False))
        self.assertEqual((bad["callId"], bad["ok"], bad["errorCode"]), (second["callId"], False, "MALFORMED_ARGS"))
        for e in (ok, bad):
            self.assertEqual(sorted(e), ["bytes", "callId", "ok", "sha256", "truncated", "ts", "type"] if e is ok
                             else ["bytes", "callId", "errorCode", "ok", "sha256", "truncated", "ts", "type"])
        self.assertEqual(sorted(p.name for p in (self.run_dir() / "tools").iterdir()),
                         sorted(f"{e['callId']}.txt" for e in (ok, bad)))
        responses = [e for e in events if e["type"] == "model_response"]
        self.assertEqual([(e["provider"], e["finishReason"]) for e in responses],
                         [("A", "tool_calls"), ("B", "tool_calls"), ("B", "stop")])    # the last provider repeats
        self.assertEqual([len(e["toolCalls"]) for e in responses], [1, 1, 0])
        self.assertEqual(responses[0]["toolCalls"][0]["id"], first["callId"])
        result = self.result()
        self.assertEqual({k: result["usage"][k] for k in ("turns", "toolCalls", "toolErrors")},
                         {"turns": 3, "toolCalls": 2, "toolErrors": 1})
        self.assertIn("toolSnapshotHash", result)

    def test_a_run_that_does_not_complete_exits_1_and_has_no_answer(self):
        error = {"code": "MODEL_ERROR", "message": "model HTTP 402"}
        done = self.run_manifest(sample_manifest(), config={"run": [{"response": {"status": "failed", "error": error}}]})
        self.assertEqual(done.returncode, 1)
        result = self.result()
        self.assertEqual((result["status"], result["error"], "answer" in result), ("failed", error, False))
        events = self.trace()
        self.assertEqual([e["type"] for e in events], ["run_start", "model_request", "run_end"])    # no model_response
        self.assertEqual(events[-1]["error"], error)

    def test_a_cut_off_answer_is_budget_exceeded_with_a_response_that_finished_on_length(self):
        done = self.run_manifest(sample_manifest(), config={"run": [{"response": {"status": "budget_exceeded", "respond": True,
                                                                                  "finish_reason": "length"}}]})
        self.assertEqual(done.returncode, 1)
        result = self.result()
        self.assertEqual((result["status"], "answer" in result, "error" in result), ("budget_exceeded", False, False))
        self.assertEqual([e["finishReason"] for e in self.trace() if e["type"] == "model_response"], ["length"])

    def test_a_run_without_a_result_leaves_no_result_json(self):
        done = self.run_manifest(sample_manifest(), config={"run": [{"response": {"no_result": True}}]})
        self.assertEqual(done.returncode, 1)
        self.assertTrue(self.run_dir().is_dir())
        self.assertFalse((self.run_dir() / "result.json").exists())

    def test_it_refuses_a_run_dir_that_exists(self):
        self.assertEqual(self.run_manifest(sample_manifest(), config={"run": [{"response": {"answer": "eerste"}}]}).returncode, 0)
        done = self.run_manifest(sample_manifest(), config={"run": [{"response": {"answer": "tweede"}}]})
        self.assertEqual(done.returncode, 1)
        self.assertIn("run dir already exists", done.stderr)
        self.assertEqual(self.result()["answer"], "eerste")

    def test_the_probe_gate_for_a_tools_manifest(self):
        tools = sample_manifest("tools")
        done = self.run_manifest(tools)                                           # no probe at all
        self.assertEqual(done.returncode, 1)
        self.assertIn("PROBE_REQUIRED", done.stderr)
        self.assertFalse(self.run_dir().exists())                                 # it exits before it opens the run dir
        self.assertEqual(self.probe("another/model").returncode, 0)               # a probe of another model does not count
        self.assertEqual(self.run_manifest(tools).returncode, 1)
        unreliable = {"probe": [{"response": {"fail": {"c_two_tools": "no second call"}}}]}
        self.assertEqual(self.probe(config=unreliable).returncode, 1)
        done = self.run_manifest(tools)
        self.assertEqual(done.returncode, 1)
        self.assertIn("rates tool calling as unreliable", done.stderr)
        self.assertFalse(self.run_dir().exists())
        self.assertEqual(self.run_manifest(tools, "--skip-probe").returncode, 0)  # the escape hatch
        self.out = self.tmp / "out2"
        self.assertEqual(self.run_manifest(sample_manifest(model=model_block(baseUrl="http://127.0.0.1:11434/v1"))).returncode,
                         0)                                                       # profile answer: no gate
        self.assertEqual(self.probe().returncode, 0)
        wrong_url = sample_manifest("tools", model=model_block(baseUrl="https://elsewhere.example/v1"))
        done = self.run_manifest(wrong_url)                                       # a probe for another baseUrl
        self.assertEqual(done.returncode, 1)
        self.assertIn("was made for", done.stderr)

    def test_a_manifest_the_real_harness_would_refuse_is_refused(self):
        for n, (why, over) in enumerate(INVALID_MANIFESTS.items()):
            with self.subTest(why):
                self.out = self.tmp / f"out-{n}"
                done = self.run_manifest(sample_manifest(**over))
                self.assertEqual(done.returncode, 1)
                self.assertIn("invalid manifest", done.stderr)
                self.assertFalse(self.out.exists())
        self.out = self.tmp / "out-tools"
        done = self.run_manifest(sample_manifest("tools", tools=None), "--skip-probe")    # profile tools without tools
        self.assertEqual((done.returncode, "tools" in done.stderr), (1, True))

    def test_a_manifest_the_real_harness_accepts_is_accepted(self):
        history = [{"role": "user", "content": "Vraag"}, {"role": "assistant", "content": "Antwoord"}]
        accepted = sample_manifest(history=history, model=model_block(baseUrl="http://127.0.0.1:11434/v1", name="m:1",
                                                                      reasoningEffort="none", extraBody={"seed": 2}),
                                   limits={k: v for k, v in ROW_LIMITS.items() if k != "contextTokens"})   # it is optional
        done = self.run_manifest(accepted)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.trace()[0]["manifest"]["history"], history)

    def test_every_invocation_is_logged_with_its_argv(self):
        self.probe()
        self.run_manifest(sample_manifest("tools"))
        lines = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([entry["argv"][0] for entry in lines], ["probe", "run"])
        self.assertEqual(lines[0]["argv"][1:5], ["--base-url", "https://openrouter.ai/api/v1", "--model", "qwen/qwen3.6-35b-a3b"])
        self.assertEqual(lines[1]["argv"][2:], ["--out", str(self.out)])

    def test_an_api_key_variable_that_is_not_set_stops_the_command_and_a_set_one_is_never_shown(self):
        done = self.run_manifest(sample_manifest(), "--api-key-env", "NO_SUCH_VARIABLE_FOR_TESTS")
        self.assertEqual(done.returncode, 1)
        self.assertIn("NO_SUCH_VARIABLE_FOR_TESTS", done.stderr)
        self.assertFalse(self.out.exists())
        done = self.run_manifest(sample_manifest(), "--api-key-env", "OPENROUTER_API_KEY", OPENROUTER_API_KEY=DUMMY_KEY)
        self.assertEqual(done.returncode, 0, done.stderr)
        done = self.probe("m", "--api-key-env", "OPENROUTER_API_KEY", OPENROUTER_API_KEY=DUMMY_KEY)
        self.assertEqual(done.returncode, 0, done.stderr)
        everything = done.stdout + done.stderr + "".join(p.read_text() for p in self.tmp.rglob("*") if p.is_file())
        self.assertNotIn(DUMMY_KEY, everything)

    def test_extra_body_file_is_a_probe_option_only(self):
        done = self.run_manifest(sample_manifest(), "--extra-body-file", self.tmp / "x.json")
        self.assertEqual(done.returncode, 1)
        self.assertIn("harness probe", done.stderr)
        self.assertFalse(self.out.exists())

    def test_the_rules_of_a_config_merge_in_file_order(self):
        history = [{"role": "user", "content": "Vraag"}, {"role": "assistant", "content": "Antwoord"}]
        config = {"run": [
            {"response": {"answer": "standaard", "providers": ["P"]}},
            {"when": {"turn": 2}, "response": {"answer": "beurt twee"}},
            {"when": {"seed": 2}, "response": {"answer": "seed twee"}},
            {"when": {"prompt_contains": "bijzonder"}, "response": {"answer": "bijzonder antwoord"}},
            {"when": {"model": "other/model", "turn": 1}, "response": {"answer": "ander model"}},
            {"when": {"poging": 2}, "response": {"answer": "tweede poging"}}]}
        cases = (("t1", sample_manifest(id="a1-p1-t1"), "standaard"),
                 ("t2", sample_manifest(id="a1-p1-t2", history=history), "beurt twee"),
                 ("seed", sample_manifest(id="a2-p1-t1", model=model_block(extraBody={"seed": 2})), "seed twee"),
                 ("prompt", sample_manifest(id="a3-p1-t1", prompt="Iets bijzonders"), "bijzonder antwoord"),
                 ("model", sample_manifest(id="a4-p1-t1", model=model_block(name="other/model")), "ander model"),
                 ("poging", sample_manifest(id="a5-p2-t1"), "tweede poging"),
                 ("last wins", sample_manifest(id="a6-p2-t2", history=history), "tweede poging"))
        for why, manifest, answer in cases:
            with self.subTest(why):
                self.assertEqual(self.run_manifest(manifest, config=config).returncode, 0)
                self.assertEqual(self.result(manifest["id"])["answer"], answer)
        self.assertEqual(self.trace("a1-p1-t1")[2]["provider"], "P")             # a field that no later rule sets stays


# Taak 11a: run.py --backend harness. fake_harness.py (above) is the harness; models.json holds the labels.
MODELS_FILE = HERE / "models.json"
PROMPT_FILE = PROMPTS / "promptverfijner-systeem.txt"
ADDENDUM_FILE = PROMPTS / "promptverfijner-docs-addendum.txt"
PROVIDER_BLOCK = {"data_collection": "deny", "require_parameters": True}
LOCAL_MODELS = {"gsq-lokaal": "qwen3.8-gsq-rco:27b-iq3_s-text", "qwen3.6-lokaal": "qwen3.6:35b-a3b-coding"}
OPENROUTER_MODELS = {"qwen3.6-openrouter": "qwen/qwen3.6-35b-a3b", "qwen3.8-openrouter": "qwen/qwen3.8-27b",
                     "gemma-openrouter": "google/gemma-4-31b-it", "qwen3.5-122b-openrouter": "qwen/qwen3.5-122b-a10b",
                     "nemotron-openrouter": "nvidia/nemotron-3-super-120b-a12b"}
LOCAL, REMOTE = "gsq-lokaal", "qwen3.6-openrouter"     # a label that needs no key and one that needs OPENROUTER_API_KEY
KEY_VARIABLE = "OPENROUTER_API_KEY"                     # the name; a test lends the variable DUMMY_KEY and nothing else
LOCAL_URL, REMOTE_URL = "http://127.0.0.1:11434/v1", "https://openrouter.ai/api/v1"


def script(*answers, **response):
    """A config for the fake harness: the answer to model turn n is answers[n - 1], and the last answer goes on repeating.
    response: more fields of the fake's response (usage, providers, ...) for every turn."""
    rules = [{"response": {"answer": answers[-1], **response}}]
    rules += [{"when": {"turn": n}, "response": {"answer": text}} for n, text in enumerate(answers[:-1], start=1)]
    return {"run": rules}


ASK = script(QUESTIONS, FENCE_REPLY)      # the model asks first and then writes the prompt (FakeOllama "ask")
DIRECT = script(FENCE_REPLY)              # the model writes the prompt at once (FakeOllama "direct")
NEVER = script(QUESTIONS)                 # the model never writes a prompt (FakeOllama "never")


def sha256_hex(text):
    return hashlib.sha256(text.encode()).hexdigest()


def probe_fails(model, **fail):
    """A fake-harness rule: the probe of model fails the steps named in fail ({step: reason})."""
    return {"when": {"model": model}, "response": {"fail": fail}}


class HarnessRunBase(unittest.TestCase):
    """run.py --backend harness with fake_harness.py as the harness. It holds no test, so a subclass does not repeat any."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = (self.tmp / "run").resolve()         # run.py creates it
        self.log = self.tmp / "invocations.jsonl"
        self.harness = f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKE_HARNESS))}"

    def run_py(self, *args, config=None, check=True, cwd=None, **env):
        """run.py --backend harness with args. config: what the fake harness answers; check: expect exit status 0;
        env: more variables for run.py and so for the harness."""
        (self.tmp / "fake.json").write_text(json.dumps(config or {}))
        variant = [] if "--variant" in args else ["--variant", "nodocs"]       # run.py wants it said; most tests run nodocs
        argv = [sys.executable, str(HERE / "run.py"), "--backend", "harness", "--harness", self.harness, *variant,
                "--out", str(self.out), *map(str, args)]
        done = subprocess.run(argv, capture_output=True, text=True, cwd=cwd,
                              env=clean_env(FAKE_HARNESS_CONFIG=str(self.tmp / "fake.json"), FAKE_HARNESS_LOG=str(self.log),
                                            **env))
        if check:
            self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def rows(self):
        return [json.loads(line) for line in (self.out / "raw.jsonl").read_text(encoding="utf-8").splitlines()]

    def turn_rows(self):
        return [r for r in self.rows() if isinstance(r["turn"], int)]

    def end_rows(self):
        return [r for r in self.rows() if r["turn"] == "end"]

    def manifests(self):
        """{id: manifest} of the turns of the run, in the order of the ids."""
        return {p.stem: json.loads(p.read_text(encoding="utf-8"))
                for p in sorted((self.out / "manifests").glob("*.json")) if re.fullmatch(r"[0-9a-f]{6}-p\d+-t\d+", p.stem)}

    def invocations(self):
        """The argv of every call run.py made to the fake harness."""
        return [json.loads(line)["argv"] for line in self.log.read_text().splitlines()] if self.log.exists() else []


class BlindIdsTest(unittest.TestCase):
    """The blind ids of the backend harness: six hexadecimal digits, one per conversation, from the stamp as for the backend ollama."""

    def test_the_ids_are_those_the_ollama_loop_draws_for_the_same_stamp(self):
        stamp = "20260930T120000Z"
        rng, ids = random.Random(stamp), run.blind_ids(stamp)
        for _ in range(8):
            drawn = next(ids)
            self.assertRegex(drawn, r"^[0-9a-f]{6}$")
            self.assertEqual(drawn, f"{rng.randrange(16**6):06x}")

    def test_an_id_that_was_given_is_not_given_again(self):
        with mock.patch.object(run.random, "Random") as fake:
            fake.return_value.randrange.side_effect = [5, 5, 5, 7, 7, 9]
            ids = run.blind_ids("stamp")
            self.assertEqual([next(ids) for _ in range(3)], ["000005", "000007", "000009"])


class ModelsFileTest(unittest.TestCase):
    """models.json: the seven labels of the spec, with the settings of Task 2 and no key."""

    def setUp(self):
        self.models = json.loads(MODELS_FILE.read_text(encoding="utf-8"))

    def test_it_holds_the_seven_labels_in_the_order_of_the_plan(self):
        self.assertEqual(list(self.models), ["gsq-lokaal", "qwen3.6-lokaal", "qwen3.6-openrouter", "qwen3.8-openrouter",
                                             "gemma-openrouter", "qwen3.5-122b-openrouter", "nemotron-openrouter"])

    def test_the_local_labels_are_the_two_installed_models_with_reasoning_off_without_docs_only(self):
        for label, name in LOCAL_MODELS.items():
            with self.subTest(label):
                self.assertEqual(self.models[label], {
                    "base_url": LOCAL_URL, "name": name,
                    "nodocs": {"reasoningEffort": "none", "extraBody": {}},
                    "docs": {"extraBody": {}},
                    "probe": {"extraBody": {"reasoning_effort": "none"}}})

    def test_the_openrouter_labels_carry_the_provider_block_and_the_reasoning_of_task_2(self):
        for label, name in OPENROUTER_MODELS.items():
            with self.subTest(label):
                self.assertEqual(self.models[label], {
                    "base_url": REMOTE_URL, "name": name, "api_key_env": KEY_VARIABLE,
                    "nodocs": {"extraBody": {"provider": PROVIDER_BLOCK, "reasoning": {"effort": "none"}}},
                    "docs": {"extraBody": {"provider": PROVIDER_BLOCK, "reasoning": {"effort": "medium"}}},
                    "probe": {"extraBody": {"provider": PROVIDER_BLOCK, "reasoning": {"effort": "none"}}}})

    def test_run_py_adds_temperature_and_seed_so_the_labels_do_not_hold_them(self):
        for label, cfg in self.models.items():
            for variant in ("nodocs", "docs", "probe"):
                self.assertFalse({"temperature", "seed"} & set(cfg[variant]["extraBody"]), (label, variant))

    def test_the_only_thing_about_a_key_is_the_name_of_a_variable(self):
        def walk(value, path=()):
            if isinstance(value, dict):
                for k, v in value.items():
                    yield from walk(v, path + (k,))
            else:
                yield path, value
        for path, value in walk(self.models):
            if re.search(r"(?i)key|token|secret|auth|password", path[-1]):
                self.assertEqual((path[1:], value), (("api_key_env",), KEY_VARIABLE), path)

    def test_load_models_returns_the_labels_asked_for_and_refuses_the_others(self):
        models = run.load_models(MODELS_FILE, [LOCAL, REMOTE])
        self.assertEqual(list(models), [LOCAL, REMOTE])
        self.assertEqual(models[REMOTE]["name"], "qwen/qwen3.6-35b-a3b")
        with self.assertRaisesRegex(run.RunError, "no-such-label.*gsq-lokaal.*nemotron-openrouter"):
            run.load_models(MODELS_FILE, ["no-such-label"])

    def test_a_value_in_api_key_env_is_refused_and_never_quoted_back(self):
        # api_key_env goes into argv as it is: a key pasted into it has to stop the run, and the message must not repeat it
        path = Path(tempfile.mkdtemp()) / "models.json"
        self.addCleanup(shutil.rmtree, path.parent, ignore_errors=True)
        pasted = ("sk-or-v1-" + "0123456789", DUMMY_KEY)            # key-shaped, built here so no such text is in the source
        for value in (*pasted, "OPENROUTER KEY", "", 5, None):
            with self.subTest(value):
                path.write_text(json.dumps({"x": {**self.models["gsq-lokaal"], "api_key_env": value}}))
                with self.assertRaisesRegex(run.RunError, "x.*api_key_env") as caught:
                    run.load_models(path, ["x"])
                for text in pasted:
                    self.assertNotIn(text, str(caught.exception))
        path.write_text(json.dumps({"x": {**self.models["gsq-lokaal"], "api_key_env": "SOME_OTHER_KEY_2"}}))
        self.assertEqual(run.load_models(path, ["x"])["x"]["api_key_env"], "SOME_OTHER_KEY_2")

    def test_a_models_file_that_is_no_object_of_labels_is_refused(self):
        path = Path(tempfile.mkdtemp()) / "models.json"
        self.addCleanup(shutil.rmtree, path.parent, ignore_errors=True)
        for text in ("[]", '"gsq-lokaal"', "{broken"):
            with self.subTest(text):
                path.write_text(text)
                with self.assertRaisesRegex(run.RunError, "models file"):
                    run.load_models(path, [LOCAL])
        with self.assertRaisesRegex(run.RunError, "models file"):
            run.load_models(path.parent / "nowhere.json", [LOCAL])

    def test_load_models_refuses_a_label_that_lacks_a_field_naming_the_label_and_the_field(self):
        broken = self.models["gsq-lokaal"]
        for field in ("base_url", "name", "nodocs", "docs", "probe"):
            with self.subTest(field):
                path = Path(tempfile.mkdtemp()) / "models.json"
                self.addCleanup(shutil.rmtree, path.parent, ignore_errors=True)
                path.write_text(json.dumps({"gsq-lokaal": {k: v for k, v in broken.items() if k != field}}))
                with self.assertRaisesRegex(run.RunError, f"gsq-lokaal.*{field}"):
                    run.load_models(path, ["gsq-lokaal"])
        path = Path(tempfile.mkdtemp()) / "models.json"
        self.addCleanup(shutil.rmtree, path.parent, ignore_errors=True)
        path.write_text(json.dumps({"x": {**broken, "probe": {}}}))
        with self.assertRaisesRegex(run.RunError, "x.*probe.*extraBody"):
            run.load_models(path, ["x"])


class SystemTextTest(unittest.TestCase):
    """The system text as it is sent: the prompt file, in the docs variant with the addendum behind it."""

    def test_without_docs_it_is_the_prompt_file_as_it_is(self):
        self.assertEqual(run.system_text(PROMPT_FILE, "nodocs", "bench-agent-harness"), PROMPT_FILE.read_text())

    def test_with_docs_the_addendum_follows_a_blank_line_with_the_product_id_filled_in(self):
        text = run.system_text(PROMPT_FILE, "docs", "bench-agent-harness")
        prompt, addendum = PROMPT_FILE.read_text().rstrip(), ADDENDUM_FILE.read_text().rstrip()
        self.assertEqual(text, prompt + "\n\n" + addendum.replace("{product_id}", "bench-agent-harness"))
        self.assertTrue(text.startswith(prompt + "\n\n# Documentation tools\n"))
        self.assertIn('Pass product_id "bench-agent-harness" on every call.', text)
        self.assertNotIn("{product_id}", text)
        self.assertFalse(text.endswith(("\n", " ")))      # trailing whitespace of both parts is stripped

    def test_only_the_addendum_is_filled_in_and_a_brace_in_the_prompt_is_left_alone(self):
        path = Path(tempfile.mkdtemp()) / "prompt.txt"
        self.addCleanup(shutil.rmtree, path.parent, ignore_errors=True)
        path.write_text("Schrijf {product_id} en {x} letterlijk.\n\n\n")
        text = run.system_text(path, "docs", "{p}")
        self.assertTrue(text.startswith("Schrijf {product_id} en {x} letterlijk.\n\n# Documentation tools\n"))
        self.assertIn('Pass product_id "{p}" on every call.', text)


class TurnRowTest(unittest.TestCase):
    """What run.py takes from result.json and trace.jsonl for the row of a turn."""

    RESULT = {"runId": "a1b2c3-p1-t2", "status": "completed", "answer": "Antwoord.",
              "model": {"name": "m", "baseUrl": LOCAL_URL},
              "usage": {"source": "provider_reported", "inputTokens": 1200, "outputTokens": 300, "turns": 3, "toolCalls": 2,
                        "toolErrors": 0, "cachedTokens": 64, "costUsd": 0.0004, "reasoningTokens": 120},
              "durationMs": 6200}

    @staticmethod
    def response(turn, provider=None, finish="stop"):
        return {"ts": "t", "type": "model_response", "turn": turn, "content": "x", "toolCalls": [], "finishReason": finish,
                "usage": {"source": "provider_reported", "inputTokens": 1, "outputTokens": 1}, "durationMs": 5,
                **({"provider": provider} if provider else {})}

    @staticmethod
    def call(call_id, name="search_product_docs", arguments='{"query": "x"}'):
        return {"ts": "t", "type": "tool_call", "callId": call_id, "name": name, "arguments": arguments,
                "argumentsWasObject": False}

    @staticmethod
    def outcome(call_id, ok=True, error_code=None):
        return {"ts": "t", "type": "tool_result", "callId": call_id, "ok": ok, "truncated": False, "sha256": "0" * 64,
                "bytes": 3, **({"errorCode": error_code} if error_code else {})}

    def row(self, events=(), **result):
        return run.turn_row({**self.RESULT, **result}, list(events), 2, "a1b2c3-p1-t2", "0" * 64, ROW_LIMITS)

    def test_the_row_of_a_completed_turn(self):
        events = [{"ts": "t", "type": "run_start", "manifest": {}}, self.response(1, "Novita", "tool_calls"), self.call("c1"),
                  self.outcome("c1"), self.response(2, "Novita", "stop"), {"ts": "t", "type": "run_end", "status": "completed"}]
        expected = {
            "turn": 2, "content": "Antwoord.", "status": "completed", "error_code": None, "model_turns": 3,
            "tool_calls": [{"name": "search_product_docs", "arguments": {"query": "x"}, "ok": True, "error_code": None}],
            "input_tokens": 1200, "output_tokens": 300, "cached_tokens": 64, "reasoning_tokens": 120, "cost_usd": 0.0004,
            "providers": ["Novita"], "finish_reason": "stop", "wall_s": 6.2, "harness_run": "harness/a1b2c3-p1-t2",
            "prompt_sha256": "0" * 64, "limits": ROW_LIMITS}
        row = self.row(events)
        self.assertEqual(row, expected)
        self.assertEqual(list(row), list(expected))

    def test_a_tool_call_pairs_with_its_result_by_call_id_not_by_position(self):
        events = [self.call("c1", "search_product_docs"), self.call("c2", "get_product_doc", '{"slug": "a"}'),
                  self.outcome("c2", ok=False, error_code="TOOL_ERROR"), self.outcome("c1")]
        calls = run.tool_calls(events)
        self.assertEqual(calls, [{"name": "search_product_docs", "arguments": {"query": "x"}, "ok": True, "error_code": None},
                                 {"name": "get_product_doc", "arguments": {"slug": "a"}, "ok": False,
                                  "error_code": "TOOL_ERROR"}])
        self.assertEqual(list(calls[0]), ["name", "arguments", "ok", "error_code"])

    def test_arguments_are_the_object_when_the_text_is_a_json_object_and_the_text_otherwise(self):
        for text, expected in (('{"query": "x", "limit": 3}', {"query": "x", "limit": 3}), ("{}", {}), ("{oops", "{oops"),
                               ("[1, 2]", "[1, 2]"), ('"x"', '"x"'), ("", "")):
            with self.subTest(text):
                self.assertEqual(run.tool_calls([self.call("c1", arguments=text), self.outcome("c1")])[0]["arguments"],
                                 expected)

    def test_a_tool_call_event_without_a_call_id_is_a_call_without_a_result_and_not_a_crash(self):
        event = {"ts": "t", "type": "tool_call", "name": "search_product_docs", "arguments": "{}"}
        self.assertEqual(run.tool_calls([event, self.outcome("c1")]),
                         [{"name": "search_product_docs", "arguments": {}, "ok": None, "error_code": None}])

    def test_a_call_without_a_result_has_no_verdict(self):
        self.assertEqual(run.tool_calls([self.call("c1")]),
                         [{"name": "search_product_docs", "arguments": {"query": "x"}, "ok": None, "error_code": None}])
        self.assertEqual(run.tool_calls([]), [])

    def test_providers_are_distinct_in_the_order_first_seen_and_the_finish_reason_is_the_last_response(self):
        events = [self.response(1, "B", "tool_calls"), self.response(2, "A", "tool_calls"), self.response(3),
                  self.response(4, "B", "length")]
        row = self.row(events)
        self.assertEqual((row["providers"], row["finish_reason"]), (["B", "A"], "length"))

    def test_a_run_without_a_model_response_has_no_finish_reason_and_no_providers(self):
        row = self.row([{"ts": "t", "type": "run_start", "manifest": {}}])
        self.assertEqual((row["providers"], row["finish_reason"], row["tool_calls"]), ([], None, []))

    def test_a_turn_that_did_not_complete_has_empty_content_and_the_error_code(self):
        failed = {"runId": "a1b2c3-p1-t2", "status": "failed", "error": {"code": "MODEL_ERROR", "message": "model HTTP 503"},
                  "model": {"name": "m", "baseUrl": LOCAL_URL}, "durationMs": 900,
                  "usage": {"source": "missing", "inputTokens": 0, "outputTokens": 0, "turns": 1, "toolCalls": 0,
                            "toolErrors": 0}}
        row = run.turn_row(failed, [], 2, "a1b2c3-p1-t2", "0" * 64, ROW_LIMITS)
        self.assertEqual((row["content"], row["status"], row["error_code"], row["wall_s"]), ("", "failed", "MODEL_ERROR", 0.9))
        # a budget stop has no error: its code is None, and the answer is absent
        stopped = {**failed, "status": "budget_exceeded"}
        stopped.pop("error")
        row = run.turn_row(stopped, [], 2, "a1b2c3-p1-t2", "0" * 64, ROW_LIMITS)
        self.assertEqual((row["content"], row["status"], row["error_code"]), ("", "budget_exceeded", None))

    def test_a_usage_field_that_is_not_there_is_none_and_a_zero_stays_a_zero(self):
        bare = {**self.RESULT["usage"]}
        for field in ("cachedTokens", "costUsd", "reasoningTokens"):
            bare.pop(field)
        row = self.row(usage=bare)
        self.assertEqual((row["cached_tokens"], row["reasoning_tokens"], row["cost_usd"]), (None, None, None))
        row = self.row(usage={**bare, "cachedTokens": 0, "costUsd": 0, "reasoningTokens": 0})
        self.assertEqual((row["cached_tokens"], row["reasoning_tokens"], row["cost_usd"]), (0, 0, 0))

    def test_cost_does_not_depend_on_whether_the_provider_reported_the_tokens(self):
        usage = {**self.RESULT["usage"], "source": "missing"}
        self.assertEqual(self.row(usage=usage)["cost_usd"], 0.0004)

    def test_reasoning_tokens_are_part_of_the_output_tokens_and_are_not_added(self):
        row = self.row()
        self.assertEqual((row["output_tokens"], row["reasoning_tokens"]), (300, 120))


class HarnessFilesTest(unittest.TestCase):
    """Reading what the harness wrote: a file that is not there or not usable is an error of its own, never an empty turn."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()) / "a1b2c3-p1-t1"
        self.dir.mkdir()
        self.addCleanup(shutil.rmtree, self.dir.parent, ignore_errors=True)

    def test_a_missing_result_json_is_a_harness_error_that_names_the_run_dir(self):
        with self.assertRaisesRegex(run.HarnessError, r"a1b2c3-p1-t1.*result\.json"):
            run.read_result(self.dir)

    def test_a_result_json_that_is_no_result_is_refused(self):
        for text in ("", "{not json", "[]", '{"status": "unknown"}', "{}"):
            with self.subTest(text):
                (self.dir / "result.json").write_text(text)
                with self.assertRaisesRegex(run.HarnessError, r"result\.json"):
                    run.read_result(self.dir)

    def test_a_result_json_is_returned_as_it_is(self):
        result = {"runId": "a1b2c3-p1-t1", "status": "failed", "durationMs": 5, "usage": {}}
        (self.dir / "result.json").write_text(json.dumps(result))
        self.assertEqual(run.read_result(self.dir), result)

    def test_a_missing_trace_is_a_harness_error(self):
        with self.assertRaisesRegex(run.HarnessError, r"a1b2c3-p1-t1.*trace\.jsonl"):
            run.read_trace(self.dir)

    def test_a_trace_line_that_is_no_json_is_refused_with_its_line_number(self):
        (self.dir / "trace.jsonl").write_text('{"type": "run_start"}\n{broken\n')
        with self.assertRaisesRegex(run.HarnessError, r"trace\.jsonl.*line 2"):
            run.read_trace(self.dir)

    def test_a_trace_is_read_in_order_and_blank_lines_are_skipped(self):
        (self.dir / "trace.jsonl").write_text('{"type": "run_start"}\n\n{"type": "run_end", "status": "completed"}\n')
        self.assertEqual([e["type"] for e in run.read_trace(self.dir)], ["run_start", "run_end"])


class ProbeRowTest(unittest.TestCase):
    """The row run.py writes for a probe, which score.py reads (load_meta, probe_reasons)."""

    STEPS = {"a_plain": {"pass": True, "reason": "content: pong", "raw": {}},
             "b_single_tool": {"pass": True, "reason": 'echo("ping")', "raw": {}},
             "c_two_tools": {"pass": False, "reason": "turn 2: expected exactly one tool call, got 0", "raw": None},
             "d_nonexistent_tool": {"pass": False, "reason": "called: delete_everything", "raw": {}}}

    def test_the_row_names_the_verdict_and_only_the_steps_that_failed(self):
        probe = {"baseUrl": REMOTE_URL, "model": "google/gemma-4-31b-it", "tool_calling": "unreliable", "steps": self.STEPS}
        row = run.probe_row("gemma-openrouter", "docs", probe)
        expected = probe_row("gemma-openrouter", "unreliable", None,
                             {"c_two_tools": "turn 2: expected exactly one tool call, got 0",
                              "d_nonexistent_tool": "called: delete_everything"}, "docs")
        self.assertEqual(row, expected)
        self.assertEqual(list(row), list(expected))
        self.assertEqual(score.probe_reasons(row), ["probe-oordeel unreliable",
                                                    "c_two_tools: turn 2: expected exactly one tool call, got 0",
                                                    "d_nonexistent_tool: called: delete_everything"])

    def test_a_reliable_probe_has_no_reasons_even_when_a_plain_step_failed(self):
        steps = {**self.STEPS, "c_two_tools": {"pass": True, "reason": "ok", "raw": {}},
                 "d_nonexistent_tool": {"pass": True, "reason": "ok", "raw": {}},
                 "a_plain": {"pass": False, "reason": "empty content or unexpected tool call", "raw": {}}}
        row = run.probe_row(LOCAL, "nodocs", {"tool_calling": "reliable", "steps": steps})
        self.assertEqual(row, probe_row(LOCAL, "reliable", None, {"a_plain": "empty content or unexpected tool call"}))

    def test_a_probe_without_a_verdict_is_refused(self):
        with self.assertRaisesRegex(run.HarnessError, "tool_calling"):
            run.probe_row(LOCAL, "nodocs", {"tool_calling": "maybe", "steps": self.STEPS})

    def test_the_probe_directory_is_named_as_the_harness_names_it(self):
        for model, name in (("qwen/qwen3.6-35b-a3b", "probe-qwen-qwen3.6-35b-a3b"),
                            ("qwen3.8-gsq-rco:27b-iq3_s-text", "probe-qwen3.8-gsq-rco-27b-iq3-s-text"),
                            ("nvidia/nemotron-3-super-120b-a12b", "probe-nvidia-nemotron-3-super-120b-a12b"),
                            ("Google/Gemma-4-31B-IT", "probe-google-gemma-4-31b-it")):
            self.assertEqual(run.probe_dir_name(model), name)


class HarnessConversationTest(HarnessRunBase):
    """A conversation without docs: the manifest of each turn and the rows."""

    def test_the_manifest_of_each_turn_carries_the_conversation_so_far(self):
        self.run_py("--models", LOCAL, "--cases", "R07", config=NEVER)         # four user turns and never a prompt
        r07, bid = case("R07"), self.turn_rows()[0]["blind_id"]
        manifests = self.manifests()
        self.assertEqual(list(manifests), [f"{bid}-p1-t{n}" for n in (1, 2, 3, 4)])
        prompts = [r07["input"], *r07["replies"], "Akkoord, schrijf nu de prompt."]
        history = []
        for n, manifest in enumerate(manifests.values()):
            self.assertEqual((manifest["profile"], manifest["system"], manifest["prompt"], "tools" in manifest),
                             ("answer", PROMPT_FILE.read_text(), prompts[n], False))
            self.assertEqual(manifest.get("history"), history or None)      # at turn 1 there is no history
            self.assertEqual(list(manifest), ["id", "profile", "system", *(["history"] if history else []), "prompt",
                                              "model", "limits"])
            history = history + [{"role": "user", "content": prompts[n]}, {"role": "assistant", "content": QUESTIONS}]
        self.assertEqual([r["turn"] for r in self.rows()], ["probe", 1, 2, 3, 4, "end"])
        self.assertEqual(self.end_rows()[0]["status"], "no_final")

    def test_the_pressure_turn_follows_the_first_answer_without_a_prompt(self):
        self.run_py("--models", LOCAL, "--cases", "R01", config=ASK)
        r01 = case("R01")
        first, second = self.manifests().values()
        self.assertEqual(first["prompt"], r01["input"])
        self.assertEqual(second["history"], [{"role": "user", "content": r01["input"]},
                                             {"role": "assistant", "content": QUESTIONS}])
        self.assertEqual(second["prompt"], r01["pressure_reply"])
        self.assertEqual([r["content"] for r in self.turn_rows()], [QUESTIONS, FENCE_REPLY])
        self.assertEqual(self.end_rows()[0]["status"], "final")

    def test_temperature_seed_and_the_reasoning_of_the_label_are_in_the_model_block(self):
        self.run_py("--models", LOCAL, REMOTE, "--cases", "R09", "--seeds", "1", "3", "--temperature", "0.2",
                    config=DIRECT, **{KEY_VARIABLE: DUMMY_KEY})
        blocks = {}
        for manifest in self.manifests().values():
            blocks.setdefault(manifest["model"]["name"], []).append(manifest["model"])

        def by_seed(models):
            return sorted(models, key=lambda m: m["extraBody"]["seed"])
        self.assertEqual(by_seed(blocks[LOCAL_MODELS[LOCAL]]), [
            {"baseUrl": LOCAL_URL, "name": LOCAL_MODELS[LOCAL], "reasoningEffort": "none",
             "extraBody": {"temperature": 0.2, "seed": seed}} for seed in (1, 3)])
        self.assertEqual(by_seed(blocks[OPENROUTER_MODELS[REMOTE]]), [
            {"baseUrl": REMOTE_URL, "name": OPENROUTER_MODELS[REMOTE],
             "extraBody": {"provider": PROVIDER_BLOCK, "reasoning": {"effort": "none"}, "temperature": 0.2, "seed": seed}}
            for seed in (1, 3)])
        self.assertEqual(sorted(r["seed"] for r in self.end_rows()), [1, 1, 3, 3])

    def test_reasoning_effort_comes_from_the_variant_block_of_the_label(self):
        models = {"x-test": {"base_url": LOCAL_URL, "name": "x:1",
                             "nodocs": {"extraBody": {"top_k": 20}},
                             "docs": {"reasoningEffort": "low", "extraBody": {}},
                             "probe": {"extraBody": {}}}}
        path = self.tmp / "models.json"
        path.write_text(json.dumps(models))
        self.run_py("--models", "x-test", "--cases", "R09", "--models-file", path, config=DIRECT)
        (manifest,) = self.manifests().values()
        self.assertEqual(manifest["model"], {"baseUrl": LOCAL_URL, "name": "x:1",
                                             "extraBody": {"top_k": 20, "temperature": 0.7, "seed": 1}})
        self.out = self.tmp / "run-docs"
        self.run_py("--models", "x-test", "--cases", "D01", "--variant", "docs", "--models-file", path, config=DIRECT)
        (manifest,) = self.manifests().values()
        self.assertEqual(manifest["model"], {"baseUrl": LOCAL_URL, "name": "x:1", "reasoningEffort": "low",
                                             "extraBody": {"temperature": 0.7, "seed": 1}})

    def test_a_label_with_odd_characters_names_the_probe_file_safely(self):
        models = {"../odd label": {**json.loads(MODELS_FILE.read_text())[LOCAL]}}
        path = self.tmp / "models.json"
        path.write_text(json.dumps(models))
        self.run_py("--models", "../odd label", "--cases", "R09", "--models-file", path, config=DIRECT)
        self.assertEqual(sorted(p.name for p in (self.out / "manifests").glob("probe-*")), ["probe-..-odd-label.extra-body.json"])
        self.assertEqual(sorted(p.name for p in self.out.iterdir()),
                         ["blind-key.json", "harness", "manifests", "raw.jsonl", "transcripts"])

    def test_the_limits_are_in_the_manifest_and_in_the_rows(self):
        self.run_py("--models", LOCAL, "--cases", "R09", config=DIRECT)
        (manifest,) = self.manifests().values()
        self.assertEqual(manifest["limits"], {"maxTurns": 8, "maxOutputTokens": 4096, "maxWallSeconds": 240,
                                              "maxToolErrors": 2, "contextTokens": 65536})
        self.assertEqual(self.turn_rows()[0]["limits"], manifest["limits"])
        self.out = self.tmp / "run-2"
        self.run_py("--models", LOCAL, "--cases", "R09", "--max-output-tokens", "2048", "--max-wall-seconds", "120",
                    config=DIRECT)
        (manifest,) = self.manifests().values()
        self.assertEqual(manifest["limits"], {"maxTurns": 8, "maxOutputTokens": 2048, "maxWallSeconds": 120,
                                              "maxToolErrors": 2, "contextTokens": 65536})
        self.assertEqual(self.turn_rows()[0]["limits"], manifest["limits"])

    def test_the_rows_of_a_conversation_follow_the_row_contract(self):
        usage = {"inputTokens": 1200, "outputTokens": 300, "cachedTokens": 64, "costUsd": 0.0004, "reasoningTokens": 120}
        config = script(FENCE_REPLY, usage=usage, providers=["Novita"], duration_ms=2500)
        self.run_py("--models", REMOTE, "--cases", "R09", config=config, **{KEY_VARIABLE: DUMMY_KEY})
        probe, turn, end = self.rows()
        bid = turn["blind_id"]
        self.assertRegex(bid, r"^[0-9a-f]{6}$")
        self.assertEqual(probe, probe_row(REMOTE, "reliable", None, {}, "nodocs"))
        expected = {"model": REMOTE, "case": "R09", "seed": 1, "blind_id": bid, "backend": "harness", "variant": "nodocs",
                    "poging": 1, "turn": 1, "content": FENCE_REPLY, "status": "completed", "error_code": None,
                    "model_turns": 1, "tool_calls": [], "input_tokens": 1200, "output_tokens": 300, "cached_tokens": 64,
                    "reasoning_tokens": 120, "cost_usd": 0.0004, "providers": ["Novita"], "finish_reason": "stop",
                    "wall_s": 2.5, "harness_run": f"harness/{bid}-p1-t1", "prompt_sha256": sha256_hex(PROMPT_FILE.read_text()),
                    "limits": ROW_LIMITS}
        self.assertEqual(turn, expected)
        self.assertEqual(list(turn), list(expected))
        self.assertTrue((self.out / turn["harness_run"] / "result.json").is_file())
        self.assertEqual(list(end), ["model", "case", "seed", "blind_id", "backend", "variant", "poging", "turn", "status",
                                     "conversation_wall_s", "cost_usd"])
        self.assertEqual({k: end[k] for k in ("model", "case", "seed", "blind_id", "backend", "variant", "poging", "turn",
                                              "status", "cost_usd")},
                         {"model": REMOTE, "case": "R09", "seed": 1, "blind_id": bid, "backend": "harness",
                          "variant": "nodocs", "poging": 1, "turn": "end", "status": "final", "cost_usd": 0.0004})
        self.assertIsInstance(end["conversation_wall_s"], float)
        self.assertGreaterEqual(end["conversation_wall_s"], 0)
        for row in (turn, end):                           # the Ollama-only fields are not there
            self.assertFalse({"ps_before", "tei_on", "ollama", "options", "think"} & set(row))
        self.assertEqual(sorted(p.name for p in self.out.iterdir()),
                         ["blind-key.json", "harness", "manifests", "raw.jsonl", "transcripts"])
        self.assertEqual(sorted(p.name for p in (self.out / "harness").iterdir()),
                         [f"{bid}-p1-t1", "probe-qwen-qwen3.6-35b-a3b"])

    def test_the_prompt_hash_is_that_of_the_text_in_the_manifest_and_equals_the_ollama_backends(self):
        self.run_py("--models", LOCAL, "--cases", "R09", config=DIRECT)
        (manifest,) = self.manifests().values()
        self.assertEqual(self.turn_rows()[0]["prompt_sha256"], sha256_hex(manifest["system"]))
        self.assertEqual(manifest["system"], PROMPT_FILE.read_text())
        self.assertEqual(self.turn_rows()[0]["prompt_sha256"], hashlib.sha256(PROMPT_FILE.read_bytes()).hexdigest())

    def test_the_prompt_option_names_the_system_prompt(self):
        other = PROMPTS / "promptverfijner-systeem-v2.txt"
        self.run_py("--models", LOCAL, "--cases", "R09", "--prompt", other, config=DIRECT)
        (manifest,) = self.manifests().values()
        self.assertEqual(manifest["system"], other.read_text())
        self.assertEqual(self.turn_rows()[0]["prompt_sha256"], hashlib.sha256(other.read_bytes()).hexdigest())

    def test_the_end_row_costs_the_sum_of_the_known_costs_and_none_when_no_turn_names_one(self):
        def priced(first, second):
            def usage(cost):
                return {"usage": {"costUsd": cost}} if cost is not None else {}
            return {"run": [{"response": {"answer": FENCE_REPLY}},
                            {"when": {"turn": 1}, "response": {"answer": QUESTIONS, **usage(first)}},
                            {"when": {"turn": 2}, "response": usage(second)}]}
        for n, (first, second, total) in enumerate(((0.001, 0.0025, 0.0035), (0.001, None, 0.001), (None, None, None),
                                                    (0, 0, 0))):
            with self.subTest(first=first, second=second):
                self.out = self.tmp / f"run-{n}"
                self.run_py("--models", LOCAL, "--cases", "R01", config=priced(first, second))
                self.assertEqual([r["cost_usd"] for r in self.turn_rows()], [first, second])
                self.assertEqual(self.end_rows()[0]["cost_usd"], total)

    def test_the_blind_key_and_the_transcripts_hide_the_model_but_name_the_conversation(self):
        self.run_py("--models", LOCAL, "--cases", "R01,R09", "--seeds", "1", "2", config=ASK)
        key = json.loads((self.out / "blind-key.json").read_text())
        self.assertEqual(sorted(key.values(), key=lambda v: (v["case"], v["seed"])),
                         [{"model": LOCAL, "case": cid, "seed": seed} for cid in ("R01", "R09") for seed in (1, 2)])
        self.assertEqual(sorted(key), sorted(p.stem for p in (self.out / "transcripts").iterdir()))
        for bid, who in key.items():
            text = (self.out / "transcripts" / f"{bid}.md").read_text()
            self.assertTrue(text.startswith(f"# Transcript {bid} ({who['case']}: {case(who['case'])['titel']})\n"))
            self.assertIn("### Gebruiker", text)
            self.assertIn("### Model", text)
            self.assertNotIn(LOCAL, text)
            self.assertNotIn(LOCAL_MODELS[LOCAL], text)
        self.assertEqual(len(key), 4)

    def test_every_label_of_models_json_runs_in_both_variants_and_its_manifest_is_accepted(self):
        labels = [*LOCAL_MODELS, *OPENROUTER_MODELS]
        self.run_py("--models", *labels, "--cases", "R09", config=DIRECT, **{KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual([r["model"] for r in self.end_rows()], labels)
        self.assertEqual({m["model"]["name"] for m in self.manifests().values()},
                         {*LOCAL_MODELS.values(), *OPENROUTER_MODELS.values()})
        self.out = self.tmp / "run-docs"
        self.run_py("--models", *labels, "--cases", "D01", "--variant", "docs", config=DIRECT, **{KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual([(r["model"], r["variant"], r["status"]) for r in self.end_rows()],
                         [(label, "docs", "final") for label in labels])


class HarnessAttemptTest(HarnessRunBase):
    """attempt() takes the poging and the limits as parameters, so a second attempt of a conversation (Task 11b) is another
    call with its own ids and limits and not new code."""

    def test_a_second_attempt_has_its_own_poging_its_own_ids_and_its_own_limits(self):
        (self.out / "manifests").mkdir(parents=True)
        (self.tmp / "fake.json").write_text(json.dumps(ASK))
        backend = run.HarnessBackend(run.Harness([sys.executable, str(FAKE_HARNESS)], self.out / "harness"), self.out,
                                     "nodocs", PROMPT_FILE.read_text(), run.load_models(MODELS_FILE, [LOCAL]), 0.7, None)
        rows, doubled = [], {**ROW_LIMITS, "maxOutputTokens": 8192, "maxWallSeconds": 480}
        env = {"FAKE_HARNESS_CONFIG": str(self.tmp / "fake.json"), "FAKE_HARNESS_LOG": str(self.log)}
        with mock.patch.dict(os.environ, env):
            first = backend.attempt(LOCAL, case("R01"), 1, "abc123", 1, dict(ROW_LIMITS), rows.append)
            second = backend.attempt(LOCAL, case("R01"), 1, "abc123", 2, doubled, rows.append)
        self.assertEqual((first[0], second[0]), ("final", "final"))
        self.assertEqual([(r["poging"], r["turn"]) for r in rows],
                         [(1, 1), (1, 2), (1, "end"), (2, 1), (2, 2), (2, "end")])
        self.assertEqual(sorted(p.stem for p in (self.out / "manifests").glob("abc123-*.json")),
                         ["abc123-p1-t1", "abc123-p1-t2", "abc123-p2-t1", "abc123-p2-t2"])
        manifest = json.loads((self.out / "manifests" / "abc123-p2-t1.json").read_text())
        self.assertEqual((manifest["limits"], rows[3]["limits"], rows[0]["limits"]), (doubled, doubled, ROW_LIMITS))
        self.assertEqual(rows[3]["harness_run"], "harness/abc123-p2-t1")
        # score.py takes the attempt with the highest poging and remembers how the first one ended
        (self.out / "raw.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        conversation_of_run = score.load_run(self.out)[(LOCAL, "R01", 1)]
        self.assertEqual((conversation_of_run["poging"], conversation_of_run["first_attempt_status"],
                          conversation_of_run["status"]), (2, "final", "final"))


class HarnessDocsTest(HarnessRunBase):
    """A conversation with docs: the addendum, the tool server and the tool calls of the trace."""

    SEARCH_CALL = {"name": "search_product_docs",
                   "arguments": {"product_id": "bench-agent-harness", "query": "doc-server"}}
    GET_CALL = {"name": "get_product_doc", "ok": False, "error_code": "TOOL_ERROR",
                "arguments": {"product_id": "bench-agent-harness", "folder": "runbooks", "slug": "task-worker"}}
    CONFIG = {"run": [{"response": {"answer": FENCE_REPLY}},
                      {"when": {"turn": 1}, "response": {"answer": QUESTIONS, "calls": [SEARCH_CALL, GET_CALL],
                                                         "providers": ["Novita", "Chutes"]}}]}

    def docs_run(self, *args, **kw):
        return self.run_py("--models", REMOTE, "--variant", "docs", "--cases", "D01", *args,
                           **{"config": self.CONFIG, KEY_VARIABLE: DUMMY_KEY, **kw})

    def test_the_manifest_has_the_profile_tools_the_addendum_and_the_tool_server(self):
        self.docs_run()
        first, second = self.manifests().values()
        system = PROMPT_FILE.read_text().rstrip() + "\n\n" + ADDENDUM_FILE.read_text().rstrip().replace(
            "{product_id}", "bench-agent-harness")
        for manifest in (first, second):
            self.assertEqual((manifest["profile"], manifest["system"]), ("tools", system))
            self.assertEqual(manifest["tools"], {
                "server": {"command": sys.executable,
                           "args": [str(FAKE_HARNESS), "doc-server", "--dir", str((HERE / "docset").resolve()),
                                    "--product-id", "bench-agent-harness"]},
                "allow": DOC_TOOL_NAMES})
        self.assertEqual(list(first), ["id", "profile", "system", "prompt", "model", "tools", "limits"])
        self.assertEqual(list(second), ["id", "profile", "system", "history", "prompt", "model", "tools", "limits"])
        self.assertEqual(second["history"][0], {"role": "user", "content": case("D01")["input"]})

    def test_the_prompt_hash_of_a_docs_row_is_that_of_the_text_with_the_addendum(self):
        self.docs_run()
        for row, manifest in zip(self.turn_rows(), self.manifests().values()):
            self.assertEqual(row["prompt_sha256"], sha256_hex(manifest["system"]))
            self.assertNotEqual(row["prompt_sha256"], sha256_hex(PROMPT_FILE.read_text()))

    def test_the_tool_calls_of_the_trace_are_in_the_row_of_the_turn_that_made_them(self):
        self.docs_run()
        first, second = self.turn_rows()
        self.assertEqual(first["tool_calls"], [
            {"name": "search_product_docs", "arguments": self.SEARCH_CALL["arguments"], "ok": True, "error_code": None},
            {"name": "get_product_doc", "arguments": self.GET_CALL["arguments"], "ok": False, "error_code": "TOOL_ERROR"}])
        self.assertEqual(second["tool_calls"], [])
        self.assertEqual((first["model_turns"], second["model_turns"]), (3, 1))          # two calls and the answer; the answer
        self.assertEqual((first["providers"], first["finish_reason"], second["providers"]), (["Novita", "Chutes"], "stop", []))
        self.assertEqual((first["variant"], second["variant"]), ("docs", "docs"))

    def test_the_run_call_has_no_skip_probe_and_names_the_key_variable_only(self):
        self.docs_run()
        run_calls = [argv for argv in self.invocations() if argv[0] == "run"]
        self.assertEqual(len(run_calls), 2)
        for argv, manifest_id in zip(run_calls, self.manifests()):
            self.assertEqual(argv, ["run", str(self.out / "manifests" / f"{manifest_id}.json"), "--out",
                                    str(self.out / "harness"), "--api-key-env", KEY_VARIABLE])

    def test_the_tool_server_command_and_arguments_come_from_the_harness_option(self):
        self.harness = f"{shlex.quote(sys.executable)} -u {shlex.quote(str(FAKE_HARNESS))}"
        self.docs_run()
        (server,) = {json.dumps(m["tools"]["server"]) for m in self.manifests().values()}
        self.assertEqual(json.loads(server), {"command": sys.executable,
                                              "args": ["-u", str(FAKE_HARNESS), "doc-server", "--dir",
                                                       str((HERE / "docset").resolve()), "--product-id",
                                                       "bench-agent-harness"]})

    def test_a_relative_docset_becomes_absolute_and_its_product_id_goes_into_the_addendum_and_the_server_arguments(self):
        docset = self.tmp / "mijn-docset"
        docset.mkdir()
        (docset / "docset.json").write_text(json.dumps({"product_id": "mijn-product", "files": []}))
        self.docs_run("--docset", "mijn-docset", cwd=self.tmp)
        (manifest, _) = self.manifests().values()
        self.assertEqual(manifest["tools"]["server"]["args"][-4:],
                         ["--dir", str(docset.resolve()), "--product-id", "mijn-product"])
        self.assertIn('Pass product_id "mijn-product" on every call.', manifest["system"])
        self.assertNotIn("bench-agent-harness", manifest["system"])

    def test_a_docset_without_docset_json_is_an_error_before_anything_runs(self):
        done = self.docs_run("--docset", self.tmp / "nowhere", check=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("docset.json", done.stderr)
        self.assertEqual(self.invocations(), [])

    def test_the_docset_is_not_needed_without_docs(self):
        self.run_py("--models", LOCAL, "--cases", "R09", "--docset", self.tmp / "nowhere", config=DIRECT)
        self.assertEqual(len(self.manifests()), 1)


class HarnessProbeTest(HarnessRunBase):
    """The probe: once per model, before its conversations, in both variants; docs only after a reliable one."""

    def test_the_probe_runs_once_per_model_before_the_conversations_of_that_model(self):
        self.run_py("--models", LOCAL, REMOTE, "--cases", "R09", "--seeds", "1", "2", config=DIRECT,
                    **{KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual([argv[0] for argv in self.invocations()], ["probe", "run", "run", "probe", "run", "run"])
        self.assertEqual([(r["model"], r["turn"]) for r in self.rows()],
                         [(LOCAL, "probe"), (LOCAL, 1), (LOCAL, "end"), (LOCAL, 1), (LOCAL, "end"),
                          (REMOTE, "probe"), (REMOTE, 1), (REMOTE, "end"), (REMOTE, 1), (REMOTE, "end")])
        self.assertEqual(self.rows()[0], probe_row(LOCAL, "reliable", None, {}, "nodocs"))

    def test_the_probe_call_carries_the_endpoint_the_model_the_key_variable_name_and_the_extra_body_file(self):
        self.run_py("--models", LOCAL, REMOTE, "--cases", "R09", config=DIRECT, **{KEY_VARIABLE: DUMMY_KEY})
        local, remote = [argv for argv in self.invocations() if argv[0] == "probe"]
        harness_out = str(self.out / "harness")
        self.assertEqual(local[:7], ["probe", "--base-url", LOCAL_URL, "--model", LOCAL_MODELS[LOCAL], "--out", harness_out])
        self.assertEqual(remote[:7], ["probe", "--base-url", REMOTE_URL, "--model", OPENROUTER_MODELS[REMOTE], "--out",
                                      harness_out])
        self.assertEqual(local[7], "--extra-body-file")
        self.assertEqual(remote[7:9], ["--api-key-env", KEY_VARIABLE])
        self.assertEqual(remote[9], "--extra-body-file")
        self.assertEqual(len(local), 9)
        self.assertEqual(len(remote), 11)
        self.assertEqual(json.loads(Path(local[8]).read_text()), {"reasoning_effort": "none"})
        self.assertEqual(json.loads(Path(remote[10]).read_text()),
                         {"provider": PROVIDER_BLOCK, "reasoning": {"effort": "none"}})
        self.assertTrue(Path(local[8]).resolve().is_relative_to(self.out))

    def test_the_probe_row_of_a_probe_that_is_not_reliable_names_the_failing_steps(self):
        config = {**DIRECT, "probe": [probe_fails(OPENROUTER_MODELS[REMOTE], c_two_tools="turn 2: expected exactly one "
                                                                                         "tool call, got 0")]}
        self.run_py("--models", REMOTE, "--cases", "R09", config=config, **{KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(self.rows()[0], probe_row(REMOTE, "unreliable", None,
                                                   {"c_two_tools": "turn 2: expected exactly one tool call, got 0"}))
        config["probe"] = [probe_fails(OPENROUTER_MODELS[REMOTE], b_single_tool="expected exactly one tool call, got 0",
                                       c_two_tools="turn 1: expected exactly one tool call, got 0")]
        self.out = self.tmp / "run-none"
        self.run_py("--models", REMOTE, "--cases", "R09", config=config, **{KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual(self.rows()[0]["verdict"], "none")
        self.assertEqual(list(self.rows()[0]["reasons"]), ["b_single_tool", "c_two_tools"])

    def test_without_docs_a_model_whose_probe_is_not_reliable_still_has_its_conversations(self):
        config = {**DIRECT, "probe": [probe_fails(LOCAL_MODELS[LOCAL], d_nonexistent_tool="called: delete_everything")]}
        self.run_py("--models", LOCAL, "--cases", "R09", config=config)
        self.assertEqual([r["turn"] for r in self.rows()], ["probe", 1, "end"])
        self.assertEqual(self.rows()[0]["verdict"], "unreliable")
        self.assertEqual([argv[0] for argv in self.invocations()], ["probe", "run"])

    def test_with_docs_a_model_whose_probe_is_not_reliable_has_no_conversations_but_the_other_models_do(self):
        config = {**DIRECT, "probe": [probe_fails(OPENROUTER_MODELS[REMOTE], c_two_tools="no second call")]}
        self.run_py("--models", REMOTE, "qwen3.8-openrouter", "--variant", "docs", "--cases", "D01", config=config,
                    **{KEY_VARIABLE: DUMMY_KEY})
        rows = self.rows()
        self.assertEqual(rows[0], probe_row(REMOTE, "unreliable", None, {"c_two_tools": "no second call"}, "docs"))
        self.assertEqual(rows[1], probe_row("qwen3.8-openrouter", "reliable", None, {}, "docs"))
        self.assertEqual({r["model"] for r in rows[2:]}, {"qwen3.8-openrouter"})
        self.assertEqual([argv[0] for argv in self.invocations()], ["probe", "probe", "run"])      # no run for REMOTE
        self.assertEqual({m["model"]["name"] for m in self.manifests().values()}, {"qwen/qwen3.8-27b"})
        self.assertEqual([who["model"] for who in json.loads((self.out / "blind-key.json").read_text()).values()],
                         ["qwen3.8-openrouter"])
        self.assertEqual(len(list((self.out / "transcripts").iterdir())), 1)

    def test_a_harness_command_that_cannot_be_started_is_an_error_that_names_it(self):
        self.harness = "no-such-harness-command-for-tests cli.js"
        done = self.run_py("--models", LOCAL, "--cases", "R09", config=DIRECT, check=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("no-such-harness-command-for-tests", done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertEqual(self.invocations(), [])

    def test_a_probe_that_leaves_no_probe_json_stops_the_run_with_an_error(self):
        config = {**DIRECT, "probe": [{"response": {"crash": "connect ECONNREFUSED"}}]}
        done = self.run_py("--models", LOCAL, "--cases", "R09", config=config, check=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("probe.json", done.stderr)
        self.assertIn(LOCAL_MODELS[LOCAL], done.stderr)
        self.assertIn("exit status 1", done.stderr)
        self.assertIn("ECONNREFUSED", done.stderr)                  # what the harness said is passed on
        self.assertEqual([r for r in self.rows() if r["turn"] != "probe"], [])
        self.assertEqual([argv[0] for argv in self.invocations()], ["probe"])


class HarnessKeyTest(HarnessRunBase):
    """The key is a variable name and never a value."""

    def test_the_variable_name_is_in_argv_for_the_labels_that_need_a_key_and_the_value_is_nowhere(self):
        done = self.run_py("--models", LOCAL, REMOTE, "--cases", "R01", "--variant", "nodocs", config=ASK,
                           **{KEY_VARIABLE: DUMMY_KEY})

        def model_of(argv):
            if argv[0] == "probe":
                return argv[argv.index("--model") + 1]
            return json.loads(Path(argv[1]).read_text())["model"]["name"]

        for argv in self.invocations():
            needs_key = model_of(argv) == OPENROUTER_MODELS[REMOTE]
            self.assertEqual(argv.count("--api-key-env"), 1 if needs_key else 0, argv)
            if needs_key:
                self.assertEqual(argv[argv.index("--api-key-env") + 1], KEY_VARIABLE)
            self.assertNotIn("--skip-probe", argv)
            self.assertFalse(any(DUMMY_KEY in part for part in argv))
        self.assertEqual(sum("--api-key-env" in argv for argv in self.invocations()), 1 + 2)       # one probe, two runs
        hits = [p.name for p in self.out.rglob("*") if p.is_file() and DUMMY_KEY in p.read_text(encoding="utf-8")]
        self.assertEqual(hits, [])
        self.assertNotIn(DUMMY_KEY, done.stdout + done.stderr + self.log.read_text())
        for manifest in self.manifests().values():
            self.assertNotIn("apiKey", manifest["model"])
        self.assertIn(KEY_VARIABLE, self.log.read_text())        # the name does appear

    def test_a_key_variable_that_is_not_set_stops_the_run_before_any_call_and_names_the_variable(self):
        done = self.run_py("--models", REMOTE, "--cases", "R09", config=DIRECT, check=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(KEY_VARIABLE, done.stderr)
        self.assertEqual(self.invocations(), [])
        self.assertFalse((self.out / "raw.jsonl").exists())
        # a run of labels that need no key does not ask for one
        self.assertEqual(self.run_py("--models", LOCAL, "--cases", "R09", config=DIRECT).returncode, 0)


class HarnessFailureTest(HarnessRunBase):
    """A turn that does not complete, and a harness that leaves no result."""

    FAILED = {"status": "failed", "error": {"code": "MODEL_ERROR", "message": "model HTTP 503"},
              "usage": {"inputTokens": 0, "outputTokens": 0, "costUsd": 0.0005}}

    def rules(self, *extra):
        """A model that never writes a prompt, with a cost on its first turn, and the rules in extra on top."""
        return {"run": [{"response": {"answer": QUESTIONS}},
                        {"when": {"turn": 1}, "response": {"usage": {"costUsd": 0.001}}}, *extra]}

    def test_a_turn_that_does_not_complete_gets_its_row_and_ends_the_conversation_with_status_error(self):
        config = self.rules({"when": {"turn": 2, "seed": 1}, "response": self.FAILED})
        done = self.run_py("--models", LOCAL, "--cases", "R07", "--seeds", "1", "2", config=config)
        by_seed = {}
        for row in self.rows()[1:]:
            by_seed.setdefault(row["seed"], []).append(row)
        failing, fine = by_seed[1], by_seed[2]
        self.assertEqual([(r["turn"], r["status"]) for r in failing], [(1, "completed"), (2, "failed"), ("end", "error")])
        row = failing[1]
        self.assertEqual((row["content"], row["error_code"], row["cost_usd"], row["finish_reason"], row["providers"]),
                         ("", "MODEL_ERROR", 0.0005, None, []))
        self.assertEqual(failing[2]["cost_usd"], 0.0015)                 # a failed turn is paid for too
        self.assertEqual([(r["turn"], r["status"]) for r in fine],       # the next seed ran, all four turns
                         [(1, "completed"), (2, "completed"), (3, "completed"), (4, "completed"), ("end", "no_final")])
        self.assertEqual(len(self.manifests()), 2 + 4)                   # no turn 3 and 4 after the failure
        self.assertIn("error", done.stdout)
        transcript = (self.out / "transcripts" / f"{failing[0]['blind_id']}.md").read_text()
        self.assertEqual(transcript.count("### Model"), 1)               # the failed turn has no text to show

    def test_every_status_that_is_not_completed_ends_the_conversation(self):
        for status in ("failed", "budget_exceeded", "timed_out"):
            with self.subTest(status):
                self.out = self.tmp / f"run-{status}"
                self.run_py("--models", LOCAL, "--cases", "R07",
                            config=self.rules({"when": {"turn": 2}, "response": {"status": status}}))
                rows = self.rows()[1:]
                self.assertEqual([(r["turn"], r["status"]) for r in rows], [(1, "completed"), (2, status), ("end", "error")])
                self.assertEqual(rows[1]["content"], "")

    def test_a_run_without_result_json_is_an_error_that_names_the_manifest_and_stops_run_py(self):
        config = self.rules({"when": {"turn": 2}, "response": {"no_result": True}})
        done = self.run_py("--models", LOCAL, "--cases", "R07", "--seeds", "1", "2", config=config, check=False)
        self.assertNotEqual(done.returncode, 0)
        manifest_id = sorted(self.manifests())[1]
        self.assertTrue(manifest_id.endswith("-p1-t2"))
        self.assertIn(manifest_id, done.stderr)
        self.assertIn("result.json", done.stderr)
        self.assertIn("exit status 1", done.stderr)
        self.assertIn("stopped before result.json was written", done.stderr)      # what the harness said is passed on
        self.assertNotIn("Traceback", done.stderr)                       # a message, not a stack trace
        self.assertEqual(len(self.manifests()), 2)                       # the second seed never started
        # what was written before stays: the probe row and the first turn, without a row for the missing one or an end row
        rows = self.rows()
        self.assertEqual([r["turn"] for r in rows], ["probe", 1])
        # the conversation that was under way keeps its place in the blind key, so its rows can still be read
        self.assertEqual(json.loads((self.out / "blind-key.json").read_text()),
                         {rows[1]["blind_id"]: {"model": LOCAL, "case": "R07", "seed": 1}})


class HarnessSelectionTest(HarnessRunBase):
    """Which cases a variant runs, and the refusals before anything runs."""

    PLAIN = [f"R{n:02d}" for n in range(1, 11)]
    DOCS = [f"D{n:02d}" for n in range(1, 6)]

    def test_nodocs_runs_the_ten_plain_cases_and_no_doc_case(self):
        self.run_py("--models", LOCAL, config=DIRECT)
        self.assertEqual([r["case"] for r in self.end_rows()], self.PLAIN)
        self.assertEqual(len({r["blind_id"] for r in self.end_rows()}), 10)          # a blind id of its own per conversation
        self.assertEqual({r["variant"] for r in self.rows() if r["turn"] != "probe"}, {"nodocs"})
        self.assertEqual({m["profile"] for m in self.manifests().values()}, {"answer"})

    def test_docs_runs_the_doc_cases_only(self):
        self.run_py("--models", REMOTE, "--variant", "docs", config=DIRECT, **{KEY_VARIABLE: DUMMY_KEY})
        self.assertEqual([r["case"] for r in self.end_rows()], self.DOCS)
        self.assertEqual({r["variant"] for r in self.rows()}, {"docs"})
        self.assertEqual({m["profile"] for m in self.manifests().values()}, {"tools"})

    def test_cases_narrows_the_selection_and_a_case_of_the_other_variant_is_left_out(self):
        self.run_py("--models", LOCAL, "--cases", "R03,D02,R09", config=DIRECT)
        self.assertEqual([r["case"] for r in self.end_rows()], ["R03", "R09"])

    def test_a_selection_without_a_case_is_an_error_before_anything_runs(self):
        done = self.run_py("--models", LOCAL, "--cases", "D01", check=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("D01", done.stderr)
        self.assertEqual(self.invocations(), [])

    def test_an_unknown_label_is_refused_with_the_known_ones_before_anything_runs(self):
        done = self.run_py("--models", LOCAL, "no-such-label", check=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("no-such-label", done.stderr)
        self.assertIn("nemotron-openrouter", done.stderr)
        self.assertEqual(self.invocations(), [])

    def test_a_run_directory_that_already_holds_files_is_refused(self):
        # one invocation is one variant of one prompt version and has a run directory of its own (spec 5.7)
        self.out.mkdir()
        (self.out / "raw.jsonl").write_text("")
        done = self.run_py("--models", LOCAL, "--cases", "R09", config=DIRECT, check=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(str(self.out), done.stderr)
        self.assertEqual(self.invocations(), [])
        self.assertEqual((self.out / "raw.jsonl").read_text(), "")
        self.out = self.tmp / "empty"
        self.out.mkdir()                                               # an empty directory is fine
        self.run_py("--models", LOCAL, "--cases", "R09", config=DIRECT)

    def test_the_harness_command_and_the_variant_have_to_be_said(self):
        # one invocation is one variant: a variant that falls back on a default is a run of the wrong one, unseen
        for args, missing in ((["--models", LOCAL], ["--harness", "--variant"]),
                              (["--models", LOCAL, "--variant", "docs"], ["--harness"]),
                              (["--models", LOCAL, "--harness", self.harness], ["--variant"])):
            with self.subTest(args):
                done = subprocess.run([sys.executable, str(HERE / "run.py"), "--backend", "harness", *args],
                                      capture_output=True, text=True)
                self.assertEqual(done.returncode, 2)
                self.assertIn("needs " + " and ".join(missing), done.stderr)

    def test_an_option_of_the_other_backend_is_refused(self):
        for args in (["--think", "true"], ["--num-ctx", "8192"], ["--host", "http://127.0.0.1:1"]):
            with self.subTest(args):
                done = self.run_py("--models", LOCAL, *args, check=False)
                self.assertEqual(done.returncode, 2)
                self.assertIn(args[0], done.stderr)
        self.assertEqual(self.invocations(), [])
        for args in (["--variant", "docs"], ["--models-file", "x.json"], ["--harness", "node cli.js"],
                     ["--docset", "d"], ["--max-output-tokens", "1"], ["--max-wall-seconds", "1"]):
            with self.subTest(args):
                done = subprocess.run([sys.executable, str(HERE / "run.py"), "--models", "m", *args],
                                      capture_output=True, text=True)
                self.assertEqual(done.returncode, 2)
                self.assertIn(args[0], done.stderr)

    def test_a_limit_that_is_not_a_positive_number_is_refused_before_anything_runs(self):
        for args in (["--max-output-tokens", "0"], ["--max-wall-seconds", "-5"], ["--max-output-tokens", "many"]):
            with self.subTest(args):
                done = self.run_py("--models", LOCAL, *args, check=False)
                self.assertEqual(done.returncode, 2)
                self.assertIn(args[0], done.stderr)
        self.assertEqual(self.invocations(), [])

    def test_the_tool_names_the_manifest_allows_are_the_ones_score_py_counts_as_doc_lookups(self):
        self.assertEqual(list(run.DOC_TOOLS), DOC_TOOL_NAMES)
        self.assertEqual(set(run.DOC_TOOLS), set(score.DOC_TOOLS))


class FlowParityTest(HarnessRunBase):
    """The conversation flow is one piece of code for both backends: the same user messages in the same order."""

    PAIRS = (("R01", "ask"), ("R01", "direct"), ("R03", "ask"), ("R03", "direct"), ("R07", "never"), ("R10", "never"),
             ("R09", "direct"))

    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.host = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_both_backends_send_the_same_user_messages_and_end_the_same_way(self):
        configs = {"ask": ASK, "direct": DIRECT, "never": NEVER}
        for cid, behaviour in self.PAIRS:
            with self.subTest(case=cid, behaviour=behaviour):
                FakeOllama.behaviour, FakeOllama.calls = behaviour, []
                ollama_out = self.tmp / f"ollama-{cid}-{behaviour}"
                subprocess.run([sys.executable, str(HERE / "run.py"), "--models", "fake:model", "--cases", cid,
                                "--host", self.host, "--out", str(ollama_out)], check=True, capture_output=True)
                ollama_users = [m["content"] for m in FakeOllama.calls[-1]["messages"] if m["role"] == "user"]
                ollama_end = [json.loads(line) for line in (ollama_out / "raw.jsonl").read_text().splitlines()][-1]
                self.out = self.tmp / f"harness-{cid}-{behaviour}"
                self.run_py("--models", LOCAL, "--cases", cid, config=configs[behaviour])
                last = list(self.manifests().values())[-1]
                harness_users = [h["content"] for h in last.get("history", []) if h["role"] == "user"] + [last["prompt"]]
                self.assertEqual(harness_users, ollama_users)
                self.assertEqual(len(self.manifests()), len(FakeOllama.calls))
                self.assertEqual(self.end_rows()[0]["status"], ollama_end["status"])
                known = score.user_messages(case(cid))
                for text in harness_users:
                    self.assertIn(text, known)


class HarnessScoreTest(HarnessRunBase):
    """score.py reads the rows run.py writes."""

    USAGE = {"inputTokens": 1000, "outputTokens": 200, "reasoningTokens": 50, "costUsd": 0.001}

    def score(self):
        done = subprocess.run([sys.executable, str(HERE / "score.py"), str(self.out)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        with (self.out / "summary.csv").open(newline="", encoding="utf-8") as f:
            return done.stdout, list(csv.DictReader(f))

    def test_a_run_without_docs_is_scored_with_the_harness_columns(self):
        config = {"run": [{"response": {"answer": FENCE_REPLY, "usage": self.USAGE, "providers": ["Novita"]}},
                          {"when": {"turn": 1}, "response": {"answer": QUESTIONS, "usage": self.USAGE,
                                                             "providers": ["Novita"]}}]}
        self.run_py("--models", LOCAL, "--cases", "R06,R07", config=config)
        output, rows = self.score()
        with (self.out / "summary.csv").open(encoding="utf-8") as f:
            self.assertEqual(f.readline().strip().split(","), [*score.COLUMNS, *score.HARNESS_COLUMNS])
        self.assertEqual([r["case"] for r in rows], ["R06", "R07"])
        for row in rows:
            self.assertEqual({k: row[k] for k in ("model", "status", "turns", "variant", "poging", "first_attempt_status",
                                                  "model_turns", "tool_calls", "input_tokens", "output_tokens",
                                                  "reasoning_tokens", "cost_usd", "providers")},
                             {"model": LOCAL, "status": "final", "turns": "2", "variant": "nodocs", "poging": "1",
                              "first_attempt_status": "final", "model_turns": "2", "tool_calls": "0",
                              "input_tokens": "2000", "output_tokens": "400", "reasoning_tokens": "100",
                              "cost_usd": "0.002", "providers": "Novita"})
            self.assertGreaterEqual(float(row["wall_s"]), 0)
            self.assertEqual(row["eval_tokens"], "")                    # the Ollama measurements stay empty
        table = parse_tables(output)["nodocs"][LOCAL]
        self.assertEqual({k: table[k] for k in ("Backend", "Probe", "Afgerond", "Tokens in", "Tokens uit", "Aanbieders")},
                         {"Backend": "harness", "Probe": "reliable", "Afgerond": "2/2", "Tokens in": "4000",
                          "Tokens uit": "800", "Aanbieders": "Novita"})

    def test_a_docs_run_is_scored_on_the_tool_calls_and_the_statuses_of_its_rows(self):
        search = {"name": "search_product_docs", "arguments": {"product_id": "bench-agent-harness", "query": "doc-server"}}
        config = {"run": [{"response": {"answer": FENCE_REPLY}},
                          {"when": {"turn": 1}, "response": {"answer": QUESTIONS, "calls": [search, search]}}]}
        self.run_py("--models", REMOTE, "--variant", "docs", "--cases", "D01", config=config, **{KEY_VARIABLE: DUMMY_KEY})
        output, (row,) = self.score()
        self.assertEqual((row["variant"], row["tool_calls"], row["model_turns"], row["D1"], row["D6"], row["status"]),
                         ("docs", "2", "4", "pass", "pass", "final"))
        self.assertIn("### Variant docs", output)

    def test_a_docs_conversation_with_a_failed_turn_is_an_error_with_a_failed_d6(self):
        failed = {"status": "failed", "error": {"code": "MODEL_ERROR", "message": "model HTTP 503"}}
        config = {"run": [{"response": {"answer": FENCE_REPLY}},
                          {"when": {"turn": 1}, "response": {"answer": QUESTIONS, "usage": {"costUsd": 0.001}}},
                          {"when": {"turn": 2}, "response": failed}]}
        self.run_py("--models", REMOTE, "--variant", "docs", "--cases", "D01", config=config, **{KEY_VARIABLE: DUMMY_KEY})
        output, (row,) = self.score()
        self.assertEqual((row["status"], row["D6"], row["turns"]), ("error", "fail", "2"))
        self.assertIn("D6 status: beurt 2 failed", row["notes"])
        self.assertIn("error (beurt 2 failed, MODEL_ERROR, $0.0010)", output)

    def test_a_model_without_docs_conversations_is_shown_with_the_reasons_of_its_probe(self):
        config = {**DIRECT, "probe": [probe_fails(OPENROUTER_MODELS[REMOTE], c_two_tools="turn 2: no second call")]}
        self.run_py("--models", REMOTE, "qwen3.8-openrouter", "--variant", "docs", "--cases", "D01", config=config,
                    **{KEY_VARIABLE: DUMMY_KEY})
        output, rows = self.score()
        self.assertEqual([r["model"] for r in rows], ["qwen3.8-openrouter"])
        table = parse_tables(output)["docs"]
        self.assertEqual((table[REMOTE]["Probe"], table[REMOTE]["Zeef"], table["qwen3.8-openrouter"]["Probe"]),
                         ("unreliable", "niet gedraaid", "reliable"))
        self.assertIn(f"- {REMOTE} (niet gedraaid): probe-oordeel unreliable; c_two_tools: turn 2: no second call", output)


# Taak 11a: the backend ollama after the backend harness came. The same ten cases and the same rows as on 29 September; the only
# change is that a case with variant "docs" is skipped.
class OllamaBackendTest(unittest.TestCase):
    TURN_KEYS = ["model", "case", "seed", "blind_id", "ps_before", "tei_on", "ollama", "prompt_sha256", "options", "think",
                 "turn", "content", "thinking_chars", "prompt_eval_count", "prompt_eval_s", "eval_count", "eval_s", "load_s",
                 "total_s", "done_reason", "wall_s"]
    END_KEYS = ["model", "case", "seed", "blind_id", "ps_before", "tei_on", "ollama", "prompt_sha256", "options", "think",
                "turn", "status", "conversation_wall_s"]

    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.host = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def run_ollama(self, *args, behaviour="direct"):
        """run.py with the backend ollama (the default) against the fake Ollama; returns (out, rows)."""
        FakeOllama.behaviour, FakeOllama.calls = behaviour, []
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        subprocess.run([sys.executable, str(HERE / "run.py"), "--models", "fake:model", "--host", self.host,
                        "--out", str(out), *map(str, args)], check=True, capture_output=True)
        return out, [json.loads(line) for line in (out / "raw.jsonl").read_text().splitlines()]

    def test_the_ten_plain_cases_run_and_no_doc_case(self):
        out, rows = self.run_ollama()
        ended = [r["case"] for r in rows if r["turn"] == "end"]
        self.assertEqual(ended, [f"R{n:02d}" for n in range(1, 11)])
        self.assertEqual(len(FakeOllama.calls), sum(isinstance(r["turn"], int) for r in rows))
        self.assertEqual(sorted(json.loads((out / "blind-key.json").read_text()).values(), key=lambda v: v["case"])[0],
                         {"model": "fake:model", "case": "R01", "seed": 1})

    def test_a_doc_case_asked_for_by_name_is_skipped(self):
        _, rows = self.run_ollama("--cases", "D01,R09,D05")
        self.assertEqual({r["case"] for r in rows}, {"R09"})

    def test_the_rows_keep_their_fields_in_their_order(self):
        _, rows = self.run_ollama("--cases", "R09")
        turn, end = rows
        self.assertEqual(list(turn), self.TURN_KEYS)
        self.assertEqual(list(end), self.END_KEYS)
        self.assertEqual((turn["options"], turn["think"], turn["ollama"], turn["tei_on"] in (True, False, None)),
                         ({"num_ctx": 16384, "temperature": 0.7}, False, "0.0-test", True))
        self.assertEqual((end["status"], end["turn"]), ("final", "end"))

    def test_the_prompt_is_the_prompt_file_unless_prompt_names_another(self):
        text = PROMPT_FILE.read_text()
        _, rows = self.run_ollama("--cases", "R09")
        self.assertEqual(FakeOllama.calls[0]["messages"][0], {"role": "system", "content": text})
        self.assertEqual(rows[0]["prompt_sha256"], hashlib.sha256(text.encode()).hexdigest())
        other = PROMPTS / "promptverfijner-systeem-v2.txt"
        _, rows = self.run_ollama("--cases", "R09", "--prompt", other)
        self.assertEqual(FakeOllama.calls[0]["messages"][0], {"role": "system", "content": other.read_text()})
        self.assertEqual(rows[0]["prompt_sha256"], hashlib.sha256(other.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
