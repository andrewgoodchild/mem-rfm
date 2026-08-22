#!/usr/bin/env python3
"""Extended paired A/B stream: harder tasks, longer accumulation.

Task list: tasks_v2.json — pytest's remaining 11 tasks (continuing the pilot's
memory store) then sphinx's full 44-task sequence (fresh per-repo store),
chronological within repo. Protocol identical to run_pilot.py; scoring is
pytest-node-id based for both repos (sphinx's suite runs on pytest).

Modes:
  --validate   no LLM: for every task check (a) gold test_patch applies,
               (b) FAIL_TO_PASS fails pre-fix, (c) passes with the gold
               patch applied. Writes validation.jsonl; the run skips tasks
               that failed validation.
  (default)    run the paired sessions for validated tasks.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AB = os.path.join(HERE, "..", "..", "integrations", "claude-code", "ab", "ab-claude")
TASKS = json.load(open(os.path.join(HERE, "tasks_v2.json")))
SESSION_TIMEOUT = 30 * 60
MAX_TURNS = "60"

REPO = {
    "pytest": {"tests_dir": "testing/", "memory_db": "rfm-memory.db"},
    "sphinx": {"tests_dir": "tests/", "memory_db": "rfm-memory-sphinx.db"},
    "xarray": {"tests_dir": "xarray/tests/", "memory_db": "rfm-memory-xarray.db"},
}


def era_pins(repo, task):
    """Version pins so era-appropriate deps resolve: old sphinx needs
    pkg_resources (gone in new setuptools), pytest<8 plugin API, jinja2<3.1
    (environmentfilter), markupsafe<2.1, docutils<0.18 (sphinx 3.x).
    xarray: numpy<1.24 (np.bool removal breaks pre-2023 code), pandas eras,
    setuptools-scm for the legacy setup.py builds."""
    created = task["created_at"]
    if repo == "pytest":
        return ["hypothesis"]
    if repo == "xarray":
        # arm64 floor: numpy grows Apple-Silicon wheels at 1.21, pandas at
        # 1.3 — older pins cannot install on this host. numpy<1.24 caps the
        # np.bool removal that breaks pre-2023 code.
        pins = ["setuptools-scm", "packaging", "pytest<8"]
        if created < "2022":
            pins += ["numpy>=1.21,<1.24", "pandas>=1.3,<1.4"]
        elif created < "2023":
            pins += ["numpy<1.24", "pandas<2"]
        return pins
    if created >= "2023":
        return []
    pins = ["pytest<7.2", "setuptools<60", "jinja2<3.1", "markupsafe<2.1"]
    if created < "2022":
        pins.append("docutils<0.18")
    return pins

PROMPT = """You are working in a checkout of the {repo} project. A user filed this bug report:

<bug_report>
{problem}
</bug_report>

Fix the bug in the SOURCE code of this checkout. Do not commit. Do not modify files under {tests_dir} — the fix belongs in the library source. Verify your change by writing a tiny reproduction or running closely related existing tests with `python -m pytest` (the project is installed editable in the active environment). Keep the change minimal and idiomatic.

