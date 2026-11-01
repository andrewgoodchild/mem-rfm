"""The integration's own columns and tables, in one place.

The engine owns its marked columns (rfm_schema.sql); everything else in the
store is host-owned, and used to be added by whichever process happened to
run first (server, session_end, sweep), with no record of what a store was
built with. ensure() is now the one migration path, stamped in PRAGMA
user_version, and the rules several delivery paths must share live here
beside it: which scope a directory is, what scope a session may see, and
what has cleared quarantine.

export_store / import_store are the lossless round trip. A ledger earned
over months is the one thing a store holds that cannot be rebuilt, and
memory_export is a truncated markdown view for reading, not a backup.
"""
import base64
import json
import os
import re
import sqlite3
import time

SCHEMA_VERSION = 2
FORMAT = "mem-rfm-export"
FORMAT_VERSION = 1

COLUMNS = (("embedding", "BLOB"), ("scope", "TEXT"),
           ("condition_class", "TEXT"), ("sightings", "INTEGER"),
           ("era", "TEXT"), ("origins", "TEXT"), ("source", "TEXT"))
TABLES = (
    # Text before a memory_update. An edit keeps the ledger on purpose, so
    # a memory can bank a reputation and then be rewritten; this is what
    # makes that auditable. The trigger means every delete path (forget,
    # prune, evict) also forgets the old text.
    """CREATE TABLE IF NOT EXISTS rfm_memory_history (
  memory_id     INTEGER NOT NULL,
  content       TEXT NOT NULL,
  replaced_at   REAL NOT NULL,
  value_score   REAL NOT NULL,
  outcome_count INTEGER NOT NULL
)""",
    """CREATE TRIGGER IF NOT EXISTS rfm_memory_history_forget
  AFTER DELETE ON rfm_memories BEGIN
  DELETE FROM rfm_memory_history WHERE memory_id = OLD.id;
END""",
    # rfm_meta is the engine's and numeric; this one holds host strings.
    """CREATE TABLE IF NOT EXISTS rfm_host_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
)""",
)
# Every table a store's history lives in, in the order import restores them.
DUMPED = ("rfm_meta", "rfm_host_meta", "rfm_memories", "rfm_accesses",
          "rfm_memory_history")


def ensure(db):
    """Bring a store to SCHEMA_VERSION. Idempotent, and cheap once stamped:
    every hook runs it. The caller must have registered the engine."""
    db.execute("SELECT rfm_init()")
    if db.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
        return
    have = {r[1] for r in db.execute("PRAGMA table_info(rfm_memories)")}
    for name, kind in COLUMNS:
        if name in have:
            continue
        try:
            db.execute(f"ALTER TABLE rfm_memories ADD COLUMN {name} {kind}")
        except sqlite3.OperationalError as e:
            # The store is user-global: two sessions starting at once can
            # both see the column missing and race the ALTER. Losing that
            # race is success, not failure.
            if "duplicate column" not in str(e):
                raise
    for ddl in TABLES:
        db.execute(ddl)
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


# ------------------------------------------------------------------- scope

_WORKTREE = re.compile(r"gitdir:\s*(.+?)[/\\]\.git[/\\]worktrees[/\\]")


def project(cwd=None):
    """The scope of a directory: its repository's name, the convention the
    agent is told to save under (install_hooks.MD_BLOCK). A linked worktree
    is its main repository. Outside any repository, the directory's own
    name."""
    start = os.path.abspath(cwd or os.getcwd())
    probe = start
    while True:
        marker = os.path.join(probe, ".git")
        if os.path.isdir(marker):
            return os.path.basename(probe) or None
        if os.path.isfile(marker):
            try:
                with open(marker) as f:
                    m = _WORKTREE.match(f.read())
            except OSError:
                m = None
            if m:
                return os.path.basename(m.group(1))
            return os.path.basename(probe) or None
        parent = os.path.dirname(probe)
        if parent == probe:
            return os.path.basename(start) or None
        probe = parent


