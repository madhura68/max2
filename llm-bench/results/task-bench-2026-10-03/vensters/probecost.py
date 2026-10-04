# Som van usage.costUsd in probe.json (plan Taak 6): steps.<stap>.raw.usage.costUsd, voor c_two_tools raw.turn1/turn2.
import json, sys
p = json.load(open(sys.argv[1]))
total, seen, provs = 0.0, 0, []
def take(raw):
    global total, seen
    if not isinstance(raw, dict): return
    u = raw.get("usage") or {}
    if isinstance(u.get("costUsd"), (int, float)):
        total += u["costUsd"]; seen += 1
    if raw.get("provider"): provs.append(raw["provider"])
for name, step in (p.get("steps") or {}).items():
    raw = step.get("raw")
    if isinstance(raw, dict) and ("turn1" in raw or "turn2" in raw):
        take(raw.get("turn1")); take(raw.get("turn2"))
    else:
        take(raw)
print(json.dumps({"tool_calling": p.get("tool_calling"), "cost_sum": round(total, 8) if seen else None, "amounts": seen, "providers": provs}))
