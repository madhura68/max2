#!/usr/bin/env python3
"""Count the files under some directories that hold the value of an environment variable (M5, T-60).

  ./check_key.py --env OPENROUTER_API_KEY results/refiner-<stamp> [more directories]

--env is the NAME of the variable. The value is read from the environment and never from argv, and it is never printed:
per directory the output is one line with counts and the name of the variable, and no file name.

  check_key OPENROUTER_API_KEY <directory>: files_scanned=19 unreadable=0 with_key=0

files_scanned is the number of files it could read, unreadable the number of files it could not read plus the directories it
could not list (what is in them goes unchecked, which is why they are counted), and with_key the number of files that
contain the value, however often. The value counts without the whitespace around it: a server echoes the trimmed form.

Exit status 0: no file holds the value. 1: at least one file does. 2: the check could not be made: the variable is not set
or empty, --env is not the name of a variable (a key given by mistake is not quoted back), or a directory is not one.

run.py runs this after a run over the run directory, once for each key variable of its models (spec 5.7, plan Task 11).

Stdlib only.
"""
import argparse
import os
import re
import sys
from pathlib import Path

NAME = re.compile(r"[A-Z_][A-Z0-9_]*")      # as run.py requires of api_key_env: a value would end up in argv


def scan(directory, needle):
    """{files_scanned, unreadable, with_key} for the files under directory, all the way down (a symlinked directory is not
    followed). needle is the value as bytes."""
    counts = {"files_scanned": 0, "unreadable": 0, "with_key": 0}

    def cannot_list(error):      # os.walk skips a directory it cannot list unless it is told: count it, do not pass it over
        counts["unreadable"] += 1

    for here, _, names in os.walk(directory, onerror=cannot_list):
        for name in names:
            try:
                data = Path(here, name).read_bytes()
            except OSError:
                counts["unreadable"] += 1
                continue
            counts["files_scanned"] += 1
            counts["with_key"] += needle in data
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", required=True, metavar="VAR", help="the NAME of the environment variable that holds the key")
    ap.add_argument("dirs", nargs="+", metavar="DIR", help="the directories to scan, all the way down")
    args = ap.parse_args(argv)
    if not NAME.fullmatch(args.env):
        ap.error("--env is the name of an environment variable (capitals, digits and _), not the key itself")
    value = os.environ.get(args.env, "")
    if not value.strip():
        print(f"check_key: environment variable {args.env} is not set or empty", file=sys.stderr)
        return 2
    for n, directory in enumerate(args.dirs, start=1):      # all of them before the first line: no claim about a part
        if not Path(directory).is_dir():
            print(f"check_key: directory argument {n} is not a directory", file=sys.stderr)
            return 2
    needle = os.fsencode(value.strip())
    found = False
    for directory in args.dirs:
        counts = scan(directory, needle)
        print(f"check_key {args.env} {directory}: " + " ".join(f"{k}={v}" for k, v in counts.items()))
        found = found or counts["with_key"] > 0
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
