# Controle op de Mac na de kopie van een gehost venster (plan Taak 9). Gebruik: python3 controle-gehost.py <M>
# Leest alleen bench-result.json per run (nooit ws*/), de endpointlijsten, de probes en het grootboek.
import glob, json, math, os, sys
from collections import Counter
M = sys.argv[1]; G = os.path.join(M, "gehost"); LABEL = "qwen3.8-openrouter"; problems = []
sixteen = set()
for f in sorted(glob.glob(os.path.join(G, "endpoints-*.json"))):
    eps = json.load(open(f))["data"]["endpoints"]
    sixteen |= {e["provider_name"] for e in eps if e.get("quantization") in ("bf16", "fp16")}
print("16-bit-aanbieders in de endpointlijsten:", sorted(sixteen))
runs = []
for f in glob.glob(os.path.join(G, LABEL, "*", "bench-result.json")):
    b = json.load(open(f)); b["_mtime"] = os.stat(f).st_mtime; runs.append(b)
runs.sort(key=lambda b: b["_mtime"])
print(f"{'run':38} {'status':22} {'beurten':>7} {'tools':>5} {'fout':>4} {'min':>5} {'kosten':>9} herh aanbieders")
for b in runs:
    u = b["usage"]; prov = Counter(b["providers"])
    print(f"{b['runId']:38} {b['status']:22} {u.get('turns', 0):7} {u.get('toolCalls', 0):5} {u.get('toolErrors', 0):4} "
          f"{b['durationMs'] / 60000:5.1f} {u.get('costUsd') or 0:9.5f} {len(b['retries']):4} {dict(prov)}"
          + (f"  [{b.get('benchError') or (b.get('error') or {}).get('code')}]" if b["status"] == "benchfout" or b.get("error") else ""))
    if not set(b["providers"]) <= sixteen:
        problems.append(f"{b['runId']}: aanbieder buiten 16-bit: {sorted(set(b['providers']) - sixteen)}")
    if not b["providers"] and b["runStatus"] != "not_run":
        problems.append(f"{b['runId']}: geen aanbieder")
last = {}
for b in runs:
    last[b["caseId"]] = b["status"]
print("laatste status per case:", dict(sorted(last.items())))
print("tellingen:", dict(Counter(last.values())))
rows = [json.loads(l) for l in open(os.path.join(M, "ledger.jsonl")) if l.strip()]
tot = math.fsum(r["cost_usd"] or 0 for r in rows)
print(f"grootboek: {len(rows)} regels, totaal ${tot:.6f}, null-bedragen: {sum(1 for r in rows if r['cost_usd'] is None)}")
print("PROBLEMEN:" if problems else "controle: geen problemen", problems if problems else "")
sys.exit(1 if problems else 0)
