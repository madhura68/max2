# Voegt per kandidaat samen: case-check.json (uit de Mac-kopie), het C4/C5-oordeel (beoordeling-G*.md + eigen oordeel) en de case.
# Gebruik: python3 voorstel.py <M-selectiemap>   (bv. ~/Development/m7-runs/task-bench-2026-10-03/selectie)
import glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
M = sys.argv[1]
cases = {c["id"]: c for c in map(json.loads, open(os.path.join(HERE, "cases-kandidaten.jsonl")))}
oordeel = {}
for f in sorted(glob.glob(os.path.join(HERE, "beoordeling-G*.md"))):
    for block in re.split(r"(?m)^### ", open(f).read())[1:]:
        cid = block.split()[0]
        get = lambda k: (re.search(rf"(?m)^- {k}: (.*)$", block) or [None, ""])[1].strip()
        oordeel[cid] = {"C4": get("C4"), "C5": get("C5"), "opm": get("Opmerking")}
# eigen oordeel van de controller (niet door een beoordelaar gedaan)
oordeel["AH-01"] = {"C4": "ok — eerder getoetst (proef): tests volgen de Interfaces van de taak; onafhankelijke implementatie uit de taaktekst haalt 11/11",
                    "C5": "ok — plan geeft signaturen en regels, geen implementatie", "opm": "praktijkproef 2026-10-03: geslaagd"}
oordeel["MC-19"] = {"C4": "ok — tests eisen requiredCapability, de foutmelding en required_capability/runtime CLAUDE; alle drie letterlijk in het plan",
                    "C5": "ok — plan in proza met exacte waarden, geen codeblok", "opm": "product Agent-harness (M3), niet Scrum4Me"}
oordeel["MC-18"] = {"C4": "ok — tests eisen de SQL-fragmenten en predicaatuitkomsten die het plan vastlegt",
                    "C5": "nee — alle coderegels van de src-wijziging staan letterlijk in het contractblok (zelfde maat als MC-20)", "opm": "product Agent-harness (M3)"}

def klasse(n):
    return "klein" if 20 <= n <= 80 else "middel" if n <= 200 else "groot" if n <= 400 else "buiten"

rows = []
for cid in [l.strip() for l in open(os.path.join(HERE, "lijst-alle.txt")) if l.strip()]:
    c = cases[cid]
    found = glob.glob(os.path.join(M, cid, f"{cid}-check-*", "case-check.json"))
    chk = json.load(open(found[0])) if len(found) == 1 else None
    lines = chk["lines"] if chk else c["lines"]
    rows.append({
        "id": cid, "repo": "agent-harness" if cid.startswith("AH") else "scrum4me-mcp", "taak": c["task"]["code"],
        "ref": c["ref_commit"][:8], "regels": lines, "klasse": klasse(lines), "soort": c["kind"], "tests": c["hidden_tests"],
        "ok": chk["ok"] if chk else None, "base_groen": chk and chk["baseVerifyGreen"],
        "op_base": chk and chk["hiddenOnBase"]["reason"], "op_ref": chk and chk["hiddenOnRef"]["reason"],
        "problemen": chk["problems"] if chk else ["geen case-check.json"], **oordeel.get(cid, {}),
    })
json.dump(rows, open(os.path.join(HERE, "voorstel.json"), "w"), ensure_ascii=False, indent=1)
for r in rows:
    print(f'{r["id"]} {r["taak"]:7} {r["ref"]} {r["regels"]:4} {r["klasse"]:6} {r["soort"]:4} check={r["ok"]} | base: {r["op_base"]} | ref: {r["op_ref"]} | {r["problemen"]}')
