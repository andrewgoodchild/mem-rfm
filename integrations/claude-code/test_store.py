#!/usr/bin/env python3
"""The store's promises. Stdlib only: the checks that need the MCP stack
(search, update) skip without the integration venv; smoke_test.py covers
those end to end. Exit 0 = pass.

Usage: test_store.py
"""
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="rfm-storetest-")
DB = os.path.join(TMP, "store.db")
os.environ["RFM_MEMORY_DB"] = DB
os.environ["RFM_LOG"] = "0"
sys.path.insert(0, HERE)
import sweep  # noqa: E402
import store  # noqa: E402
import rfm    # noqa: E402
sweep.DB_PATH = DB

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail
                                                   else ""))
    if not ok:
        failures.append(name)


def fresh(path=DB):
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    sweep.ensure_schema(db)
    return db


def columns(db):
    return {r[1] for r in db.execute("PRAGMA table_info(rfm_memories)")}


def add(db, content, **cols):
    names = ["content", "created_at", *cols]
    cur = db.execute(f"INSERT INTO rfm_memories ({', '.join(names)}) VALUES "
                     f"({', '.join('?' * len(names))})",
                     (content, 1.8e9, *cols.values()))
    db.commit()
    return cur.lastrowid


print("migration")
old = os.path.join(TMP, "old.db")
db = sqlite3.connect(old)
rfm.register(db)
db.execute("SELECT rfm_init()")
db.execute("ALTER TABLE rfm_memories ADD COLUMN scope TEXT")
db.execute("INSERT INTO rfm_memories (content, created_at, scope) "
           "VALUES ('kept', 1.8e9, 'a')")
db.commit()
store.ensure(db)
store.ensure(db)
check("adds what is missing, keeps what is there",
      {c for c, _k in store.COLUMNS} <= columns(db)
      and db.execute("SELECT scope FROM rfm_memories").fetchone() == ("a",))
check("stamps user_version",
      db.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION)

print("a directory's scope")
repo = os.path.join(TMP, "Widget")
os.makedirs(os.path.join(repo, ".git"))
os.makedirs(os.path.join(repo, "src", "deep"))
check("a repository's name, from anywhere inside it",
      store.project(os.path.join(repo, "src", "deep")) == "Widget")
tree = os.path.join(TMP, "wt-feature")
os.makedirs(tree)
with open(os.path.join(tree, ".git"), "w") as f:
    f.write(f"gitdir: {repo}/.git/worktrees/wt-feature\n")
check("a linked worktree is its main repository",
      store.project(tree) == "Widget", store.project(tree))
plain = os.path.join(TMP, "notes")
os.makedirs(plain)
check("outside a repository, the directory", store.project(plain) == "notes")


print("every delivery path stops at scope")
# The default path run for real, as Claude Code runs it.
def session_start(cwd):
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "hooks", "session_start.py")],
        input=json.dumps({"session_id": "s", "cwd": cwd}), text=True,
        capture_output=True, check=True,
        env={**os.environ, "RFM_MEMORY_DB": DB})
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


db = fresh()
add(db, "HERE lives in widget", scope="widget")
add(db, "OTHER lives in another repository", scope="gadget")
add(db, "GLOBAL applies everywhere")
ctx = session_start(os.path.join(repo, "src"))
check("session start: own scope, case-folded", "HERE" in ctx, ctx[:200])
check("session start: unscoped", "GLOBAL" in ctx)
check("session start: never another project's", "OTHER" not in ctx)

import mod_bridge  # noqa: E402
import post_tool_use  # noqa: E402
db.execute("UPDATE rfm_memories SET condition_class = 'extensionerror'")
db.commit()
db.close()
mod_bridge.SE.DB_PATH = post_tool_use.DB_PATH = DB
hits = mod_bridge.match({"output": "ExtensionError: boom", "cwd": repo})
got = " ".join(h["content"] for h in hits["memories"])
check("mod: never another project's", hits["memories"] and "OTHER" not in got,
      got)
post_tool_use.STATE_DIR = os.path.join(TMP, "state")
seen = ""
for n in range(3):
    seen += post_tool_use.jit_inject("ExtensionError: boom", f"j{n}",
                                     repo) or ""
