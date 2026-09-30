"""Tests for the refiner eval: runner against a fake Ollama, checks against fixed transcripts,
and the frozen docset with its freezer and check.

  python3 -m unittest llm-bench/refiner/test_refiner.py
"""
import hashlib
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


if __name__ == "__main__":
    unittest.main()
