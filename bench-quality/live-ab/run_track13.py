#!/usr/bin/env python3
"""Track 13 — the weak-agent arm (REVALIDATION.md, registered before any
session).

Track 11's protocol with two arms (none, verbatim) and the model pinned
to haiku in BOTH arms — the pin is the treatment. Reuses run_track11's
task list, store builder, hygiene, and preflight, retargeted at track13/.

Usage: run_track13.py [--dry-run]
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_stream as rs        # noqa: E402
import run_reval as rv         # noqa: E402  (clause-free PROMPT)
import run_track11 as t11      # noqa: E402  (TASKS, build_store, hygiene)

INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
import install_hooks           # noqa: E402

DIR = os.path.join(HERE, "track13")
DB = os.path.join(DIR, "rfm-memory.db")
RESULTS = os.path.join(DIR, "results.jsonl")
SESSIONS = os.path.join(DIR, "sessions")
MODEL = "claude-haiku-4-5-20251001"

# Retarget run_track11's helpers (build_store, clean_session_state,
# preflight) at this track's directory and store.
t11.DIR, t11.DB = DIR, DB

ARMS = [("none", "control", None), ("verbatim", "rfm", "verbatim")]


def run_session(task, arm_name, ab_arm):
    clone, venv = rs.prepare("sphinx", ab_arm, task)
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": DB}
    cmd = [rs.AB, "--arm", ab_arm,
           "--label", f"track13-{task['instance_id']}-{arm_name}",
           "-p", rv.PROMPT.format(repo="sphinx",
                                  problem=task["problem_statement"],
                                  tests_dir=rs.REPO["sphinx"]["tests_dir"]),
           "--max-turns", rs.MAX_TURNS, "--allowedTools", rs.ALLOWED,
           "--model", MODEL]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=clone, env=env, capture_output=True,
                           text=True, timeout=rs.SESSION_TIMEOUT)
        timed_out = False
    except subprocess.TimeoutExpired as e:
        r, timed_out = e, True
    wall = time.time() - t0
    os.makedirs(SESSIONS, exist_ok=True)

    def _text(x):
        if isinstance(x, bytes):
            return x.decode("utf-8", errors="replace")
        return x if isinstance(x, str) else ""
    with open(os.path.join(SESSIONS,
                           f"{task['instance_id']}.{arm_name}.log"), "w") as f:
        f.write(_text(getattr(r, "stdout", "")))
        f.write("\n--- STDERR ---\n")
        f.write(_text(getattr(r, "stderr", "")))
    return clone, venv, wall, timed_out


def main():
    problems, by_id = t11.preflight()
    if problems:
        for p in problems:
            print(f"PREFLIGHT: {p}")
        sys.exit(1)
    print(f"preflight ok: {len(t11.TASKS)} tasks x {len(ARMS)} arms = "
          f"{len(t11.TASKS) * len(ARMS)} sessions, model {MODEL}")
    if "--dry-run" in sys.argv:
        return

    done = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS):
            r = json.loads(line)
            done.add((r["instance_id"], r["arm"]))
    if done:
        print(f"resuming: {len(done)} session(s) already recorded")

    for change in install_hooks.sync_claude_md(remove=True):
        print(f"CLAUDE.md: {change}")
    try:
        with open(RESULTS, "a") as sink:
            for iid in t11.TASKS:
                task = by_id[iid]
                for arm_name, ab_arm, variant in ARMS:
                    if (iid, arm_name) in done:
                        continue
                    print(f"=== {iid} [{arm_name}] "
                          f"({task['difficulty']}) ===", flush=True)
                    t11.clean_session_state()
                    if variant is not None:
                        t11.build_store(variant)
                    clone, venv, wall, timed_out = run_session(
                        task, arm_name, ab_arm)
                    if not rs.apply_test_patch(clone, task):
                        resolved, detail = None, "SCORING ERROR: test_patch failed"
                    else:
                        try:
                            resolved, detail = rs.run_f2p(clone, venv, task)
                        except subprocess.TimeoutExpired:
                            resolved, detail = None, "SCORING ERROR: F2P timed out"
                    rec = {"instance_id": iid, "repo": "sphinx",
                           "difficulty": task["difficulty"], "arm": arm_name,
                           "ab_arm": ab_arm, "track": "track13",
                           "model": MODEL, "resolved": resolved,
                           "wall_s": round(wall), "timed_out": timed_out,
                           "detail": detail}
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    print(f"    resolved={resolved} wall={round(wall)}s "
                          f"{detail}", flush=True)
                    # No ratify: formation is not under test.
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
