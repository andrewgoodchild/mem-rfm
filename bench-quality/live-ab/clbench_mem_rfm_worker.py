#!/usr/bin/env python3
"""The mem-rfm side of the Continual Learning Bench system (Track 36). Runs in
this repository's integration venv; clbench_mem_rfm.py calls it, one process
per call, JSON on stdin, JSON on stdout. Every payload carries "db".

  retrieve  {"query", "k", "floor"} -> [{"id", "content", "sim", "prior"}]
            cosine x rfm_prior over released rows above the floor, top k; each
            delivered row records an access (the per-turn hook's rule).
  learn     {"outcomes": [{"id", "value"}], "notes": [str]}
            -> {"outcomes", "admitted", "merged"}
            Outcomes first: one per access, so a memory whose latest access
            already carries an outcome gets a fresh access and then the
            outcome (session_end.record_outcomes' rule). Then the notes: a
            near-duplicate of a stored row bumps that row's sightings and
            records an access; anything else is inserted with sightings 1.
            Quarantine is off here (RFM_QUARANTINE=1): one agent, one source.
  dump      {} -> every row with its ledger, for the run artifact.
  selftest  no input; real embedder, exit 0 on pass.

Usage: clbench_mem_rfm_worker.py retrieve|learn|dump|selftest  < json
"""
import json
import os
import sqlite3
import struct
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
os.environ.setdefault("RFM_LOG", "0")
os.environ.setdefault("RFM_QUARANTINE", "1")
os.environ.setdefault("RFM_MEMORY_DB", os.path.join(tempfile.gettempdir(),
                                                    "mem-rfm-clb-unused.db"))
sys.path.insert(0, INTEGRATION)
sys.path.insert(0, os.path.join(INTEGRATION, "hooks"))
sys.path.insert(0, os.path.join(INTEGRATION, "..", ".."))
import rfm                       # noqa: E402
import secret_scan               # noqa: E402
import similarity                # noqa: E402
import store                     # noqa: E402
import sweep                     # noqa: E402
import transcripts               # noqa: E402
import user_prompt_submit as U   # noqa: E402

DEDUPE = float(sweep.CONFIG["dedupe_threshold"])


def open_db(path):
    db = sqlite3.connect(path, timeout=30.0)
    rfm.register(db)
    store.ensure(db)
    if not db.execute("SELECT 1 FROM rfm_host_meta WHERE key = 'embedder'").fetchone():
        store.stamp_embedder(db, U.EMBEDDER_ID, len(U.embed("x")))
    return db


def retrieve(payload):
    qvec = U.embed(payload["query"])
    db = open_db(payload["db"])
    rows = db.execute(
        "SELECT id, content, embedding, rfm_prior(id) AS prior "
        "FROM rfm_memories "
        "WHERE NOT (outcome_count > 0 AND value_score < 0) "
        f"AND {store.released()} AND {store.not_contradicted()} "
        "AND embedding IS NOT NULL").fetchall()
    floor = float(payload.get("floor", 0.0))
    scored = []
    for mid, content, blob, prior in rows:
        sim = U.cosine(qvec, blob)
        if sim >= floor:
            scored.append((sim * prior, sim, prior, mid, content))
    scored.sort(reverse=True)
    out = []
    for _score, sim, prior, mid, content in scored[: int(payload["k"])]:
        db.execute("SELECT rfm_record_access(?)", (mid,))
        out.append({"id": mid, "content": U.sanitize(content),
                    "sim": round(float(sim), 3), "prior": round(float(prior), 4)})
    db.commit()
    db.close()
    return out


def record_outcome(db, mid, value):
    row = db.execute(
        "SELECT outcome FROM rfm_accesses WHERE memory_id = ? "
        "ORDER BY accessed_at DESC, rowid DESC LIMIT 1", (mid,)).fetchone()
    if row is None or row[0] is not None:
        db.execute("SELECT rfm_record_access(?)", (mid,))
    db.execute("SELECT rfm_record_outcome(?, ?)", (mid, float(value)))


