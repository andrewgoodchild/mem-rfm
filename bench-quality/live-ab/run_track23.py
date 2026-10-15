#!/usr/bin/env python3
"""Track 23 — show-on-error, live: does a memory shown only when its
condition fires help, and does it avoid Track 19's injection tax?

Track 19 injected the era memory at SessionStart into every sweep-arm
session; the agent rarely met the condition (P1: 1 of 20 control
sessions) and paid +25% wall for carrying it. Show-on-error inverts the
delivery: nothing is shown until the condition appears in a Bash result,
so a session that never meets it carries nothing.

Two changes from Track 19, both disclosed in the registration:
  1. The condition is made to bind: the prompt requires the fix to be
     verified by running the task's existing fail-to-pass test FILES
     bare, and --validate keeps only tasks where that run shows the era
     class before any fix (LLM-free).
  2. Delivery is the rfm-live mod (integrations/claude-code/mod/rfm-live),
     loaded with --plugin-dir in the show arm only: memories surface on
     the failing result, and outcomes are recorded live through
     mod_bridge.py. No global hooks, no SessionStart injection, no MCP
     server in either arm (both run ab-claude's empty MCP config).

The store is a copy of Track 19's end-of-run store (the era memory,
26 sightings, 0 outcomes), taken once; the mod's live outcomes then
accumulate in it across the run, as they would in use.

Each session's transcript is copied into track23/transcripts/ as soon as
the session ends (Claude Code's 30-day cleanup deleted the transcripts
of every earlier track).

Modes:
  run_track23.py --validate     LLM-free pool probe; writes
                                validation-track23.jsonl.
  run_track23.py --smoke ID     one session pair on a task OUTSIDE the
                                pool, into track23-smoke/ (plumbing only).
  run_track23.py [--dry-run]    the paired run (after registration).
"""
import glob
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_stream as rs        # noqa: E402
import run_reval as rv         # noqa: E402  (clause-free PROMPT)
import run_track19 as t19      # noqa: E402  (stubs builder, F2P, era regex)

INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
import install_hooks           # noqa: E402

MOD = os.path.join(INTEGRATION, "mod", "rfm-live")
SEED = os.path.join(HERE, "track19", "rfm-memory.db")
VFILE = os.path.join(HERE, "validation-track23.jsonl")
MODEL = "claude-fable-5-1"
ARMS = (("control", "control", False), ("show", "rfm", True))
MIN_POOL = 12

VERIFY = ("\n\nYour fix counts as verified only when `python -m pytest -q "
          "{files}` runs without errors. Run it before you finish.")


# The friction under test: plugins too new for the checkout's Sphinx.
# rs.prepare only ever ADDS to the arm's venv, so an agent that "fixes"
# the environment by downgrading these (or by dropping a sitecustomize
# shim into site-packages) fixes it for every later session of that arm
# -- the shared venvs were found in exactly that state before this track.
# reset_env restores the era break before every session and the probe.
ERA_PACKAGES = ["alabaster", "sphinxcontrib-applehelp", "sphinxcontrib-devhelp",
                "sphinxcontrib-htmlhelp", "sphinxcontrib-serializinghtml",
                "sphinxcontrib-qthelp"]


def reset_env(venv):
    """Latest plugin releases (they require Sphinx >= 5), no shims; returns
    the installed versions, stamped into each record."""
    env = {**os.environ, "VIRTUAL_ENV": venv}
    r = rs.sh(["uv", "pip", "install", "-q", "--upgrade", *ERA_PACKAGES],
              env=env)
    if r.returncode != 0:
        raise RuntimeError(f"reset_env: {r.stderr[-300:]}")
    for name in ("sitecustomize.py", "usercustomize.py"):
        for hit in glob.glob(f"{venv}/lib/python*/site-packages/{name}"):
            os.remove(hit)
    r = rs.sh([f"{venv}/bin/python", "-c",
               "import importlib.metadata as m, json, sys; print(json.dumps("
               "{d: m.version(d) for d in sys.argv[1:]}))", *ERA_PACKAGES])
    return json.loads(r.stdout) if r.returncode == 0 else {}


def test_files(task):
    return sorted({t.split("::")[0] for t in task["fail_to_pass"]})


def prompt(task):
    return rv.PROMPT.format(
        repo="sphinx", problem=task["problem_statement"],
        tests_dir=rs.REPO["sphinx"]["tests_dir"]) + VERIFY.format(
            files=" ".join(test_files(task)))


def paths(out):
    return {"dir": out, "db": os.path.join(out, "rfm-memory.db"),
            "results": os.path.join(out, "results.jsonl"),
            "sessions": os.path.join(out, "sessions"),
            "transcripts": os.path.join(out, "transcripts")}


