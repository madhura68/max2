#!/usr/bin/env python3
"""Score a refiner run directory with the automatic checks A1-A8 (PBI-8, T-3).

  ./score.py results/refiner-<stamp> [--docset <dir>]   # writes summary.csv, prints a markdown table per variant

A1 language, A2 question form, A3 rounds, A4 final shape, A5 restraint (a flag, disqualifying
only after JP confirms it), A6 fidelity, A7 Opus prompt rules, A8 revision. See PLANS/refiner-eval.
The checks are heuristics: A1 detects which language, not how fluent; A5/A6 match patterns.
A forbid_statement pattern counts only in a statement (statement_hits). For a docs case (variant
"docs") the same A5 rule is reported as D5 and its A5 is n.v.t.; such a case also gets D1 (the docs were
consulted in turn 1), D2 (the docs' facts are in the last prompt), D3 (nothing invented: paths, doc references
and, for a fact the docs lack, a channel), D4 (no needless question) and D6 (every harness turn completed).

A run of the backend harness has rows with a `poging`: per conversation the highest poging counts. Its summary.csv has
the columns of HARNESS_COLUMNS after the plain ones; a run of the backend ollama keeps exactly COLUMNS. Tokens, model
turns and tool calls are those of the attempt that counts; cost_usd is the spend over all attempts (a discarded first
attempt was billed too), and empty when no turn row names a cost. The output lists, per conversation with a second
attempt or without an end, the status, failed turn, error code and cost of each attempt, and the stops of the run once.
Per model and variant sieve() applies the provisional cut-off of spec 5.8 (90% of the conversations end with a prompt,
no A5 or D5 flag, every other check in 80% of the conversations it applies to). The denominator of the first rule is
the plan row of the model (load_meta), so a conversation that never ran counts as not finished. The docset that D3
reads is the frozen one next to this file unless --docset names another; it is read only when a run has a docs case.
"""
import argparse
import csv
import json
import re
import statistics
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
DOC_CHECKS = ["D1", "D2", "D3", "D4", "D5", "D6"]
# summary.csv: a run of the backend ollama has exactly COLUMNS; a run of the backend harness has HARNESS_COLUMNS after them
COLUMNS = ["model", "case", "seed", "blind_id", *CHECKS, "status", "turns", "wall_s", "eval_tokens", "max_prompt_tokens",
           "other_model_loaded", "notes"]
HARNESS_COLUMNS = ["variant", "poging", "first_attempt_status", *DOC_CHECKS, "model_turns", "tool_calls", "input_tokens",
                   "output_tokens", "reasoning_tokens", "cost_usd", "providers"]
