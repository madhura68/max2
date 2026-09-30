"""Tests for the refiner eval: runner against a fake Ollama, checks against fixed transcripts.

  python3 -m unittest llm-bench/refiner/test_refiner.py
"""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
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


if __name__ == "__main__":
    unittest.main()
