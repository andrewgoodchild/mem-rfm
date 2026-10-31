#!/usr/bin/env python3
"""Track 25's live run: does the mod record outcomes in real sessions now
that acted_on and the verdict are fixed? Show arm only, the pool's first 4
tasks, Track 23's harness and a fresh copy of its seed store. This tests
capture, not benefit: there is no control.

Usage: run_track25.py [--dry-run]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_track23 as T      # noqa: E402

TASKS = ["sphinx-doc__sphinx-7440", "sphinx-doc__sphinx-7748",
         "sphinx-doc__sphinx-7985", "sphinx-doc__sphinx-8035"]


def main():
    T.ARMS = (("show", "rfm", True),)
    problems = T.preflight()
    if problems:
        for x in problems:
            print(f"PREFLIGHT: {x}")
        sys.exit(1)
    by_id = {t["instance_id"]: t for t in json.load(
        open(os.path.join(HERE, "tasks_v2.json")))}
    print(f"preflight ok: {len(TASKS)} show sessions, model {T.MODEL}, "
          f"cli {T.rs.cli_version()}")
    if "--dry-run" in sys.argv:
        return
    T.run_pairs(TASKS, by_id, T.paths(os.path.join(HERE, "track25")),
                "track25")


if __name__ == "__main__":
    main()
