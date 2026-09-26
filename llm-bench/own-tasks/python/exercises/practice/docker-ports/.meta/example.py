import re

_PUBLISHED = re.compile(r"^(?:\[[^\]]*\]|[^:\[\]]+):(\d+)(?:-(\d+))?->")


def published_ports(ps_output, prefix):
    result = {}
    for line in ps_output.splitlines():
        if not line.strip():
            continue
        name, _, ports = line.partition("\t")
        name = name.strip()
        if not name.startswith(prefix):
            continue
        found = set()
        for entry in ports.split(","):
            m = _PUBLISHED.match(entry.strip())
            if m:
                lo = int(m.group(1))
                hi = int(m.group(2)) if m.group(2) else lo
                found.update(range(lo, hi + 1))
        result[name] = sorted(found)
    return result
