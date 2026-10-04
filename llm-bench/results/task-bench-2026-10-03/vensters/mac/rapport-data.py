# M7 Taak 11: kopieert de bewaarde uitvoer naar llm-bench/results/task-bench-2026-10-03/ (per run bench-result.json, patch.diff,
# hidden-vitest.json en trace.jsonl; nooit ws*/, tools/ of containers/) en schrijft rapport-data.json met de cijfers per run.
# Gebruik: python3 rapport-data.py <M> <repo-resultatenmap>
import glob, json, os, shutil, sys
from collections import Counter

M, OUT = sys.argv[1], sys.argv[2]
RUNFILES = ("bench-result.json", "patch.diff", "hidden-vitest.json", "trace.jsonl")
LABELS = {"qwen3.8-openrouter": os.path.join(M, "gehost", "qwen3.8-openrouter"), "gsq-lokaal": os.path.join(M, "gsq", "gsq-lokaal"),
          "proef": os.path.join(M, "proef")}


def cp(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


runs = []
for label, root in LABELS.items():
    for rd in sorted(glob.glob(os.path.join(root, "*", ""))):
        rid = os.path.basename(os.path.dirname(rd))
        br = os.path.join(rd, "bench-result.json")
        if not os.path.isfile(br):
            continue
        for f in RUNFILES:
            if os.path.isfile(os.path.join(rd, f)):
                cp(os.path.join(rd, f), os.path.join(OUT, "runs", label, rid, f))
        b = json.load(open(br))
        failing = []
        hv = os.path.join(rd, "hidden-vitest.json")
        if os.path.isfile(hv):
            for tr in json.load(open(hv)).get("testResults", []):
                for a in tr.get("assertionResults", []):
                    if a.get("status") == "failed":
                        failing.append({"file": os.path.basename(tr.get("name", "")), "test": a.get("fullName"),
                                        "message": (a.get("failureMessages") or [""])[0].split("\n")[0][:240]})
        sub_edits = []
        for line in open(os.path.join(rd, "trace.jsonl")):
            e = json.loads(line)
            if e.get("type") == "tool_call" and e.get("name") in ("write_file", "edit_file"):
                try:
                    path = json.loads(e.get("arguments") or "{}").get("path", "")
                except ValueError:
                    path = ""
                if path.startswith("vendor/"):
                    sub_edits.append(path)
        u = b["usage"]
        runs.append({"label": label, "run": rid, "case": b["caseId"], "status": b["status"], "runStatus": b["runStatus"],
                     "error": (b.get("error") or {}).get("code"), "benchError": b.get("benchError"), "gateReds": b["gate"]["reds"],
                     "hidden": (b.get("hidden") or {}).get("reason"), "failing": failing, "turns": u.get("turns"),
                     "toolCalls": u.get("toolCalls"), "toolErrors": u.get("toolErrors"), "inputTokens": u.get("inputTokens"),
                     "outputTokens": u.get("outputTokens"), "reasoningTokens": u.get("reasoningTokens"), "costUsd": u.get("costUsd"),
                     "providers": dict(Counter(b["providers"])), "retries": b["retries"], "patchBytes": b["patchBytes"],
                     "minutes": round(b["durationMs"] / 60000, 1), "submoduleEdits": sorted(set(sub_edits))})

# vensterbestanden: grootboek, scores, endpointlijsten, probes, scripts, logs, sid's, dienststanden en configs
keep = ["ledger.jsonl", "summary.csv", "task-config.json", "case-AH-01.json", "cases-proef.jsonl", "model-qwen3.8-openrouter.json",
        "extra-body-qwen3.8-openrouter.json", "voorbereiding.txt", "endpoints-proef.json"]
patterns = ["*.sh", "*.log", "*.sid", "dienststand-*.txt", "sleutelstand-*.json", "*.py", "gsq-api-ps-na.json"]
n = 0
for name in keep + sorted({p for pat in patterns for p in map(os.path.basename, glob.glob(os.path.join(M, pat)))}):
    src = os.path.join(M, name)
    if os.path.isfile(src):
        cp(src, os.path.join(OUT, "vensters", name)); n += 1
for sub in ("gehost", "gsq"):
    for p in glob.glob(os.path.join(M, sub, "endpoints-*.json")) + glob.glob(os.path.join(M, sub, "model-*.json")) + \
            glob.glob(os.path.join(M, sub, "extra-body-*.json")):
        cp(p, os.path.join(OUT, "vensters", sub, os.path.basename(p))); n += 1
    for p in glob.glob(os.path.join(M, sub, "probes", "*", "*", "probe.json")):
        rel = os.path.relpath(p, os.path.join(M, sub)); cp(p, os.path.join(OUT, "vensters", sub, rel)); n += 1
for p in glob.glob(os.path.join(M, "probes", "*", "probe.json")):
    cp(p, os.path.join(OUT, "vensters", "proef", os.path.relpath(p, M))); n += 1
for p in glob.glob(os.path.join(M, "proef-check", "*", "case-check.json")):
    cp(p, os.path.join(OUT, "vensters", "proef", os.path.relpath(p, M))); n += 1
start_log = os.path.join(M, "scripts-mac", "start-gsq.log")
for p in [start_log] + glob.glob(os.path.join(M, "scripts-mac", "*.sh")) + glob.glob(os.path.join(M, "scripts-mac", "*.py")):
    if os.path.isfile(p):
        cp(p, os.path.join(OUT, "vensters", "mac", os.path.basename(p))); n += 1
json.dump(runs, open(os.path.join(OUT, "rapport-data.json"), "w"), ensure_ascii=False, indent=1)
print("runs:", len(runs), Counter(r["label"] for r in runs), "| vensterbestanden:", n)
for r in runs:
    print(r["label"][:5], r["case"], r["status"], r["turns"], r["toolErrors"], r["minutes"], r["costUsd"], r["error"], r["submoduleEdits"],
          [f["test"][:70] for f in r["failing"]])
