#!/usr/bin/env python3
"""Acceptance audit for the reconcile step of SessionEnd staging: every
staged candidate is followed by one metadata line naming its nearest
stored memories and pending candidates (similarity, likely-duplicate
mark, shared condition class) and its transcript provenance — without
changing what any "- " reader of the pending file sees. Self-contained;
exit 0 = pass.

Embedding-mode checks run only where fastembed imports (the integration
venv); the degraded token-overlap mode is forced and checked everywhere.

Usage: hooks/test_reconcile.py
"""
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="rfm-reconciletest-")
os.environ["RFM_MEMORY_DB"] = os.path.join(TMP, "test.db")
os.environ["RFM_LOG"] = "0"
os.environ.pop("RFM_RECONCILE", None)
sys.path.insert(0, HERE)
import session_end as se  # noqa: E402  (reads env at import)
import session_start  # noqa: E402
import similarity  # noqa: E402

E = se.transcripts.Event  # (cmd, is_err, body, got)
failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail
                                                   else ""))
    if not ok:
        failures.append(name)


STORED = ("In this project, `python -m pytest xarray/tests/test_merge.py -q` "
          "fails (pkg_resources); use `PYTHONPATH=/tmp/shim python -m pytest "
          "xarray/tests/test_merge.py -q` instead.")
OTHER = ("dask is not installed in the xarray test environment; dask-chunked "
         "parametrizations are skipped during pytest runs.")


def fresh_store(rows):
    for p in (se.DB_PATH, se.OUT):
        if os.path.exists(p):
            os.remove(p)
    db = sqlite3.connect(se.DB_PATH)
    db.execute("CREATE TABLE rfm_memories (id INTEGER PRIMARY KEY, "
               "content TEXT, created_at REAL, scope TEXT)")
    for content in rows:
        db.execute("INSERT INTO rfm_memories (content, created_at, scope) "
                   "VALUES (?, 0, 'xarray')", (content,))
    db.commit()
    db.close()


def cand(failed, fixed, error, ij=(3, 4)):
    return {"failed": failed, "fixed": fixed, "error": error, "events": ij}


DUP = cand("python -m pytest xarray/tests/test_dataset.py -q",
           "PYTHONPATH=/tmp/shim python -m pytest xarray/tests/test_dataset.py -q",
           "pkg_resources")
NEW = cand("flake8 sphinx/ext/autodoc/typehints.py",
           "python -m flake8 sphinx/ext/autodoc/typehints.py",
           "command not found", (7, 9))


def pending():
    with open(se.OUT) as f:
        return f.read().splitlines()


def meta_for(lines, needle):
    for k, line in enumerate(lines):
        if line.startswith("- ") and needle in line:
            return lines[k + 1]
    return ""


print("corrections() records provenance")
events = [E("pip install foo", True, "bash: pip: command not found", True),
          E("python -m pip install foo", False, "Successfully installed", True)]
found = se.corrections(events)
check("failed->fixed pair carries its event indices",
      len(found) == 1 and found[0]["events"] == (0, 1), str(found))

print("degraded mode (token overlap) — forced")
saved_emb = dict(similarity._EMB)
similarity._EMB.update({"tried": True, "model": None})
fresh_store([STORED, OTHER])
n = se.stage([DUP, NEW], "sessdeg1", "/tmp/t/session.jsonl")
lines = pending()
cands = [l for l in lines if l.startswith("- ")]
check("staged count returned", n == 2, str(n))
check("exactly one '- ' line per candidate (metadata lines are not)",
      len(cands) == 2, str(len(cands)))
check("session_start's backlog count is unchanged by metadata",
      session_start.staged_review_note()[1] == 2,
      str(session_start.staged_review_note()))
m_dup, m_new = meta_for(lines, "test_dataset"), meta_for(lines, "flake8")
check("metadata line follows each candidate",
      m_dup.startswith(se.META) and m_new.startswith(se.META))
check("degraded mode is named on the line", "nearest[tokens]=" in m_dup,
      m_dup)
check("restated lesson flagged against the stored row id",
      "#1 " in m_dup and "likely-duplicate" in m_dup.split(";")[0], m_dup)
check("shared condition class reported", "condition=pkg_resources" in m_dup,
      m_dup)
