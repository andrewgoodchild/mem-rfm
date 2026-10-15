#!/usr/bin/env python3
"""mod_bridge.py, the mod's live outcome path: a memory is shown only when
its condition fires, an outcome is recorded only for a command drawn from
it, and the SessionEnd hook defers to what the mod already recorded.
Exit 0 = pass.

Usage: test_mod_bridge.py
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="rfm-modtest-")
DB = os.path.join(TMP, "mod.db")
ENV = {**os.environ, "RFM_MEMORY_DB": DB, "RFM_LOG": "0"}
os.environ.update(RFM_MEMORY_DB=DB, RFM_LOG="0")
sys.path.insert(0, HERE)
import sweep  # noqa: E402
sys.path.insert(0, os.path.join(HERE, "hooks"))
import session_end  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail
                                                   else ""))
    if not ok:
        failures.append(name)


def bridge(req):
    out = subprocess.run([sys.executable, os.path.join(HERE, "mod_bridge.py")],
                         input=json.dumps(req), capture_output=True, text=True,
                         env=ENV, check=True)
    return json.loads(out.stdout)


SHIM = ("setuptools 82 dropped pkg_resources, so `import xarray` fails with "
        "ModuleNotFoundError. Fix: `PYTHONPATH=/tmp/shim python -m pytest` "
        "with a pkg_resources shim on the path.")
UNRELATED = "Run `make docs` before editing the sphinx theme."

db = sqlite3.connect(DB)
sweep.ensure_schema(db)
for text in (SHIM, UNRELATED):
    db.execute("INSERT INTO rfm_memories (content, created_at) VALUES (?, ?)",
               (text, time.time()))
db.commit()
db.close()
SHIM_ID, UNRELATED_ID = 1, 2

print("match")
quiet = bridge({"op": "match", "output": "3 passed in 0.4s"})
check("no condition in the output -> nothing shown", quiet["memories"] == [])
err = ("Traceback (most recent call last):\n  File ...\n"
       "ModuleNotFoundError: No module named 'pkg_resources'")
hit = bridge({"op": "match", "output": err})
check("condition fired -> the conditioned memory is shown",
      [m["id"] for m in hit["memories"]] == [SHIM_ID], hit)
check("fired classes are reported",
      set(hit["fired"]) == {"modulenotfounderror", "pkg_resources"}, hit)
other = bridge({"op": "match", "output":
               "ModuleNotFoundError: No module named 'dask'"})
check("generic class with no shared key -> not shown (signature_match)",
      other["memories"] == [] and "modulenotfounderror" in other["fired"],
      other)

print("outcome")
start = time.time() - 60
miss = bridge({"op": "outcome", "id": SHIM_ID, "command": "ls -la",
               "is_error": False, "output": "", "fired": hit["fired"],
               "session_start": start})
check("a command not drawn from the memory decides nothing",
      miss == {"acted": False, "outcome": None, "recorded": False}, miss)
ambiguous = bridge({"op": "outcome", "id": SHIM_ID,
                    "command": "PYTHONPATH=/tmp/shim python -m pytest",
                    "is_error": False, "output": "ImportError: still broken",
                    "fired": hit["fired"], "session_start": start})
check("zero exit but error-shaped output abstains",
      ambiguous["acted"] and ambiguous["outcome"] is None, ambiguous)
good = bridge({"op": "outcome", "id": SHIM_ID,
               "command": "PYTHONPATH=/tmp/shim python -m pytest",
               "is_error": False, "output": "12 passed",
               "fired": hit["fired"], "session_start": start})
check("acted on, clean success -> +1 recorded",
      good == {"acted": True, "outcome": 1.0, "recorded": True}, good)

db = sqlite3.connect(DB)
outcomes = db.execute("SELECT outcome FROM rfm_accesses WHERE memory_id = ?",
                      (SHIM_ID,)).fetchall()
db.close()
check("exactly one outcome in the ledger", outcomes == [(1.0,)], outcomes)

print("SessionEnd defers")
session_end.DB_PATH = DB
n = session_end.record_outcomes(
    [{"id": SHIM_ID, "outcome": 1.0, "cmd": "PYTHONPATH=/tmp/shim pytest"}],
    start, frozenset(hit["fired"]))
check("the transcript pass does not double-count the mod's outcome", n == 0)

print("condition gate")
silent = bridge({"op": "outcome", "id": UNRELATED_ID, "command": "make docs",
                 "is_error": False, "output": "build succeeded",
                 "fired": [], "session_start": start})
check("an unconditioned memory still earns a plain outcome",
      silent["recorded"], silent)

print("PASS" if not failures else f"FAIL: {failures}")
sys.exit(1 if failures else 0)
