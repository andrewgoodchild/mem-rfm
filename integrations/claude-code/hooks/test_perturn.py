#!/usr/bin/env python3
"""Acceptance audit for per-turn retrieval (RFM_PERTURN). No fastembed:
a stub embedder maps text to a tiny deterministic vector so similarity
is controllable. Exit 0 = pass.

Usage: test_perturn.py
"""
import json
import os
import struct
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="rfm-ptrntest-")
os.environ["RFM_MEMORY_DB"] = os.path.join(TMP, "p.db")
os.environ["RFM_LOG"] = "0"
os.environ["RFM_PERTURN"] = "1"
os.environ["RFM_AB_ARM"] = "rfm"
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))
import user_prompt_submit as ups  # noqa: E402
import rfm                        # noqa: E402
ups.DB_PATH = os.environ["RFM_MEMORY_DB"]

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail
                                                   else ""))
    if not ok:
        failures.append(name)


# A 3-D "embedding" space; texts map to axis-aligned unit vectors by keyword.
VECS = {"gluten": [1.0, 0.0, 0.0], "dask": [0.0, 1.0, 0.0],
        "rome": [1.0, 0.0, 0.0], "linter": [0.0, 0.0, 1.0]}


def stub_embed(text):
    t = text.lower()
    for k, v in VECS.items():
        if k in t:
            return v
    return [0.0, 0.0, 0.0]


ups._EMBED["tried"] = True
ups._EMBED["fn"] = stub_embed


def blob(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def store(rows):
    p = os.environ["RFM_MEMORY_DB"]
    if os.path.exists(p):
        os.remove(p)
    db = sqlite3.connect(p)
    rfm.register(db)
    db.execute("SELECT rfm_init()")
    db.execute("ALTER TABLE rfm_memories ADD COLUMN embedding BLOB")
    db.execute("ALTER TABLE rfm_memories ADD COLUMN sightings INTEGER")
    for i, (content, vec, sight, val, oc) in enumerate(rows, 1):
        db.execute("INSERT INTO rfm_memories (id, content, created_at, "
                   "embedding, sightings, value_score, outcome_count) "
                   "VALUES (?,?,?,?,?,?,?)",
                   (i, content, 1e9, blob(vec), sight, val, oc))
    db.commit()
    db.close()


GLUTEN = ("User avoids gluten.", VECS["gluten"], 2, 0.0, 0)
DASK = ("dask is not installed in this venv.", VECS["dask"], 2, 0.0, 0)

# 1. A relevant memory surfaces for a matching turn.
store([GLUTEN, DASK])
top = ups.retrieve("Recommend restaurants in Rome")   # rome ~ gluten axis
check("relevant memory retrieved on matching turn",
      any("gluten" in c.lower() for _s, _sim, _m, c in top), str(len(top)))

# 2. An unrelated turn surfaces nothing (relevance floor).
top = ups.retrieve("Tell me a joke")                   # zero vector
check("relevance floor: unrelated turn retrieves nothing", top == [])

# 3. The wrong-topic memory is not surfaced for a different topic.
top = ups.retrieve("How do I run the dask tests")      # dask axis
ids = [m for _s, _sim, m, _c in top]
check("topic match: dask turn gets dask memory, not gluten",
      ids == [2], str(ids))

# 4. Quarantine: single-sighting memory withheld.
store([("User avoids gluten.", VECS["gluten"], 1, 0.0, 0)])
check("quarantine: single-sighting withheld",
      ups.retrieve("gluten free in Rome") == [])

# 5. Negative floor: demoted memory withheld.
store([("User avoids gluten.", VECS["gluten"], 2, -0.5, 3)])
check("negative floor: demoted memory withheld",
      ups.retrieve("gluten free in Rome") == [])

# 6. Access recorded on the surfaced memory.
store([GLUTEN, DASK])
ups.retrieve("gluten options in Rome")
db = sqlite3.connect(os.environ["RFM_MEMORY_DB"])
acc = db.execute("SELECT access_count FROM rfm_memories WHERE id=1").fetchone()[0]
db.close()
check("access recorded on surfaced memory", acc == 1, f"access={acc}")

# 7. K cap honored.
os.environ["RFM_PERTURN_K"] = "1"
ups.K = 1
store([GLUTEN, ("also gluten note", VECS["gluten"], 2, 0.5, 5)])
top = ups.retrieve("gluten in Rome")
check("K cap: at most K surfaced", len(top) == 1, str(len(top)))

print(f"\n{'PASS' if not failures else 'FAIL: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
