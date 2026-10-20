#!/usr/bin/env python3
"""Checks a review-bench case (M8 spec §4.2, AC9) without the harness: the bytes the bench will hand the model are the pinned bytes.

  python3 llm-bench/review_bench/check_case.py llm-bench/review_bench/cases/<id>

It checks
- every sha256 in case.json (prompt, payload, each source) against the file it names;
- that the keys and hashes of payload.dispatch.source_artifacts equal those of sources[], in both directions;
- that each review_documents item of the payload whose key is a source carries the sha256 of that source file.

Exit 0 if all of it holds. Otherwise exit 1, with one line per deviation on stdout. Standard library only.
"""
import hashlib
import json
import sys
from pathlib import Path


def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path, problems):
    """The parsed JSON of path, or None with one line in problems."""
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError) as err:
        problems.append(f"{path.name}: niet te lezen als JSON ({type(err).__name__}: {err})")
        return None


def case_file(case_dir, name, problems):
    """The path of a file case.json names, if it is a relative path inside the case dir; else None with a line in problems."""
    if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
        problems.append(f"case.json: bestandsnaam {name!r} is geen relatief pad binnen de case")
        return None
    return case_dir / name


def check_pinned(case_dir, label, ref, problems):
    """Checks one {file, sha256} of case.json. Returns the sha256 found, or None."""
    if not isinstance(ref, dict) or "file" not in ref or "sha256" not in ref:
        problems.append(f"case.json: {label} heeft geen file en sha256")
        return None
    path = case_file(case_dir, ref["file"], problems)
    if path is None:
        return None
    if not path.is_file() or path.is_symlink():
        problems.append(f"{ref['file']}: ontbreekt of is geen gewoon bestand")
        return None
    found = sha256_of(path)
    if found != ref["sha256"]:
        problems.append(f"{ref['file']}: sha256 wijkt af: verwacht {ref['sha256']}, gevonden {found}")
    return found


def check_case(case_dir):
    """All deviations of the case in case_dir, one line each; an empty list means the case is sound."""
    case_dir = Path(case_dir)
    problems = []
    case = read_json(case_dir / "case.json", problems)
    if not isinstance(case, dict):
        if case is not None:
            problems.append("case.json: is geen object")
        return problems

    check_pinned(case_dir, "prompt", case.get("prompt"), problems)
    check_pinned(case_dir, "payload", case.get("payload"), problems)
    sources = case.get("sources")
    if not isinstance(sources, list) or not sources:
        problems.append("case.json: sources ontbreekt of is leeg")
        sources = []
    pinned = {}   # key -> sha256 as case.json pins it
    actual = {}   # key -> sha256 of the file
    for i, source in enumerate(sources):
        key = source.get("key") if isinstance(source, dict) else None
        if not isinstance(key, str) or not key:
            problems.append(f"case.json: sources[{i}] heeft geen key")
            continue
        if key in pinned:
            problems.append(f"case.json: sleutel {key} komt twee keer voor in sources")
            continue
        pinned[key] = source.get("sha256")
        found = check_pinned(case_dir, f"sources[{i}] ({key})", source, problems)
        if found is not None:
            actual[key] = found

    payload_ref = case.get("payload")
    if not isinstance(payload_ref, dict) or case_file(case_dir, payload_ref.get("file"), []) is None:
        return problems
    payload = read_json(case_dir / payload_ref["file"], problems)
    dispatch = payload.get("dispatch") if isinstance(payload, dict) else None
    if not isinstance(dispatch, dict):
        if payload is not None:
            problems.append(f"{payload_ref['file']}: dispatch ontbreekt")
        return problems

    artifacts = dispatch.get("source_artifacts")
    declared = {}
    if not isinstance(artifacts, list):
        problems.append(f"{payload_ref['file']}: dispatch.source_artifacts ontbreekt")
    else:
        for artifact in artifacts:
            if isinstance(artifact, dict) and isinstance(artifact.get("key"), str):
                declared[artifact["key"]] = artifact.get("sha256")
    for key in sorted(set(declared) - set(pinned)):
        problems.append(f"source_artifacts: {key} staat niet in sources[] van case.json")
    for key in sorted(set(pinned) - set(declared)):
        problems.append(f"sources[]: {key} staat niet in source_artifacts van de payload")
    for key in sorted(set(declared) & set(pinned)):
        if declared[key] != pinned[key]:
            problems.append(f"source_artifacts: {key} heeft sha256 {declared[key]}, case.json pint {pinned[key]}")

    documents = dispatch.get("input", {}).get("review_documents") if isinstance(dispatch.get("input"), dict) else None
    items = documents.get("items") if isinstance(documents, dict) else None
    if not isinstance(items, list):
        problems.append(f"{payload_ref['file']}: dispatch.input.review_documents.items ontbreekt")
        return problems
    for item in items:
        key = item.get("key") if isinstance(item, dict) else None
        if key not in pinned:
            problems.append(f"review_documents: {key!r} is geen bron in case.json")
        elif key in actual and item.get("sha256") != actual[key]:
            problems.append(f"review_documents: {key} heeft sha256 {item.get('sha256')}, het bronbestand {actual[key]}")
    return problems


def main(argv):
    if len(argv) != 2:
        print("gebruik: check_case.py <case-dir>", file=sys.stderr)
        return 2
    problems = check_case(argv[1])
    for line in problems:
        print(line)
    if not problems:
        print(f"case in orde: {argv[1]}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
