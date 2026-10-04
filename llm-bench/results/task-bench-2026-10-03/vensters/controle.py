# Controle op de Mac na de kopie (plan Taak 6). Gebruik: python3 controle.py <M>
import glob, json, os, sys
from collections import Counter
M = sys.argv[1]; problems = []
cc = glob.glob(f"{M}/proef-check/AH-01-check-*/case-check.json")
ok = len(cc) == 1 and json.load(open(cc[0])).get("ok") is True
print("case-check ok:", ok); ok or problems.append("case-check")
ep = json.load(open(f"{M}/endpoints-proef.json"))["data"]["endpoints"]
sixteen = {e["provider_name"] for e in ep if e.get("quantization") in ("bf16", "fp16")}
br = glob.glob(f"{M}/proef/*/bench-result.json")
print("bench-result.json:", br)
if len(br) != 1:
    problems.append("bench-result"); print("PROBLEMEN:", problems); sys.exit(1)
b = json.load(open(br[0])); d = os.path.dirname(br[0])
u = b["usage"]
print("status:", b["status"], "| runStatus:", b["runStatus"], "| error:", (b.get("error") or {}).get("code"), "| benchError:", b.get("benchError"))
print("gate reds:", b["gate"]["reds"], "| patchBytes:", b["patchBytes"], "| duur:", round(b["durationMs"] / 60000, 1), "min")
print("hidden:", json.dumps(b.get("hidden"), ensure_ascii=False))
print("usage:", json.dumps(u))
print("providers:", dict(Counter(b["providers"])), "| allemaal 16-bit:", set(b["providers"]) <= sixteen, "| 16-bit-lijst:", sorted(sixteen))
print("retries:", len(b["retries"]), json.dumps(b["retries"]))
print("hidden-vitest.json:", os.path.exists(f"{d}/hidden-vitest.json"), "| patch.diff:", os.path.exists(f"{d}/patch.diff"))
if not b["providers"]: problems.append("geen providers")
if not set(b["providers"]) <= sixteen: problems.append("aanbieder buiten 16-bit")
crit2 = b["runStatus"] == "completed" and b["patchBytes"] > 0 and os.path.exists(f"{d}/hidden-vitest.json") and b["status"] in ("geslaagd", "verborgen_tests_rood")
print("criterium 2 (verborgen toets op het modelpad):", crit2)
crit2 or problems.append("criterium 2")
if (u.get("costUsd") or 0) > 1.0: problems.append("run > $1,00: stop voor JP")
print("PROBLEMEN:" if problems else "controle: geen problemen", problems if problems else "")
sys.exit(1 if problems else 0)
