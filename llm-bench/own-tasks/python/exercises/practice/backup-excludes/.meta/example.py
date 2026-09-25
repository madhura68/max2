import re


def _component_regex(comp):
    out = []
    for ch in comp:
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def _compile(pattern):
    anchored = pattern.startswith("/")
    comps = pattern.strip("/").split("/")
    rx = ""
    for i, comp in enumerate(comps):
        last = i == len(comps) - 1
        if comp == "**":
            rx += ".*" if last else "(?:[^/]+/)*"
        else:
            rx += _component_regex(comp) + ("" if last else "/")
    # Paths are absolute, so an unanchored pattern starts right after some "/".
    return re.compile(("^/" if anchored else "^(?:.*/)") + rx + "$")


def _matches(rule, path, is_dir):
    rx, dir_only = rule
    if dir_only and not is_dir:
        return False
    return rx.match(path) is not None


def _decide(path, is_dir, rules):
    excluded = False
    for negate, rule in rules:
        if _matches(rule, path, is_dir):
            excluded = not negate
    return excluded


def is_excluded(path, patterns):
    rules = []
    for p in patterns:
        if not p or p.startswith("#"):
            continue
        negate = p.startswith("!")
        if negate:
            p = p[1:]
        dir_only = p.endswith("/")
        rules.append((negate, (_compile(p.rstrip("/") if dir_only else p), dir_only)))
    comps = path.strip("/").split("/")
    for i in range(1, len(comps)):
        if _decide("/" + "/".join(comps[:i]), True, rules):
            return True
    return _decide(path, False, rules)
