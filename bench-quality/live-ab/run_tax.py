#!/usr/bin/env python3
"""Track 4 — the attachment-tax ablation (REVALIDATION.md; registered
before any session runs).

Two arms over the 10 pilot sphinx tasks:
  control  no MCP server (ab-claude --arm control)
  idle     the rfm-memory MCP server ATTACHED but inert — empty store,
           hooks off (RFM_HOOKS_OFF=1, sidecar still written), nothing
           injected, mined, or ratified. The only differences from
           control are the server's presence: its tool schemas in every
           session's context, and its startup.

This isolates what Track 3 could not: whether merely attaching a memory
server costs wall clock and resolution, independent of any memory
content. Both arms run the clause-free prompt.

Usage:  python3 run_tax.py [--dry-run]
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_stream as rs        # noqa: E402
import run_pilot2 as p2        # noqa: E402  (PILOT_IDS, preflight)
import run_reval as rv         # noqa: E402  (clause-free PROMPT)

INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
import install_hooks  # noqa: E402

PILOT_DIR = os.path.join(HERE, "tax")
DB = os.path.join(PILOT_DIR, "rfm-memory.db")   # created empty, stays empty
SESSIONS = os.path.join(PILOT_DIR, "sessions")
RESULTS = os.path.join(PILOT_DIR, "results.jsonl")


def clean_room():
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for arm in ("control", "rfm"):
        mem = rs.builtin_memory_dir("sphinx", arm)
        if os.path.isdir(mem):
            dst = os.path.join(PILOT_DIR, "builtin-archive", f"{arm}-{stamp}")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(mem, dst)
            print(f"clean-room: archived built-in memory -> {dst}")
    for pat in ("/tmp/sphinx*", "/tmp/*_repro"):
        for path in glob.glob(pat):
            (shutil.rmtree if os.path.isdir(path) else os.remove)(path)
            print(f"clean-room: removed {path}")


def run_session(task, arm):
    clone, venv = rs.prepare("sphinx", "control" if arm == "control" else "rfm",
                             task)
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": DB}
    ab_arm = "control" if arm == "control" else "rfm"
    if arm == "idle":
        env["RFM_HOOKS_OFF"] = "1"
    cmd = [rs.AB, "--arm", ab_arm, "--label", f"tax-{task['instance_id']}-{arm}",
           "-p", rv.PROMPT.format(repo="sphinx",
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


def main():
    dry = "--dry-run" in sys.argv
    problems, by_id = p2.preflight()
    if problems:
        for p in problems:
            print(f"PREFLIGHT: {p}")
        sys.exit(1)
    print(f"preflight ok: 10 paired tasks, idle store at {DB}")
    if dry:
        return

    os.makedirs(PILOT_DIR, exist_ok=True)
    done = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS):
            rec = json.loads(line)
            done.add((rec["instance_id"], rec["arm"]))
    if done:
        print(f"resuming: {len(done)} session(s) recorded (clean-room skipped)")
    else:
        clean_room()

    for change in install_hooks.sync_claude_md(remove=True):
        print(f"CLAUDE.md: {change}")
    try:
        with open(RESULTS, "a") as sink:
            for iid in p2.PILOT_IDS:
                task = by_id[iid]
                for arm in ("control", "idle"):
                    if (iid, arm) in done:
                        continue
                    print(f"=== {iid} [{arm}/tax] ({task['difficulty']}) ===",
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
                           "track": "tax", "resolved": resolved,
                           "wall_s": round(wall), "timed_out": timed_out,
                           "detail": detail}
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    print(f"    resolved={resolved} wall={round(wall)}s "
                          f"{detail}", flush=True)
        # The idle arm's store must have stayed empty, or the arm was not idle.
        import sqlite3
        if os.path.exists(DB):
            n = sqlite3.connect(DB).execute(
                "SELECT count(*) FROM rfm_memories").fetchone()[0]
            print(f"idle-store integrity: {n} memories (must be 0)")
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