# the sieve (spec 5.8), provisional: the percentage of the conversations that must end with a prompt, the percentage of
# the conversations a check applies to that it must pass, and the conversations a check needs before it counts. A5 and
# D5 are the flag rule; D6 is shown but not counted (the spec lists A1-A4, A6-A8 and D1-D4, and D6 follows from "afgerond").
DONE_PERCENT, CHECK_PERCENT, MIN_CONVERSATIONS = 90, 80, 5
FLAG_CHECKS = ["A5", "D5"]
SIEVE_CHECKS = ["A1", "A2", "A3", "A4", "A6", "A7", "A8", "D1", "D2", "D3", "D4"]
META_KINDS = ("plan", "probe", "stop")      # the rows of a run that belong to a model and no conversation
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
    one trailing '.', ',', ';' or ':' (a PATH_ABS match can end in the full stop of the sentence), then without one
    trailing '/' (a directory written with a slash and closed by that full stop reads "dir/.": the hit is the directory,
    and "dir/" occurs in no text), and without a leading './' (./src/cli.ts is src/cli.ts written differently)."""
    hits = []
    for pattern in (PATH_ABS, PATH_REL, DOC_REF):
        for m in pattern.finditer(text):
            hit = m.group(0)
            hit = hit[:-1] if hit[-1] in ".,;:" else hit
            hit = hit[:-1] if hit.endswith("/") else hit
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


def read_rows(rundir):
    """De rijen van raw.jsonl in de run-map."""
    text = (Path(rundir) / "raw.jsonl").read_text(encoding="utf-8")
    # split on "\n" only: the rows are written with ensure_ascii=False, so U+2028, U+2029 and U+0085 stay raw inside a string,
    # and str.splitlines() would cut a row at each of them
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def end_status(rows):
    """De status van de sluitrij (turn 'end') in rows; None zonder sluitrij."""
    return next((r.get("status") for r in reversed(rows or []) if r.get("turn") == "end"), None)


def amount(rows, key):
    """De som van key over rows; een ontbrekend of leeg bedrag telt als nul."""
    return sum(r.get(key) or 0 for r in rows)


def attempt_facts(rows):
    """{'status', 'failed', 'cost_usd'} van één poging, uit zijn rijen. status: die van de sluitrij (None zonder).
    failed: (beurt, status, foutcode) van de eerste beurtrij waarvan de harness-status niet 'completed' is, of None; rijen
    zonder status, zoals die van de Ollama-backend, stranden niet. cost_usd: de som van het bedrag van de beurtrijen (een
    ontbrekend bedrag telt als nul); de sluitrij herhaalt die som en telt niet mee."""
    turn_rows = [r for r in rows if isinstance(r.get("turn"), int)]
    failed = next(((r["turn"], r["status"], r.get("error_code")) for r in turn_rows
                   if r.get("status") not in (None, "completed")), None)
    return {"status": end_status(rows), "failed": failed, "cost_usd": round(float(amount(turn_rows, "cost_usd")), 8)}


def load_run(rundir):
    """Zoals nu {(model, case, seed): gesprek}. Heeft een gesprek rijen met `poging`, dan telt de hoogste; het gesprek
    krijgt dan ook `poging` en `first_attempt_status`. Rijen zonder `case` horen bij geen gesprek.
    Een gesprek heeft blind_id, turns (elke tekst `content` van de beurtrijen), rows (elke rij met een geheel getal als
    `turn`, dus ook een mislukte beurt met content ''), status en wall_s (uit de sluitrij; None zonder), ps_before,
    tei_on en de backend en variant van de rijen (de eerste rij die ze noemt; None bij de rijen van de Ollama-backend van
    29 september). first_attempt_status is de status van de sluitrij van poging 1 (None als die ontbreekt).
    Wat de andere pogingen deden, staat in `attempts`: {poging: attempt_facts()} voor elke poging, ook een ongetelde
    (een poging van Ollama-rijen zonder `poging` is poging 1). `cost_reported`: of een beurtrij van een poging een bedrag
    noemt; zo niet, dan is de som van de kosten onbekend en niet nul (een lokaal model, en de sluitrij telt niet)."""
    attempts = {}      # (model, case, seed) -> {poging: rijen}
    for r in read_rows(rundir):
        if r.get("case") is None:
            continue
        attempts.setdefault((r["model"], r["case"], r["seed"]), {}).setdefault(r.get("poging", 1), []).append(r)
    convs = {}
    for k, by_poging in attempts.items():
        last = max(by_poging)
        first_row = by_poging[last][0]
        every_row = [r for n in sorted(by_poging) for r in by_poging[n]]
        c = convs[k] = {"blind_id": first_row["blind_id"], "turns": [], "rows": [], "status": None, "wall_s": None,
                        "ps_before": first_row.get("ps_before"), "tei_on": first_row.get("tei_on"),
                        "backend": next((r["backend"] for r in every_row if r.get("backend")), None),
                        "variant": next((r["variant"] for r in every_row if r.get("variant")), None),
                        "attempts": {n: attempt_facts(by_poging[n]) for n in sorted(by_poging)},
                        "cost_reported": any(r.get("cost_usd") is not None
                                             for r in every_row if isinstance(r.get("turn"), int))}
        for r in by_poging[last]:
            if r.get("turn") == "end":
                c["status"], c["wall_s"] = r.get("status"), r.get("conversation_wall_s")
            elif isinstance(r.get("turn"), int):
                c["rows"].append(r)
                if isinstance(r.get("content"), str):
                    c["turns"].append(r["content"])
        if any("poging" in r for rows in by_poging.values() for r in rows):
            c["poging"], c["first_attempt_status"] = last, end_status(by_poging.get(1))
    return convs


def load_meta(rundir):
    """{model: {'plan': rij of None, 'probe': rij of None, 'stop': rij of None}}, uit de rijen met turn 'plan', 'probe'
    en 'stop'. Een model zonder zulke rijen komt er niet in. Van twee rijen van dezelfde soort voor één model geldt de
    laatste. Twee plan- of proberijen van één model met een andere variant zijn een fout: een run-map heeft één variant
    (spec 5.7), en de noemer van de zeef hoort bij die ene variant."""
    meta = {}
    for r in read_rows(rundir):
        kind = r.get("turn")
        if kind not in META_KINDS:
            continue
        mine = meta.setdefault(r["model"], dict.fromkeys(META_KINDS))
        before = mine[kind]
        if before is not None and kind != "stop" and before.get("variant") != r.get("variant"):
            raise ValueError(f"raw.jsonl: {r['model']} heeft {kind}-rijen van twee varianten ({before.get('variant')} en "
                             f"{r.get('variant')}); een run-map heeft één variant")
        mine[kind] = r
    return meta


def meets(n, total, percent):
    """Of n van total minstens percent procent is; met hele getallen, zodat geen afronding beslist."""
    return n * 100 >= total * percent


def share(n, total):
    """n van total als percentage met één decimaal, voor in een reden."""
    return f"{100 * n / total:.1f}%"


def probe_reasons(probe):
    """De reden uit de proberij voor een model dat niet draaide: het label ('geen aanbieder', 'probe-fout <status>') of
    anders het oordeel, en daarna per reden van een probestap de stappen waarvoor die gold. Zonder proberij een
    algemene reden."""
    if not probe:
        return ["geen plan, geen gesprekken en geen proberij"]
    verdict = probe.get("verdict") or "onbekend"
    head = probe.get("label") or (f"probe-oordeel {verdict}" if verdict != "reliable" else "geen plan en geen gesprekken")
    steps = {}
    for step, reason in (probe.get("reasons") or {}).items():
        steps.setdefault(reason, []).append(step)
    return [head] + [f"{', '.join(names)}: {reason}" for reason, names in steps.items()]


def sieve(scored, planned=None, probe=None):
    """scored: de gescoorde gesprekken van één model en één variant, elk een dict zoals een rij van summary.csv (case,
    seed, blind_id, status = de eindstatus van het gesprek, eventueel first_attempt_status, en per check pass, fail,
    flag of n.v.t.); planned: de (case, seed)-paren uit de plan-rij; probe: de proberij.
    Geeft {'outcome': 'door' | 'gezakt' | 'niet gedraaid', 'completed': (n, totaal), 'first_attempt_completed': n,
    'flags': [blind_id, ...], 'checks': {naam: (geslaagd, van, telt_mee)}, 'reasons': [...]}.
    Zonder geplande en zonder aanwezige gesprekken is de uitkomst 'niet gedraaid', met de reden uit de proberij.
    Spec 5.8: minstens 90% van de gesprekken eindigt met een prompt (eindstatus 'final'). De noemer is het aantal
    geplande gesprekken, en een gepland gesprek zonder rijen telt als niet afgerond; zonder plan is het het aantal
    aanwezige gesprekken. Geen vlag op A5 of D5, hoeveel gesprekken ook. Elke check van SIEVE_CHECKS slaagt in minstens
    80% van de gesprekken waarvoor hij geldt en telt pas mee vanaf vijf gesprekken; D6 wordt getoond maar telt niet
    mee. 'telt_mee' van A5 en D5 is of zij voor minstens één gesprek gelden. 'reasons' is leeg bij 'door'; bij
    'gezakt' noemt het elke regel waarop het model zakte, en de statussen van de niet-afgeronde gesprekken. De checks
    en vlaggen tellen alle gescoorde gesprekken; het plan bepaalt alleen de noemer van de eerste regel."""
    if planned:
        by_key = {(c["case"], c["seed"]): c for c in scored}
        slots = [(tuple(p), by_key.get(tuple(p))) for p in planned]      # None: gepland, maar zonder rijen
    else:
        slots = [((c["case"], c["seed"]), c) for c in scored]
    if not slots:
        return {"outcome": "niet gedraaid", "completed": (0, 0), "first_attempt_completed": 0, "flags": [], "checks": {},
                "reasons": probe_reasons(probe)}

    def first_status(c):      # a run without poging has no first_attempt_status: its one attempt is the first
        return c["first_attempt_status"] if "first_attempt_status" in c else c.get("status")

    total = len(slots)
    done = sum(c is not None and c.get("status") == "final" for _, c in slots)
    first = sum(c is not None and first_status(c) == "final" for _, c in slots)
    not_done = {}
    for (case, seed), c in slots:
        if c is None or c.get("status") != "final":
            status = "ontbreekt" if c is None else (c.get("status") or "zonder eindrij")
            not_done.setdefault(status, []).append(f"{case}/{seed}")

    checks = {}
    for name in CHECKS + DOC_CHECKS:
        if any(name in c for c in scored):
            values = [v for v in (c.get(name) for c in scored) if v in ("pass", "fail", "flag")]
            counts = bool(values) if name in FLAG_CHECKS else name in SIEVE_CHECKS and len(values) >= MIN_CONVERSATIONS
            checks[name] = (values.count("pass"), len(values), counts)
    reasons = []
    if not meets(done, total, DONE_PERCENT):
        reasons.append(f"afgerond: {done} van {total} ({share(done, total)}), minder dan {DONE_PERCENT}%")
    for name in FLAG_CHECKS:
        flagged = [c["blind_id"] for c in scored if c.get(name) == "flag"]
        if flagged:
            reasons.append(f"vlag op {name}: {', '.join(flagged)}")
    for name in SIEVE_CHECKS:
        if name in checks:
            passed, of, counts = checks[name]
            if counts and not meets(passed, of, CHECK_PERCENT):
                reasons.append(f"{name}: {passed} van {of} ({share(passed, of)}), minder dan {CHECK_PERCENT}%")
    if reasons and not_done:
        reasons.append("niet afgerond: " + "; ".join(f"{status} {len(ids)}x ({', '.join(ids)})"
                                                    for status, ids in not_done.items()))
    return {"outcome": "gezakt" if reasons else "door", "completed": (done, total), "first_attempt_completed": first,
            "flags": [c["blind_id"] for c in scored if any(c.get(name) == "flag" for name in FLAG_CHECKS)],
            "checks": checks, "reasons": reasons}


def providers_of(rows):
    """De aanbieders die op de rijen staan, elk één keer, op alfabet."""
    return sorted({p for r in rows for p in r.get("providers") or []})


def summary_row(model, cid, seed, c, res, notes, harness):
    """De rij van summary.csv voor gesprek c, in een run van de backend harness of van de Ollama-backend. Dat is een
    eigenschap van de run en niet van het gesprek: de sluitrij van een gesprek noemt geen backend. De metingen van de
    Ollama-runner (eval_tokens, max_prompt_tokens, other_model_loaded) bestaan niet voor de backend harness en blijven
    daar leeg; de kolommen van HARNESS_COLUMNS zijn er alleen voor die backend. reasoning_tokens zijn een deel van
    output_tokens en worden er niet bij opgeteld. Tokens, model_turns en tool_calls zijn die van de poging die telt;
    cost_usd is wat het gesprek kostte over alle pogingen (een weggegooide eerste poging is ook betaald), en leeg als geen
    beurtrij een bedrag noemt: onbekend is niet gratis."""
    row = {"model": model, "case": cid, "seed": seed, "blind_id": c["blind_id"], **res, "status": c["status"],
           "turns": len(c["turns"]), "wall_s": c["wall_s"]}
    if not harness:
        row.update(eval_tokens=sum(r.get("eval_count") or 0 for r in c["rows"]),
                   max_prompt_tokens=max([r.get("prompt_eval_count") or 0 for r in c["rows"]] or [0]),
                   other_model_loaded=any(p != model for p in (c["ps_before"] or [])))
    row["notes"] = "; ".join(notes)
    if harness:
        rows = c["rows"]
        row.update(variant=c["variant"], poging=c.get("poging"), first_attempt_status=c.get("first_attempt_status"),
                   model_turns=amount(rows, "model_turns"),
                   tool_calls=sum(len(r.get("tool_calls") or []) for r in rows),
                   input_tokens=amount(rows, "input_tokens"), output_tokens=amount(rows, "output_tokens"),
                   reasoning_tokens=amount(rows, "reasoning_tokens"),
                   cost_usd=(round(float(sum(a["cost_usd"] for a in c["attempts"].values())), 8)
                             if c["cost_reported"] else None),
                   providers=", ".join(providers_of(rows)))
    return row


def score_run(rundir, docset_dir=None):
    """Scoort elk gesprek van de run. Geeft (records, meta, harness): per gesprek een dict met 'row' (de rij van
    summary.csv), 'turns', 'notes', 'backend', 'providers' en 'attempts' (van load_run); load_meta(rundir); en of de
    run van de backend harness is (een gesprek of een proberij met backend 'harness'). Een docs-case krijgt zijn rijen
    en de docset; die komt uit docset_dir (standaard de bevroren docset naast dit bestand) en wordt alleen gelezen als
    de run zo'n case heeft."""
    cases = {c["id"]: c for c in (json.loads(l) for l in (HERE / "cases.jsonl").read_text().splitlines() if l.strip())}
    convs, meta = load_run(rundir), load_meta(rundir)
    harness = (any(c["backend"] == "harness" for c in convs.values())
               or any((m["probe"] or {}).get("backend") == "harness" for m in meta.values()))
    docset, records = None, []
    for (model, cid, seed), c in sorted(convs.items()):
        if cases[cid].get("variant") == "docs":
            docset = docset or load_docset(docset_dir or HERE / "docset")
            res, notes = score_conversation(cases[cid], c["turns"], c["rows"], docset)
        else:
            res, notes = score_conversation(cases[cid], c["turns"])
        records.append({"row": summary_row(model, cid, seed, c, res, notes, harness), "turns": c["turns"],
                        "notes": notes, "backend": c["backend"] or ("harness" if harness else "ollama"),
                        "providers": providers_of(c["rows"]), "attempts": c["attempts"]})
    return records, meta, harness


