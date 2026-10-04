# Alleen getalvelden van GET /api/v1/key; de sleutel komt uit os.environ en wordt nooit geprint.
import json, os, urllib.request
req = urllib.request.Request("https://openrouter.ai/api/v1/key",
                             headers={"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]})
d = json.load(urllib.request.urlopen(req, timeout=30))["data"]
print(json.dumps({k: d.get(k) for k in ("limit", "limit_remaining", "usage")}))
