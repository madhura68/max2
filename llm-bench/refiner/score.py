#!/usr/bin/env python3
"""Score a refiner run directory with the automatic checks A1-A8 (PBI-8, T-3).

  ./score.py results/refiner-<stamp>          # writes summary.csv, prints a markdown table

A1 language, A2 question form, A3 rounds, A4 final shape, A5 restraint (a flag, disqualifying
only after JP confirms it), A6 fidelity, A7 Opus prompt rules, A8 revision. See PLANS/refiner-eval.
The checks are heuristics: A1 detects which language, not how fluent; A5/A6 match patterns.
A forbid_statement pattern counts only in a statement (statement_hits). For a docs case (variant
"docs") the same A5 rule is reported as D5 and its A5 is n.v.t.; such a case also gets D1 (the docs were
consulted in turn 1), D2 (the docs' facts are in the last prompt), D3 (nothing invented: paths, doc references
and, for a fact the docs lack, a channel), D4 (no needless question) and D6 (every harness turn completed).
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
# clauses() cuts after . ! ? : ; and the closing markup that follows it (as in QEND), before the whitespace
CLAUSE_CUT = re.compile(r"([.!?:;](?:</\w+>|[*_`\"'»”’)\]}>])*)\s+")
LINE_END = re.compile(r"\n+")
# a clause ends in '?' when only closing markup follows it: a closing tag, quote, bracket, * _ or backtick
QEND = re.compile(r"\?(?:</\w+>|[\s*_`\"'»”’)\]}>])*$")
CHECKS = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"]
# the doc-checks D1-D6 (docs cases): the tools that read the docs, what D3 takes for a path or a doc reference, and for
# D04 (a fact the docs lack) what counts as a channel name and as marking a fact unknown
DOC_TOOLS = ("search_product_docs", "get_product_doc", "list_product_docs", "related_product_docs")
PATH_ABS = re.compile(r"(?<![\w.:/~-])~?/[\w.~-]+(?:/[\w.~-]+)+")                              # /srv/x/y, ~/x/y
PATH_REL = re.compile(r"(?<![\w.:/~-])[a-z_.][\w.-]*(?:/[\w.-]+)+\.[A-Za-z]{1,6}(?![\w/-])")   # src/cli.ts, docs/x/y.md
# Amended tail (the brief had (?![\w/.-])): a full stop that closes the sentence ("Bron: specs/x.") no longer hides the
# reference; a full stop and a letter ("specs/x.md") is a file name and stays with PATH_REL
DOC_REF = re.compile(r"(?<![\w.:/~-])(?:adr|architecture|grills|patterns|plans|runbooks|specs|manual|api)"
                     r"/[a-z0-9][a-z0-9-]*(?![\w/-]|\.\w)")                                    # specs/<slug>
CHANNEL = re.compile(r"(?<![\w&])#(?![0-9a-f]{3}(?:[0-9a-f]{3})?\b)[a-z][a-z0-9_-]+")          # #harness-alerts, geen #e01e5a
CHANNEL_CONTEXT = re.compile(r"(?i)kanaal|channel|slack")                                    # een #naam telt alleen in zo'n zin
MARK = re.compile(r"(?i)onbekend|unknown|niet bekend|not known|ontbre|missing|nog in te vullen|to be provided"
                  r"|aanname|assumption|\[(FILL IN|INVULLEN)")
# the assumptions section of a final answer: its heading ("**Aannames:**", "B. Assumptions") and its bullets
ASSUMPTIONS_HEAD = re.compile(r"(?i)^\W*(?:[AB][.)]\s*)?\W*(aannames|assumptions)\b")
BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s")


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
    D04-markering zou die knip onderwerp en invulplek scheiden ("Webhook: [FILL IN: …]").
    Geknipt wordt ook als er tussen het leesteken en de witruimte alleen sluitende opmaak staat (een sluittag,
    aanhalingsteken, haakje, * _ of backtick); die opmaak blijft bij het zinsdeel ervoor."""
    return _parts(LINE_END, CLAUSE_CUT.sub(r"\1\n", text))


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


def last_prompt(turns):
    """De laatste prompt: het laatste codeblok over alle modelbeurten van het gesprek ('' zonder codeblok)."""
    blocks = [b for t in turns for b in fences(t)]
    return blocks[-1] if blocks else ""


def user_messages(case):
    """The user turns run.py can send for this case: the input, the scripted replies, the pressure reply, the revision
    and the go-ahead line converse() falls back on when the replies run out. A path or channel name that one of them
    holds is the user's own, so D3 does not call it invented."""
    go = "Fine, write the prompt now." if case.get("lang") == "en" else "Akkoord, schrijf nu de prompt."
    sent = [case.get("input"), *(case.get("replies") or []), case.get("pressure_reply"), case.get("revision"), go]
    return [m for m in sent if m]


