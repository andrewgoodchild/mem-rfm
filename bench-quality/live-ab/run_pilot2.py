#!/usr/bin/env python3
"""Pilot 2 (exploratory, NOT pre-registered): the hooks-era memory stack
under a recurrence-friendly workload.

The July extended A/B measured AGENT-DRIVEN memory work (the model calling
memory_save/memory_feedback mid-task) and found per-bug code lessons don't
transfer (15 of 16 outcomes negative) while the one operational fact earned
sustained positive value. Since then the stack changed: formation and
outcomes are harness-owned (SessionStart injection, SessionEnd correction
mining + inferred outcomes, staging ratified by /memory-review). None of
that pipeline has run under load. This pilot is its integration test, and
a first read on the recurrence hypothesis — NOT a re-test of resolution
rate, which ceilinged in July and is underpowered at this n.

Design deltas from run_stream.py:
  * 10 validated sphinx tasks, chronological, era-coherent (2020-2021, so
    the same era pins and venv gotchas recur task to task). sphinx-7590
    excluded: marginal validation provenance (RESULTS.md Corrections #4).
  * Fresh store under pilot2/ (DB, pending file, rfm-log.jsonl, sessions,
    results all isolated there; nothing touches ~/.sqlite-rfm or the July
    stores).
  * The hooks ARE the system under test: the run refuses to start unless
    both are registered in ~/.claude/settings.json (install_hooks.py).
    session_start/session_end gate themselves to the rfm arm via
    RFM_AB_ARM, which ab-claude exports for every session.
  * After each rfm session, ratify_staged.py stands in for /memory-review
    (approve-all), so staged lessons are in the store before the next task.
    A ratifier failure is fatal — a backlog would trigger the SessionStart
    review nudge and distract the next session.
  * The managed rfm-memory block in ~/.claude/CLAUDE.md is stripped for the
    duration of the run and restored afterwards: it names memory tools,
    which biases control sessions (see ab-claude's contamination warning).
    Interactive sessions you run meanwhile will miss it until restore.

Primary readouts (post-hoc, not computed here): wall/turns/tokens via
ab/ab_stats.py, formation/injection/outcome trace via
log_stats.py pilot2/rfm-log.jsonl, repeated-failure counts from
transcripts, and the pilot store audit. resolution stays recorded but is
secondary.

Cost: 20 headless sessions (10 paired tasks), 30-min cap each — budget a
few hours of wall clock and real LLM quota.

Usage:  python3 run_pilot2.py            # runs (resumes where it left off)
        python3 run_pilot2.py --dry-run  # preflight checks only
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_stream as rs  # noqa: E402  (prepare/scoring shared verbatim)

INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
import install_hooks  # noqa: E402  (hook registry + CLAUDE.md fence owner)

VENV_PY = os.path.join(INTEGRATION, ".venv", "bin", "python")
PILOT_DIR = os.path.join(HERE, "pilot2")
DB = os.path.join(PILOT_DIR, "rfm-memory.db")
SESSIONS = os.path.join(PILOT_DIR, "sessions")
RESULTS = os.path.join(PILOT_DIR, "results.jsonl")

# First 10 validated sphinx tasks in chronological order, 7590 excluded.
PILOT_IDS = [
    "sphinx-doc__sphinx-7454", "sphinx-doc__sphinx-7462",
    "sphinx-doc__sphinx-7757", "sphinx-doc__sphinx-7889",
    "sphinx-doc__sphinx-7910", "sphinx-doc__sphinx-8056",
    "sphinx-doc__sphinx-9281", "sphinx-doc__sphinx-9320",
    "sphinx-doc__sphinx-9367", "sphinx-doc__sphinx-9658",
]


def preflight():
    problems = []
    if not os.path.exists(VENV_PY):
        problems.append(f"venv python missing: {VENV_PY}")

    # The hooks are the system under test — an unregistered hook would run
    # a perfectly clean control-vs-control comparison and report nothing.
    try:
        settings = json.load(open(os.path.expanduser("~/.claude/settings.json")))
    except (OSError, json.JSONDecodeError):
        settings = {}
    for event, script in install_hooks.HOOKS.items():
        entries = [h for g in settings.get("hooks", {}).get(event, [])
                   for h in g.get("hooks", [])
                   if install_hooks.mentions(h, script)]
        if not entries:
            problems.append(
                f"{event} hook not registered — run "
                f"{INTEGRATION}/install_hooks.py first")

    valid = set()
    try:
        for line in open(os.path.join(HERE, "validation.jsonl")):
            rec = json.loads(line)
            if rec.get("valid"):
                valid.add(rec["instance_id"])
    except OSError:
        problems.append("validation.jsonl missing — run run_stream.py --validate")
    missing = [i for i in PILOT_IDS if i not in valid]
    if missing and valid:
        problems.append(f"pilot tasks not validated: {missing}")

    by_id = {t["instance_id"]: t for t in rs.TASKS}
    absent = [i for i in PILOT_IDS if i not in by_id]
    if absent:
        problems.append(f"pilot tasks not in tasks_v2.json: {absent}")
    return problems, by_id


def run_session(task, arm):
    """rs.run_session with the pilot's DB, sessions dir, and label prefix.
    Everything the agent sees (prompt, tools, turn cap) stays identical to
    run_stream so July numbers remain comparable."""
    clone, venv = rs.prepare("sphinx", arm, task)
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": DB}
    cmd = [rs.AB, "--arm", arm, "--label", f"pilot2-{task['instance_id']}",
           "-p", rs.PROMPT.format(repo="sphinx",
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
    with open(os.path.join(SESSIONS, f"{task['instance_id']}.{arm}.log"), "w") as f:
        f.write(_text(getattr(r, "stdout", "")))
        f.write("\n--- STDERR ---\n")
        f.write(_text(getattr(r, "stderr", "")))
    return clone, venv, wall, timed_out


def ratify(scope):
    r = subprocess.run([VENV_PY, os.path.join(HERE, "ratify_staged.py"),
                        "--db", DB, "--scope", scope],
                       capture_output=True, text=True, timeout=360)
    out = (r.stdout or "").strip()
    if out:
        print(f"    {out}", flush=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"ratify_staged.py failed (exit {r.returncode}): "
            f"{(r.stderr or '')[-300:]} — stopping so the backlog cannot "
            "leak into the next session's review nudge")


def main():
    dry = "--dry-run" in sys.argv
    problems, by_id = preflight()
    if problems:
        for p in problems:
            print(f"PREFLIGHT: {p}")
        sys.exit(1)
    print(f"preflight ok: 10 tasks, store at {DB}")
    if dry:
        return

    os.makedirs(PILOT_DIR, exist_ok=True)
    done = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS):
            rec = json.loads(line)
            done.add((rec["instance_id"], rec["arm"]))
    if done:
        print(f"resuming: {len(done)} session(s) already recorded")

    # Strip the managed memory block from ~/.claude/CLAUDE.md for the run
    # window; the finally puts it back even on Ctrl-C. install_hooks owns
    # the fence, so this touches nothing else in the file.
    for change in install_hooks.sync_claude_md(remove=True):
        print(f"CLAUDE.md: {change}")
    try:
        with open(RESULTS, "a") as sink:
            for iid in PILOT_IDS:
                task = by_id[iid]
                for arm in ("control", "rfm"):
                    if (iid, arm) in done:
                        continue
                    print(f"=== {iid} [{arm}] ({task['difficulty']}) ===",
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
                           "resolved": resolved, "wall_s": round(wall),
                           "timed_out": timed_out, "detail": detail}
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    print(f"    resolved={resolved} wall={round(wall)}s {detail}",
                          flush=True)
                    if arm == "rfm":
                        ratify("sphinx")
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
