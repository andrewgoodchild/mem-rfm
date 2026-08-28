#!/usr/bin/env python3
"""Track 19 — the rebuilt testbed: era-locked sphinx tasks, sweep stack
live. (Registration lands in REVALIDATION.md after --validate commits
the pool; sessions only after that.)

The pool is built from the sphinx tasks the original validation
EXCLUDED because their fail-to-pass tests are app-based: on these
checkouts the too-new sphinxcontrib/alabaster venv makes every
verification attempt die with VersionRequirementError until the stubs
workaround exists. The condition fires by construction — the friction
Tracks 10–17 never had. Scoring applies the stubs (the harness must be
able to judge the fix); sessions run BARE (the agent must face, and
solve, the environment).

Modes:
  run_track19.py --validate     LLM-free triple over the candidates:
                                bare F2P shows the era class; stubs
                                F2P pre-fix genuinely fails; stubs F2P
                                with gold patch passes. Writes
                                validation-track19.jsonl.
  run_track19.py [--dry-run]    the paired run (after registration).
"""
import glob
import json
import os
import re
import shutil
import sqlite3
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

DIR = os.path.join(HERE, "track19")
DB = os.path.join(DIR, "rfm-memory.db")
RESULTS = os.path.join(DIR, "results.jsonl")
SESSIONS = os.path.join(DIR, "sessions")
VFILE = os.path.join(HERE, "validation-track19.jsonl")
STUBS = os.path.join(HERE, "clones", "era-stubs")
MODEL = "claude-fable-5"
TMP_GLOBS = ["/tmp/sphinx*", "/tmp/*_repro", "/tmp/napoleon_repro"]

# The 27 sphinx tasks the original validation excluded; the triple
# decides which belong to the pool. Chronological.
CANDIDATES = [
    "sphinx-doc__sphinx-7440", "sphinx-doc__sphinx-7748",
    "sphinx-doc__sphinx-7985", "sphinx-doc__sphinx-8035",
    "sphinx-doc__sphinx-8120", "sphinx-doc__sphinx-8265",
    "sphinx-doc__sphinx-8269", "sphinx-doc__sphinx-8459",
    "sphinx-doc__sphinx-8475", "sphinx-doc__sphinx-8548",
    "sphinx-doc__sphinx-8551", "sphinx-doc__sphinx-8593",
    "sphinx-doc__sphinx-8595", "sphinx-doc__sphinx-8621",
    "sphinx-doc__sphinx-8638", "sphinx-doc__sphinx-8721",
    "sphinx-doc__sphinx-9229", "sphinx-doc__sphinx-9230",
    "sphinx-doc__sphinx-9258", "sphinx-doc__sphinx-9461",
    "sphinx-doc__sphinx-9591", "sphinx-doc__sphinx-9602",
    "sphinx-doc__sphinx-9673", "sphinx-doc__sphinx-9698",
    "sphinx-doc__sphinx-9711", "sphinx-doc__sphinx-10435",
    "sphinx-doc__sphinx-10614",
]

ERA_RE = re.compile(r"VersionRequirementError|ExtensionError")


def build_stubs(venv):
    """The era workaround, as committed harness code — used at SCORING
    time only. Sessions never see this; discovering the workaround is
    the task's recurring friction."""
    sc = os.path.join(STUBS, "sphinxcontrib")
    os.makedirs(sc, exist_ok=True)
    with open(os.path.join(sc, "__init__.py"), "w") as f:
        f.write("__path__ = __import__('pkgutil')"
                ".extend_path(__path__, __name__)\n")
    for m in ("applehelp", "devhelp", "htmlhelp", "serializinghtml",
              "qthelp"):
        with open(os.path.join(sc, f"{m}.py"), "w") as f:
            f.write("def setup(app):\n    return {'version': 'stub', "
                    "'parallel_read_safe': True}\n")
    al = os.path.join(STUBS, "alabaster")
    os.makedirs(al, exist_ok=True)
    hits = glob.glob(f"{venv}/lib/python*/site-packages/alabaster")
    real = os.path.abspath(hits[0]) if hits else ""
    with open(os.path.join(al, "__init__.py"), "w") as f:
        f.write(f"import os\n__version__ = '0.7.11'\n_REAL = {real!r}\n"
                f"if _REAL and os.path.isdir(_REAL):\n"
                f"    __path__.append(_REAL)\n"
                f"def get_path():\n"
                f"    return os.path.dirname(_REAL) if _REAL else "
                f"os.path.dirname(os.path.abspath(__file__))\n"
                f"def setup(app):\n    return {{'version': 'stub', "
                f"'parallel_read_safe': True}}\n")


