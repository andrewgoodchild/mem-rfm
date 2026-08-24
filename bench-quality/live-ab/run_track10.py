#!/usr/bin/env python3
"""Track 10 — live paired A/B against a store built by the prose harvest.

The first formation experiment in this project worth spending sessions on,
because for once the store contains memories a human would keep.

Design constraints that make the result mean something:

  HELD OUT   The 5 memories were extracted from 9 xarray tasks. All 13
             tasks here contributed nothing to the store. Testing on a
             task whose own session produced the memory would measure
             nothing but leakage.
  FROZEN     No ratify() call. Staged candidates accumulate in
             pending-memories.md and are never saved, so the store stays
             at exactly the 5 consolidated memories for every session.
             This is an A/B on the harvest's output, not on the miner.
  PAIRED     Same task, both arms, control first.

Metric of record is NOT resolved-rate. With 13 tasks that is hopelessly
underpowered and this project has already learned that lesson twice. The
metric is events-before-first-green-test (formation_study.py's
counterfactual view), which is the instrument that actually discriminated
on reval-sphinx: control 6 events, memory arm 1.

Usage: run_track10.py [--dry-run]
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

INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
import install_hooks           # noqa: E402

DIR = os.path.join(HERE, "track10")
DB = os.path.join(DIR, "rfm-memory.db")
RESULTS = os.path.join(DIR, "results.jsonl")
SESSIONS = os.path.join(DIR, "sessions")

# 13 validated xarray tasks, none of which contributed a memory.
HELD_OUT = [
    "pydata__xarray-2905", "pydata__xarray-3095", "pydata__xarray-3151",
    "pydata__xarray-3677", "pydata__xarray-3993", "pydata__xarray-4094",
    "pydata__xarray-4695", "pydata__xarray-4966", "pydata__xarray-6461",
    "pydata__xarray-6721", "pydata__xarray-6744", "pydata__xarray-6938",
    "pydata__xarray-7233",
]


def run_session(task, arm):
    clone, venv = rs.prepare("xarray", arm, task)
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": DB}
    cmd = [rs.AB, "--arm", arm,
           "--label", f"track10-{task['instance_id']}",
           "-p", rv.PROMPT.format(repo="xarray",
                                  problem=task["problem_statement"],
                                  tests_dir=rs.REPO["xarray"]["tests_dir"]),
           "--max-turns", rs.MAX_TURNS, "--allowedTools", rs.ALLOWED]
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
                           f"{task['instance_id']}.{arm}.log"), "w") as f:
        f.write(_text(getattr(r, "stdout", "")))
        f.write("\n--- STDERR ---\n")
        f.write(_text(getattr(r, "stderr", "")))
    return clone, venv, wall, timed_out


def main():
    tasks = {t["instance_id"]: t
             for t in json.load(open(os.path.join(HERE, "tasks_xarray.json")))}
    missing = [i for i in HELD_OUT if i not in tasks]
    if missing:
        sys.exit(f"PREFLIGHT: unknown task ids {missing}")
    import sqlite3
    n = sqlite3.connect(DB).execute(
        "SELECT count(*) FROM rfm_memories").fetchone()[0]
    if n != 5:
        sys.exit(f"PREFLIGHT: store has {n} memories, expected the 5 "
                 f"consolidated ones — rebuild before running")
    print(f"preflight ok: {len(HELD_OUT)} held-out xarray tasks, "
          f"frozen store of {n} memories at {DB}")
    if "--dry-run" in sys.argv:
        return

    os.makedirs(DIR, exist_ok=True)
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
            for iid in HELD_OUT:
                task = tasks[iid]
                for arm in ("control", "rfm"):
                    if (iid, arm) in done:
                        continue
                    print(f"=== {iid} [{arm}] ({task['difficulty']}) ===",
                          flush=True)
                    clone, venv, wall, timed_out = run_session(task, arm)
                    if not rs.apply_test_patch(clone, task):
                        resolved, detail = None, "SCORING ERROR: test_patch failed"
                    else:
                        try:
                            resolved, detail = rs.run_f2p(clone, venv, task)
                        except subprocess.TimeoutExpired:
                            resolved, detail = None, "SCORING ERROR: F2P timed out"
                    rec = {"instance_id": iid, "repo": "xarray",
                           "difficulty": task["difficulty"], "arm": arm,
                           "track": "track10", "resolved": resolved,
                           "wall_s": round(wall), "timed_out": timed_out,
                           "detail": detail}
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    print(f"    resolved={resolved} wall={round(wall)}s "
                          f"{detail}", flush=True)
                    # Deliberately no ratify(): the store stays frozen.
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
