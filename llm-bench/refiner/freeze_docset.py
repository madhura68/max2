#!/usr/bin/env python3
"""Freeze the agent-harness docs byte for byte into a docset, and check that docset (M5, T-53).

The refiner with docs reads eight agent-harness files through a doc server. They come from one
pinned commit and are never edited, so every model and every run reads the same text:

  ./freeze_docset.py --repo ~/Development/agent-harness --commit <full sha> --out docset
  ./freeze_docset.py --check docset

Freezing takes each file with `git show <sha>:<path>` and writes the bytes unchanged to
<out>/<folder>/<slug>.md (README.md becomes manual/readme.md, the rest keeps its name in lower
case), plus <out>/docset.json with the pin, the time, and a sha256 and size per file.

--check verifies those hashes and counts key shapes (sk-..., ghp_...) and Bearer values in the
files. It prints counts and file names, never a matched value, and exits 1 on a changed or
missing file or on any hit. The docset goes to OpenRouter as it stands, so a hit means stop.

Stdlib only.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

SOURCE_REPO = "janpeter/agent-harness"
PRODUCT_ID = "bench-agent-harness"
# (folder, path in the agent-harness repo); the slug is the file name without .md, in lower case
SOURCES = [
    ("manual", "README.md"),
    ("specs", "docs/specs/2026-09-26-agent-harness-v0-design.md"),
    ("specs", "docs/specs/2026-09-26-idea-chat-local-llm-design.md"),
    ("specs", "docs/specs/2026-09-27-task-implementation-local-llm-design.md"),
    ("specs", "docs/specs/2026-09-28-harness-run-logging-design.md"),
    ("runbooks", "docs/runbooks/idea-chat-worker.md"),
    ("runbooks", "docs/runbooks/probe-and-run-max2.md"),
    ("runbooks", "docs/runbooks/task-worker.md"),
]
# The \b keeps names like 'task-implementation-...' (they contain 'sk-') from counting as a key.
KEY_SHAPE = re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,})")
BEARER = re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}")
FULL_SHA = re.compile(r"[0-9a-f]{40}")


def git_show(repo, commit, path):
    r = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"], capture_output=True)
    if r.returncode != 0:
        sys.exit(f"freeze_docset: git show {commit[:12]}:{path} failed: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def freeze(repo, commit, out):
    """Write the docset for one commit. All files are fetched before the first one is written."""
    fetched = [(folder, path, git_show(repo, commit, path)) for folder, path in SOURCES]
    out, files = Path(out), []
    for folder, path, data in fetched:
        slug = PurePosixPath(path).stem.lower()
        (out / folder).mkdir(parents=True, exist_ok=True)
        (out / folder / f"{slug}.md").write_bytes(data)
        files.append({"folder": folder, "slug": slug, "source_path": path,
                      "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    manifest = {"source_repo": SOURCE_REPO, "source_commit": commit,
                "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "product_id": PRODUCT_ID, "files": files}
    (out / "docset.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def scan(text):
    """Count (key shapes, Bearer values) in a text."""
    return len(KEY_SHAPE.findall(text)), len(BEARER.findall(text))


def check(docset):
    """Verify every listed file against its sha256 and scan it. Prints counts and file names only.

    Returns True when no file is changed or missing and nothing matches a pattern."""
    docset = Path(docset)
    try:
        files = json.loads((docset / "docset.json").read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError) as e:
        sys.exit(f"freeze_docset: no usable docset.json in {docset} ({type(e).__name__})")
    mismatched, hits = [], []
    n_keys = n_bearers = 0
    for f in files:
        name = f"{f['folder']}/{f['slug']}"
        try:
            data = (docset / f["folder"] / f"{f['slug']}.md").read_bytes()
        except OSError:
            mismatched.append(name)
            continue
        if hashlib.sha256(data).hexdigest() != f["sha256"]:
            mismatched.append(name)
        keys, bearers = scan(data.decode("utf-8", errors="replace"))
        n_keys, n_bearers = n_keys + keys, n_bearers + bearers
        if keys or bearers:
            hits.append((name, keys, bearers))
    print(f"files={len(files)} hash_mismatches={len(mismatched)} key_shapes={n_keys} bearer_values={n_bearers}")
    for name in mismatched:
        print(f"hash mismatch: {name}")
    for name, keys, bearers in hits:
        print(f"hits in {name}: key_shapes={keys} bearer_values={bearers}")
    return not (mismatched or n_keys or n_bearers)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="agent-harness checkout to read with git show")
    ap.add_argument("--commit", help="full 40-character sha to freeze")
    ap.add_argument("--out", help="docset folder to write")
    ap.add_argument("--check", metavar="DOCSET", help="verify the hashes of a docset and scan it for secrets")
    args = ap.parse_args(argv)
    if args.check is not None:
        if args.repo or args.commit or args.out:
            ap.error("--check takes no other option")
        return 0 if check(args.check) else 1
    if not (args.repo and args.commit and args.out):
        ap.error("freezing needs --repo, --commit and --out (or use --check DOCSET)")
    if not FULL_SHA.fullmatch(args.commit):
        ap.error("--commit must be a full 40-character lowercase hex sha, not a branch or an abbreviation")
    manifest = freeze(args.repo, args.commit, args.out)
    print(f"froze {len(manifest['files'])} files, {sum(f['bytes'] for f in manifest['files'])} bytes, from {args.commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