def f2p(clone, venv, task, stubs):
    env = dict(os.environ)
    if stubs:
        env["PYTHONPATH"] = STUBS
    r = subprocess.run([f"{venv}/bin/python", "-m", "pytest", "-q",
                        *task["fail_to_pass"]], cwd=clone, env=env,
                       capture_output=True, text=True, timeout=900)
    out = (r.stdout or "") + (r.stderr or "")
    summ = next((l for l in reversed(out.splitlines())
                 if re.search(r"\d+ (passed|failed|error)", l)), "")
    return r.returncode == 0, bool(ERA_RE.search(out)), summ[:80]


def validate(by_id):
    ok = 0
    with open(VFILE, "w") as sink:
        for iid in CANDIDATES:
            task = by_id[iid]
            rec = {"instance_id": iid}
            try:
                clone, venv = rs.prepare("sphinx", "control", task)
                build_stubs(venv)
                if not rs.apply_test_patch(clone, task):
                    raise RuntimeError("test_patch apply failed")
                _, era_bare, s0 = f2p(clone, venv, task, stubs=False)
                pre_pass, _, s1 = f2p(clone, venv, task, stubs=True)
                r = rs.sh(["git", "-C", clone, "apply", "-"],
                          input=task["gold_patch"])
                if r.returncode != 0:
                    raise RuntimeError("gold patch apply failed")
                gold_pass, _, s2 = f2p(clone, venv, task, stubs=True)
                rec.update(era_bare=era_bare, stubs_pre_fails=not pre_pass,
                           stubs_gold_passes=gold_pass,
                           valid=era_bare and not pre_pass and gold_pass,
                           detail=f"{s0} | {s1} | {s2}")
                ok += rec["valid"]
            except Exception as e:
                rec.update(valid=False, reason=str(e)[:200])
            finally:
                clone = os.path.join(HERE, "clones", "sphinx-control")
                rs.sh(["git", "-C", clone, "checkout", "-qf",
                       task["base_commit"]])
                rs.sh(["git", "-C", clone, "clean", "-fdq"])
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            print(f"{iid[-10:]}: "
                  f"{'POOL' if rec.get('valid') else 'excluded'} "
                  f"({rec.get('detail', rec.get('reason', ''))[:90]})",
                  flush=True)
    print(f"\npool: {ok}/{len(CANDIDATES)}", flush=True)