# ------------------------------------------------------------- validate

def validate(by_id):
    """Pool = Track 19's validated tasks whose fail-to-pass test files,
    run bare BEFORE any fix and without the test patch (what the agent
    will run), show the era class."""
    t19_pool = [json.loads(l)["instance_id"] for l in open(t19.VFILE)
                if json.loads(l).get("valid")]
    ok = 0
    with open(VFILE, "w") as sink:
        for iid in t19_pool:
            task = by_id[iid]
            rec = {"instance_id": iid, "files": test_files(task)}
            try:
                clone, venv = rs.prepare("sphinx", "control", task)
                rec["env"] = reset_env(venv)
                r = subprocess.run(
                    [f"{venv}/bin/python", "-m", "pytest", "-q",
                     *rec["files"]], cwd=clone, capture_output=True,
                    text=True, timeout=900)
                out = (r.stdout or "") + (r.stderr or "")
                rec.update(era_bare=bool(t19.ERA_RE.search(out)),
                           exit=r.returncode)
                rec["valid"] = rec["era_bare"]
                ok += rec["valid"]
            except Exception as e:
                rec.update(valid=False, reason=str(e)[:200])
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            print(f"{iid[-10:]}: {'POOL' if rec.get('valid') else 'excluded'}"
                  f" {rec.get('reason', '')}", flush=True)
    print(f"\npool: {ok}/{len(t19_pool)}", flush=True)


# ------------------------------------------------------------- sessions

def preflight():
    """Only the mod may act: no rfm hooks in the user's settings, no rfm
    block in CLAUDE.md, and the mod and its bridge present."""
    problems = []
    try:
        settings = json.load(open(os.path.expanduser(
            "~/.claude/settings.json")))
    except (OSError, json.JSONDecodeError):
        settings = {}
    for event, script in install_hooks.HOOKS.items():
        if [h for g in settings.get("hooks", {}).get(event, [])
                for h in g.get("hooks", [])
                if install_hooks.mentions(h, script)]:
            problems.append(f"rfm {event} hook is installed; remove it "
                            "(install_hooks.py --remove) for this track")
    if install_hooks.sync_claude_md(dry=True, remove=True):
        problems.append("rfm block present in ~/.claude/CLAUDE.md")
    for p in (os.path.join(MOD, ".claude-plugin", "plugin.json"),
              os.path.join(INTEGRATION, "mod_bridge.py"), SEED):
        if not os.path.exists(p):
            problems.append(f"missing {p}")
    return problems


def clean_session_state(out):
    for pat in t19.TMP_GLOBS:
        for path in glob.glob(pat):
            (shutil.rmtree if os.path.isdir(path) else os.remove)(path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for _, ab_arm, _ in ARMS:
        mem = rs.builtin_memory_dir("sphinx", ab_arm)
        if os.path.isdir(mem):
            dst = os.path.join(out, "builtin-archive", f"{ab_arm}-{stamp}")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(mem, dst)


def transcript_of(session_id):
    """The session's own transcript, found by the id the runner gave it.
    (ab-claude's sidecar is written by the SessionStart hook, which this
    track does not install, so its last line belongs to another run.)"""
    hits = glob.glob(os.path.join(os.path.expanduser("~/.claude/projects"),
                                  "*", f"{session_id}.jsonl"))
    return hits[0] if len(hits) == 1 else None


def run_session(task, arm_name, ab_arm, with_mod, p):
    clone, venv = rs.prepare("sphinx", ab_arm, task)
    era_env = reset_env(venv)
    label = f"track23-{task['instance_id']}-{arm_name}"
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": p["db"]}
    # Both arms on ab-claude's control config (empty MCP): the only
    # difference between them is the mod.
    session_id = str(uuid.uuid4())
    cmd = [rs.AB, "--arm", "control", "--label", label, "-p", prompt(task),
           "--session-id", session_id,
           "--max-turns", rs.MAX_TURNS, "--allowedTools", rs.ALLOWED,
           "--model", MODEL]
    if with_mod:
        cmd += ["--plugin-dir", MOD]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=clone, env=env, capture_output=True,
                           text=True, timeout=rs.SESSION_TIMEOUT)
        timed_out = False
    except subprocess.TimeoutExpired as e:
        r, timed_out = e, True
    wall = time.time() - t0

    def _text(x):
        if isinstance(x, bytes):
            return x.decode("utf-8", errors="replace")
        return x if isinstance(x, str) else ""
    os.makedirs(p["sessions"], exist_ok=True)
    with open(os.path.join(p["sessions"],
                           f"{task['instance_id']}.{arm_name}.log"), "w") as f:
        f.write(_text(getattr(r, "stdout", "")))
        f.write("\n--- STDERR ---\n")
        f.write(_text(getattr(r, "stderr", "")))
    tp = transcript_of(session_id)
    saved = None
    if tp and os.path.exists(tp):
        os.makedirs(p["transcripts"], exist_ok=True)
        saved = os.path.join(p["transcripts"],
                             f"{task['instance_id']}.{arm_name}.jsonl")
        shutil.copy2(tp, saved)
    return clone, venv, wall, timed_out, saved, era_env


