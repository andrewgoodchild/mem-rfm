#!/usr/bin/env python3
"""Track 5 — struggle-triggered synthesis (REVALIDATION.md; registered
before any session runs).

Ten pytest tasks, rfm arm only, fresh store, RFM_SYNTHESIS=1. The baseline
is reval-pytest's own rfm arm — same tasks, same stack, same clause-free
prompt, miner only — so the delta isolates the synthesis channel.

This is a CAPTURE test. It asks whether the channel writes down the
expensive knowledge the failed→fixed miner provably misses on this repo
(the coverage scorecard marks modulenotfounderror and pkg_resources NOT
CAPTURED). It makes no performance claim; a benefit claim needs the
token-matched control, deferred to a follow-up.

Usage:  python3 run_synth.py [--dry-run]
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
import run_pilot2 as p2        # noqa: E402  (VENV_PY)
import run_reval as rv         # noqa: E402  (clause-free PROMPT, task lists)

INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
import install_hooks  # noqa: E402

PILOT_DIR = os.path.join(HERE, "synth")
DB = os.path.join(PILOT_DIR, "rfm-memory.db")
SESSIONS = os.path.join(PILOT_DIR, "sessions")
RESULTS = os.path.join(PILOT_DIR, "results.jsonl")
TASK_IDS = [i for ph in rv.TRACKS["pytest"]["phases"].values() for i in ph]


def clean_room():
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for arm in ("control", "rfm"):
        mem = rs.builtin_memory_dir("pytest", arm)
        if os.path.isdir(mem):
            dst = os.path.join(PILOT_DIR, "builtin-archive", f"{arm}-{stamp}")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(mem, dst)
            print(f"clean-room: archived built-in memory -> {dst}")
    for pat in ("/tmp/pytest*", "/tmp/*_repro"):
        for path in glob.glob(pat):
            (shutil.rmtree if os.path.isdir(path) else os.remove)(path)
            print(f"clean-room: removed {path}")


def run_session(task):
    clone, venv = rs.prepare("pytest", "rfm", task)
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": DB,
           "RFM_SYNTHESIS": "1"}          # the whole experiment, one flag
    cmd = [rs.AB, "--arm", "rfm", "--label", f"synth-{task['instance_id']}",
           "-p", rv.PROMPT.format(repo="pytest",
                                  problem=task["problem_statement"],
                                  tests_dir=rs.REPO["pytest"]["tests_dir"]),
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
                           f"{task['instance_id']}.rfm.log"), "w") as f:
        f.write(_text(getattr(r, "stdout", "")))
        f.write("\n--- STDERR ---\n")
        f.write(_text(getattr(r, "stderr", "")))
    return clone, venv, wall, timed_out


def ratify():
    r = subprocess.run([p2.VENV_PY, os.path.join(HERE, "ratify_staged.py"),
                        "--db", DB, "--scope", "pytest"],
                       capture_output=True, text=True, timeout=360)
    out = (r.stdout or "").strip()
    if out:
        print(f"    {out}", flush=True)
    if r.returncode != 0:
        raise RuntimeError(f"ratify_staged.py failed: {(r.stderr or '')[-300:]}")


def main():
    problems, by_id = rv.preflight(rv.TRACKS["pytest"])
    if problems:
        for p in problems:
            print(f"PREFLIGHT: {p}")
        sys.exit(1)
    # The experiment is inert without its hook registered.
    settings = json.load(open(os.path.expanduser("~/.claude/settings.json")))
    script = install_hooks.HOOKS["PostToolUse"]
    if not [h for g in settings.get("hooks", {}).get("PostToolUse", [])
            for h in g.get("hooks", []) if install_hooks.mentions(h, script)]:
        print("PREFLIGHT: PostToolUse hook not registered — run install_hooks.py")
        sys.exit(1)
    print(f"preflight ok: 10 pytest tasks, synthesis ON, store at {DB}")
    if "--dry-run" in sys.argv:
        return

    os.makedirs(PILOT_DIR, exist_ok=True)
    done = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS):
            done.add(json.loads(line)["instance_id"])
    if done:
        print(f"resuming: {len(done)} session(s) recorded (clean-room skipped)")
    else:
        clean_room()

    for change in install_hooks.sync_claude_md(remove=True):
        print(f"CLAUDE.md: {change}")
    try:
        with open(RESULTS, "a") as sink:
            for iid in TASK_IDS:
                if iid in done:
                    continue
                task = by_id[iid]
                print(f"=== {iid} [rfm/synth] ({task['difficulty']}) ===",
                      flush=True)
                clone, venv, wall, timed_out = run_session(task)
                if not rs.apply_test_patch(clone, task):
                    resolved, detail = None, "SCORING ERROR: test_patch failed to apply"
                else:
                    try:
                        resolved, detail = rs.run_f2p(clone, venv, task)
                    except subprocess.TimeoutExpired:
                        resolved, detail = None, "SCORING ERROR: F2P run timed out"
                rec = {"instance_id": iid, "repo": "pytest",
                       "difficulty": task["difficulty"], "arm": "rfm",
                       "track": "synth", "resolved": resolved,
                       "wall_s": round(wall), "timed_out": timed_out,
                       "detail": detail}
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
