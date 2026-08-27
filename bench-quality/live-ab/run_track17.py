#!/usr/bin/env python3
"""Track 17 — formation-tier matching (REVALIDATION.md, registered before
any session). Haiku's own struggles, mined and tested on haiku, xarray.

  Phase A: 11 first-half tasks, control arm only (struggle collection).
  Phase B: 11 second-half tasks, paired none/mined arms; requires
           store-track17.json (committed after formation review).

Usage: run_track17.py A|B [--dry-run]
"""
import json
import glob
import os
import shutil
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import run_stream as rs        # noqa: E402
import run_reval as rv         # noqa: E402  (clause-free PROMPT)

INTEGRATION = os.path.join(ROOT, "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
import install_hooks           # noqa: E402

DIR = os.path.join(HERE, "track17")
DB = os.path.join(DIR, "rfm-memory.db")
SPEC = os.path.join(HERE, "store-track17.json")
RESULTS = os.path.join(DIR, "results.jsonl")
SESSIONS = os.path.join(DIR, "sessions")
MODEL = "claude-haiku-4-5-20251001"
TMP_GLOBS = ["/tmp/xarray*", "/tmp/*_repro"]

PHASES = {
    "A": ["pydata__xarray-2905", "pydata__xarray-3095", "pydata__xarray-3151",
          "pydata__xarray-3305", "pydata__xarray-3677", "pydata__xarray-3993",
          "pydata__xarray-4075", "pydata__xarray-4094", "pydata__xarray-4356",
          "pydata__xarray-4629", "pydata__xarray-4687"],
    "B": ["pydata__xarray-4695", "pydata__xarray-4966", "pydata__xarray-6461",
          "pydata__xarray-6599", "pydata__xarray-6721", "pydata__xarray-6744",
          "pydata__xarray-6938", "pydata__xarray-6992", "pydata__xarray-7229",
          "pydata__xarray-7233", "pydata__xarray-7393"],
}
ARMS = {"A": [("none", "control")],
        "B": [("none", "control"), ("mined", "rfm")]}


def clean_session_state():
    for pat in TMP_GLOBS:
        for path in glob.glob(pat):
            (shutil.rmtree if os.path.isdir(path) else os.remove)(path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for arm in ("control", "rfm"):
        mem = rs.builtin_memory_dir("xarray", arm)
        if os.path.isdir(mem):
            dst = os.path.join(DIR, "builtin-archive", f"{arm}-{stamp}")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(mem, dst)
    pending = os.path.join(DIR, "pending-memories.md")
    if os.path.exists(pending):
        os.remove(pending)


def build_store():
    """Fresh store from the committed spec: cold ledgers (created_at only),
    condition_class stamped from the spec — this store earns its own
    outcomes under the conditioned gate."""
    s = json.load(open(SPEC))
    if os.path.exists(DB):
        os.remove(DB)
    db = sqlite3.connect(DB)
    db.executescript(open(os.path.join(ROOT, "rfm_schema.sql")).read())
    db.execute("ALTER TABLE rfm_memories ADD COLUMN condition_class TEXT")
    for i, m in enumerate(s["memories"], 1):
        db.execute(
            "INSERT INTO rfm_memories (id, content, created_at,"
            " condition_class) VALUES (?, ?, ?, ?)",
            (i, m["content"], time.time(), m.get("condition_class", "")))
    db.commit()
    db.close()


def run_session(task, phase, arm_name, ab_arm):
    clone, venv = rs.prepare("xarray", ab_arm, task)
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": DB}
    cmd = [rs.AB, "--arm", ab_arm,
           "--label", f"track17-{task['instance_id']}-{phase}{arm_name}",
           "-p", rv.PROMPT.format(repo="xarray",
                                  problem=task["problem_statement"],
                                  tests_dir=rs.REPO["xarray"]["tests_dir"]),
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
                           f"{task['instance_id']}.{phase}{arm_name}.log"),
              "w") as f:
        f.write(_text(getattr(r, "stdout", "")))
        f.write("\n--- STDERR ---\n")
        f.write(_text(getattr(r, "stderr", "")))
    return clone, venv, wall, timed_out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1 or args[0] not in PHASES:
        sys.exit("usage: run_track17.py A|B [--dry-run]")
    phase = args[0]
    problems = []
    valid = {json.loads(l)["instance_id"]
             for l in open(os.path.join(HERE, "validation-xarray.jsonl"))
             if json.loads(l).get("valid")}
    missing = [i for i in PHASES[phase] if i not in valid]
    if missing:
        problems.append(f"not validated: {missing}")
    by_id = {t["instance_id"]: t for t in json.load(
        open(os.path.join(HERE, "tasks_xarray.json")))}
    absent = [i for i in PHASES[phase] if i not in by_id]
    if absent:
        problems.append(f"not in tasks_xarray.json: {absent}")
    if phase == "B":
        if not os.path.exists(SPEC):
            problems.append(f"{SPEC} missing — commit the reviewed store "
                            f"before Phase B (registration order)")
        else:
            mems = json.load(open(SPEC))["memories"]
            if not (1 <= len(mems) <= 6):
                problems.append(f"spec has {len(mems)} memories, "
                                f"registered bound is 1..6")
            bad = [m for m in mems if not m.get("condition_class")]
            if bad:
                problems.append(f"{len(bad)} memories missing the mandatory "
                                f"condition_class")
    if problems:
        for p in problems:
            print(f"PREFLIGHT: {p}")
        sys.exit(1)
    n = len(PHASES[phase]) * len(ARMS[phase])
    print(f"preflight ok: phase {phase}, {n} sessions, model {MODEL}, "
          f"cli {rs.cli_version()}")
    if "--dry-run" in sys.argv:
        return

    os.makedirs(DIR, exist_ok=True)
    done = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS):
            r = json.loads(line)
            done.add((r["instance_id"], r["phase"], r["arm"]))
    if done:
        print(f"resuming: {len(done)} session(s) already recorded")

    cli = rs.cli_version()
    for change in install_hooks.sync_claude_md(remove=True):
        print(f"CLAUDE.md: {change}")
    try:
        with open(RESULTS, "a") as sink:
            for iid in PHASES[phase]:
                task = by_id[iid]
                for arm_name, ab_arm in ARMS[phase]:
                    if (iid, phase, arm_name) in done:
                        continue
                    print(f"=== {iid} [{phase}/{arm_name}] "
                          f"({task['difficulty']}) ===", flush=True)
                    clean_session_state()
                    if ab_arm == "rfm":
                        build_store()
                    clone, venv, wall, timed_out = run_session(
                        task, phase, arm_name, ab_arm)
                    if not rs.apply_test_patch(clone, task):
                        resolved, detail = None, "SCORING ERROR: test_patch failed"
                    else:
                        try:
                            resolved, detail = rs.run_f2p(clone, venv, task)
                        except subprocess.TimeoutExpired:
                            resolved, detail = None, "SCORING ERROR: F2P timed out"
                    rec = {"instance_id": iid, "repo": "xarray",
                           "difficulty": task["difficulty"], "arm": arm_name,
                           "phase": phase, "track": "track17",
                           "model": MODEL, "cli": cli,
                           "resolved": resolved, "wall_s": round(wall),
                           "timed_out": timed_out, "detail": detail}
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    print(f"    resolved={resolved} wall={round(wall)}s "
                          f"{detail}", flush=True)
                    # No ratify: formation happens once, between phases,
                    # reviewed and committed — not during the runs.
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
