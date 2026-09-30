"""Tests for the refiner eval: runner against a fake Ollama, checks against fixed transcripts,
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
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