def first_fence(turns):
    """The index of the first model turn with a code block (None when no turn has one)."""
    return next((i for i, t in enumerate(turns) if fences(t)), None)


def question_turns(turns):
    """The model turns before the first one with a code block (all of them when none has one): the turns in which
    the model still asks."""
    first = first_fence(turns)
    return turns if first is None else turns[:first]


def question_lines(turns):
    """The question lines of turns: lines with a '?' and lines that start with a number (NUMBERED)."""
    return [ln for t in turns for ln in t.splitlines() if "?" in ln or NUMBERED.match(ln)]


def path_hits(text):
    """The path-like strings in text, each once: the matches of PATH_ABS, PATH_REL and DOC_REF, in that order, without
    one trailing '.', ',', ';' or ':' (a PATH_ABS match can end in the full stop of the sentence) and without a
    leading './' (./src/cli.ts is src/cli.ts written differently)."""
    hits = []
    for pattern in (PATH_ABS, PATH_REL, DOC_REF):
        for m in pattern.finditer(text):
            hit = m.group(0)
            hit = hit[:-1] if hit[-1] in ".,;:" else hit
            hit = hit[2:] if hit.startswith("./") else hit
            if hit not in hits:
                hits.append(hit)
    return hits


def occurs(hit, text):
    """Whether hit occurs in text as a whole: what follows it may not go on with the same name (a word character, a
    hyphen, or a full stop and a word character), so a truncated path or slug does not occur where the full one does.
    Only the right edge is checked: a relative path is legitimately the end of a longer one, and a directory (followed
    by a slash) occurs in the paths below it."""
    return re.search(re.escape(hit) + r"(?![\w-]|\.\w)", text) is not None


def listed(hit, refs):
    """Whether hit names a document that docset.json lists (refs is its 'folder/slug' set): the reference itself, or
    that reference written as a file name, folder/slug.md with or without the docs/ of the source repo. The docs spell
    manual/readme as README.md, so the text never holds manual/readme.md, while the addendum has the model cite
    folder/slug and models often add .md. Exact: one docs/, a lower-case .md, and a whole folder/slug."""
    name = hit[len("docs/"):] if hit.startswith("docs/") else hit
    return hit in refs or (name.endswith(".md") and name[:-len(".md")] in refs)


def assumption_bullets(text):
    """The bullets in the assumptions section(s) of text, outside the code block: the line that starts with
    "Aannames" or "Assumptions" (after markup or a letter like "B.") and the bullets directly under it, blank lines
    allowed. A heading alone proves nothing: the system prompt has the model write one in every final answer."""
    bullets, in_section = [], False
    for line in outside(text).splitlines():
        if ASSUMPTIONS_HEAD.match(line):
            in_section = True
        elif in_section and BULLET.match(line):
            bullets.append(line)
        elif in_section and line.strip():
            in_section = False
    return bullets


def channels(text):
    """The channel names (CHANNEL) in the sentences of text that also mention CHANNEL_CONTEXT."""
    return {m.group(0) for s in sentences(text) if CHANNEL_CONTEXT.search(s) for m in CHANNEL.finditer(s)}


def absent_topic(case, turns):
    """What the model did about a fact the docs lack (case doc_absent_topic, D04), as {'asked', 'marked', 'invented'}:
    asked: a question line before the first code block names the topic;
    marked: in the last turn, a sentence names the topic and holds a MARK, or an assumption bullet names it;
    invented: the doc_absent_forbid patterns that hit a model turn, then the channel names in the last prompt that no
    question line before the first code block and no user message holds. A channel written without '#' is not found."""
    topic = re.compile(case["doc_absent_topic"])
    lines = question_lines(question_turns(turns))
    last = turns[-1] if turns else ""
    asked = any(topic.search(ln) for ln in lines)
    marked = (any(topic.search(s) and MARK.search(s) for s in sentences(last))
              or any(topic.search(b) for b in assumption_bullets(last)))
    named = {m.group(0) for text in lines + user_messages(case) for m in CHANNEL.finditer(text)}
    invented = [p for p in case.get("doc_absent_forbid") or [] if any(matches(p, t) for t in turns)]
    invented += sorted(channels(last_prompt(turns)) - named)
    return {"asked": asked, "marked": marked, "invented": invented}


