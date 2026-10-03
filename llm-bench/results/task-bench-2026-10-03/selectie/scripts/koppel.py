# Koppelt de kandidaten (kandidaten.jsonl, door=True) aan afgeronde Scrum4Me-taken via de COMMIT-logs van de story
# (spec §4.2: product Agent-harness voor agent-harness, product Scrum4Me voor scrum4me-mcp). Schrijft gekoppeld.jsonl.
import json, re

PRODUCT = {"agent-harness": "cmuhjw9e80003mt7rq4w3sauu", "scrum4me-mcp": "cmohrysyj0000rd17clnjy4tc"}
cands = [json.loads(l) for l in open("kandidaten.jsonl") if l.strip()]
cands = [c for c in cands if c["door"]]
logs = json.load(open("commit-logs.json"))
tasks = json.load(open("tasks.json"))
by_story = {}
for t in tasks:
    by_story.setdefault(t["story_id"], []).append(t)
by_id = {t["id"]: t for t in tasks}
COMMIT_LINE = re.compile(r"[Cc]ommit[^`\n]*`([^`\n]+)`")


def norm(s):
    return re.sub(r"\s+", " ", s.strip().lower())


out, stats = [], {}
for c in cands:
    st = stats.setdefault(c["repo"], {"kandidaten": 0, "met_log": 0, "gekoppeld_done": 0, "dubbelzinnig": 0, "niet_done": 0})
    st["kandidaten"] += 1
    hits = [l for l in logs if l["commit_hash"] and len(l["commit_hash"]) >= 7 and c["ref"].startswith(l["commit_hash"].lower())
            and l["product_id"] == PRODUCT[c["repo"]]]
    if not hits:
        continue
    st["met_log"] += 1
    found, how = {}, {}
    for l in hits:
        story_tasks = by_story.get(l["story_id"], [])
        tid = (l.get("metadata") or {}).get("task_id") if isinstance(l.get("metadata"), dict) else None
        if tid and tid in by_id:
            found[tid] = by_id[tid]; how[tid] = "metadata.task_id"; continue
        codes = set(re.findall(r"\bT-\d+\b", (l.get("commit_message") or "") + " " + c["subject"]))
        m = [t for t in story_tasks if t["code"] in codes]
        if len(m) == 1:
            found[m[0]["id"]] = m[0]; how[m[0]["id"]] = "taakcode"; continue
        m = [t for t in story_tasks if any(norm(x) == norm(c["subject"]) for x in COMMIT_LINE.findall(t.get("implementation_plan") or ""))]
        if len(m) == 1:
            found[m[0]["id"]] = m[0]; how[m[0]["id"]] = "commitregel-plan"; continue
        if len(story_tasks) == 1:
            found[story_tasks[0]["id"]] = story_tasks[0]; how[story_tasks[0]["id"]] = "enige-taak"; continue
        for t in story_tasks:
            found.setdefault("?" + t["id"], t)
    sure = {k: v for k, v in found.items() if not k.startswith("?")}
    row = dict(c)
    if len(sure) == 1:
        (tid, t), = sure.items()
        row.update(task_id=tid, task_code=t["code"], task_title=t["title"], task_status=t["status"], sprint_id=t["sprint_id"],
                   story_id=t["story_id"], story_code=t["story_code"], koppeling=how[tid])
        if t["status"] == "DONE":
            st["gekoppeld_done"] += 1
        else:
            st["niet_done"] += 1
    else:
        st["dubbelzinnig"] += 1
        row.update(task_id=None, opties=[{"id": t["id"], "code": t["code"], "title": t["title"], "status": t["status"]} for t in found.values()][:12])
    out.append(row)

with open("gekoppeld.jsonl", "w") as f:
    for r in out:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(json.dumps(stats, indent=1))
for r in out:
    if r.get("task_id") and r["task_status"] == "DONE":
        print(r["repo"][:5], r["ref"][:8], r["lines"], r["klasse"], r["task_code"], r["koppeling"], "|", r["subject"][:70], "| tests:", len(r["hidden"]), "| buiten:", r["outside"][:3])
print("--- dubbelzinnig:")
for r in out:
    if not r.get("task_id"):
        print(r["repo"][:5], r["ref"][:8], r["lines"], r["subject"][:60], "| opties:", [(o["code"], o["status"]) for o in r["opties"]][:6])