If memory tools are available, check them for relevant lessons from earlier work on this codebase before exploring, and save any durable, non-obvious lesson you learn (APIs, gotchas, structure) when done."""

ALLOWED = "Bash,Edit,Write,Read,Grep,Glob,mcp__rfm-memory"


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def paths(repo, arm):
    return (os.path.join(HERE, "clones", f"{repo}-{arm}"),
            os.path.join(HERE, "clones", f"{repo}-{arm}-venv"))


def prepare(repo, arm, task):
    clone, venv = paths(repo, arm)
    r = sh(["git", "-C", clone, "checkout", "-qf", task["base_commit"]])
    if r.returncode != 0:
        raise RuntimeError(f"checkout {task['base_commit']} failed: {r.stderr[-200:]}")
    sh(["git", "-C", clone, "clean", "-fdq"])
    env = {**os.environ, "VIRTUAL_ENV": venv}
    if repo == "xarray" and task["created_at"] < "2022":
        # Legacy xarray setup.py imports pkg_resources at build time; uv's
        # isolated build env ignores venv pins and would use setuptools 81+
        # (pkg_resources removed). Constrain the BUILD env instead — <81
        # still ships pkg_resources and the PEP 660 editable hook.
        env["UV_BUILD_CONSTRAINT"] = os.path.join(
            HERE, "build-constraints-legacy.txt")
    spec = f"{clone}[test]" if repo == "sphinx" else clone
    r = sh(["uv", "pip", "install", "-q", "-e", spec,
            *era_pins(repo, task)], env=env)
    if r.returncode != 0:
        raise RuntimeError(f"install: {r.stderr[-300:]}")
    return clone, venv


def apply_test_patch(clone, task):
    for line in task["test_patch"].splitlines():
        if line.startswith("+++ b/"):
            sh(["git", "-C", clone, "checkout", "-q", "--", line.split()[1][2:]])
    return sh(["git", "-C", clone, "apply", "-"], input=task["test_patch"]).returncode == 0


def run_f2p(clone, venv, task):
    r = sh([f"{venv}/bin/python", "-m", "pytest", "-q", *task["fail_to_pass"]],
           cwd=clone, timeout=900)
    tail = (r.stdout or "").strip().splitlines()
    return r.returncode == 0, (tail[-1] if tail else (r.stderr or "")[-120:])


def validate():
    sink = open(os.path.join(HERE, "validation.jsonl"), "w")
    ok = 0
    for task in TASKS:
        repo = task["repo"]
        rec = {"instance_id": task["instance_id"], "repo": repo}
        try:
            clone, venv = prepare(repo, "control", task)
            if not apply_test_patch(clone, task):
                raise RuntimeError("test_patch apply failed")
            pre_pass, pre_tail = run_f2p(clone, venv, task)
            if pre_pass:
                raise RuntimeError("F2P passes pre-fix")
            r = sh(["git", "-C", clone, "apply", "-"], input=task["gold_patch"])
            if r.returncode != 0:
                raise RuntimeError("gold patch apply failed")
            post_pass, post_tail = run_f2p(clone, venv, task)
            if not post_pass:
                raise RuntimeError(f"F2P fails WITH gold patch: {post_tail}")
            rec["valid"] = True
            ok += 1
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            rec.update(valid=False, reason=str(e)[:200])
        finally:
            clone, _ = paths(repo, "control")
            sh(["git", "-C", clone, "checkout", "-qf", task["base_commit"]])
            sh(["git", "-C", clone, "clean", "-fdq"])
        sink.write(json.dumps(rec) + "\n")
        sink.flush()
        print(f"{task['instance_id']}: {'ok' if rec['valid'] else 'EXCLUDED: ' + rec['reason']}",
              flush=True)
    print(f"\nvalidated {ok}/{len(TASKS)}", flush=True)


def run_session(repo, arm, task, clone, venv):
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": os.path.join(HERE, REPO[repo]["memory_db"])}
    cmd = [AB, "--arm", arm, "--label", f"swe-{task['instance_id']}",
           "-p", PROMPT.format(repo=repo, problem=task["problem_statement"],
                               tests_dir=REPO[repo]["tests_dir"]),
           "--max-turns", MAX_TURNS, "--allowedTools", ALLOWED]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=clone, env=env, capture_output=True,
                           text=True, timeout=SESSION_TIMEOUT)
        timed_out = False
    except subprocess.TimeoutExpired as e:
        r, timed_out = e, True
    wall = time.time() - t0
    os.makedirs(os.path.join(HERE, "sessions"), exist_ok=True)
    def _text(x):
        if isinstance(x, bytes):
            return x.decode("utf-8", errors="replace")
        return x if isinstance(x, str) else ""
    with open(os.path.join(HERE, "sessions", f"{task['instance_id']}.{arm}.log"), "w") as f:
        f.write(_text(getattr(r, "stdout", "")))
        f.write("\n--- STDERR ---\n")
        f.write(_text(getattr(r, "stderr", "")))
    return wall, timed_out


def main():
    if "--validate" in sys.argv:
        validate()
        return
    valid = {json.loads(l)["instance_id"]
             for l in open(os.path.join(HERE, "validation.jsonl"))
             if json.loads(l).get("valid")}
    results_path = os.path.join(HERE, "results.jsonl")
    done = set()
    if os.path.exists(results_path):
        for line in open(results_path):
            rec = json.loads(line)
            done.add((rec["instance_id"], rec["arm"]))
    with open(results_path, "a") as sink:
        for task in TASKS:
            if task["instance_id"] not in valid:
                continue
            repo = task["repo"]
            for arm in ("control", "rfm"):
                if (task["instance_id"], arm) in done:
                    continue
                print(f"=== {task['instance_id']} [{arm}] ({task['difficulty']}) ===",
                      flush=True)
                clone, venv = prepare(repo, arm, task)
                wall, timed_out = run_session(repo, arm, task, clone, venv)
                if not apply_test_patch(clone, task):
                    resolved, detail = None, "SCORING ERROR: test_patch failed to apply"
                else:
                    try:
                        resolved, detail = run_f2p(clone, venv, task)
                    except subprocess.TimeoutExpired:
                        resolved, detail = None, "SCORING ERROR: F2P run timed out"
                rec = {"instance_id": task["instance_id"], "repo": repo,
                       "difficulty": task["difficulty"], "arm": arm,
                       "resolved": resolved, "wall_s": round(wall),
                       "timed_out": timed_out, "detail": detail}
                sink.write(json.dumps(rec) + "\n")
                sink.flush()
                print(f"    resolved={resolved} wall={round(wall)}s {detail}",
                      flush=True)


if __name__ == "__main__":
    main()
