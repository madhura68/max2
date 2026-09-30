#!/usr/bin/env python3
"""Score a refiner run directory with the automatic checks A1-A8 (PBI-8, T-3).

  ./score.py results/refiner-<stamp>          # writes summary.csv, prints a markdown table

A1 language, A2 question form, A3 rounds, A4 final shape, A5 restraint (a flag, disqualifying
only after JP confirms it), A6 fidelity, A7 Opus prompt rules, A8 revision. See PLANS/refiner-eval.
The checks are heuristics: A1 detects which language, not how fluent; A5/A6 match patterns.
A forbid_statement pattern counts only in a statement (statement_hits). For a docs case (variant
"docs") the same A5 rule is reported as D5 and its A5 is n.v.t.
"""
import csv
import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FENCE = re.compile(r"```[^\n]*\n(.*?)(?:```|\Z)", re.S)
NL = set("de het een en je jij van is niet dat voor met op te zijn wat ik we er ook naar als of bij".split())
EN = set("the and you of to is for that with on are what it be this your or as have".split())
EFFORT = re.compile(r"\b(low|medium|high|xhigh|max)\b", re.I)
NUMBERED = re.compile(r"^\s*\d+[.)]\s", re.M)
A7_CI = [r"stap voor stap", r"step[- ]by[- ]step", r"denk (goed|zorgvuldig|eerst|grondig) na",
         r"think (carefully|hard)", r"controleer (nogmaals|dubbel)", r"double[- ]check",
         r"begin je antwoord met", r"start your answer with", r"!!!"]
A7_CS = r"\b(BELANGRIJK|MOET|NOOIT|ALTIJD|CRITICAL|MUST|NEVER|ALWAYS|IMPORTANT)\b"
QWORD = re.compile(r"(?i)\b(of|whether|if|wanneer|when|hoe|how|wat|what)\b")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
CLAUSE_END = re.compile(r"(?<=[.!?:;])\s+|\n+")
# a clause ends in '?' when only closing markup follows it: a closing tag, quote, bracket, * _ or backtick
QEND = re.compile(r"\?(?:</\w+>|[\s*_`\"'»”’)\]}>])*$")
CHECKS = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"]


def fences(text):
    return FENCE.findall(text)


def outside(text):
    return FENCE.sub(" ", text)


def lang_of(text):
    words = re.findall(r"[a-zA-Zëéèïö']+", text.lower())
    nl, en = sum(w in NL for w in words), sum(w in EN for w in words)
    if nl + en < 3:
        return None
    return "nl" if nl >= en else "en"


def matches(pattern, text):
    return re.search(pattern, text) is not None


def _parts(end, text):
    return [s.strip() for s in end.split(text) if s.strip()]


def sentences(text):
    """De zinnen van text: geknipt op . ! ? gevolgd door witruimte, en op regeleinden. Voor de D04-markering en CHANNEL_CONTEXT."""
    return _parts(SENTENCE_END, text)


def clauses(text):
    """Als sentences(), maar ook geknipt op : en ; gevolgd door witruimte. Alleen voor statement_hits(): in de
    D04-markering zou die knip onderwerp en invulplek scheiden ("Webhook: [FILL IN: …]")."""
    return _parts(CLAUSE_END, text)


def statement_hits(patterns, text):
    """De patronen met een treffer in een bewering: in een zinsdeel uit clauses() dat niet op '?' eindigt, en helemaal
    vóór het eerste QWORD van dat zinsdeel (er wordt alleen gezocht in s[:start van dat QWORD]). forbid_statement telt alleen zo.
    Een zinsdeel dat op '?' eindigt, eventueel gevolgd door sluitende opmaak (een sluittag, aanhalingsteken, haakje,
    * _ of backtick), telt niet als bewering."""
    heads = []
    for s in clauses(text):
        if not QEND.search(s):
            q = QWORD.search(s)
            heads.append(s[:q.start()] if q else s)
    return [p for p in patterns if any(matches(p, h) for h in heads)]


