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


JUDGE_MAP = os.path.join(DIR, "judged_map.json")
JUDGE_PROMPT = """A user asked a software team's assistant:

REQUEST: {q}

These stored facts about the team's work may be relevant. Which are
NEEDED to answer correctly? Topical relation alone does not count.

{cands}

Reply JSON only: {{"needed": [numbers]}} — at most 3, empty if none."""


def precompute_judged():
    """Offline: per (instance, question), cosine-prefilter the store and
    judge which facts are applicable. Cached to judged_map.json. This is
    the retrieval DECISION the live hook makes; run here because an LLM
    judge cannot run inside a per-turn hook (REVALIDATION Track 21b)."""
    import math
    import re as _re
    import struct as _struct
    from fastembed import TextEmbedding
    model = TextEmbedding(model_name=EMBEDDER_ID)
    model.model.tokenizer.enable_truncation(max_length=256)

    def enc(t):
        v = next(iter(model.embed([t[:2000]])))
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def cos(qv, blob):
        m = _struct.unpack(f"{len(blob)//4}f", blob)
        return sum(a * b for a, b in zip(qv, m))

    os.makedirs(DIR, exist_ok=True)
    cache = {}
    if os.path.exists(JUDGE_MAP):
        cache = json.load(open(JUDGE_MAP))
    inst = t20.usable(t20.instances())
    for i in inst:
        db = sqlite3.connect(t20.store_path(i))
        mems = db.execute("SELECT id, content, embedding FROM rfm_memories "
                          "WHERE embedding IS NOT NULL").fetchall()
        db.close()
        for qi, q in enumerate(i["questions"]):
            key = f"{i['id']}#{qi}"
            if key in cache:
                continue
            qv = enc(q)
            ranked = sorted(mems, key=lambda r: -cos(qv, r[2]))[:8]
            numbered = "\n".join(f"{k+1}. {c[:220]}"
                                 for k, (_m, c, _b) in enumerate(ranked))
            try:
                r = subprocess.run(
                    ["claude", "-p",
                     JUDGE_PROMPT.format(q=q[:400], cands=numbered),
                     "--model", "haiku"],
                    env={**os.environ, "RFM_HOOKS_OFF": "1"},
                    capture_output=True, text=True, timeout=90)
                mm = _re.search(r"\{.*\}", r.stdout or "", _re.S)
                nums = json.loads(mm.group(0)).get("needed", []) if mm else []
            except Exception:
                nums = []
            applic = [ranked[n - 1][1] for n in nums
                      if isinstance(n, int) and 1 <= n <= len(ranked)][:3]
            cache[key] = applic
            with open(JUDGE_MAP, "w") as f:
                json.dump(cache, f, indent=1)
        print(f"  judged {i['id']} ({len(i['questions'])}q)", flush=True)
    print(f"precompute done: {len(cache)} question-keys")


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


def run_instance(inst, arm_name, judged):
    """Precomputed judged retrieval: the perturn arm prepends the
    judge-selected facts to each question; control gets the bare
    question. No hook — delivery is in the prompt (REVALIDATION Track
    21b architecture correction)."""
    wd, has_repo = t20.build_workspace(inst)
    env = {**os.environ, "RFM_HOOKS_OFF": "1",
           "RFM_MEMORY_DB": t20.store_path(inst)}
    t0 = time.time()
    given, sid, delivered = [], None, 0
    for qi, q in enumerate(inst["questions"]):
        facts = (judged.get(f"{inst['id']}#{qi}", [])
                 if arm_name == "perturn" else [])
        if facts:
            delivered += 1
            prompt = ("Relevant notes from the team's memory (use if "
                      "helpful):\n" + "\n".join(f"- {f}" for f in facts)
                      + f"\n\n{q}")
        else:
            prompt = q
        ans, sid = turn(prompt, wd, env, sid)
        m = re.search(r"\[ANSWER[^\]]*\]\s*(.+)", ans) if ans else None
        given.append((m.group(1).strip() if m else ans.strip()[:200]))
    wall = time.time() - t0
    os.makedirs(SESSIONS, exist_ok=True)
    with open(os.path.join(SESSIONS, f"{inst['id']}.{arm_name}.json"),
              "w") as f:
        json.dump({"given": given}, f, indent=1)
    shutil.rmtree(wd, ignore_errors=True)
    return given, wall, delivered


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
    if "--precompute" in sys.argv:
        precompute_judged()
        return
    inst = t20.usable(t20.instances())
    print(f"usable instances {len(inst)}, cli {rs.cli_version()}")
    if "--dry-run" in sys.argv:
        return
    if "--smoke" in sys.argv:
        inst = inst[:int(sys.argv[sys.argv.index("--smoke") + 1])]
    if not os.path.exists(JUDGE_MAP):
        sys.exit("PREFLIGHT: judged_map.json missing — run --precompute first")
    judged = json.load(open(JUDGE_MAP))

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
                for arm_name in ("control", "perturn"):
                    if (i["id"], arm_name) in done:
                        continue
                    print(f"=== {i['id']} [{arm_name}] "
                          f"({len(i['questions'])}q) ===", flush=True)
                    given, wall, delivered = run_instance(i, arm_name, judged)
                    rec = {"id": i["id"], "arm": arm_name, "track": "track21b",
                           "model": MODEL, "cli": cli,
                           "nq": len(i["questions"]),
                           "answered": sum(1 for g in given if g),
                           "delivered": delivered,
                           "given": [g[:120] for g in given],
                           "wall_s": round(wall)}
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    print(f"    answered {rec['answered']}/{rec['nq']} "
                          f"delivered {delivered} wall={round(wall)}s",
                          flush=True)
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