check("distinct lesson not flagged", "likely-duplicate" not in m_new, m_new)
check("provenance: event range and transcript",
      "from=bash#3->#4 of /tmp/t/session.jsonl" in m_dup
      and "from=bash#7->#9" in m_new, m_dup)
check("ref is session.index", "ref=sessdeg1.1" in m_dup
      and "ref=sessdeg1.2" in m_new)

print("a later session meets the pending backlog")
again = cand("python -m pytest xarray/tests/test_dataset.py -q -x",
             "PYTHONPATH=/tmp/shim python -m pytest xarray/tests/test_dataset.py -q",
             "pkg_resources", (11, 12))
se.stage([again], "sessdeg2", "/tmp/t/other.jsonl")
lines = pending()
m_again = meta_for(lines, "test_dataset.py -q -x")
check("flagged against the still-pending candidate by its ref",
      "sessdeg1.1" in m_again and "likely-duplicate" in m_again, m_again)
check("pending_entries recovers refs from metadata lines",
      [r for r, _ in se.pending_entries(se.OUT)]
      == ["sessdeg1.1", "sessdeg1.2", "sessdeg2.1"],
      str(se.pending_entries(se.OUT)))
check("pending_entries content never includes metadata",
      all(not c.startswith("<!--") and "rfm-reconcile" not in c
          for _, c in se.pending_entries(se.OUT)))

print("advisory: never blocks staging")
fresh_store([STORED])
real_prime = similarity.prime


def boom(_texts):
    raise RuntimeError("embedder exploded")


similarity.prime = boom
se.stage([DUP], "sessfail", "/tmp/t/s.jsonl")
similarity.prime = real_prime
lines = pending()
m = meta_for(lines, "test_dataset")
check("candidate still staged when reconcile fails",
      sum(l.startswith("- ") for l in lines) == 1)
check("falls back to provenance-only metadata",
      "from=bash#3->#4" in m and "nearest" not in m, m)

def slow(_texts):
    import time
    time.sleep(5)


fresh_store([STORED])
similarity.prime, budget = slow, se.RECONCILE_BUDGET_S
se.RECONCILE_BUDGET_S = 0.2
se.stage([DUP], "sesslow", "/tmp/t/s.jsonl")
similarity.prime, se.RECONCILE_BUDGET_S = real_prime, budget
m = meta_for(pending(), "test_dataset")
check("reconcile over its time budget: staged, provenance only",
      sum(l.startswith("- ") for l in pending()) == 1
      and "from=bash#3->#4" in m and "nearest" not in m, m)

fresh_store([STORED])
se.stage([DUP], "sessres", "/tmp/t/s.jsonl")
se.stage([NEW], "sessres", "/tmp/t/s.jsonl")       # --resume: same id again
refs = [r for r, _ in se.pending_entries(se.OUT)]
check("a resumed session's candidates get fresh refs",
      len(refs) == len(set(refs)) == 2 and "sessres.1" in refs, str(refs))

se.RECONCILE = False
fresh_store([STORED])
se.stage([DUP], "sessoff", "/tmp/t/s.jsonl")
m = meta_for(pending(), "test_dataset")
check("RFM_RECONCILE=0: provenance only", "nearest" not in m
      and "from=bash#3->#4" in m, m)
se.RECONCILE = True

print("no store, no pending file")
for p in (se.DB_PATH, se.OUT):
    if os.path.exists(p):
        os.remove(p)
se.stage([NEW], "sessempty", "/tmp/t/s.jsonl")
m = meta_for(pending(), "flake8")
check("nearest=none on an empty world", "=none" in m, m)

similarity._EMB.clear()
similarity._EMB.update(saved_emb)

print("embedding mode")
if similarity.mode() == "embedding":
    fresh_store([STORED, OTHER])
    se.stage([DUP, NEW], "sessemb", "/tmp/t/session.jsonl")
    lines = pending()
    m_dup, m_new = meta_for(lines, "test_dataset"), meta_for(lines, "flake8")
    check("embedding mode named", "nearest[embedding]=" in m_dup, m_dup)
    check("restated lesson flagged against #1",
          "#1 " in m_dup and "likely-duplicate" in m_dup.split(";")[0], m_dup)
    check("distinct lesson not flagged", "likely-duplicate" not in m_new,
          m_new)
else:
    print("  skip  fastembed not importable here (run under the venv)")

if failures:
    print(f"\nFAIL: {len(failures)} check(s): {failures}")
    sys.exit(1)
print("\nPASS")
