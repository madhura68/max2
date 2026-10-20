"""Tests for the review bench (M8): check_case.py on a synthetic case in a tmp dir, and once on the frozen case of this repo. No
model, no network, no key.

  python3 -m unittest discover -s llm-bench/review_bench -v
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_case  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
