#!/usr/bin/env python3
"""Registered revalidation runner — see REVALIDATION.md (committed before
any session runs; the stack is frozen at the registration commit).

  python3 run_reval.py pytest [--dry-run]   # Track 1: two-phase, empty store
  python3 run_reval.py sphinx [--dry-run]   # Track 2: hold-out era, pilot-4 seed

Both tracks: clean-room before the FIRST session only (resumes never
re-clean — pilot 4's boundary lesson), paired arms, ratify after each
rfm session, pilot 3's prompt, results/log/store under reval-<track>/.
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
import run_pilot3 as p3        # noqa: E402  (frozen prompt)

INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
import install_hooks  # noqa: E402

# Registered Tracks 1-3 ran p3.PROMPT, which keeps "If memory tools are
# available, check them..." — a harness artifact that forces memory
# engagement real sessions don't have (Track 3 measured it at 0-2 calls
# per session against a thin store: pure cost, and part of a FAIL).
# Future runs use the clause-free prompt: the injection trailer is the
# only memory steering, as in real usage.
PROMPT = p3.PROMPT.replace(
    "\n\nIf memory tools are available, check them for relevant lessons "
    "from earlier work on this codebase before exploring,.", "")
assert PROMPT != p3.PROMPT, "prompt surgery no longer matches"

TRACKS = {
    "pytest": {
        "repo": "pytest",
        # REVALIDATION.md Track 1: phase A accumulates, phase B measures.
        "phases": {
            "A": ["pytest-dev__pytest-5631", "pytest-dev__pytest-5787",
                  "pytest-dev__pytest-5809", "pytest-dev__pytest-5840",
                  "pytest-dev__pytest-6197"],
            "B": ["pytest-dev__pytest-6202", "pytest-dev__pytest-8399",
                  "pytest-dev__pytest-10051", "pytest-dev__pytest-10081",
                  "pytest-dev__pytest-10356"],
        },
        "seed": None,
        "tmp": ["/tmp/pytest*"],
    },
    "sphinx": {
        "repo": "sphinx",
        "phases": {
            "A": ["sphinx-doc__sphinx-10323", "sphinx-doc__sphinx-10449",
                  "sphinx-doc__sphinx-10466", "sphinx-doc__sphinx-10673",
                  "sphinx-doc__sphinx-11445", "sphinx-doc__sphinx-11510"],
        },
        "seed": os.path.join(HERE, "pilot4", "rfm-memory.db"),
        "tmp": ["/tmp/sphinx*", "/tmp/*_repro", "/tmp/napoleon_repro"],
    },
    "xarray": {
        "repo": "xarray",
        # REVALIDATION.md Track 3: chronological halves, all 22 validated.
        # Phase A accumulates (2019-04..2020-12), phase B measures
        # (2020-12..2022-12; the 2022 era shift inside B is disclosed).
        "phases": {
            "A": ["pydata__xarray-2905",
                  "pydata__xarray-3095",
                  "pydata__xarray-3151",
                  "pydata__xarray-3305",
                  "pydata__xarray-3677",
                  "pydata__xarray-3993",
                  "pydata__xarray-4075",
                  "pydata__xarray-4094",
                  "pydata__xarray-4356",
                  "pydata__xarray-4629",
                  "pydata__xarray-4687"],
            "B": ["pydata__xarray-4695",
                  "pydata__xarray-4966",
                  "pydata__xarray-6461",
                  "pydata__xarray-6599",
                  "pydata__xarray-6721",
                  "pydata__xarray-6744",
                  "pydata__xarray-6938",
                  "pydata__xarray-6992",
                  "pydata__xarray-7229",
                  "pydata__xarray-7233",
                  "pydata__xarray-7393"],
        },
        "seed": None,
        "tmp": ["/tmp/xarray*", "/tmp/*_repro"],
        "tasks_file": "tasks_xarray.json",
        "validation_file": "validation-xarray.jsonl",
    },
}


def clone_mem_dirs(repo):
    return [rs.builtin_memory_dir(repo, arm) for arm in ("control", "rfm")]


def preflight(track):
    problems = []
    if not os.path.exists(p2.VENV_PY):
        problems.append(f"venv python missing: {p2.VENV_PY}")
    try:
        settings = json.load(open(os.path.expanduser("~/.claude/settings.json")))
    except (OSError, json.JSONDecodeError):
        settings = {}
    for event, script in install_hooks.HOOKS.items():
        if not [h for g in settings.get("hooks", {}).get(event, [])
                for h in g.get("hooks", []) if install_hooks.mentions(h, script)]:
            problems.append(f"{event} hook not registered — run install_hooks.py")
    vfile = os.path.join(HERE, track.get("validation_file", "validation.jsonl"))
    valid = set()
    try:
        for line in open(vfile):
            rec = json.loads(line)
            if rec.get("valid"):
                valid.add(rec["instance_id"])
    except OSError:
        problems.append(f"{os.path.basename(vfile)} missing — run with --validate first")
    ids = [i for ph in track["phases"].values() for i in ph]
    missing = [i for i in ids if i not in valid]
    if missing and valid:
        problems.append(f"not validated: {missing}")
    if track["seed"] and not os.path.exists(track["seed"]):
        problems.append(f"seed store missing: {track['seed']}")
    tfile = os.path.join(HERE, track.get("tasks_file", "tasks_v2.json"))
    by_id = {t["instance_id"]: t for t in json.load(open(tfile))}
    absent = [i for i in ids if i not in by_id]
    if absent:
        problems.append(f"not in {os.path.basename(tfile)}: {absent}")
    return problems, by_id


def clean_room(track, pilot_dir):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for mem in clone_mem_dirs(track["repo"]):
        if os.path.isdir(mem):
            arm = "rfm" if "-rfm" in mem else "control"
            dst = os.path.join(pilot_dir, "builtin-archive", f"{arm}-{stamp}")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(mem, dst)
            print(f"clean-room: archived built-in memory -> {dst}")
    for pat in track["tmp"]:
        for path in glob.glob(pat):
            (shutil.rmtree if os.path.isdir(path) else os.remove)(path)
            print(f"clean-room: removed {path}")


def run_session(track, task, arm, db, sessions_dir):
    repo = track["repo"]
    clone, venv = rs.prepare(repo, arm, task)
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": db}
    cmd = [rs.AB, "--arm", arm,
           "--label", f"reval-{repo}-{task['instance_id']}",
           "-p", PROMPT.format(repo=repo,
                                  problem=task["problem_statement"],
                                  tests_dir=rs.REPO[repo]["tests_dir"]),
           "--max-turns", rs.MAX_TURNS, "--allowedTools", rs.ALLOWED]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=clone, env=env, capture_output=True,
                           text=True, timeout=rs.SESSION_TIMEOUT)
        timed_out = False
    except subprocess.TimeoutExpired as e:
        r, timed_out = e, True
    wall = time.time() - t0
    os.makedirs(sessions_dir, exist_ok=True)

    def _text(x):
        if isinstance(x, bytes):
            return x.decode("utf-8", errors="replace")
        return x if isinstance(x, str) else ""
    with open(os.path.join(sessions_dir,
                           f"{task['instance_id']}.{arm}.log"), "w") as f:
        f.write(_text(getattr(r, "stdout", "")))
        f.write("\n--- STDERR ---\n")
        f.write(_text(getattr(r, "stderr", "")))
    return clone, venv, wall, timed_out


def ratify(track, db):
    r = subprocess.run([p2.VENV_PY, os.path.join(HERE, "ratify_staged.py"),
                        "--db", db, "--scope", track["repo"]],
                       capture_output=True, text=True, timeout=360)
    out = (r.stdout or "").strip()
    if out:
        print(f"    {out}", flush=True)
    if r.returncode != 0:
        raise RuntimeError(f"ratify_staged.py failed (exit {r.returncode}): "
                           f"{(r.stderr or '')[-300:]}")


def validate(track, by_id):
    """LLM-free gate, same checks as run_stream.validate: gold test patch
    applies, F2P fails pre-fix, passes with the gold patch. Writes the
    track's validation file; the run skips tasks that fail."""
    repo = track["repo"]
    vfile = os.path.join(HERE, track.get("validation_file", "validation.jsonl"))
    ok = 0
    ids = [i for ph in track["phases"].values() for i in ph]
    with open(vfile, "w") as sink:
        for iid in ids:
            task = by_id[iid]
            rec = {"instance_id": iid, "repo": repo}
            try:
                clone, venv = rs.prepare(repo, "control", task)
                if not rs.apply_test_patch(clone, task):
                    raise RuntimeError("test_patch apply failed")
                pre_pass, _ = rs.run_f2p(clone, venv, task)
                if pre_pass:
                    raise RuntimeError("F2P passes pre-fix")
                r = rs.sh(["git", "-C", clone, "apply", "-"],
                          input=task["gold_patch"])
                if r.returncode != 0:
                    raise RuntimeError("gold patch apply failed")
                post_pass, tail = rs.run_f2p(clone, venv, task)
                if not post_pass:
                    raise RuntimeError(f"F2P fails WITH gold patch: {tail}")
                rec["valid"] = True
                ok += 1
            except (RuntimeError, Exception) as e:
                rec.update(valid=False, reason=str(e)[:200])
            finally:
                clone = os.path.join(HERE, "clones", f"{repo}-control")
                rs.sh(["git", "-C", clone, "checkout", "-qf", task["base_commit"]])
                rs.sh(["git", "-C", clone, "clean", "-fdq"])
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            print(f"{iid}: {'ok' if rec['valid'] else 'EXCLUDED: ' + rec['reason']}",
                  flush=True)
    print(f"validated {ok}/{len(ids)}", flush=True)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1 or args[0] not in TRACKS:
        sys.exit(f"usage: run_reval.py {{{'|'.join(TRACKS)}}} [--dry-run]")
    name, track = args[0], TRACKS[args[0]]
    pilot_dir = os.path.join(HERE, f"reval-{name}")
    db = os.path.join(pilot_dir, "rfm-memory.db")
    results = os.path.join(pilot_dir, "results.jsonl")
    sessions_dir = os.path.join(pilot_dir, "sessions")

    if "--validate" in sys.argv:
        tfile = os.path.join(HERE, track.get("tasks_file", "tasks_v2.json"))
        by_id = {t["instance_id"]: t for t in json.load(open(tfile))}
        validate(track, by_id)
        return
    problems, by_id = preflight(track)
    if problems:
        for p in problems:
            print(f"PREFLIGHT: {p}")
        sys.exit(1)
    n = sum(len(v) for v in track["phases"].values())
    print(f"preflight ok: track={name}, {n} paired tasks, store at {db}")
    if "--dry-run" in sys.argv:
        return

    os.makedirs(pilot_dir, exist_ok=True)
    if track["seed"] and not os.path.exists(db):
        shutil.copy(track["seed"], db)
        print(f"seeded store from {track['seed']}")

    done = set()
    if os.path.exists(results):
        for line in open(results):
            rec = json.loads(line)
            done.add((rec["instance_id"], rec["arm"]))
    if done:
        print(f"resuming: {len(done)} session(s) recorded (clean-room skipped)")
    else:
        clean_room(track, pilot_dir)

    for change in install_hooks.sync_claude_md(remove=True):
        print(f"CLAUDE.md: {change}")
    try:
        with open(results, "a") as sink:
            for phase, ids in track["phases"].items():
                for iid in ids:
                    task = by_id[iid]
                    for arm in ("control", "rfm"):
                        if (iid, arm) in done:
                            continue
                        print(f"=== {iid} [{arm}/reval-{name}/{phase}] "
                              f"({task['difficulty']}) ===", flush=True)
                        clone, venv, wall, timed_out = run_session(
                            track, task, arm, db, sessions_dir)
                        if not rs.apply_test_patch(clone, task):
                            resolved, detail = None, "SCORING ERROR: test_patch failed to apply"
                        else:
                            try:
                                resolved, detail = rs.run_f2p(clone, venv, task)
                            except subprocess.TimeoutExpired:
                                resolved, detail = None, "SCORING ERROR: F2P run timed out"
                        rec = {"instance_id": iid, "repo": track["repo"],
                               "difficulty": task["difficulty"], "arm": arm,
                               "track": name, "phase": phase,
                               "resolved": resolved, "wall_s": round(wall),
                               "timed_out": timed_out, "detail": detail}
                        sink.write(json.dumps(rec) + "\n")
                        sink.flush()
                        print(f"    resolved={resolved} wall={round(wall)}s "
                              f"{detail}", flush=True)
                        if arm == "rfm":
                            ratify(track, db)
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
