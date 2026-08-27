#!/usr/bin/env python3
"""Acceptance audit for the open-throttle sweep (DESIGN_NOTES
2026-08-28). No LLM calls — these test the mechanical guarantees:
dedupe-as-frequency, provenance at admission, the quarantine gate, the
cap, and the conditioned outcome mapping. Exit 0 = pass.

Usage: test_sweep.py
"""
import os
import sqlite3
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="rfm-sweeptest-")
os.environ["RFM_MEMORY_DB"] = os.path.join(TMP, "test.db")
os.environ["RFM_LOG"] = "0"
sys.path.insert(0, HERE)
import sweep  # noqa: E402
sweep.DB_PATH = os.environ["RFM_MEMORY_DB"]
sweep.LOG = os.path.join(TMP, "rfm-log.jsonl")

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail
                                                   else ""))
    if not ok:
        failures.append(name)


def fresh():
    if os.path.exists(sweep.DB_PATH):
        os.remove(sweep.DB_PATH)
    db = sqlite3.connect(sweep.DB_PATH)
    sweep.ensure_schema(db)
    return db


MEM = {"content": "In this venv, dask is not installed so dask-chunked "
                  "tests are skipped; this is expected.",
       "condition_class": "not-installed", "action": "", "scope": "xarray"}

# 1. Admission inserts a cold, quarantined, condition-stamped row.
db = fresh()
mid = sweep.admit(db, MEM, [], "t1")
row = db.execute("SELECT sightings, condition_class, value_score, "
                 "outcome_count FROM rfm_memories WHERE id = ?",
                 (mid,)).fetchone()
check("admit: new row sightings=1, cold ledger, condition set",
      row == (1, "not-installed", 0.0, 0), str(row))

# 2. Near-duplicate does not insert — it bumps sightings and access.
mid2 = sweep.admit(db, {**MEM, "content": MEM["content"].replace(
    "expected", "normal and expected")}, [], "t2")
n = db.execute("SELECT count(*) FROM rfm_memories").fetchone()[0]
s = db.execute("SELECT sightings, access_count FROM rfm_memories "
               "WHERE id = ?", (mid,)).fetchone()
check("dedupe: near-dup merges, sightings and access bump",
      mid2 == mid and n == 1 and s == (2, 1), f"rows={n} {s}")

# 3. Provenance: an action the session never ran is dropped; a run one kept.
db = fresh()
composed = {**MEM, "content": "pkg_resources is missing in this venv.",
            "condition_class": "pkg_resources",
            "action": "pip install setuptools<81"}
mid = sweep.admit(db, composed, ["python -m pytest -q tests/"], "t3")
text = db.execute("SELECT content FROM rfm_memories WHERE id = ?",
                  (mid,)).fetchone()[0]
check("provenance: composed action dropped", "pip install" not in text, text)
db = fresh()
mid = sweep.admit(db, composed, ["uv pip install 'setuptools<81' -q"], "t4")
text = db.execute("SELECT content FROM rfm_memories WHERE id = ?",
                  (mid,)).fetchone()[0]
check("provenance: transcript-run action kept", "setuptools<81" in text, text)

# 4. Quarantine: sightings=1 not injectable; sightings>=2 and NULL are.
db = fresh()
sweep.admit(db, MEM, [], "t5")                                # sightings 1
db.execute("INSERT INTO rfm_memories (content, created_at, sightings) "
           "VALUES ('twice-seen fact', ?, 2)", (time.time(),))
db.execute("INSERT INTO rfm_memories (content, created_at) "
           "VALUES ('explicit human save', ?)", (time.time(),))
db.commit()
rows = db.execute(
    "SELECT content FROM rfm_memories "
    "WHERE NOT (outcome_count > 0 AND value_score < 0) "
    "AND (sightings IS NULL OR sightings >= 2)").fetchall()
got = {r[0] for r in rows}
check("quarantine: single-sighting row held back",
      "twice-seen fact" in got and "explicit human save" in got
      and len(got) == 2, str(got))

# 5. Cap: lowest-score rows past grace are evicted; fresh rows survive.
db = fresh()
old_cap, old_grace = sweep.CONFIG["max_entries"], sweep.CONFIG["evict_grace_hours"]
sweep.CONFIG["max_entries"], sweep.CONFIG["evict_grace_hours"] = 3, 0
for i in range(5):
    db.execute("INSERT INTO rfm_memories (content, created_at) VALUES "
               "(?, ?)", (f"filler fact number {i} entirely distinct", 1000.0))
db.execute("UPDATE rfm_memories SET value_score = 1.0, outcome_count = 5 "
           "WHERE id = 1")
db.commit()
sweep.evict(db)
n = db.execute("SELECT count(*) FROM rfm_memories").fetchone()[0]
kept = db.execute("SELECT id FROM rfm_memories WHERE id = 1").fetchone()
check("cap: evicts to max_entries, keeps the earner",
      n == 3 and kept is not None, f"n={n}")
sweep.CONFIG["max_entries"], sweep.CONFIG["evict_grace_hours"] = old_cap, old_grace

# 6. The conditioned outcome mapping (the C4 guarantee, pure).
o = sweep.outcome_of
check("judge: helped + condition -> +1",
      o({"verdict": "helped", "condition_present": True}) == 1.0)
check("judge: helped, condition absent -> nothing (the C4 case)",
      o({"verdict": "helped", "condition_present": False}) is None)
check("judge: harmed -> -1 in any state",
      o({"verdict": "harmed", "condition_present": False}) == -1.0)
check("judge: unclear -> nothing",
      o({"verdict": "unclear", "condition_present": True}) is None)

print(f"\n{'PASS' if not failures else 'FAIL: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
