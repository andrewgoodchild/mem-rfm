#!/usr/bin/env python3
"""Pilot 3 (exploratory, NOT pre-registered): pilot 2's rfm arm re-run
after the cost-side interventions, to measure the overhead delta.

Interventions under test (vs the pilot-2 stack):
  * injection floor — outcome-demoted memories are never re-injected
  * feedback-on-surprise trailer — routine outcomes left to session_end
    inference (attachment-scan + rehydration fixes make it carry 9/15 of
    pilot 2's explicit outcomes in offline replay)
  * no volunteered saves — the prompt's "save any durable lesson" sentence
    is gone and the trailer forbids unprompted memory_save; the store
    grows ONLY through the miner (now with the environment-error class)
    ratified between tasks
Control arm is untouched by all of the above, so pilot 2's control rows
remain the baseline; only the rfm arm runs here. Same 10 tasks, same
prompt otherwise, fresh store under pilot3/.

Readouts: wall/turns/tokens vs pilot 2's rfm arm (overhead delta) and
control (remaining overhead); pilot3/rfm-log.jsonl for whether the
mined-only store still delivers the era-pin workaround and whether
inference closes the loops the trailer no longer asks the agent to.

Usage:  python3 run_pilot3.py [--dry-run]
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_stream as rs        # noqa: E402
import run_pilot2 as p2        # noqa: E402  (task list + preflight + ratify)

INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
import install_hooks  # noqa: E402

PILOT_DIR = os.path.join(HERE, "pilot3")
DB = os.path.join(PILOT_DIR, "rfm-memory.db")
SESSIONS = os.path.join(PILOT_DIR, "sessions")
RESULTS = os.path.join(PILOT_DIR, "results.jsonl")

# rs.PROMPT minus the volunteered-save instruction: formation is
# harness-owned now, and pilot 2 measured the volunteered saves as most
# of the token overhead with zero earned value.
PROMPT = rs.PROMPT.replace(
    " and save any durable, non-obvious lesson you learn (APIs, gotchas, "
    "structure) when done", "")
assert PROMPT != rs.PROMPT, "prompt surgery no longer matches run_stream"


def run_session(task):
    clone, venv = rs.prepare("sphinx", "rfm", task)
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": DB}
    cmd = [rs.AB, "--arm", "rfm", "--label", f"pilot3-{task['instance_id']}",
           "-p", PROMPT.format(repo="sphinx",
                               problem=task["problem_statement"],
                               tests_dir=rs.REPO["sphinx"]["tests_dir"]),
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
    with open(os.path.join(SESSIONS, f"{task['instance_id']}.rfm.log"), "w") as f:
        f.write(_text(getattr(r, "stdout", "")))
        f.write("\n--- STDERR ---\n")
        f.write(_text(getattr(r, "stderr", "")))
    return clone, venv, wall, timed_out


def ratify():
    r = subprocess.run([p2.VENV_PY, os.path.join(HERE, "ratify_staged.py"),
                        "--db", DB, "--scope", "sphinx"],
                       capture_output=True, text=True, timeout=360)
    out = (r.stdout or "").strip()
    if out:
        print(f"    {out}", flush=True)
    if r.returncode != 0:
        raise RuntimeError(f"ratify_staged.py failed (exit {r.returncode}): "
                           f"{(r.stderr or '')[-300:]}")


def main():
    dry = "--dry-run" in sys.argv
    problems, by_id = p2.preflight()
    if problems:
        for p in problems:
            print(f"PREFLIGHT: {p}")
        sys.exit(1)
    print(f"preflight ok: 10 rfm sessions, store at {DB}")
    if dry:
        return

    os.makedirs(PILOT_DIR, exist_ok=True)
    done = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS):
            done.add(json.loads(line)["instance_id"])
    if done:
        print(f"resuming: {len(done)} session(s) already recorded")

    for change in install_hooks.sync_claude_md(remove=True):
        print(f"CLAUDE.md: {change}")
    try:
        with open(RESULTS, "a") as sink:
            for iid in p2.PILOT_IDS:
                if iid in done:
                    continue
                task = by_id[iid]
                print(f"=== {iid} [rfm/pilot3] ({task['difficulty']}) ===",
                      flush=True)
                clone, venv, wall, timed_out = run_session(task)
                if not rs.apply_test_patch(clone, task):
                    resolved, detail = None, "SCORING ERROR: test_patch failed to apply"
                else:
                    try:
                        resolved, detail = rs.run_f2p(clone, venv, task)
                    except subprocess.TimeoutExpired:
                        resolved, detail = None, "SCORING ERROR: F2P run timed out"
                rec = {"instance_id": iid, "repo": "sphinx",
                       "difficulty": task["difficulty"], "arm": "rfm",
                       "pilot": 3, "resolved": resolved, "wall_s": round(wall),
                       "timed_out": timed_out, "detail": detail}
                sink.write(json.dumps(rec) + "\n")
                sink.flush()
                print(f"    resolved={resolved} wall={round(wall)}s {detail}",
                      flush=True)
                ratify()
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
