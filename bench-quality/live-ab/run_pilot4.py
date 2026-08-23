#!/usr/bin/env python3
"""Pilot 4 (exploratory, NOT pre-registered): clean-start paired A/B with
the selection policy the offline evaluation chose.

Selection: replaying pilot 2's ten rfm sessions offline against outcome
ground truth ranked the policies (hits / injected / distractors):
  as-run prior top-5            19 / 44 / 2
  prior top-3 + neg-floor       18 / 25 / 1   <- adopted (TOP_K=3)
  sim or sim*prior top-3        12 / 27 / 0   <- REJECTED
Query-similarity ranking anti-selects transferable memories: per-bug
content surface-matches new bug reports while the operational gotchas
that actually help match nothing in particular. The outcome prior is the
better selector; a UserPromptSubmit query-aware hook was therefore NOT
built. This run validates prior-top-3 + floor live.

Clean-start protocol (the pilot-3 confound, handled):
  * both clones' Claude Code built-in auto-memory dirs are archived away
    into pilot4/builtin-archive/ before the run — no cross-run
    inheritance; built-in memory still accumulates WITHIN the run in
    both arms equally (declared design: clean-start marginal-over-built-in);
  * pilot agents' /tmp artifacts from earlier runs are removed, so the
    era-pin failure can actually recur and formation gets a live test of
    the widened environment-error class.

Store: the rfm arm is SEEDED with pilot 2's earned ledger for ids 1-4
(the env gotcha, the mined invocation, one inert mined pair, one demoted
memory) — per-bug memories 5-13 are dropped to avoid same-task leakage.
The demoted memory tests the floor live; the prior ranks the rest.

Both arms use pilot 3's prompt (no volunteered-save sentence).
Usage:  python3 run_pilot4.py [--dry-run]
"""
import glob
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_stream as rs        # noqa: E402
import run_pilot2 as p2        # noqa: E402  (PILOT_IDS, preflight, VENV_PY)
import run_pilot3 as p3        # noqa: E402  (the no-volunteered-save PROMPT)

INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
import install_hooks  # noqa: E402

PILOT_DIR = os.path.join(HERE, "pilot4")
DB = os.path.join(PILOT_DIR, "rfm-memory.db")
SEED_SRC = os.path.join(HERE, "pilot2", "rfm-memory.db")
SESSIONS = os.path.join(PILOT_DIR, "sessions")
RESULTS = os.path.join(PILOT_DIR, "results.jsonl")

CLONE_MEM = {arm: rs.builtin_memory_dir("sphinx", arm)
             for arm in ("control", "rfm")}
TMP_ARTIFACTS = ["/tmp/sphinx*", "/tmp/quickstart_9367_repro.py",
                 "/tmp/napoleon_repro", "/tmp/*_repro"]


def clean_room():
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for arm, mem in CLONE_MEM.items():
        if os.path.isdir(mem):
            dst = os.path.join(PILOT_DIR, "builtin-archive",
                               f"{arm}-{stamp}")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(mem, dst)
            print(f"clean-room: archived built-in memory {arm} -> {dst}")
    for pat in TMP_ARTIFACTS:
        for path in glob.glob(pat):
            (shutil.rmtree if os.path.isdir(path) else os.remove)(path)
            print(f"clean-room: removed {path}")


def seed_store():
    if os.path.exists(DB):
        return
    os.makedirs(PILOT_DIR, exist_ok=True)
    shutil.copy(SEED_SRC, DB)
    db = sqlite3.connect(DB)
    db.execute("DELETE FROM rfm_accesses WHERE memory_id > 4")
    db.execute("DELETE FROM rfm_memories WHERE id > 4")
    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"seeded store: pilot 2 ledger, ids 1-4 only -> {DB}")


def run_session(task, arm):
    clone, venv = rs.prepare("sphinx", arm, task)
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": DB}
    cmd = [rs.AB, "--arm", arm, "--label", f"pilot4-{task['instance_id']}",
           "-p", p3.PROMPT.format(repo="sphinx",
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
    with open(os.path.join(SESSIONS,
                           f"{task['instance_id']}.{arm}.log"), "w") as f:
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
    print(f"preflight ok: 10 paired tasks, store at {DB}")
    if dry:
        return

    seed_store()
    done = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS):
            rec = json.loads(line)
            done.add((rec["instance_id"], rec["arm"]))
    if done:
        # A resume must NOT re-clean: clean-room means no CROSS-run
        # inheritance; within-run accumulation is part of the design, and
        # wiping it mid-run makes the boundary pair asymmetric (its control
        # ran with accumulated state, its rfm without). Learned on the
        # 2026-08-22 run, whose 8056 pair is flagged for exactly this.
        print(f"resuming: {len(done)} session(s) already recorded "
              "(clean-room skipped)")
    else:
        clean_room()

    for change in install_hooks.sync_claude_md(remove=True):
        print(f"CLAUDE.md: {change}")
    try:
        with open(RESULTS, "a") as sink:
            for iid in p2.PILOT_IDS:
                task = by_id[iid]
                for arm in ("control", "rfm"):
                    if (iid, arm) in done:
                        continue
                    print(f"=== {iid} [{arm}/pilot4] ({task['difficulty']}) ===",
                          flush=True)
                    clone, venv, wall, timed_out = run_session(task, arm)
                    if not rs.apply_test_patch(clone, task):
                        resolved, detail = None, "SCORING ERROR: test_patch failed to apply"
                    else:
                        try:
                            resolved, detail = rs.run_f2p(clone, venv, task)
                        except subprocess.TimeoutExpired:
                            resolved, detail = None, "SCORING ERROR: F2P run timed out"
                    rec = {"instance_id": iid, "repo": "sphinx",
                           "difficulty": task["difficulty"], "arm": arm,
                           "pilot": 4, "resolved": resolved,
                           "wall_s": round(wall), "timed_out": timed_out,
                           "detail": detail}
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    print(f"    resolved={resolved} wall={round(wall)}s {detail}",
                          flush=True)
                    if arm == "rfm":
                        ratify()
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