def write_summary(rundir, records, harness):
    """summary.csv in de run-map, met een vaste kolomlijst; een rij zonder een kolom krijgt daar een lege cel."""
    with open(Path(rundir) / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=(COLUMNS + HARNESS_COLUMNS) if harness else COLUMNS, restval="")
        w.writeheader()
        w.writerows(rec["row"] for rec in records)


def variant_of(x):
    """De variant van een rij of een plan- of proberij. Zonder variant (de rijen van de Ollama-backend) is het nodocs:
    die rijen hebben geen doctools."""
    return x.get("variant") or "nodocs"


def check_cell(name, counts):
    """'geslaagd/van', '-' voor een check die voor geen gesprek geldt, en een * als een check van de 80%-regel wegens te
    weinig gesprekken niet meetelt."""
    passed, of, counted = counts
    if of == 0:
        return "-"
    return f"{passed}/{of}" + ("*" if not counted and name in SIEVE_CHECKS else "")


def quote(text):
    """text als markdown-citaat."""
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def table_row(model, recs, meta, variant, names, default_backend):
    """(cellen, uitkomst van sieve) van de rij van een model in de tabel van variant. recs: de gescoorde gesprekken van
    het model in die variant; het plan telt alleen als het van die variant is. Waar een model niets te tellen heeft
    (geen gesprekken, of niet gedraaid, of geen bedrag bekend), staat een streepje. De kosten zijn die van alle
    pogingen; de tokens die van de poging die telt."""
    rows = [rec["row"] for rec in recs]
    m = meta.get(model) or dict.fromkeys(META_KINDS)
    plan = m["plan"] if m["plan"] and variant_of(m["plan"]) == variant else None
    verdict = sieve(rows, plan["conversations"] if plan else None, m["probe"])
    ran = verdict["outcome"] != "niet gedraaid"
    backend = recs[0]["backend"] if recs else (m["probe"] or {}).get("backend") or default_backend
    is_harness = backend == "harness"
    walls = [r["wall_s"] for r in rows if r.get("wall_s") is not None]
    costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]      # the spend of all attempts, where known
    probe = (m["probe"].get("label") or m["probe"].get("verdict") or "-") if m["probe"] else "-"
    done, total = verdict["completed"]
    cells = [model, backend, probe]
    cells += [check_cell(n, verdict["checks"].get(n, (0, 0, False))) for n in names]
    cells += [f"{done}/{total}" if ran else "-",
              str(verdict["first_attempt_completed"]) if ran else "-",
              f"{statistics.median(walls):.0f}" if walls else "-",
              str(amount(rows, "input_tokens")) if rows and is_harness else "-",
              str(amount(rows, "output_tokens" if is_harness else "eval_tokens")) if rows else "-",
              f"{sum(costs):.4f}" if costs else "-",
              ", ".join(sorted({p for rec in recs for p in rec["providers"]})) or "-",
              verdict["outcome"]]
    return cells, verdict