def clean_session_state():
    for pat in TMP_GLOBS:
        for path in glob.glob(pat):
            (shutil.rmtree if os.path.isdir(path) else os.remove)(path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for arm in ("control", "rfm"):
        mem = rs.builtin_memory_dir("sphinx", arm)
        if os.path.isdir(mem):
            dst = os.path.join(DIR, "builtin-archive", f"{arm}-{stamp}")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(mem, dst)
    # The gated miner's staging file: under the open-throttle stack the
    # sweep is the formation channel, and the staged-review note must
    # not spend the sweep arm's injection budget.
    pending = os.path.join(DIR, "pending-memories.md")
    if os.path.exists(pending):
        os.remove(pending)


def sweep_transcript():
    """After a sweep-arm session: find its transcript via the ab sidecar
    and run the open-throttle sweep against the track19 store."""
    sidecar = os.path.join(INTEGRATION, "ab", "ab_sessions.jsonl")
    with open(sidecar) as f:
        last = json.loads(f.readlines()[-1])
    tp = last.get("transcript_path")
    if not tp or not os.path.exists(tp):
        print("    sweep: no transcript found", flush=True)
        return
    listfile = os.path.join(DIR, "last-transcript.txt")
    with open(listfile, "w") as f:
        f.write(tp + "\n")
    venv_py = os.path.join(INTEGRATION, ".venv", "bin", "python")
    py = venv_py if os.path.exists(venv_py) else sys.executable
    r = subprocess.run([py, os.path.join(INTEGRATION, "sweep.py"),
                        "--replay", listfile],
                       env={**os.environ, "RFM_MEMORY_DB": DB},
                       capture_output=True, text=True, timeout=900)
    tail = (r.stdout or "").strip().splitlines()
    print(f"    {tail[-1] if tail else 'sweep: no output'}", flush=True)


def run_session(task, arm_name, ab_arm):
    clone, venv = rs.prepare("sphinx", ab_arm, task)
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": DB}
    cmd = [rs.AB, "--arm", ab_arm,
           "--label", f"track19-{task['instance_id']}-{arm_name}",
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
    by_id = {t["instance_id"]: t for t in json.load(
        open(os.path.join(HERE, "tasks_v2.json")))}
    if "--validate" in sys.argv:
        validate(by_id)
        return
    problems = []
    try:
        pool = [json.loads(l)["instance_id"] for l in open(VFILE)
                if json.loads(l).get("valid")]
    except OSError:
        problems.append("validation-track19.jsonl missing — run "
                        "--validate first")
        pool = []
    if len(pool) < 8:
        problems.append(f"pool has {len(pool)} tasks; the registration "
                        f"requires >= 8")
    try:
        settings = json.load(open(os.path.expanduser(
            "~/.claude/settings.json")))
    except (OSError, json.JSONDecodeError):
        settings = {}
    for event, script in install_hooks.HOOKS.items():
        if not [h for g in settings.get("hooks", {}).get(event, [])
                for h in g.get("hooks", [])
                if install_hooks.mentions(h, script)]:
            problems.append(f"{event} hook not registered")
    if problems:
        for p in problems:
            print(f"PREFLIGHT: {p}")
        sys.exit(1)
    print(f"preflight ok: {len(pool)} pool tasks x 2 arms = "
          f"{2 * len(pool)} sessions, model {MODEL}, "
          f"cli {rs.cli_version()}")
    if "--dry-run" in sys.argv:
        return

    os.makedirs(DIR, exist_ok=True)
    done = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS):
            r = json.loads(line)
            done.add((r["instance_id"], r["arm"]))
    if done:
        print(f"resuming: {len(done)} session(s) recorded")

    cli = rs.cli_version()
    for change in install_hooks.sync_claude_md(remove=True):
        print(f"CLAUDE.md: {change}")
    try:
        with open(RESULTS, "a") as sink:
            for iid in pool:
                task = by_id[iid]
                for arm_name, ab_arm in (("control", "control"),
                                         ("sweep", "rfm")):
                    if (iid, arm_name) in done:
                        continue
                    print(f"=== {iid} [{arm_name}] "
                          f"({task['difficulty']}) ===", flush=True)
                    clean_session_state()
                    clone, venv, wall, timed_out = run_session(
                        task, arm_name, ab_arm)
                    build_stubs(venv)
                    if not rs.apply_test_patch(clone, task):
                        resolved, detail = None, "SCORING ERROR: test_patch"
                    else:
                        try:
                            resolved, _, detail = f2p(clone, venv, task,
                                                      stubs=True)
                        except subprocess.TimeoutExpired:
                            resolved, detail = None, "SCORING ERROR: F2P timeout"
                    rec = {"instance_id": iid, "repo": "sphinx",
                           "difficulty": task["difficulty"],
                           "arm": arm_name, "ab_arm": ab_arm,
                           "track": "track19", "model": MODEL, "cli": cli,
                           "resolved": resolved, "wall_s": round(wall),
                           "timed_out": timed_out, "detail": detail}
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    print(f"    resolved={resolved} wall={round(wall)}s "
                          f"{detail}", flush=True)
                    if ab_arm == "rfm":
                        sweep_transcript()
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
