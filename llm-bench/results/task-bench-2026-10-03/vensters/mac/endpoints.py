import json, sys
d = json.load(open(sys.argv[1]))["data"]
print("model:", d.get("id"), "endpoints:", len(d["endpoints"]))
for e in d["endpoints"]:
    sp = e.get("supported_parameters") or []
    p = e.get("pricing") or {}
    print("-", repr(e.get("provider_name")), "q=", e.get("quantization"), "tools=", "tools" in sp,
          "reasoning=", "reasoning" in sp, "status=", e.get("status"), "ctx=", e.get("context_length"),
          "in=", p.get("prompt"), "out=", p.get("completion"))
ok = [e.get("provider_name") for e in d["endpoints"]
      if e.get("quantization") in ("bf16", "fp16") and "tools" in (e.get("supported_parameters") or [])]
print("16-bit met tools:", ok)
sys.exit(0 if ok else 1)
