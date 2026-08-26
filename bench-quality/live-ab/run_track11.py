#!/usr/bin/env python3
"""Track 11 — same fact, four forms: a token-matched content ablation.

Registered in REVALIDATION.md before any session. One underlying fact — the
corpus's highest-value memory (pilot 4 store, id 2: the sphinx era-pin stubs
workaround) — delivered in four content forms plus two controls, on the 8
in-era sphinx tasks that neither minted nor amended it.

Arms, fixed order per task:
  none      control arm, no MCP server (Track 4: attachment tax is
            context-cost-only at this scale)
  placebo   rfm arm, store holds true-but-inapplicable content (Track 10's
            kept xarray memories, different technique family), same ledger
  prose     rfm arm, the fact described with no runnable command or path
  verbatim  rfm arm, the stored memory byte-identical
  abstract  rfm arm, the generalized recipe with placeholder commands

Constant treatment: the store is rebuilt from store-track11.json before
EVERY injected session (one memory, the flagship's earned ledger cloned, so
R/F/M state and the injection line's rank are identical across arms and
sessions — only the content differs). No ratify. /tmp artifacts and the
built-in auto-memory dirs are cleared before every session, because arms
share clones and the verbatim text names a /tmp stubs dir a prior arm's
session may have created.

Usage: run_track11.py [--dry-run]
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
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import run_stream as rs        # noqa: E402
import run_reval as rv         # noqa: E402  (clause-free PROMPT)
import rfm                     # noqa: E402  (floor-query preflight)

INTEGRATION = os.path.join(ROOT, "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
import install_hooks           # noqa: E402

DIR = os.path.join(HERE, "track11")
DB = os.path.join(DIR, "rfm-memory.db")
SPEC = os.path.join(HERE, "store-track11.json")
RESULTS = os.path.join(DIR, "results.jsonl")
SESSIONS = os.path.join(DIR, "sessions")
TMP_GLOBS = ["/tmp/sphinx*", "/tmp/*_repro", "/tmp/napoleon_repro"]

# The 10 in-era pilot tasks minus sphinx-7454 (its session minted the
# flagship memory) and sphinx-9658 (its checkout, 232dbe41c, is named in
# the memory text — that session amended it). Chronological.
TASKS = [
    "sphinx-doc__sphinx-7462", "sphinx-doc__sphinx-7757",
    "sphinx-doc__sphinx-7889", "sphinx-doc__sphinx-7910",
    "sphinx-doc__sphinx-8056", "sphinx-doc__sphinx-9281",
    "sphinx-doc__sphinx-9320", "sphinx-doc__sphinx-9367",
]

# (arm name, ab-claude arm, spec variant)
ARMS = [
    ("none", "control", None),
    ("placebo", "rfm", "placebo"),
    ("prose", "rfm", "prose"),
    ("verbatim", "rfm", "verbatim"),
    ("abstract", "rfm", "abstract"),
]

# Injection contract this run depends on (hooks/session_start.py): the
# whole memory must land as ONE unbroken line, so every variant plus the
# "- [1] " prefix must fit CHAR_BUDGET with no truncation.
CHAR_BUDGET = 1500
LINE_PREFIX = len("- [1] ")


def spec():
    return json.load(open(SPEC))


def build_store(variant):
    """Fresh single-memory store: the variant's text under the flagship's
    cloned ledger. Rebuilt before every injected session — no carryover."""
    s = spec()
    if os.path.exists(DB):
        os.remove(DB)
    db = sqlite3.connect(DB)
    db.executescript(open(os.path.join(ROOT, "rfm_schema.sql")).read())
    led = s["ledger"]
    db.execute(
        "INSERT INTO rfm_memories (id, content, created_at, access_count,"
        " last_access, bla_cache, value_score, outcome_count)"
        " VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
        (s["variants"][variant], led["created_at"], led["access_count"],
         led["last_access"], led["bla_cache"], led["value_score"],
         led["outcome_count"]))
    db.commit()
    db.close()


def floor_query_rows():
    """The exact selection the SessionStart hook runs."""
    db = sqlite3.connect(DB)
    rfm.register(db)
    rows = db.execute(
        "SELECT id, content, rfm_score(id) AS s FROM rfm_memories "
        "WHERE NOT (outcome_count > 0 AND value_score < 0) "
        "ORDER BY s DESC LIMIT 3").fetchall()
    db.close()
    return rows


def clean_session_state():
    """Before EVERY session: /tmp artifacts (the verbatim memory names a
    /tmp stubs dir another arm may have created), the built-in auto-memory
    dirs (arms share clones; that channel is not under test), and the
    staged-candidates file (its count would leak into the next session's
    injection note). rfm-log.jsonl is append-only audit and stays."""
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
    pending = os.path.join(DIR, "pending-memories.md")
    if os.path.exists(pending):
        os.remove(pending)


def preflight():
    problems = []
    s = spec()
    ref = len(s["variants"]["verbatim"])
    src = sqlite3.connect(os.path.join(HERE, "pilot4", "rfm-memory.db"))
    original = src.execute(
        "SELECT content FROM rfm_memories WHERE id=2").fetchone()[0]
    if s["variants"]["verbatim"] != original:
        problems.append("verbatim variant is not byte-identical to pilot4 "
                        "store memory 2")
    for name, text in s["variants"].items():
        if abs(len(text) - ref) > 0.10 * ref:
            problems.append(f"{name} variant {len(text)} chars is outside "
                            f"the registered ±10% band around {ref}")
        if len(text) + LINE_PREFIX > CHAR_BUDGET:
            problems.append(f"{name} variant would be truncated at injection")
        if "</memories>" in text:
            problems.append(f"{name} variant contains a close tag")
    if s["ledger"]["value_score"] <= 0:
        problems.append("cloned ledger value_score not positive — the "
                        "injection floor would exclude the memory")
    try:
        settings = json.load(open(os.path.expanduser("~/.claude/settings.json")))
    except (OSError, json.JSONDecodeError):
        settings = {}
    for event, script in install_hooks.HOOKS.items():
        if not [h for g in settings.get("hooks", {}).get(event, [])
                for h in g.get("hooks", []) if install_hooks.mentions(h, script)]:
            problems.append(f"{event} hook not registered — run install_hooks.py")
    valid = {json.loads(l)["instance_id"]
             for l in open(os.path.join(HERE, "validation.jsonl"))
             if json.loads(l).get("valid")}
    missing = [i for i in TASKS if i not in valid]
    if missing:
        problems.append(f"not validated: {missing}")
    by_id = {t["instance_id"]: t for t in json.load(
        open(os.path.join(HERE, "tasks_v2.json")))}
    absent = [i for i in TASKS if i not in by_id]
    if absent:
        problems.append(f"not in tasks_v2.json: {absent}")
    os.makedirs(DIR, exist_ok=True)
    for _name, _ab, variant in ARMS:
        if variant is None:
            continue
        build_store(variant)
        rows = floor_query_rows()
        if len(rows) != 1 or rows[0][0] != 1:
            problems.append(f"{variant}: floor query did not return the "
                            f"single seeded memory")
    return problems, by_id


def run_session(task, arm_name, ab_arm):
    clone, venv = rs.prepare("sphinx", ab_arm, task)
    env = {**os.environ,
           "PATH": f"{venv}/bin:{os.environ['PATH']}",
           "VIRTUAL_ENV": venv,
           "RFM_MEMORY_DB": DB}
    cmd = [rs.AB, "--arm", ab_arm,
           "--label", f"track11-{task['instance_id']}-{arm_name}",
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
                           f"{task['instance_id']}.{arm_name}.log"), "w") as f:
        f.write(_text(getattr(r, "stdout", "")))
        f.write("\n--- STDERR ---\n")
        f.write(_text(getattr(r, "stderr", "")))
    return clone, venv, wall, timed_out


def main():
    problems, by_id = preflight()
    if problems:
        for p in problems:
            print(f"PREFLIGHT: {p}")
        sys.exit(1)
    print(f"preflight ok: {len(TASKS)} tasks x {len(ARMS)} arms = "
          f"{len(TASKS) * len(ARMS)} sessions, store spec {SPEC}")
    if "--dry-run" in sys.argv:
        return

    done = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS):
            r = json.loads(line)
            done.add((r["instance_id"], r["arm"]))
    if done:
        print(f"resuming: {len(done)} session(s) already recorded")

    for change in install_hooks.sync_claude_md(remove=True):
        print(f"CLAUDE.md: {change}")
    try:
        with open(RESULTS, "a") as sink:
            for iid in TASKS:
                task = by_id[iid]
                for arm_name, ab_arm, variant in ARMS:
                    if (iid, arm_name) in done:
                        continue
                    print(f"=== {iid} [{arm_name}] "
                          f"({task['difficulty']}) ===", flush=True)
                    clean_session_state()
                    if variant is not None:
                        build_store(variant)
                    clone, venv, wall, timed_out = run_session(
                        task, arm_name, ab_arm)
                    if not rs.apply_test_patch(clone, task):
                        resolved, detail = None, "SCORING ERROR: test_patch failed"
                    else:
                        try:
                            resolved, detail = rs.run_f2p(clone, venv, task)
                        except subprocess.TimeoutExpired:
                            resolved, detail = None, "SCORING ERROR: F2P timed out"
                    rec = {"instance_id": iid, "repo": "sphinx",
                           "difficulty": task["difficulty"], "arm": arm_name,
                           "ab_arm": ab_arm, "track": "track11",
                           "resolved": resolved, "wall_s": round(wall),
                           "timed_out": timed_out, "detail": detail}
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    print(f"    resolved={resolved} wall={round(wall)}s "
                          f"{detail}", flush=True)
                    # Deliberately no ratify(): formation is not under test.
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