def in_scope(scope):
    """(sql, args): this scope plus everything unscoped, the rule _scope_sql
    gives an explicit search. Case-folded here because a directory name and
    an agent's spelling of a repo name need not agree on case."""
    if not scope:
        return "scope IS NULL", ()
    return "(scope IS NULL OR scope = ? COLLATE NOCASE)", (scope,)


def released():
    """SQL: this row has cleared the sweep's quarantine. NULL sightings are
    explicit saves and miner-ratified rows, which never entered it."""
    n = int(os.environ.get("RFM_QUARANTINE", 2))
    return f"(sightings IS NULL OR sightings >= {n})"


# ---------------------------------------------------------------- embedder

def embedder_clash(db, model, dim):
    """None, or why vectors from `model` cannot be ranked against this
    store. A changed dimension makes vec_distance_cosine raise over the
    whole scan; a same-dimension swap would not raise at all, and rank by
    meaningless scores. The first caller stamps the store."""
    got = dict(db.execute("SELECT key, value FROM rfm_host_meta "
                          "WHERE key IN ('embedder', 'dim')"))
    if not got:
        row = db.execute("SELECT length(embedding) FROM rfm_memories WHERE "
                         "embedding IS NOT NULL LIMIT 1").fetchone()
        if row and row[0] != dim * 4:
            return (f"stored vectors have {row[0] // 4} dimensions, "
                    f"{model} has {dim}")
        stamp_embedder(db, model, dim)
        return None
    if got.get("embedder") != model or got.get("dim") != str(dim):
        return (f"store was embedded with {got.get('embedder')} "
                f"({got.get('dim')} dimensions), this process uses {model} "
                f"({dim})")
    return None


def stamp_embedder(db, model, dim):
    db.executemany("INSERT OR REPLACE INTO rfm_host_meta(key, value) "
                   "VALUES (?, ?)", (("embedder", model), ("dim", str(dim))))
    db.commit()


# ------------------------------------------------------------ export/import

def _encode(value):
    if isinstance(value, bytes):
        return {"$b64": base64.b64encode(value).decode("ascii")}
    return value


def _decode(value):
    if isinstance(value, dict):
        return base64.b64decode(value["$b64"])
    return value


def export_store(db, fh):
    """Every row of every table, rowids included: access order is what
    'the latest access' means to the engine. Returns the rows written."""
    n = 0
    fh.write(json.dumps({"format": FORMAT, "version": FORMAT_VERSION,
                         "schema": SCHEMA_VERSION,
                         "exported_at": time.time()}) + "\n")
    for table in DUMPED:
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
        for row in db.execute(f"SELECT {', '.join(cols)} FROM {table} "
                              "ORDER BY rowid"):
            fh.write(json.dumps({"table": table, "row": dict(
                zip(cols, map(_encode, row)))}) + "\n")
            n += 1
    return n


def import_store(db, fh):
    """Restore an export into an empty store, all or nothing. Ids are kept,
    which is why it refuses to merge: transcripts and accesses name them.
    Returns the rows restored."""
    head = json.loads(fh.readline() or "{}")
    if head.get("format") != FORMAT:
        raise ValueError("not a mem-rfm export")
    if head.get("version", 0) > FORMAT_VERSION or \
            head.get("schema", 0) > SCHEMA_VERSION:
        raise ValueError("export is newer than this checkout; update first")
    ensure(db)
    if db.execute("SELECT count(*) FROM rfm_memories").fetchone()[0]:
        raise ValueError("import needs an empty store")
    cols = {t: {r[1] for r in db.execute(f"PRAGMA table_info({t})")}
            for t in DUMPED}
    n = 0
    try:
        for line in fh:
            rec = json.loads(line)
            table, row = rec["table"], rec["row"]
            # Names come from the file, so they are checked, never trusted.
            if table not in cols or not set(row) <= cols[table]:
                raise ValueError(f"unknown table or column in {table!r}")
            names = list(row)
            db.execute(
                f"INSERT OR REPLACE INTO {table} ({', '.join(names)}) "
                f"VALUES ({', '.join('?' * len(names))})",
                [_decode(row[c]) for c in names])
            n += 1
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return n