check("show-on-error: never another project's", seen and "OTHER" not in seen,
      seen[:120])

print("the sweep keeps what it asked for")
db = fresh()
mid = sweep.admit(db, {"content": "Widget's tests need the fixture server up.",
                       "condition_class": "fixtures", "scope": "acme/Widget",
                       "era": "2.x only"}, [], "t1", project="Widget")
row = db.execute("SELECT scope, era FROM rfm_memories WHERE id = ?",
                 (mid,)).fetchone()
check("the session's repository is kept, the era stored",
      row == ("Widget", "2.x only"), str(row))
mid = sweep.admit(db, {"content": "Lockfiles drift when pip and uv are mixed.",
                       "condition_class": "lockfile", "scope": "python"},
                  [], "t2", project="Widget")
row = db.execute("SELECT scope FROM rfm_memories WHERE id = ?", (mid,)).fetchone()
check("a free-form context stays global, not hidden", row == (None,), str(row))

print("a sighting is an independent origin")
LESSON = {"content": "Always run bootstrap.sh before building this project.",
          "condition_class": "bootstrap"}
TWIN = {**LESSON, "content": LESSON["content"].replace("Always", "Always do")}
db = fresh()
for k in range(1, 5):
    sweep.admit(db, TWIN if k % 2 else LESSON, [], f"s{k}", fired=frozenset(),
                project="victim")
got = db.execute("SELECT sightings FROM rfm_memories").fetchall()
check("read in many sessions of one repo: one sighting", got == [(1,)], str(got))
sweep.admit(db, LESSON, [], "s9", fired=frozenset(), project="elsewhere")
got = db.execute("SELECT sightings FROM rfm_memories").fetchall()
check("read in a second repo: a second sighting", got == [(2,)], str(got))
db = fresh()
for k in (1, 2):
    sweep.admit(db, LESSON, [], f"s{k}", fired=frozenset({"bootstrap"}),
                project="victim")
got = db.execute("SELECT sightings FROM rfm_memories").fetchall()
check("observed first hand in two sessions: two", got == [(2,)], str(got))
got = json.loads(db.execute("SELECT origins FROM rfm_memories").fetchone()[0])
check("origins record the channel", got == ["session:s1", "session:s2"], str(got))
db = fresh()
add(db, LESSON["content"], condition_class="bootstrap", sightings=1)
sweep.admit(db, LESSON, [], "s1", fired=frozenset(), project="victim")
got = db.execute("SELECT sightings FROM rfm_memories").fetchall()
check("a row from before origins can still be seen again", got == [(2,)], str(got))

print("export and import")
db = fresh()
a = add(db, "first", scope="widget", sightings=1, embedding=b"\x00\x01\xff",
        era="2.x", condition_class="x", origins='["session:s"]')
b = add(db, "second")
db.execute("SELECT rfm_record_access(?)", (a,))
db.execute("SELECT rfm_record_outcome(?, ?)", (a, -1.0))
db.execute("SELECT rfm_record_access(?)", (a,))
db.execute("INSERT INTO rfm_memory_history VALUES (?, 'older', 1.0, 0.5, 2)", (a,))
db.commit()
store.stamp_embedder(db, "m", 384)
buf = io.StringIO()
n = store.export_store(db, buf)


def dump(conn):
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
            for t in store.DUMPED}


other = fresh(os.path.join(TMP, "other.db"))
back = store.import_store(other, io.StringIO(buf.getvalue()))
check("every row comes back", back == n, f"{back} of {n}")
check("byte for byte, ledger and embeddings included", dump(other) == dump(db))
check("scores agree",
      other.execute("SELECT rfm_score(?)", (a,)).fetchone()[0] > 0
      and other.execute("SELECT value_score FROM rfm_memories WHERE id = ?",
                        (a,)).fetchone()
      == db.execute("SELECT value_score FROM rfm_memories WHERE id = ?",
                    (a,)).fetchone())


def refused(conn, text):
    try:
        store.import_store(conn, io.StringIO(text))
    except ValueError:
        return True
    return False


