"""Name-corrected MBPP+ samples (runs inside the evalplus image).

MBPP+ prompts only name the expected function inside an `assert` line, and models often pick
their own name (`remove_occurrence` instead of `remove_Occ`). That is a naming miss, not a coding
miss. For every sanitized solution that does not define the expected entry point, append
`<entry_point> = <first top-level function>` so the tests can call it. Nothing else changes.

  python /opt/alias_fix.py /work/<model-dir>
writes <model-dir>/mbpp.aliased.jsonl (evaluate it separately; the official score stays as is).
"""
import ast
import json
import sys
from pathlib import Path

from evalplus.data import get_mbpp_plus


def main(model_dir):
    d = Path(model_dir)
    problems = get_mbpp_plus()
    fixed = 0
    with open(d / "mbpp.aliased.jsonl", "w") as out:
        for line in open(d / "mbpp.raw-sanitized.jsonl"):
            s = json.loads(line)
            entry = problems[s["task_id"]]["entry_point"]
            sol = s["solution"]
            try:
                tree = ast.parse(sol)
                funcs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            except SyntaxError:
                funcs = []
            if entry not in funcs and funcs:
                sol = f"{sol}\n\n{entry} = {funcs[0]}\n"
                fixed += 1
            out.write(json.dumps({"task_id": s["task_id"], "solution": sol}) + "\n")
    print(f"aliased {fixed} solutions")


if __name__ == "__main__":
    main(sys.argv[1])