def ledger(db):
    con = sqlite3.connect(db)
    try:
        return [list(r) for r in con.execute(
            "SELECT id, outcome_count, round(value_score, 3) "
            "FROM rfm_memories ORDER BY id")]
    finally:
        con.close()


def run_pairs(ids, by_id, p, track):
    os.makedirs(p["dir"], exist_ok=True)
    if not os.path.exists(p["db"]):
        src = sqlite3.connect(SEED)
        dst = sqlite3.connect(p["db"])
        src.backup(dst)
        dst.close()
        src.close()
    done = set()
    if os.path.exists(p["results"]):
        for line in open(p["results"]):
            r = json.loads(line)
            done.add((r["instance_id"], r["arm"]))
    if done:
        print(f"resuming: {len(done)} session(s) recorded")
    cli = rs.cli_version()
    with open(p["results"], "a") as sink:
        for iid in ids:
            task = by_id[iid]
            for arm_name, ab_arm, with_mod in ARMS:   # control first
                if (iid, arm_name) in done:
                    continue
                print(f"=== {iid} [{arm_name}] ({task['difficulty']}) ===",
                      flush=True)
                clean_session_state(p["dir"])
                clone, venv, wall, timed_out, saved, era_env = run_session(
                    task, arm_name, ab_arm, with_mod, p)
                t19.build_stubs(venv)
                if not rs.apply_test_patch(clone, task):
                    resolved, detail = None, "SCORING ERROR: test_patch"
                else:
                    try:
                        resolved, _, detail = t19.f2p(clone, venv, task,
                                                      stubs=True)
                    except subprocess.TimeoutExpired:
                        resolved, detail = None, "SCORING ERROR: F2P timeout"
                rec = {"instance_id": iid, "repo": "sphinx",
                       "difficulty": task["difficulty"], "arm": arm_name,
                       "track": track, "model": MODEL, "cli": cli,
                       "resolved": resolved, "wall_s": round(wall),
                       "timed_out": timed_out, "detail": detail,
                       "transcript": saved and os.path.relpath(saved, HERE),
                       "env": era_env, "ledger": ledger(p["db"])}
                sink.write(json.dumps(rec) + "\n")
                sink.flush()
                print(f"    resolved={resolved} wall={round(wall)}s "
                      f"{detail}", flush=True)


def main():
    by_id = {t["instance_id"]: t for t in json.load(
        open(os.path.join(HERE, "tasks_v2.json")))}
    if "--validate" in sys.argv:
        validate(by_id)
        return
    problems = preflight()
    if "--smoke" in sys.argv:
        iid = sys.argv[sys.argv.index("--smoke") + 1]
        pool = {json.loads(l)["instance_id"] for l in open(VFILE)} \
            if os.path.exists(VFILE) else set()
        if iid in pool:
            problems.append(f"{iid} is a pool task; smoke runs use "
                            "tasks outside the pool")
        if problems:
            for x in problems:
                print(f"PREFLIGHT: {x}")
            sys.exit(1)
        run_pairs([iid], by_id, paths(os.path.join(HERE, "track23-smoke")),
                  "track23-smoke")
        return
    try:
        pool = [json.loads(l)["instance_id"] for l in open(VFILE)
                if json.loads(l).get("valid")]
    except OSError:
        problems.append("validation-track23.jsonl missing — run --validate")
        pool = []
    if len(pool) < MIN_POOL:
        problems.append(f"pool has {len(pool)} tasks; registration "
                        f"requires >= {MIN_POOL}")
    if problems:
        for x in problems:
            print(f"PREFLIGHT: {x}")
        sys.exit(1)
    print(f"preflight ok: {len(pool)} pool tasks x 2 arms = "
          f"{2 * len(pool)} sessions, model {MODEL}, cli {rs.cli_version()}")
    if "--dry-run" in sys.argv:
        return
    run_pairs(pool, by_id, paths(os.path.join(HERE, "track23")), "track23")


if __name__ == "__main__":
    main()
