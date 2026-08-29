#!/usr/bin/env python3
"""Track 21b — per-turn retrieval, the fresh causal test (REVALIDATION.md).
Questions presented ONE PER TURN via `claude -p --resume`, so the
UserPromptSubmit per-turn hook (RFM_PERTURN) retrieves against each
question. Reuses Track 20's stores (embeddings backfilled), Track 20's
workspaces, and the 21a judge for scoring.

Modes:
  run_track21b.py --embed-stores   backfill MiniLM embeddings into the
                                   Track 20 stores (no LLM; idempotent)
  run_track21b.py --smoke N        drive N instances, both arms, report
  run_track21b.py [--dry-run]      the full paired run

Requires the UserPromptSubmit hook registered (install_hooks.py).
"""
import glob
import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, HERE)
INTEGRATION = os.path.join(ROOT, "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
sys.path.insert(0, os.path.join(INTEGRATION, "hooks"))
import run_stream as rs        # noqa: E402
import run_track20 as t20      # noqa: E402  (workspace, instances, judge reuse)
import install_hooks          # noqa: E402

DIR = os.path.join(HERE, "track21b")
STORES = os.path.join(HERE, "track20", "stores")
RESULTS = os.path.join(DIR, "results.jsonl")
SESSIONS = os.path.join(DIR, "sessions")
MODEL = "claude-fable-5"
EMBEDDER_ID = "sentence-transformers/all-MiniLM-L6-v2"


def embed_stores():
    from fastembed import TextEmbedding
    import math
    model = TextEmbedding(model_name=EMBEDDER_ID)
    model.model.tokenizer.enable_truncation(max_length=256)

    def enc(t):
        v = next(iter(model.embed([t[:2000]])))
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return struct.pack(f"{len(v)}f", *[x / n for x in v])

    n_stores = 0
    for db_path in sorted(glob.glob(os.path.join(STORES, "*.db"))):
        db = sqlite3.connect(db_path)
        cols = [r[1] for r in db.execute("PRAGMA table_info(rfm_memories)")]
        if "embedding" not in cols:
            db.execute("ALTER TABLE rfm_memories ADD COLUMN embedding BLOB")
        todo = db.execute("SELECT id, content FROM rfm_memories "
                          "WHERE embedding IS NULL").fetchall()
        for mid, content in todo:
            db.execute("UPDATE rfm_memories SET embedding=? WHERE id=?",
                       (enc(str(content)), mid))
        db.commit()
        db.close()
        n_stores += 1
    print(f"embedded {n_stores} stores")


def turn(question, cwd, env, resume_sid):
    cmd = ["claude", "-p", question, "--model", MODEL,
           "--output-format", "json",
           "--allowedTools", "Bash,Read,Grep,Glob"]
    if resume_sid:
        cmd += ["--resume", resume_sid]
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                           text=True, timeout=600)
        out = json.loads(r.stdout or "{}")
        return out.get("result", ""), out.get("session_id")
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return "", resume_sid


def run_instance(inst, arm_name, ab_arm):
    wd, has_repo = t20.build_workspace(inst)
    env = {**os.environ, "RFM_AB_ARM": ab_arm,
           "RFM_MEMORY_DB": t20.store_path(inst),
           "RFM_AB_SESSION": f"21b-{inst['id']}-{arm_name}"}
    if ab_arm == "rfm":
        env["RFM_PERTURN"] = "1"
    else:
        env.pop("RFM_PERTURN", None)
    t0 = time.time()
    given, sid = [], None
    for q in inst["questions"]:
        ans, sid = turn(q, wd, env, sid)
        m = re.search(r"\[ANSWER[^\]]*\]\s*(.+)", ans) if ans else None
        given.append((m.group(1).strip() if m else ans.strip()[:200]))
    wall = time.time() - t0
    os.makedirs(SESSIONS, exist_ok=True)
    with open(os.path.join(SESSIONS, f"{inst['id']}.{arm_name}.json"),
              "w") as f:
        json.dump({"given": given}, f, indent=1)
    shutil.rmtree(wd, ignore_errors=True)
    return given, wall


def inj_count(iid, arm):
    """per-turn retrievals logged for this instance/arm."""
    log = os.path.join(STORES, "rfm-log.jsonl")
    n = 0
    if os.path.exists(log):
        for l in open(log):
            r = json.loads(l)
            if r.get("op") == "perturn_retrieval" and r.get("injected"):
                n += 1
    return n


def main():
    if "--embed-stores" in sys.argv:
        embed_stores()
        return
    inst = t20.usable(t20.instances())
    print(f"usable instances {len(inst)}, cli {rs.cli_version()}")
    # ensure the per-turn hook is registered
    for ev, sc in install_hooks.HOOKS.items():
        pass
    if "--dry-run" in sys.argv:
        return
    if "--smoke" in sys.argv:
        inst = inst[:int(sys.argv[sys.argv.index("--smoke") + 1])]
    missing = [i["id"] for i in inst
               if not os.path.exists(t20.store_path(i))]
    if missing:
        sys.exit(f"PREFLIGHT: stores missing {missing[:3]}")
    # verify embeddings present
    s0 = sqlite3.connect(t20.store_path(inst[0]))
    if "embedding" not in [r[1] for r in
                           s0.execute("PRAGMA table_info(rfm_memories)")]:
        s0.close()
        sys.exit("PREFLIGHT: stores lack embeddings — run --embed-stores")
    s0.close()

    os.makedirs(DIR, exist_ok=True)
    done = set()
    if os.path.exists(RESULTS):
        for l in open(RESULTS):
            r = json.loads(l)
            done.add((r["id"], r["arm"]))
    cli = rs.cli_version()
    for change in install_hooks.sync_claude_md(remove=True):
        print(f"CLAUDE.md: {change}")
    try:
        with open(RESULTS, "a") as sink:
            for i in inst:
                for arm_name, ab_arm in (("control", "control"),
                                         ("perturn", "rfm")):
                    if (i["id"], arm_name) in done:
                        continue
                    print(f"=== {i['id']} [{arm_name}] "
                          f"({len(i['questions'])}q) ===", flush=True)
                    given, wall = run_instance(i, arm_name, ab_arm)
                    rec = {"id": i["id"], "arm": arm_name, "track": "track21b",
                           "model": MODEL, "cli": cli,
                           "nq": len(i["questions"]),
                           "answered": sum(1 for g in given if g),
                           "given": [g[:120] for g in given],
                           "wall_s": round(wall)}
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    print(f"    answered {rec['answered']}/{rec['nq']} "
                          f"wall={round(wall)}s", flush=True)
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