check("refuses a store with memories in it", refused(db, buf.getvalue()))
empty = fresh(os.path.join(TMP, "empty.db"))
head = buf.getvalue().splitlines()[0]
check("refuses a foreign file", refused(empty, '{"format": "other"}\n'))
check("refuses a newer export",
      refused(empty, json.dumps({"format": store.FORMAT, "version": 99}) + "\n"))
check("refuses a column it does not know",
      refused(empty, head + "\n" + json.dumps(
          {"table": "rfm_memories",
           "row": {"id": 1, "x); DROP TABLE rfm_memories; --": 1}}) + "\n"))
bad = (head + "\n"
       + json.dumps({"table": "rfm_memories", "row": {
           "id": 1, "content": "c", "created_at": 1.0}}) + "\n"
       + json.dumps({"table": "nope", "row": {}}) + "\n")
check("a bad line restores nothing",
      refused(empty, bad) and empty.execute(
          "SELECT count(*) FROM rfm_memories").fetchone() == (0,))

print("the embedder a store was built with")
db = fresh()
check("the first use stamps", store.embedder_clash(db, "m", 384) is None)
check("the same model passes", store.embedder_clash(db, "m", 384) is None)
check("a same-dimension swap is caught, not ranked silently",
      store.embedder_clash(db, "other", 384))
check("a changed dimension is caught", store.embedder_clash(db, "m", 768))
db = fresh()
add(db, "x", embedding=b"\0" * 768 * 4)
check("an unstamped store is checked against its vectors",
      store.embedder_clash(db, "m", 384))

print("forgetting forgets the old text too")
db = fresh()
a = add(db, "new text")
db.execute("INSERT INTO rfm_memory_history VALUES (?, 'old', 1.0, 0.0, 0)", (a,))
db.execute("DELETE FROM rfm_memories WHERE id = ?", (a,))
check("delete takes its history with it",
      db.execute("SELECT count(*) FROM rfm_memory_history").fetchone() == (0,))

print("search")
try:
    import server
except ImportError:
    server = None
    print("  skip  needs the integration venv (mcp, sqlite-vec)")
if server:
    path = os.path.join(TMP, "server.db")
    server.DB_PATH = path
    server.LOG_ENABLED = False
    server.embed = lambda text: b"\x00\x00\x80\x3f" * 4   # one fixed unit-ish vector
    d = server.db()
    held = add(d, "HELD in quarantine", sightings=1)
    freed = add(d, "FREED past quarantine", sightings=2)
    hits = [h.content for h in server._search("anything", limit=10)]
    check("a quarantined row is not searchable", not any("HELD" in h for h in hits))
    check("a released sweep row is, with no reembed",
          any("FREED" in h for h in hits), str(hits))
    n = d.execute("SELECT count(*) FROM rfm_memories WHERE embedding IS NOT "
                  "NULL AND id = ?", (held,)).fetchone()[0]
    check("no vector is spent on a quarantined row", n == 0)
    mid = server._save("original text").id
    server._update(mid, "corrected text")
    got = d.execute("SELECT content FROM rfm_memory_history WHERE memory_id = ?",
                    (mid,)).fetchall()
    check("an update keeps the text it replaced", got == [("original text",)],
          str(got))
    server._update(mid, "corrected text")
    n = d.execute("SELECT count(*) FROM rfm_memory_history").fetchone()[0]
    check("a no-op update adds nothing", n == 1)
    store.stamp_embedder(d, "another-model", 4)
    try:
        server._search("anything")
        raised = False
    except ValueError:
        raised = True
    check("search refuses another model's vectors", raised)
    server.EMBEDDER_ID = "another-model"
    server._reembed()
    check("reembed covers released rows and stamps",
          store.embedder_clash(d, "another-model", 4) is None
          and d.execute("SELECT count(*) FROM rfm_memories WHERE embedding "
                        "IS NULL AND sightings >= 2").fetchone() == (0,))

print()
if failures:
    print(f"FAILED: {len(failures)} — {', '.join(failures)}")
    sys.exit(1)
print("all passed")