def flag_blocks(model, recs):
    """Bij elke A5- of D5-vlag van de gesprekken van een model: een kop, het patroon dat aansloeg, het pad van het
    transcript en de beurten van het model."""
    lines = []
    for rec in recs:
        row = rec["row"]
        for name in FLAG_CHECKS:
            if row.get(name) != "flag":
                continue
            lines += ["", f"#### Vlag {name}: {row['blind_id']} ({model}, {row['case']}, seed {row['seed']})"]
            hit = next((n for n in rec["notes"] if n.startswith(f"{name} treffer: ")), None)
            if hit:
                lines.append("Patroon: " + hit[len(f"{name} treffer: "):])
            lines.append(f"Transcript: transcripts/{row['blind_id']}.md")
            for i, text in enumerate(rec["turns"], start=1):
                lines += ["", quote(f"Model, beurt {i}:\n\n{text}")]
    return lines


def attempt_lines(model, recs):
    """Een regel per gesprek van model dat een tweede poging kreeg of niet afrondde: per poging de status, de beurt
    waarop de harness-run stukliep (met zijn status en foutcode) en de kosten, die er alleen staan als een beurtrij ze
    noemt. Een gesprek met één poging krijgt geen 'poging 1' ervoor."""
    lines = []
    for rec in recs:
        row, attempts = rec["row"], rec["attempts"]
        if len(attempts) == 1 and row["status"] == "final":
            continue
        priced = row.get("cost_usd") is not None
        texts = []
        for n, a in attempts.items():
            detail = []
            if a["failed"]:
                turn, status, code = a["failed"]
                detail.append(f"beurt {turn} {status}" + (f", {code}" if code else ""))
            if priced:
                detail.append(f"${a['cost_usd']:.4f}")
            texts.append((f"poging {n} " if len(attempts) > 1 else "") + (a["status"] or "zonder eindrij")
                         + (f" ({', '.join(detail)})" if detail else ""))
        lines.append(f"- {model}: {row['case']}/{row['seed']} ({row['blind_id']}): " + " -> ".join(texts))
    return lines


