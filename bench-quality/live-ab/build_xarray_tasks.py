#!/usr/bin/env python3
"""Extract the xarray sequence from SWE-Bench-CL into the live-ab task
format (tasks_xarray.json), chronological. Provenance: the same
SWE-Bench-CL-Curriculum.json every other live-ab task list came from
(MIT, derived from SWE-bench Verified); FAIL_TO_PASS arrives as a
stringified list and is parsed here."""
import ast
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data", "SWE-Bench-CL-Curriculum.json")

seq = next(s for s in json.load(open(DATA))["sequences"]
           if s["repo"] == "pydata/xarray")
tasks = []
for t in seq["tasks"]:
    m, e = t["metadata"], t["evaluation"]
    tasks.append({
        "instance_id": m["instance_id"],
        "repo": "xarray",
        "created_at": m["created_at"],
        "difficulty": m["difficulty"],
        "problem_statement": t["task"]["problem_statement"],
        "base_commit": m["base_commit"],
        "gold_patch": e["patch"],
        "test_patch": e["test_patch"],
        "fail_to_pass": (ast.literal_eval(e["FAIL_TO_PASS"])
                         if isinstance(e["FAIL_TO_PASS"], str)
                         else e["FAIL_TO_PASS"]),
    })
tasks.sort(key=lambda t: t["created_at"])
out = os.path.join(HERE, "tasks_xarray.json")
json.dump(tasks, open(out, "w"), indent=1)
print(f"{len(tasks)} tasks -> {out}")
for t in tasks:
    print(f"  {t['instance_id']:24} {t['created_at'][:7]}  {t['difficulty']}")
