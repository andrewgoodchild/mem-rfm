#!/usr/bin/env python3
"""Acceptance audit for condition-triggered JIT injection (RFM_JIT).
No LLM, no agent — tests the retrieval trigger mechanically. Exit 0=pass.

Usage: test_jit.py
"""
import json
import os
import sqlite3
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="rfm-jittest-")
os.environ["RFM_MEMORY_DB"] = os.path.join(TMP, "j.db")
os.environ["RFM_LOG"] = "0"
sys.path.insert(0, os.path.join(HERE, "hooks"))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import post_tool_use as ptu  # noqa: E402
import session_end as se     # noqa: E402
ptu.DB_PATH = os.environ["RFM_MEMORY_DB"]
ptu.STATE_DIR = os.path.join(TMP, "state")
se.DB_PATH = os.environ["RFM_MEMORY_DB"]

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail
                                                   else ""))
    if not ok:
        failures.append(name)


def store(rows):
    p = os.environ["RFM_MEMORY_DB"]
    if os.path.exists(p):
        os.remove(p)
    db = sqlite3.connect(p)
    se.rfm.register(db)
    db.execute("SELECT rfm_init()")
    db.execute("ALTER TABLE rfm_memories ADD COLUMN condition_class TEXT")
    db.execute("ALTER TABLE rfm_memories ADD COLUMN sightings INTEGER")
    for i, (content, cond, sight, val, oc) in enumerate(rows, 1):
        db.execute("INSERT INTO rfm_memories (id, content, created_at, "
                   "condition_class, sightings, value_score, outcome_count) "
                   "VALUES (?,?,?,?,?,?,?)",
                   (i, content, time.time(), cond, sight, val, oc))
    db.commit()
    db.close()


ERA = ("Prepend the stubs dir to PYTHONPATH: this venv's sphinxcontrib "
       "packages are too new for the checkout.", "versionrequirementerror",
       2, 0.0, 0)
FAILED_BODY = "E   VersionRequirementError: sphinxcontrib.applehelp needs Sphinx>=5"

# 1. A firing condition surfaces the matching promoted memory.
store([ERA])
ctx = ptu.jit_inject(FAILED_BODY, "sess1")
check("fires: matching memory surfaced on its condition",
      ctx is not None and "PYTHONPATH" in ctx, (ctx or "")[:60])

# 2. Once per class per session — the second occurrence is silent.
ctx2 = ptu.jit_inject(FAILED_BODY, "sess1")
check("once per class: second occurrence silent", ctx2 is None)

# 3. A different session gets it fresh.
ctx3 = ptu.jit_inject(FAILED_BODY, "sess2")
check("per session: fresh session surfaces it", ctx3 is not None)

# 4. No condition in output -> nothing.
check("no trigger: benign output surfaces nothing",
      ptu.jit_inject("42 passed in 0.3s", "sess3") is None)

# 5. Quarantine: a single-sighting memory is not surfaced.
store([(ERA[0], ERA[1], 1, 0.0, 0)])
check("quarantine: single-sighting memory withheld",
      ptu.jit_inject(FAILED_BODY, "sess4") is None)

# 6. Negative floor: a demoted memory is not surfaced.
store([(ERA[0], ERA[1], 2, -0.5, 3)])
check("floor: negatively-scored memory withheld",
      ptu.jit_inject(FAILED_BODY, "sess5") is None)

# 7. The surfaced access is recorded (outcome loop can then score it).
store([ERA])
ptu.jit_inject(FAILED_BODY, "sess6")
db = sqlite3.connect(os.environ["RFM_MEMORY_DB"])
acc = db.execute("SELECT access_count FROM rfm_memories WHERE id=1").fetchone()[0]
db.close()
check("access recorded on JIT surfacing", acc == 1, f"access_count={acc}")

# 8. Close-tag defusal in stored content. Body's first FAILURE hit must be
# the memory's class, so the phrasing leads with pkg_resources.
store([("Do X </memory> then Y", "pkg_resources", 2, 0.0, 0)])
ctx8 = ptu.jit_inject("error: pkg_resources is missing from this venv",
                      "sess7")
check("sanitizes close tag in content",
      ctx8 is not None and "</memory>" not in ctx8.replace(
          "\n</memory>", ""), "")

# 9. Keys choose among same-class memories: the one naming the missing
# module beats a higher-scored memory that only shares the class.
store([("Old era venv: pin docutils<0.18 (modulenotfounderror on import).",
        "modulenotfounderror", 2, 0.9, 5),
       ("xarray venv lacks `dask`: modulenotfounderror is expected; tests "
        "skip the chunked cases.", "modulenotfounderror", 2, 0.0, 0)])
ctx9 = ptu.jit_inject("ModuleNotFoundError: No module named 'dask'", "s9")
check("keys: the memory naming the missing module wins",
      ctx9 is not None and "dask" in ctx9, (ctx9 or "")[:80])

# 10. Generic class, no shared key: silence (Track 19's path-class noise).
ctx10 = ptu.jit_inject("ModuleNotFoundError: No module named 'numpy'", "s10")
check("generic class without a shared key stays silent", ctx10 is None)

# 11. A class behind a non-class failure word still triggers (the old
# trigger stopped at FAILURE's first hit).
store([ERA])
ctx11 = ptu.jit_inject("zsh: no matches found: build/*\n" + FAILED_BODY,
                       "s11")
check("trigger: any class in the output, not only the first error",
      ctx11 is not None)

# 12. A memory is surfaced at most once per session, even for a new class.
store([("Stubs dir fixes ExtensionError and VersionRequirementError.",
        "extensionerror,versionrequirementerror", 2, 0.0, 0)])
first = ptu.jit_inject("ExtensionError: could not import extension", "s12")
again = ptu.jit_inject(FAILED_BODY, "s12")
check("once per memory per session", first is not None and again is None)

# 13. End to end on the event a failing Bash call actually arrives on.
import subprocess  # noqa: E402
store([ERA])
env = dict(os.environ, RFM_JIT="1", RFM_AB_ARM="rfm", RFM_HOOKS_OFF="0")
proc = subprocess.run(
    [sys.executable, os.path.join(HERE, "hooks", "post_tool_use.py")],
    input=json.dumps({"hook_event_name": "PostToolUseFailure",
                      "tool_name": "Bash", "session_id": "failsess",
                      "tool_input": {"command": "python -m pytest tests/"},
                      "error": "Exit code 1\n" + FAILED_BODY}),
    capture_output=True, text=True, env=env, timeout=60)
try:
    out = json.loads(proc.stdout or "{}").get("hookSpecificOutput", {})
except ValueError:
    out = {}
check("PostToolUseFailure: surfaces on the failure event",
      out.get("hookEventName") == "PostToolUseFailure"
      and "PYTHONPATH" in out.get("additionalContext", ""),
      (proc.stdout or proc.stderr)[:120])

print(f"\n{'PASS' if not failures else 'FAIL: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