def run_stops(meta):
    """{model: reden} van de stoprijen van de run. Een stop geldt voor de hele run en heeft geen variant."""
    return {model: m["stop"].get("reason") or "onbekend" for model, m in meta.items() if m["stop"]}


def render_variant(variant, models, meta, default_backend):
    """De tabel van één variant met daaronder de legenda, de redenen van de zeef, de gesprekken met een tweede poging of
    zonder eind, en de vlaggen. models: {model: [gescoorde gesprekken van dat model in deze variant]}. De stops staan
    niet hier maar eenmaal bovenaan de uitvoer (render_report); een run die stopte, verklaart wel de gesprekken die
    ontbreken."""
    docs = variant == "docs" or any("D1" in rec["row"] for recs in models.values() for rec in recs)
    names = CHECKS + (DOC_CHECKS if docs else [])
    header = ["Model", "Backend", "Probe", *names, "Afgerond", "Eerste poging", "Mediaan s", "Tokens in", "Tokens uit",
              "Kosten $ (alle pogingen)", "Aanbieders", "Zeef"]
    lines = [f"### Variant {variant}", "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    verdicts, starred, harness = {}, False, False
    for model in sorted(models):
        cells, verdicts[model] = table_row(model, models[model], meta, variant, names, default_backend)
        lines.append("| " + " | ".join(cells) + " |")
        starred = starred or any(c.endswith("*") for c in cells[3:3 + len(names)])     # the cells of the checks
        harness = harness or cells[1] == "harness"
    legend = []
    if starred:
        legend.append("* minder dan vijf gesprekken in de noemer: getoond, telt niet mee in de zeef.")
    if docs:
        legend.append("D6 telt niet mee in de zeef (spec 5.8): de eindstatus staat al in Afgerond.")
    if harness:
        legend.append("Tokens (en in summary.csv modelbeurten en toolaanroepen): van de poging die telt; "
                      "kosten: van alle pogingen.")
    if legend:
        lines += ["", *legend]
    stopped = ", ".join(sorted(set(run_stops(meta).values())))
    why = []
    for model, v in verdicts.items():
        if v["reasons"]:
            text = "; ".join(v["reasons"])
            if stopped:      # the conversations that are missing were not run because the run stopped
                text = re.sub(r"(ontbreekt \d+x \([^)]*\))", lambda m: f"{m.group(1)} (run gestopt: {stopped})", text)
            why.append(f"- {model} ({v['outcome']}): {text}")
    if why:
        lines += ["", "Zeef (voorlopig, spec 5.8):", *why]
    attempts = [line for model in sorted(models) for line in attempt_lines(model, models[model])]
    if attempts:
        lines += ["", "Pogingen en niet afgeronde gesprekken:", *attempts]
    for model in sorted(models):
        lines += flag_blocks(model, models[model])
    return "\n".join(lines)


def render_report(records, meta, harness):
    """De uitvoer van een run: bovenaan eenmaal de stops van de hele run (uit alle stoprijen, dus ook van een model dat
    verder niets heeft), dan per variant een markdown-tabel met per model de backend, het probe-oordeel, de tellingen per
    check, afgerond (en bij de eerste poging), de mediane tijd, tokens in en uit, de kosten van alle pogingen, aanbieders
    en de zeef-uitkomst, met daaronder de redenen van de zeef, de gesprekken met een tweede poging of zonder eind, en
    bij elke A5- of D5-vlag het patroon en het transcript. Een model dat alleen een plan- of proberij heeft, staat er ook
    in."""
    stops = [f"- {model}: {reason}" for model, reason in sorted(run_stops(meta).items())]
    parts = ["\n".join(["Gestopt:", *stops])] if stops else []
    groups = {}
    for rec in records:
        groups.setdefault(variant_of(rec["row"]), {}).setdefault(rec["row"]["model"], []).append(rec)
    for model, m in meta.items():
        for kind in ("plan", "probe"):
            if m[kind]:
                groups.setdefault(variant_of(m[kind]), {}).setdefault(model, [])
    if not groups:
        return "\n\n".join(["Geen gesprekken in deze run."] + parts)
    default_backend = "harness" if harness else "ollama"
    order = sorted(groups, key=lambda v: (v != "nodocs", v))
    return "\n\n".join(parts + [render_variant(v, groups[v], meta, default_backend) for v in order])


def main(rundir, docset_dir=None):
    records, meta, harness = score_run(rundir, docset_dir)
    write_summary(rundir, records, harness)
    print(render_report(records, meta, harness))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rundir", help="the run directory, e.g. results/refiner-<stamp>")
    ap.add_argument("--docset", help="the docset D3 reads (default: the frozen docset next to this file)")
    args = ap.parse_args()
    main(args.rundir, args.docset)