def learn(payload):
    db = open_db(payload["db"])
    done = 0
    for o in payload.get("outcomes", []):
        try:
            record_outcome(db, int(o["id"]), o["value"])
            done += 1
        except sqlite3.Error:
            continue
    admitted = merged = 0
    notes = [secret_scan.redact(transcripts.flatten(n))[0].strip()
             for n in payload.get("notes", []) if isinstance(n, str) and n.strip()]
    if notes:
        rows = db.execute("SELECT id, content FROM rfm_memories").fetchall()
        similarity.prime(notes + [c for _i, c in rows])
        for text in notes:
            best, _sim = sweep.best_match(text, rows)
            if best is not None:
                db.execute("SELECT rfm_record_access(?)", (best,))
                db.execute("UPDATE rfm_memories SET sightings = "
                           "COALESCE(sightings, 1) + 1 WHERE id = ?", (best,))
                merged += 1
                continue
            vec = U.embed(text)
            cur = db.execute(
                "INSERT INTO rfm_memories (content, created_at, embedding, "
                "sightings, source) VALUES (?, ?, ?, 1, 'clbench')",
                (text, time.time(), struct.pack(f"{len(vec)}f", *vec)))
            rows.append((cur.lastrowid, text))
            admitted += 1
    db.commit()
    db.close()
    return {"outcomes": done, "admitted": admitted, "merged": merged}


def dump(payload):
    if not os.path.exists(payload["db"]):
        return []
    db = open_db(payload["db"])
    rows = [dict(zip(("id", "content", "created_at", "access_count",
                      "value_score", "outcome_count", "sightings", "score"), r))
            for r in db.execute(
                "SELECT id, content, created_at, access_count, value_score, "
                "outcome_count, sightings, rfm_score(id) FROM rfm_memories "
                "ORDER BY id")]
    db.close()
    return rows


def selftest():
    tmp = tempfile.mkdtemp(prefix="mem-rfm-clb-test-")
    db = os.path.join(tmp, "store.db")
    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"  {'ok' if cond else 'FAIL'}  {name}")
        ok = ok and bool(cond)

    got = retrieve({"db": db, "query": "average price of office products", "k": 3,
                    "floor": 0.0})
    check("empty store returns nothing", got == [])
    r = learn({"db": db, "outcomes": [], "notes": [
        "Office products (`g1`) keep prices in `g1_items`.`prc` in cents; "
        "divide by 100 for dollars. [applies to: g1; seen: SELECT prc FROM g1_items]",
        "Electronics (`g2`) have no attributes table. [applies to: g2]",
        "Office products (`g1`) store prices in cents in the `prc` column of "
        "`g1_items`, so divide by 100. [applies to: g1]"]})
    check("two notes admitted, the paraphrase merged",
          r["admitted"] == 2 and r["merged"] == 1)
    got = retrieve({"db": db, "query": "average price of office products", "k": 3,
                    "floor": 0.0})
    # The electronics note has a negative cosine to this question, and a
    # negative similarity is excluded even with the floor at 0.
    check("retrieve returns the price fact first",
          bool(got) and "prc" in got[0]["content"])
    first = got[0]["id"]
    r = learn({"db": db, "outcomes": [{"id": first, "value": 1.0}], "notes": []})
    check("outcome lands on the delivered access", r["outcomes"] == 1)
    rows = {d["id"]: d for d in dump({"db": db})}
    check("ledger shows it", rows[first]["outcome_count"] == 1
          and rows[first]["value_score"] == 1.0 and rows[first]["sightings"] == 2)
    learn({"db": db, "outcomes": [{"id": first, "value": -1.0},
                                  {"id": first, "value": -1.0}], "notes": []})
    got = retrieve({"db": db, "query": "average price of office products", "k": 3,
                    "floor": 0.0})
    check("a row voted negative leaves delivery",
          first not in [g["id"] for g in got])
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


def main():
    command = sys.argv[1]
    if command == "selftest":
        return selftest()
    payload = json.load(sys.stdin)
    fn = {"retrieve": retrieve, "learn": learn, "dump": dump}[command]
    print(json.dumps(fn(payload)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