def score_conversation(case, turns):
    """turns: model contents in order. Returns dict check -> 'pass'|'fail'|'flag'|'n.v.t.' plus notes.
    A case with variant 'docs' gets D5 (the A5 rule, after A8) and its A5 is then n.v.t."""
    res, notes = {}, []
    first_final = next((i for i, t in enumerate(turns) if fences(t)), None)
    q_turns = turns[:first_final] if first_final is not None else turns
    final = turns[first_final] if first_final is not None else None
    later = turns[first_final + 1:] if first_final is not None else []

    out_text = " ".join(outside(t) for t in turns)
    res["A1"] = "pass" if lang_of(out_text) == case["lang"] else "fail"

    bad_q = [t for t in q_turns if len(NUMBERED.findall(t)) > 4 or
             any("[" not in line for line in t.splitlines() if NUMBERED.match(line))]
    res["A2"] = "fail" if bad_q else "pass"

    if first_final is None:
        res["A3"] = "fail"
    elif case.get("expect_direct"):
        res["A3"] = "pass" if first_final == 0 else "fail"
    else:
        res["A3"] = "pass" if first_final <= 3 else "fail"

    if final is None:
        res["A4"] = "fail"
    else:
        after = final.split("```")[-1]
        bullets = len(re.findall(r"^\s*[-*•]\s", after, re.M))
        ok = len(fences(final)) == 1 and bullets <= 5 and EFFORT.search(outside(final))
        res["A4"] = "pass" if ok else "fail"

    docs = case.get("variant") == "docs"
    if case.get("forbid_regex") or case.get("outside_fence_forbid") or case.get("forbid_statement"):
        all_text = "\n".join(turns)
        hits = [p for p in case.get("forbid_regex", []) if matches(p, all_text)]
        hits += [p for p in case.get("outside_fence_forbid", []) if matches(p, out_text)]
        hits += statement_hits(case.get("forbid_statement", []), all_text)
        restraint = "flag" if hits else "pass"
        if hits:
            notes.append(("D5" if docs else "A5") + " treffer: " + ", ".join(hits))
    else:
        restraint = "n.v.t."
    res["A5"] = "n.v.t." if docs else restraint   # a docs case reports this rule as D5 instead (set after A8)

    if final is None:
        res["A6"] = "fail"
    else:
        body = fences(final)[-1]
        miss = [p for p in case.get("must_include", []) if not matches(p if p.startswith("(?") else re.escape(p), body)]
        if case.get("revision") and later and fences(later[-1]):
            rbody = fences(later[-1])[-1]
            miss += [p for p in case.get("must_include_revision", []) if p not in rbody]
            miss += [f"niet: {p}" for p in case.get("must_not_include_revision", []) if p in rbody]
        elif case.get("revision"):
            miss += ["geen revisie-fence"]
        res["A6"] = "fail" if miss else "pass"
        if miss:
            notes.append("A6 mist: " + ", ".join(miss))

    prompt_text = "\n".join(b for t in turns for b in fences(t))
    a7 = [p for p in A7_CI if re.search(p, prompt_text, re.I)]
    a7 += re.findall(A7_CS, prompt_text)
    res["A7"] = "fail" if a7 or final is None else "pass"
    if a7:
        notes.append("A7: " + ", ".join(sorted(set(a7))))

    if case.get("revision"):
        ok = (final is not None and later and fences(later[-1]) and
              len(fences(later[-1])[-1]) >= 0.5 * len(fences(final)[-1]))
        res["A8"] = "pass" if ok else "fail"
    else:
        res["A8"] = "n.v.t."
    if docs:
        res["D5"] = restraint
    return res, notes


def load_run(rundir):
    rows = [json.loads(l) for l in (Path(rundir) / "raw.jsonl").read_text().splitlines() if l.strip()]
    convs = {}
    for r in rows:
        k = (r["model"], r["case"], r["seed"])
        c = convs.setdefault(k, {"blind_id": r["blind_id"], "turns": [], "rows": [], "status": None,
                                 "wall_s": None, "ps_before": r.get("ps_before"), "tei_on": r.get("tei_on")})
        if r.get("turn") == "end":
            c["status"], c["wall_s"] = r["status"], r["conversation_wall_s"]
        elif "content" in r:
            c["turns"].append(r["content"])
            c["rows"].append(r)
    return convs


def main(rundir):
    cases = {c["id"]: c for c in (json.loads(l) for l in (HERE / "cases.jsonl").read_text().splitlines() if l.strip())}
    convs = load_run(rundir)
    out = []
    for (model, cid, seed), c in sorted(convs.items()):
        res, notes = score_conversation(cases[cid], c["turns"])
        out.append({"model": model, "case": cid, "seed": seed, "blind_id": c["blind_id"], **res,
                    "status": c["status"], "turns": len(c["turns"]), "wall_s": c["wall_s"],
                    "eval_tokens": sum(r.get("eval_count") or 0 for r in c["rows"]),
                    "max_prompt_tokens": max([r.get("prompt_eval_count") or 0 for r in c["rows"]] or [0]),
                    "other_model_loaded": any(p != model for p in (c["ps_before"] or [])),
                    "notes": "; ".join(notes)})
    with open(Path(rundir) / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print("| Model | " + " | ".join(CHECKS) + " | A5-vlaggen | mediaan s/gesprek | max s | tokens/gesprek |")
    print("|---|" + "---|" * (len(CHECKS) + 4))
    for model in sorted({r["model"] for r in out}):
        rs = [r for r in out if r["model"] == model]
        cells = []
        for ch in CHECKS:
            app = [r[ch] for r in rs if r[ch] != "n.v.t."]
            cells.append(f"{sum(v == 'pass' for v in app)}/{len(app)}")
        walls = [r["wall_s"] for r in rs if r["wall_s"] is not None]
        flags = sum(r["A5"] == "flag" for r in rs)
        print(f"| {model} | " + " | ".join(cells) +
              f" | {flags} | {statistics.median(walls):.0f} | {max(walls):.0f} | "
              f"{statistics.median(r['eval_tokens'] for r in rs):.0f} |")


if __name__ == "__main__":
    main(sys.argv[1])