def load_docset(dirpath):
    """De bevroren docset voor D3: {'texts': [inhoud van elk bestand uit docset.json], 'refs': {'folder/slug', ...}}.
    Alleen wat docset.json noemt telt mee; de hashes controleert freeze_docset.py --check."""
    d = Path(dirpath)
    files = json.loads((d / "docset.json").read_text(encoding="utf-8"))["files"]
    return {"texts": [(d / f["folder"] / f"{f['slug']}.md").read_text(encoding="utf-8") for f in files],
            "refs": {f"{f['folder']}/{f['slug']}" for f in files}}


# D1-D6 for a docs case. Each returns (outcome, notes); D5 is the restraint rule score_conversation already evaluated.
def check_d1(rows):
    """D1: the row of turn 1 holds a successful call (ok true) to one of the DOC_TOOLS."""
    used = any(tc.get("ok") is True and tc.get("name") in DOC_TOOLS
               for r in rows if r.get("turn") == 1 for tc in r.get("tool_calls") or [])
    return ("pass", []) if used else ("fail", ["D1 geen geslaagde doc-toolaanroep in beurt 1"])


def check_d2(case, turns):
    """D2: every doc_must_include value is in the last prompt (a regex if it starts "(?", else literal, as in A6)."""
    wanted = case.get("doc_must_include") or []
    if not wanted:
        return "n.v.t.", []
    body = last_prompt(turns)
    miss = [p for p in wanted if not matches(p if p.startswith("(?") else re.escape(p), body)]
    return ("fail", ["D2 mist: " + ", ".join(miss)]) if miss else ("pass", [])


def check_d3(case, turns, docset):
    """D3: nothing invented. Each path-like string in the last prompt occurs (occurs(): a whole path or slug, not the
    start of a longer one) in the text of a docset file or in a user message, or names a document listed in
    docset.json (listed(): folder/slug, also written as folder/slug.md or docs/folder/slug.md). With doc_absent_topic
    (D04) the model must also have asked for or marked the missing fact, and invented nothing (absent_topic)."""
    known = docset["texts"] + user_messages(case)
    unknown = [h for h in path_hits(last_prompt(turns))
               if not listed(h, docset["refs"]) and not any(occurs(h, t) for t in known)]
    notes = ["D3 onbekend: " + ", ".join(unknown)] if unknown else []
    if case.get("doc_absent_topic"):
        found = absent_topic(case, turns)
        if not (found["asked"] or found["marked"]):
            notes.append("D3 niet gevraagd of gemarkeerd: " + case["doc_absent_topic"])
        if found["invented"]:
            notes.append("D3 verzonnen: " + ", ".join(found["invented"]))
    return ("fail" if notes else "pass"), notes


def check_d4(case, turns):
    """D4: no doc_forbid_ask pattern in a question line before the first code block."""
    forbid = case.get("doc_forbid_ask") or []
    if not forbid:
        return "n.v.t.", []
    lines = question_lines(question_turns(turns))
    hit = [p for p in forbid if any(matches(p, ln) for ln in lines)]
    return ("fail", ["D4 vraag: " + ", ".join(hit)]) if hit else ("pass", [])


def check_d6(rows):
    """D6: every turn row has the harness status 'completed'. Only rows whose turn is a number count: the closing row
    (turn 'end') holds the status of the conversation, and the plan, probe and stop rows are no turn."""
    turn_rows = [r for r in rows if isinstance(r.get("turn"), int)]
    if not turn_rows:
        return "fail", ["D6 geen beurtrijen"]
    bad = [f"beurt {r['turn']} {r.get('status')}" for r in turn_rows if r.get("status") != "completed"]
    return ("fail", ["D6 status: " + ", ".join(bad)]) if bad else ("pass", [])


def score_conversation(case, turns, rows=None, docset=None):
    """turns: model contents in order. Returns dict check -> 'pass'|'fail'|'flag'|'n.v.t.' plus notes.
    A case with variant 'docs' also gets D1-D6 after A8 (D5 is the A5 rule, and its A5 is then n.v.t.); rows, the
    harness rows of the conversation, and docset, from load_docset(), are then required. A plain case ignores both."""
    docs = case.get("variant") == "docs"
    if docs and (rows is None or docset is None):
        raise ValueError(f"case {case.get('id')} is a docs case: score_conversation needs rows and docset")
    res, notes = {}, []
    first_final = first_fence(turns)
    q_turns = question_turns(turns)
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
        for check, (outcome, why) in (("D1", check_d1(rows)), ("D2", check_d2(case, turns)),
                                      ("D3", check_d3(case, turns, docset)), ("D4", check_d4(case, turns)),
                                      ("D5", (restraint, [])), ("D6", check_d6(rows))):
            res[check] = outcome
            notes += why
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
