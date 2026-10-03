# Grove filter van M7 Taak 8 (spec §3/§4.2): niet-merge-commits sinds 2026-08-01 op de vastgepinde origin/main, die src/ en
# een test (__tests__/**/*.test.ts, A of M) raken, package.json, lockfile en Prisma niet raken, geen runnerconfig of
# submodule wijzigen, en 20–400 regels hebben (--no-renames, zoals case-check.json). Schrijft kandidaten.jsonl.
import json, re, subprocess, sys

REPOS = {
    "agent-harness": ("/Users/janpetervisser/Development/agent-harness", "https://git.jp-visser.nl/janpeter/agent-harness.git"),
    "scrum4me-mcp": ("/Users/janpetervisser/Development/scrum4me-mcp-stable", "https://git.jp-visser.nl/janpeter/scrum4me-mcp.git"),
}
SAFE = ["-c", "core.quotepath=off", "-c", "diff.ignoreSubmodules=none", "-c", "diff.external=", "-c", "core.fsmonitor=false",
        "-c", "color.ui=false"]
RUNNER = re.compile(r"^(vitest\.config\.[^/]+|package\.json|tsconfig[^/]*\.json|package-lock\.json|npm-shrinkwrap\.json|\.npmrc)$")
HIDDEN = re.compile(r"^__tests__/.+\.test\.ts$")


def git(repo, *args):
    return subprocess.run(["git", *SAFE, "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def size_class(n):
    return "klein" if 20 <= n <= 80 else "middel" if 81 <= n <= 200 else "groot" if 201 <= n <= 400 else None


pins, out, stats = {}, [], {}
for name, (repo, url) in REPOS.items():
    pin = git(repo, "rev-parse", "origin/main").strip()
    pins[name] = pin
    shas = git(repo, "rev-list", "--no-merges", "--since=2026-08-01", pin).split()
    st = stats[name] = {"commits": len(shas), "door": 0}
    for sha in shas:
        parents = git(repo, "rev-list", "--parents", "-n1", sha).split()[1:]
        if not parents:
            continue  # wortelcommit: geen base_commit
        base = parents[0]
        ns = git(repo, "diff", "--no-renames", "--name-status", "-z", base, sha).split("\0")
        files = [(ns[i], ns[i + 1]) for i in range(0, len(ns) - 1, 2)]
        paths = [p for _, p in files]
        raw = git(repo, "diff", "--no-renames", "--raw", base, sha).splitlines()
        gitlink = any(l.split("\t")[0].split()[0] == ":160000" or l.split("\t")[0].split()[1] == "160000" for l in raw if l.startswith(":"))
        stat = git(repo, "diff", "--no-renames", "--shortstat", base, sha)
        ins = re.search(r"(\d+) insertion", stat); dels = re.search(r"(\d+) deletion", stat)
        lines = (int(ins.group(1)) if ins else 0) + (int(dels.group(1)) if dels else 0)
        hidden = [p for s, p in files if s in ("A", "M") and HIDDEN.match(p)]
        pkg = [p for p in paths if p in ("package.json", "package-lock.json", "npm-shrinkwrap.json") or p.startswith("prisma/") or p.endswith(".prisma")]
        runner = [p for p in paths if RUNNER.match(p)]
        outside = [p for p in paths if not (p.startswith(("src/", "__tests__/", "docs/")) or p.endswith(".md"))]
        subject, date = git(repo, "log", "-1", "--format=%s%x00%cI", sha).rstrip("\n").split("\0")
        ok = (any(p.startswith("src/") for p in paths) and hidden and not pkg and not runner and not gitlink
              and size_class(lines) is not None)
        row = {"repo": name, "repo_url": url, "ref": sha, "base": base, "subject": subject, "date": date, "lines": lines,
               "klasse": size_class(lines), "hidden": hidden, "outside": outside, "pkg": pkg, "runner": runner,
               "gitlink": gitlink, "door": bool(ok)}
        out.append(row)
        st["door"] += bool(ok)

with open("kandidaten.jsonl", "w") as f:
    for r in out:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
json.dump({"pins": pins, "since": "2026-08-01", "filter": "no-merges; src/ + __tests__/**/*.test.ts (A/M); geen package.json/lockfile/prisma; geen runnerconfig; geen gitlink; 20-400 regels (--no-renames shortstat)"},
          open("bron-pin.json", "w"), indent=2)
print(json.dumps(pins))
for name, st in stats.items():
    door = [r for r in out if r["repo"] == name and r["door"]]
    by = {k: sum(1 for r in door if r["klasse"] == k) for k in ("klein", "middel", "groot")}
    print(name, st, by, "met bestanden buiten src/__tests__/docs:", sum(1 for r in door if r["outside"]))
