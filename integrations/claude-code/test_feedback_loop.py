#!/usr/bin/env python3
"""The store must not confirm itself. Quarantine promotes a sweep-formed
memory only when a SECOND INDEPENDENT session produces the same lesson; a
session that was shown the memory (injected, or returned by memory_search)
and restated it is not independent. No LLM calls: sweep.llm is stubbed.
Exit 0 = pass.

Usage: test_feedback_loop.py
"""
import json
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="rfm-looptest-")
os.environ["RFM_MEMORY_DB"] = os.path.join(TMP, "loop.db")
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


LESSON = ("In this venv, dask is not installed so dask-chunked tests are "
          "skipped; this is expected, not a failure to fix.")
RESTATED = ("As the stored note says, dask is not installed in this venv, so "
            "the dask-chunked tests are skipped and that is expected rather "
            "than something to fix. I will leave those skips alone and focus "
            "on the actual failing assertion in the indexing tests instead.")


def fresh():
    if os.path.exists(sweep.DB_PATH):
        os.remove(sweep.DB_PATH)
    db = sqlite3.connect(sweep.DB_PATH)
    sweep.ensure_schema(db)
    sweep.admit(db, {"content": LESSON, "condition_class": "not-installed"},
                [], "origin")
    db.commit()
    return db


def transcript(name, shown):
    """A session whose assistant restates the lesson; `shown` puts the
    memory in front of it first via a memory_search result."""
    recs = []
    if shown:
        recs.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "s1",
             "name": "mcp__rfm-memory__memory_search",
             "input": {"query": "dask tests skipped"}}]}})
        recs.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "s1",
             "content": json.dumps({"result": [
                 {"id": 1, "content": LESSON, "score": 0.8}]})}]}})
    recs.append({"type": "assistant", "message": {"content": [
        {"type": "text", "text": RESTATED}]}})
    p = os.path.join(TMP, name)
    with open(p, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    return p


def stub_llm(prompt):
    # The extractor does what a good one would: it finds the lesson in the
    # prose. The judge has nothing acted on, so it is never reached.
    if "--- BEGIN SESSION MATERIAL ---" in prompt:
        return json.dumps([{"content": LESSON.replace("expected", "normal"),
                            "condition_class": "not-installed"}])
    return "{}"


sweep.llm = stub_llm


def sightings(db):
    return db.execute("SELECT sightings FROM rfm_memories").fetchall()


print("a session that was shown the memory")
db = fresh()
sweep.sweep_one(db, transcript("shown.jsonl", shown=True))
got = sightings(db)
check("restating an in-play memory is not a second sighting",
      got == [(1,)], str(got))

print("an independent session")
db = fresh()
sweep.sweep_one(db, transcript("independent.jsonl", shown=False))
got = sightings(db)
check("the same lesson from an unexposed session still counts",
      got == [(2,)], str(got))

print("our own injection block in assistant prose is not material")
db = fresh()
p = os.path.join(TMP, "quoted.jsonl")
with open(p, "w") as f:
    f.write(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Echoing the context I was given:\n"
         "[rfm-memory:standalone] Long-term memories ...\n<memories>\n"
         f"- [1, saved 2026-09-01] {LESSON}\n</memories>\n" + "x " * 120}]}})
            + "\n")
mat = sweep.material_of(sweep.transcripts.read(p))
check("injected block stripped from extraction material",
      "<memories>" not in mat and LESSON not in mat, mat[:120])

print()
if failures:
    print(f"FAILED: {len(failures)} — {', '.join(failures)}")
    sys.exit(1)
print("all passed")
