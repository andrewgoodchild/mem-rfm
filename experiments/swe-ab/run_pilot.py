#!/usr/bin/env python3
"""Paired A/B pilot: does mem-rfm memory help an agent fix real pytest bugs?

Protocol per task (chronological, 8 tasks from SWE-Bench-CL's pytest
sequence): for each arm (control = no memory server, rfm = mem-rfm MCP
server with a store that accumulates across tasks):
  1. checkout the task's base commit in the ARM'S OWN clone (built-in Claude
     Code memory is per-project-path, so separate clones keep it arm-local)
  2. editable-install into the arm's venv
  3. launch a headless Claude Code session via ab-claude (--strict-mcp-config
     isolates the tool environment; identical prompt in both arms)
  4. score by the SWE-bench protocol: discard agent edits to gold-test files,
     apply the gold test_patch, run FAIL_TO_PASS; resolved = all pass
Results append to results.jsonl; session stdout to sessions/.

The agent never sees the gold patch or test patch. The prompt names the
failing behaviors only via the issue text.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AB = os.path.join(HERE, "..", "..", "integrations", "claude-code", "ab", "ab-claude")
TASKS = json.load(open(os.path.join(HERE, "tasks.json")))
MEMORY_DB = os.path.join(HERE, "rfm-memory.db")
SESSION_TIMEOUT = 25 * 60
MAX_TURNS = "50"

PROMPT = """You are working in a checkout of the pytest project. A user filed this bug report:

<bug_report>
{problem}
</bug_report>

Fix the bug in the SOURCE code of this checkout. Do not commit. Do not modify files under testing/ — the fix belongs in src/. Verify your change by writing a tiny reproduction or running closely related existing tests with `python -m pytest` (the project is installed editable in the active environment). Keep the change minimal and idiomatic.

If memory tools are available, check them for relevant lessons from earlier work on this codebase before exploring, and save any durable, non-obvious lesson you learn (APIs, gotchas, structure) when done."""

ALLOWED = "Bash,Edit,Write,Read,Grep,Glob,mcp__rfm-memory"


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def prepare(arm, task):
    clone = os.path.join(HERE, "clones", arm)
    venv = os.path.join(HERE, "clones", f"{arm}-venv")
    sh(["git", "-C", clone, "checkout", "-qf", task["base_commit"]])
    sh(["git", "-C", clone, "clean", "-fdq"])
    r = sh(["uv", "pip", "install", "-q", "-e", clone, "hypothesis"],
           env={**os.environ, "VIRTUAL_ENV": venv})
    if r.returncode != 0:
        raise RuntimeError(f"install failed: {r.stderr[-500:]}")
    return clone, venv


def run_session(arm, task, clone, venv):
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": MEMORY_DB}
    cmd = [AB, "--arm", arm, "--label", f"swe-{task['instance_id']}",
           "-p", PROMPT.format(problem=task["problem_statement"]),
           "--max-turns", MAX_TURNS,
           "--allowedTools", ALLOWED]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=clone, env=env, capture_output=True,
                           text=True, timeout=SESSION_TIMEOUT)
        timed_out = False
    except subprocess.TimeoutExpired as e:
        r, timed_out = e, True
    wall = time.time() - t0
    outdir = os.path.join(HERE, "sessions")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, f"{task['instance_id']}.{arm}.log"), "w") as f:
        f.write((r.stdout or "") if hasattr(r, "stdout") else "")
        f.write("\n--- STDERR ---\n")
        stderr = r.stderr if isinstance(getattr(r, "stderr", None), str) else ""
        f.write(stderr or "")
    return wall, timed_out


def score(arm, task, clone, venv):
    """SWE-bench scoring: reset gold-test files, apply test_patch, run F2P."""
    patch = task["test_patch"]
    touched = [l.split()[1][2:] for l in patch.splitlines()
               if l.startswith("+++ b/")]
    for f in touched:
        sh(["git", "-C", clone, "checkout", "-q", "--", f])
    r = sh(["git", "-C", clone, "apply", "-"], input=patch)
    if r.returncode != 0:
        return None, "test_patch failed to apply"
    # -q only: --no-header postdates the older pytest versions under test.
    r = sh([f"{venv}/bin/python", "-m", "pytest", "-q",
            *task["fail_to_pass"]], cwd=clone, timeout=600)
    tail = (r.stdout or "").strip().splitlines()
    return r.returncode == 0, (tail[-1] if tail else "")


def main():
    only = sys.argv[1:] or None
    results_path = os.path.join(HERE, "results.jsonl")
    done = set()
    if os.path.exists(results_path):
        for line in open(results_path):
            rec = json.loads(line)
            done.add((rec["instance_id"], rec["arm"]))
    with open(results_path, "a") as sink:
        for task in TASKS:
            if only and task["instance_id"] not in only:
                continue
            for arm in ("control", "rfm"):
                key = (task["instance_id"], arm)
                if key in done:
                    print(f"skip {key} (done)", flush=True)
                    continue
                print(f"=== {task['instance_id']} [{arm}] ===", flush=True)
                clone, venv = prepare(arm, task)
                wall, timed_out = run_session(arm, task, clone, venv)
                resolved, detail = score(arm, task, clone, venv)
                rec = {"instance_id": task["instance_id"], "arm": arm,
                       "resolved": resolved, "wall_s": round(wall),
                       "timed_out": timed_out, "detail": detail}
                sink.write(json.dumps(rec) + "\n")
                sink.flush()
                print(f"    resolved={resolved} wall={round(wall)}s {detail}",
                      flush=True)


if __name__ == "__main__":
    main()
