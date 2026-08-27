#!/usr/bin/env python3
"""Track 15 — the yardstick run (REVALIDATION.md, registered before any
session). Within-condition variance: one task (sphinx-7757), control arm
only, 10 sessions per model (fable-5, haiku), model and CLI version
stamped per record.

Usage: run_track15.py [--dry-run]
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
import run_track11 as t11      # noqa: E402  (hygiene)

INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
import install_hooks           # noqa: E402

DIR = os.path.join(HERE, "track15")
RESULTS = os.path.join(DIR, "results.jsonl")
SESSIONS = os.path.join(DIR, "sessions")
TASK_ID = "sphinx-doc__sphinx-7757"
MODELS = [("fable", "claude-fable-5"), ("haiku", "claude-haiku-4-5-20251001")]
REPS = 10

# Retarget the shared hygiene helper at this track's directory.
t11.DIR = DIR


def run_session(task, alias, model, rep):
    clone, venv = rs.prepare("sphinx", "control", task)
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv}
    cmd = [rs.AB, "--arm", "control",
           "--label", f"track15-{alias}-r{rep}",
           "-p", rv.PROMPT.format(repo="sphinx",
                                  problem=task["problem_statement"],
                                  tests_dir=rs.REPO["sphinx"]["tests_dir"]),
           "--max-turns", rs.MAX_TURNS, "--allowedTools", rs.ALLOWED,
           "--model", model]
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
    with open(os.path.join(SESSIONS, f"{alias}-r{rep}.log"), "w") as f:
        f.write(_text(getattr(r, "stdout", "")))
        f.write("\n--- STDERR ---\n")
        f.write(_text(getattr(r, "stderr", "")))
    return clone, venv, wall, timed_out


def main():
    valid = {json.loads(l)["instance_id"]
             for l in open(os.path.join(HERE, "validation.jsonl"))
             if json.loads(l).get("valid")}
    if TASK_ID not in valid:
        sys.exit(f"PREFLIGHT: {TASK_ID} not validated")
    by_id = {t["instance_id"]: t for t in json.load(
        open(os.path.join(HERE, "tasks_v2.json")))}
    task = by_id[TASK_ID]
    cli = rs.cli_version()
    print(f"preflight ok: {TASK_ID}, {len(MODELS)} models x {REPS} reps "
          f"= {len(MODELS) * REPS} sessions, cli: {cli}")
    if "--dry-run" in sys.argv:
        return

    os.makedirs(DIR, exist_ok=True)
    done = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS):
            r = json.loads(line)
            done.add((r["model"], r["rep"]))
    if done:
        print(f"resuming: {len(done)} session(s) already recorded")

    for change in install_hooks.sync_claude_md(remove=True):
        print(f"CLAUDE.md: {change}")
    try:
        with open(RESULTS, "a") as sink:
            for alias, model in MODELS:
                for rep in range(1, REPS + 1):
                    if (model, rep) in done:
                        continue
                    print(f"=== {alias} r{rep} ===", flush=True)
                    t11.clean_session_state()
                    clone, venv, wall, timed_out = run_session(
                        task, alias, model, rep)
                    if not rs.apply_test_patch(clone, task):
                        resolved, detail = None, "SCORING ERROR: test_patch failed"
                    else:
                        try:
                            resolved, detail = rs.run_f2p(clone, venv, task)
                        except subprocess.TimeoutExpired:
                            resolved, detail = None, "SCORING ERROR: F2P timed out"
                    rec = {"instance_id": TASK_ID, "repo": "sphinx",
                           "arm": "control", "track": "track15",
                           "model": model, "cli": cli, "rep": rep,
                           "resolved": resolved, "wall_s": round(wall),
                           "timed_out": timed_out, "detail": detail}
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    print(f"    resolved={resolved} wall={round(wall)}s "
                          f"{detail}", flush=True)
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
