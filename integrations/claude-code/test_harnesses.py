#!/usr/bin/env python3
"""The harness registry and degraded operation. No LLM calls. Exit 0 = pass.

1. Registry: every harness declares all four lifecycle stages, with hook
   scripts that exist, and the installer's tables are exactly the
   registry's — the installed wiring and the runtime read one declaration.
2. Degraded mode (a harness whose transcript mem-rfm cannot read): the
   hooks and the sweep fail open and SAY so (readable=false in the log),
   and the MCP-only loop still learns — explicit memory_feedback alone
   moves the ranking.

Usage: .venv/bin/python test_harnesses.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="rfm-harnesstest-")
DB = os.path.join(TMP, "h.db")
LOG = os.path.join(TMP, "rfm-log.jsonl")
os.environ.update({"RFM_MEMORY_DB": DB, "RFM_LOG": LOG,
                   "RFM_ACCESS_WINDOW": "0"})
sys.path[:0] = [os.path.join(HERE, "hooks"), HERE]
import harnesses    # noqa: E402
import transcripts  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail
                                                   else ""))
    if not ok:
        failures.append(name)


print("registry")
for name, h in harnesses.HARNESSES.items():
    check(f"{name}: all four stages declared",
          set(h.hooks) == set(harnesses.STAGES), str(sorted(h.hooks)))
    missing = [s.script for s in h.hooks.values()
               if not os.path.exists(os.path.join(HERE, "hooks", s.script))]
    check(f"{name}: every hook script exists", not missing, str(missing))
    events = [s.event for s in h.hooks.values()]
    check(f"{name}: one registration per host event",
          len(events) == len(set(events)), str(events))
    check(f"{name}: config style implemented", h.config_style == "nested")
    check(f"{name}: transcript reader registered",
          h.reader in transcripts.READERS, h.reader)
    check(f"{name}: payload names transcript and session",
          {"transcript", "session"} <= set(h.payload), str(h.payload))

ms = harnesses.Harness("ms-host", "", "nested", "milliseconds", {}, "", {})
check("timeout unit: a milliseconds host gets 30s as 30000",
      harnesses.host_timeout(ms, 30) == 30000)

import install_hooks as ih  # noqa: E402
reg = harnesses.HARNESSES[harnesses.DEFAULT]
check("installer events and scripts are the registry's",
      ih.HOOKS == {s.event: os.path.join(HERE, "hooks", s.script)
                   for s in reg.hooks.values()})
check("installer timeouts are the registry's",
      all(ih.hook_entry(ih.HOOKS[s.event])["timeout"] == s.timeout
          for s in reg.hooks.values()))
check("installer matchers are the registry's",
      ih.MATCHERS == {s.event: s.matcher for s in reg.hooks.values() if s.matcher})

print("degraded mode: unreadable transcripts")
foreign = os.path.join(TMP, "codex-style.jsonl")
with open(foreign, "w") as f:           # a different harness's event log
    f.write(json.dumps({"type": "response_item", "payload": {
        "type": "function_call", "name": "shell",
        "arguments": "{\"command\": [\"pytest\"]}"}}) + "\n")
    f.write("not json at all\n")
    for scalar in ("[1, 2]", '"x"', "null", "7"):     # JSON, but not records
        f.write(scalar + "\n")
s = transcripts.read(foreign)
check("foreign transcript reads as empty and unreadable",
      not s.readable and s.events == [] and s.exposures == {}, str(s))
empty = os.path.join(TMP, "empty.jsonl")
open(empty, "w").close()
check("empty transcript reads as unreadable", not transcripts.read(empty).readable)
check("missing transcript reads as unreadable",
      not transcripts.read(os.path.join(TMP, "nope.jsonl")).readable)
check("unknown harness reads as unreadable, never raises",
      not transcripts.read(foreign, "no-such-harness").readable)


def session_end(path):
    r = subprocess.run([sys.executable, os.path.join(HERE, "hooks", "session_end.py")],
                       input=json.dumps({"transcript_path": path,
                                         "session_id": "deadbeef"}),
                       capture_output=True, text=True, env=os.environ)
    marks = [json.loads(line) for line in open(LOG)
             if '"session_end"' in line] if os.path.exists(LOG) else []
    return r.returncode, (marks[-1] if marks else {})


rc, mark = session_end(foreign)
check("session_end on a foreign transcript exits cleanly", rc == 0, str(rc))
check("...and logs it as unreadable, not as an empty session",
      mark.get("readable") is False and mark.get("harness") == "claude-code"
      and mark.get("events") == 0, str(mark))

good = os.path.join(TMP, "claude.jsonl")
with open(good, "w") as f:
    f.write(json.dumps({"type": "assistant", "timestamp": "2026-09-28T01:00:00Z",
                        "message": {"content": [{"type": "tool_use", "id": "b1",
                                                 "name": "Bash",
                                                 "input": {"command": "ls"}}]}}) + "\n")
    f.write(json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "b1", "content": "a b"}]}}) + "\n")
rc, mark = session_end(good)
check("a readable transcript logs readable with its events",
      rc == 0 and mark.get("readable") is True and mark.get("events") == 1, str(mark))

import sweep  # noqa: E402
sweep.DB_PATH, sweep.LOG = DB, LOG


def no_llm(_prompt):
    raise AssertionError("the sweep called the LLM on an unreadable transcript")


sweep.llm = no_llm
import sqlite3  # noqa: E402
db = sqlite3.connect(DB)
sweep.ensure_schema(db)
try:
    sweep.sweep_one(db, foreign)
    ok = True
except AssertionError as e:
    ok = str(e)
n = db.execute("SELECT count(*) FROM rfm_memories").fetchone()[0]
check("sweep skips an unreadable transcript without an LLM call",
      ok is True and n == 0, str(ok))
db.close()

print("degraded mode: the MCP-only loop still learns")
try:
    import server  # noqa: E402  (needs the integration venv)
except ImportError as e:
    print(f"  skip  — {e}")
else:
    server.DB_PATH = os.path.join(TMP, "mcp.db")
    # Near-twins, so similarity leaves the order to the prior. The prior is
    # a bounded blend (beta = 0.3) by design: it adjusts an order and never
    # overrides a large similarity gap, so a feedback-only flip is only a
    # fair expectation between close matches.
    a = server._save("run the test suite with pytest -q").id
    b = server._save("run the test suite with pytest -q -x").id
    q = "run the test suite with pytest"
    d = server.db()

    def prior(mid):
        return d.execute("SELECT rfm_prior(?)", (mid,)).fetchone()[0]

    pa, pb = prior(a), prior(b)
    first = [h.id for h in server._search(q, limit=2)]
    for _ in range(4):                      # explicit feedback only: no hooks
        server._search(q, limit=2)
        server._feedback(b, True)
        server._feedback(a, False)
    after = [h.id for h in server._search(q, limit=2)]
    check("feedback alone moves the priors the right way",
          prior(b) > pb and prior(a) < pa,
          f"a {pa:.3f}->{prior(a):.3f} b {pb:.3f}->{prior(b):.3f}")
    check("between close matches, the helped memory takes the lead",
          first[0] == a and after[0] == b, f"before {first} after {after}")

print()
if failures:
    print(f"FAILED: {len(failures)} — {', '.join(failures)}")
    sys.exit(1)
print("all passed")
