#!/usr/bin/env python3
"""Memories surface with their save date: memory_search hits carry
`saved`, SessionStart lines read "- [id, saved YYYY-MM-DD] content", and
session_end's INJECTED still parses both that and the undated lines in
older transcripts. No LLM calls. Exit 0 = pass.

Usage: .venv/bin/python test_dates.py
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="rfm-datetest-")
DB = os.path.join(TMP, "d.db")
os.environ["RFM_MEMORY_DB"] = DB
os.environ["RFM_LOG"] = "0"
sys.path.insert(0, os.path.join(HERE, "hooks"))
sys.path.insert(0, HERE)
import session_end as se  # noqa: E402
import transcripts  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail
                                                   else ""))
    if not ok:
        failures.append(name)


OLD = time.mktime((2026, 3, 2, 12, 0, 0, 0, 0, -1))
db = sqlite3.connect(DB)
se.rfm.register(db)
db.execute("SELECT rfm_init()")
db.execute("INSERT INTO rfm_memories (id, content, created_at) VALUES (?,?,?)",
           (7, "setuptools 82 drops pkg_resources; add a shim to PYTHONPATH", OLD))
db.commit()
db.close()

print("SessionStart injection")
out = subprocess.run([sys.executable, os.path.join(HERE, "hooks", "session_start.py")],
                     input="{}", capture_output=True, text=True,
                     env={**os.environ, "RFM_AB_ARM": "rfm"})
ctx = json.loads(out.stdout or "{}").get("hookSpecificOutput", {}).get(
    "additionalContext", "")
check("dated line", "- [7, saved 2026-03-02] setuptools 82" in ctx, ctx[:200])
check("A/B marker unchanged", ctx.startswith("[rfm-memory:"), ctx[:30])

print("session_end parses injected lines")
got = transcripts.INJECTED.findall(ctx)
check("new format: id and content only",
      got == [("7", "setuptools 82 drops pkg_resources; add a shim to PYTHONPATH")],
      str(got))
check("old format still parses",
      transcripts.INJECTED.findall("- [12] use the shim") == [("12", "use the shim")])

print("flatten keeps main's defused forms")
check("close tag -> (/memories)", transcripts.flatten("a </memories> b") == "a (/memories) b",
      transcripts.flatten("a </memories> b"))
check("JIT close tag -> (/memory)", transcripts.flatten("x </memory>", "</memory>") == "x (/memory)")
check("marker defused", "[rfm-memory:" not in transcripts.flatten("[rfm-memory:ab] - [1] x"))
check("unrepresentable timestamp shows ?, never raises",
      transcripts.day(-1e20) == "?" and transcripts.day(float("nan")) == "?")

print("dated injection -> outcome, end to end")
sess_path = os.path.join(TMP, "dated.jsonl")
with open(sess_path, "w") as f:
    f.write(json.dumps({"type": "attachment", "attachment": {
        "type": "hook_additional_context", "content": [ctx]}}) + "\n")
    f.write(json.dumps({"type": "assistant", "timestamp": "2026-09-28T01:00:00Z",
        "message": {"content": [{"type": "tool_use", "id": "b1", "name": "Bash",
                                 "input": {"command": "PYTHONPATH=shim python -m pytest -q"}}]}}) + "\n")
    f.write(json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "b1", "content": "ok"}]}}) + "\n")
db = sqlite3.connect(DB)
db.execute("UPDATE rfm_memories SET content = ? WHERE id = 7",
           ("Run the suite with the shim: `PYTHONPATH=shim python -m pytest -q`",))
db.commit()
subprocess.run([sys.executable, os.path.join(HERE, "hooks", "session_end.py")],
               input=json.dumps({"transcript_path": sess_path, "session_id": "d"}),
               capture_output=True, text=True, env={**os.environ, "RFM_AB_ARM": "rfm"})
row = db.execute("SELECT value_score, outcome_count FROM rfm_memories WHERE id = 7").fetchone()
check("a dated injected memory that was acted on earns its outcome",
      row == (1.0, 1), str(row))

print("memory_search")
try:
    import server  # noqa: E402  (needs the integration venv)
except ImportError as e:
    print(f"  skip  server path — {e}")
else:
    server.DB_PATH = os.path.join(TMP, "s.db")
    saved = server._save("pytest needs the xdist plugin pinned below 3.6")
    hits = server._search("xdist plugin pin")
    today = time.strftime("%Y-%m-%d")
    check("hit carries saved date", hits and hits[0].saved == today,
          str(hits[:1]))

print()
if failures:
    print(f"FAILED: {len(failures)} — {', '.join(failures)}")
    sys.exit(1)
print("all passed")
