# Bouwt per kandidaat de case met de exacte taaktekst (s4m-case.mjs → MCP get_sprint_context). Schrijft cases-kandidaten.jsonl.
import json, subprocess, sys
PROEF = "/private/tmp/claude-501/-Users-janpetervisser-Development-Scrum4Me--claude-worktrees-heuristic-ishizaka-8d42c7/f774c898-2ed2-4aa4-aa08-b8148524ade3/scratchpad/m7-proef/s4m-case.mjs"
PRODUCT = {"agent-harness": "cmuhjw9e80003mt7rq4w3sauu", "scrum4me-mcp": "cmohrysyj0000rd17clnjy4tc"}
KEUZE = [  # (repo, ref-prefix, taakcode) — AH-01 = T-34 zoals in de proef
    ("agent-harness", "64829bce", "T-34"), ("agent-harness", "5dc01bd2", "T-33"), ("agent-harness", "9cc00776", "T-45"),
    ("agent-harness", "f6577078", "T-46"), ("agent-harness", "90d67ab1", "T-32"), ("agent-harness", "a4f8f0ed", "T-23"),
    ("agent-harness", "764f1c15", "T-64"), ("agent-harness", "fc2130cf", "T-8"), ("agent-harness", "6f0728b4", "T-5"),
    ("agent-harness", "4842e715", "T-3"), ("agent-harness", "e0dafc81", "T-75"), ("agent-harness", "17899f01", "T-50"),
    ("agent-harness", "dbf7b56a", "T-38"), ("agent-harness", "8c49599d", "T-37"), ("agent-harness", "e76265ee", "T-36"),
    ("agent-harness", "92dd44d3", "T-24"), ("agent-harness", "3f7ddb93", "T-13"), ("agent-harness", "fc6cf16f", "T-7"),
    ("agent-harness", "ac441850", "T-2"),
    ("scrum4me-mcp", "8bd76335", "T-1926"), ("scrum4me-mcp", "722429ff", "T-1751"), ("scrum4me-mcp", "e5fc3d1d", "T-1750"),
    ("scrum4me-mcp", "9b29680b", "T-1747"), ("scrum4me-mcp", "ff0448fe", "T-1805"), ("scrum4me-mcp", "d5b0b6a2", "T-1925"),
    ("scrum4me-mcp", "134c8e86", "T-1924"), ("scrum4me-mcp", "14790c33", "T-1752"), ("scrum4me-mcp", "57d88950", "T-1746"),
    ("scrum4me-mcp", "1126e790", "T-1745"), ("scrum4me-mcp", "4a29990c", "T-1555"), ("scrum4me-mcp", "c9819879", "T-1806"),
    ("scrum4me-mcp", "2264c1c4", "T-1749"), ("scrum4me-mcp", "cad78e5d", "T-1744"), ("scrum4me-mcp", "73561299", "T-1748"),
    ("scrum4me-mcp", "fb75bdf7", "T-1807"), ("scrum4me-mcp", "8be13d85", "T-1804"),
]
cands = {c["ref"][:8]: c for c in map(json.loads, open("kandidaten.jsonl")) if c["door"]}
tasks = {(t["product_id"], t["code"]): t for t in json.load(open("tasks-all.json"))}
n = {"agent-harness": 0, "scrum4me-mcp": 0}; pre = {"agent-harness": "AH", "scrum4me-mcp": "MC"}
with open("cases-kandidaten.jsonl", "w") as out:
    for repo, ref8, code in KEUZE:
        c = cands[ref8]; t = tasks[(PRODUCT[repo], code)]
        assert c["repo"] == repo and t["status"] == "DONE", (ref8, code)
        n[repo] += 1; cid = f"{pre[repo]}-{n[repo]:02d}"
        kind = "fix" if c["subject"].startswith("fix") else "feat"
        r = subprocess.run(["node", PROEF, t["sprint_id"], t["id"], cid, c["repo_url"], c["base"], c["ref"], ",".join(c["hidden"]), str(c["lines"]), kind],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            print(cid, code, "FOUT", r.stderr[-300:]); continue
        case = json.loads(r.stdout)
        out.write(json.dumps(case, ensure_ascii=False) + "\n"); out.flush()
        print(cid, code, c["ref"][:8], c["lines"], c["klasse"], kind, len(c["hidden"]), "tests")
