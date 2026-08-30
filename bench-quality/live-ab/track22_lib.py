#!/usr/bin/env python3
"""Track 22 substrate-removal harness. The timeline lives in a binary
sqlite DB the agent CANNOT dump; the only interface is query_events,
which caps results. Enforcement is the allowedTools whitelist: the agent
gets query_events + Read/Grep/Glob (for the repo) and NO other Bash — no
cat, sqlite3, python, or find to extract the DB, and Read/Grep over the
binary DB return nothing useful.

build_restricted_workspace(inst) -> (cwd, has_repo)
QUERY_TOOL is the wrapper script written into each workspace.
ALLOWED is the restricted tool whitelist.
"""
import json
import os
import re
import shutil
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_track20 as t20   # noqa: E402  (instances, event_text, repo clone)

WORK = os.path.join(HERE, "track22", "work")
DATA = os.path.join(HERE, "track22", "data")   # OUTSIDE any workspace
CAP = 5   # max events returned per query

# query_events reads the events DB from OUTSIDE the workspace (an absolute
# path baked in, in a directory the agent's tools cannot reach) and returns
# at most CAP events matching ALL whitespace-separated keywords. No keywords
# -> the CAP most recent, so a bare call cannot enumerate the timeline.
QUERY_TOOL = '''#!/usr/bin/env python3
import sqlite3, sys
DB = {db!r}
kws = [w.lower() for w in " ".join(sys.argv[1:]).split()]
con = sqlite3.connect(DB)
rows = con.execute("SELECT ts, text FROM events ORDER BY ts").fetchall()
hits = [t for ts, t in rows if all(k in t.lower() for k in kws)] if kws \\
    else [t for _ts, t in rows[-{cap}:]]
if not hits:
    print("no matching events; try different keywords")
else:
    for t in hits[:{cap}]:
        print("-", t)
    if len(hits) > {cap}:
        print("...(%d more matches; refine keywords)" % (len(hits) - {cap}))
'''

# The restriction: query_events is the ONLY tool. No Read/Grep/Glob/Bash
# means no way to reach the external DB or dump it. Repo/code instances are
# excluded (usable_event_only) since they would need file access.
ALLOWED = "Bash(python3 query_events.py:*)"


def usable_event_only():
    """Track 22 pool: usable instances with NO code questions, so the
    restricted toolset (query_events only) suffices to answer."""
    return [i for i in t20.usable(t20.instances()) if i["code_q"] == 0]


def build_restricted_workspace(inst):
    wd = os.path.join(WORK, inst["id"])
    if os.path.exists(wd):
        shutil.rmtree(wd)
    os.makedirs(wd)
    os.makedirs(DATA, exist_ok=True)
    dbpath = os.path.join(DATA, f"{inst['id']}.db")   # OUTSIDE the workspace
    if os.path.exists(dbpath):
        os.remove(dbpath)
    db = sqlite3.connect(dbpath)
    db.execute("CREATE TABLE events (ts TEXT, text TEXT)")
    for e in json.load(open(inst["events"])):
        db.execute("INSERT INTO events VALUES (?,?)",
                   (str(e.get("timestamp", "")), t20.event_text(e)))
    db.commit()
    db.close()
    with open(os.path.join(wd, "query_events.py"), "w") as f:
        f.write(QUERY_TOOL.format(db=dbpath, cap=CAP))
    return wd, False
