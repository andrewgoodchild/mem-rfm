#!/usr/bin/env python3
"""sqlite-rfm memory MCP server — plug persistent, outcome-ranked memory into
Claude Code (or any MCP client).

Memories live in one SQLite database scored by rfm.py (pure Python, no
compiled extension): retrieval relevance is embedding similarity (MiniLM,
local) x rfm_score (ACT-R recency+frequency activation + outcome-feedback
value). Searching records accesses; feedback records outcomes; ranking
improves as memories prove themselves.

Env:
  RFM_MEMORY_DB  database path   (default ~/.sqlite-rfm/claude-code.db)
  RFM_EMBEDDER   embedding model id (default all-MiniLM-L6-v2)
  RFM_EMBED_BACKEND  'fastembed' (default, ONNX, ~137MB) or
                 'sentence-transformers' (pulls torch, ~988MB). Both produce
                 identical vectors for the same model; only install weight
                 differs.
"""
import functools
import json
import math
import os
import sqlite3
import struct
import sys
import threading
import time

import sqlite_vec
from pydantic import BaseModel, Field

try:                                    # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:                     # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
# No fallback needed: mcp 1.x ships ToolAnnotations in mcp.types natively,
# and mcp 2.x mirrors the mcp_types package there ("every name is the same
# object"). A version too old to have it cannot run this server anyway.
from mcp.types import ToolAnnotations

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import rfm  # noqa: E402  (repo-root module; scoring engine)
import log_env  # noqa: E402  (sibling module; shared RFM_LOG contract)

DB_PATH = os.path.expanduser(os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))
EMBEDDER_ID = os.environ.get("RFM_EMBEDDER", "sentence-transformers/all-MiniLM-L6-v2")
MAX_TOKENS = int(os.environ.get("RFM_MAX_TOKENS", "256"))

# mcp 2.0 renamed FastMCP to MCPServer and dropped the old module outright,
# so a fresh `pip install mcp` and a pinned 1.x install need different
# imports. The decorator, annotations and run() surfaces are the same.
mcp = _Server("sqlite-rfm-memory")
_db = None
_rfm = None      # rfm.register() state; carries last_error for diagnostics
_embedder = None


# Declared return types, so every tool ships an outputSchema and structured
# content rather than a bag of text blocks. A bare `-> dict` or `-> list`
# annotation silently disables FastMCP's structured-output path: before this,
# a 3-result search arrived as 3 separate TextContent blocks with no schema
# at all, leaving the client to re-parse what the server already had typed.
class SaveResult(BaseModel):
    id: int
    status: str = Field(description="'saved' or 'already stored'")


class SearchHit(BaseModel):
    id: int
    content: str
    score: float = Field(description="similarity x rfm_prior, the ranking score")


class MemoryRow(BaseModel):
    id: int
    content: str
    created: str
    accesses: int
    value: float = Field(description="outcome EWMA in [-1, 1]")
    outcomes: int
    score: float
    scope: str | None = Field(
        default=None, description="scope this memory is confined to; None = "
        "visible everywhere. Surfaced so a wrong-scope save is diagnosable.")


class ListResult(BaseModel):
    items: list[MemoryRow]
    total: int
    has_more: bool


class FeedbackResult(BaseModel):
    id: int
    value_score: float
    outcomes: int


class UpdateResult(BaseModel):
    id: int
    status: str
    accesses: int = Field(description="access history, preserved across the edit")
    value_score: float
    outcomes: int


class DeleteResult(BaseModel):
    id: int
    deleted: bool


class StatusResult(BaseModel):
    memories: int
    accesses: int
    outcomes: int
    db: str


# The spec's defaults are the worst case -- an unannotated tool declares
# itself destructive and open-world -- and its own schema names a memory
# tool as the canonical closed-world example. Nothing here reaches past the
# local database, so openWorldHint is false throughout.
def _ann(title, read_only=False, destructive=False, idempotent=False):
    return ToolAnnotations(title=title, readOnlyHint=read_only,
                           destructiveHint=destructive,
                           idempotentHint=idempotent, openWorldHint=False)


# The camelCase kwargs above are field names on mcp 1.x but only *aliases* on
# mcp 2.x, and pydantic's default for unknown kwargs is extra='ignore' — so an
# SDK that stopped accepting the aliases would not raise, it would silently
# construct all-None hints and every tool would present with the spec's
# worst-case defaults. Fail at startup instead.
if _ann("self-check", read_only=True).model_dump(by_alias=True).get("readOnlyHint") is not True:
    raise RuntimeError(
        "ToolAnnotations no longer accepts camelCase hint kwargs; annotations "
        "would silently fall back to destructive/open-world defaults")


# MCP SDK 2.0 dispatches sync tool handlers on a worker thread, so the
# connection is no longer confined to one thread the way it was under 1.x.
# Two things are needed, and only having one of them is a trap:
#
#   check_same_thread=False lets the connection cross threads at all, which
#   is safe because CPython's sqlite3 is built serialized (threadsafety 3);
#
#   the lock keeps whole operations atomic. _search does SELECT, then
#   several rfm_record_access, then commit -- interleave two of those on one
#   connection and a commit lands on another call's half-finished work.
#
# The DB statements are sub-millisecond, so serialising them costs nothing.
# Embedding is NOT sub-millisecond — its first call may download and load an
# entire model — so _save/_update/_search embed BEFORE taking this lock,
# under the separate _embed_lock, and other tools never queue behind a model
# load. db() acquires the (re-entrant) lock itself, so its lazy init cannot
# race even from a future caller that forgets @serialized.
_lock = threading.RLock()
_embed_lock = threading.Lock()


def serialized(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _lock:
            return fn(*args, **kwargs)
    return wrapper


def db():
    global _db, _rfm
    with _lock:
        if _db is None:
            dirname = os.path.dirname(DB_PATH)
            if dirname:                 # bare filename → cwd, nothing to create
                os.makedirs(dirname, exist_ok=True)
            conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10.0)
            # Fully initialise before publishing to the global: caching the
            # connection first means one failed init reports its real cause
            # once, then every later call skips init and fails with 'no such
            # table/function' forever.
            try:
                conn.enable_load_extension(True)
                sqlite_vec.load(conn)
                conn.enable_load_extension(False)
                _rfm = rfm.register(conn)
                conn.execute("SELECT rfm_init()")
                conn.execute("PRAGMA journal_mode=WAL")
                cols = [r[1] for r in conn.execute("PRAGMA table_info(rfm_memories)")]
                for col, ddl in (
                    ("embedding", "ALTER TABLE rfm_memories ADD COLUMN embedding BLOB"),
                    ("scope", "ALTER TABLE rfm_memories ADD COLUMN scope TEXT"),
                ):
                    if col in cols:
                        continue
                    try:
                        conn.execute(ddl)
                    except sqlite3.OperationalError as e:
                        # The store is user-global: two sessions starting at
                        # once can both see the column missing and race the
                        # ALTER. Losing that race is success, not failure.
                        if "duplicate column" not in str(e):
                            raise
            except BaseException:
                conn.close()
                raise
            _db = conn
    return _db


def embed(text: str) -> bytes:
    # Own lock, never nested inside _lock: the first call loads (and on a
    # cold cache, downloads) the model, and that must not block the DB lock
    # that every other tool waits on. The lock guards only the load —
    # encoding is safe to run concurrently once the model exists (ONNX
    # Runtime documents concurrent Run(); the tokenizer holds no per-call
    # state), so warm-path embeds from parallel tool calls don't queue.
    global _embedder
    enc = _embedder
    if enc is None:
        with _embed_lock:
            if _embedder is None:
                _embedder = _load_embedder()
            enc = _embedder
    vec = enc(text[:2000])
    return struct.pack(f"{len(vec)}f", *vec)


def _load_embedder():
    """fastembed by default: it runs the same model under ONNX and returns
    vectors identical to sentence-transformers, for 137MB of install instead
    of 988MB (torch alone is 505MB of that).

    The truncation length has to be matched explicitly. fastembed ships this
    model's tokenizer at 128 tokens while sentence-transformers uses 256, and
    the mismatch is invisible on short text -- the backends agree to
    1.000000 below the cut -- but silently halves anything longer."""
    fastembed_err = None
    if os.environ.get("RFM_EMBED_BACKEND", "fastembed") == "fastembed":
        try:
            from fastembed import TextEmbedding
            model = TextEmbedding(model_name=EMBEDDER_ID)
            tok = model.model.tokenizer
            tok.enable_truncation(max_length=MAX_TOKENS)
            pad = {k: v for k, v in (tok.padding or {}).items()
                   if k not in ("length", "pad_to_multiple_of")}
            tok.enable_padding(length=None, pad_to_multiple_of=8, **pad)

            def encode(text):
                v = next(iter(model.embed([text])))
                n = math.sqrt(sum(x * x for x in v)) or 1.0
                return [x / n for x in v]
            return encode
        except Exception as e:
            fastembed_err = e
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        # The default install ships fastembed only. Without this, any
        # fastembed failure (bad RFM_EMBEDDER id, offline first run) was
        # swallowed by the except above and surfaced as an unchained 'No
        # module named sentence_transformers' — pointing at a 988MB non-fix
        # while the real cause was discarded.
        if fastembed_err is not None:
            raise RuntimeError(
                f"fastembed backend failed ({fastembed_err}) and the "
                f"sentence-transformers fallback is not installed; fix the "
                f"fastembed error or `pip install sentence-transformers`"
            ) from fastembed_err
        raise RuntimeError(
            "RFM_EMBED_BACKEND=sentence-transformers but the package is not "
            "installed (the default install ships fastembed only); "
            "`pip install sentence-transformers` or unset RFM_EMBED_BACKEND"
        ) from e
    st = SentenceTransformer(EMBEDDER_ID)
    # show_progress_bar must stay off: the MCP transport is stdio and any
    # stray stdout output corrupts the protocol.
    return lambda text: st.encode([text], normalize_embeddings=True,
                                  show_progress_bar=False)[0].tolist()


# ---------------------------------------------------------------- logging
# Dogfooding needs to answer three questions the store itself cannot: is the
# loop closed (does feedback ever arrive), is the prior alive (does it vary
# across rows), and does it change what you actually see. An append-only
# JSONL beside the database records enough to answer all three; log_stats.py
# reads it. Never writes to stdout — the MCP transport is stdio and a stray
# byte corrupts the protocol.
# RFM_LOG / RFM_LOG_CONTENT semantics are shared with log_stats.py and
# hooks/session_end.py (log_env.py), which read/write this same file and
# must agree on where it lives and whether it's on.
LOG_ENABLED, LOG_PATH = log_env.resolve_log(
    os.environ.get("RFM_LOG", "1"), os.path.dirname(DB_PATH))
LOG_CONTENT = log_env.content_enabled(os.environ.get("RFM_LOG_CONTENT", "1"))


def log(op: str, **fields):
    if not LOG_ENABLED:
        return
    try:
        rec = {"t": round(time.time(), 3), "op": op, **fields}
        log_dir = os.path.dirname(LOG_PATH)
        if log_dir:                     # bare filename → cwd, nothing to create
            os.makedirs(log_dir, exist_ok=True)
        with open(LOG_PATH, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass          # logging must never break a tool call


def _redact(text: str) -> str:
    return log_env.redact(text, LOG_CONTENT)


# Seconds within which a repeat retrieval of the same memory does NOT record
# a second access. 0 disables the suppression.
ACCESS_WINDOW = float(os.environ.get("RFM_ACCESS_WINDOW", "60"))

# Stamped at import: Claude Code launches this server once per session over
# stdio, so process start IS the session boundary. _feedback uses it to tell
# a previous session's closed retrieval (this feedback implies a new access)
# from a duplicate vote on a retrieval made in this one (still an error).
_SERVER_START = time.time()


def _scope_sql(scope):
    """A scoped search sees its own scope plus unscoped memories. Project
    facts stay in their project; preferences saved without a scope stay
    visible everywhere, which is the split that makes one database usable
    across repositories."""
    return "" if scope is None else "AND (scope = ? OR scope IS NULL)"


def _scope_args(scope):
    return () if scope is None else (scope,)


MAX_CONTENT = 4000


def _sanitize(content: str) -> str:
    """Memory content is DATA that gets re-injected into future sessions'
    context: collapse newlines/control chars (prevents fabricating extra
    injected lines), defuse the marker prefix (prevents spoofing A/B
    attribution — format contract with hooks/session_start.py's injection
    marker and ab/ab_stats.py MARKER_RE) and the hook's close tag (prevents
    breaking out of its <memories> data block)."""
    content = "".join(ch if ch.isprintable() else " " for ch in content)
    content = content.replace("[rfm-memory:", "[rfm-memory ")
    content = content.replace("</memories>", "(/memories)")
    return " ".join(content.split())


def _check(content: str) -> str:
    """Validation failures are raised, not returned. A tool that returns
    {"error": ...} inside a success envelope reads as success to the model,
    which then does not retry; MCP requires isError so it can self-correct."""
    content = _sanitize(content.strip())
    if not content:
        raise ValueError("empty content")
    if len(content) > MAX_CONTENT:
        raise ValueError(f"content too long ({len(content)} > {MAX_CONTENT} chars); "
                         "save one self-contained fact per call")
    return content


def _save(content: str, scope: str | None = None) -> SaveResult:
    content = _check(content)
    vec = embed(content)                # before _lock: may load the model
    with _lock:
        d = db()
        # Dedup within the same scope only (IS is NULL-safe equality). A
        # content-only match returned 'already stored' with another scope's
        # row id — a success envelope for a memory that scope's searches
        # could never retrieve.
        dup = d.execute(
            "SELECT id FROM rfm_memories WHERE content = ? AND scope IS ?",
            (content, scope)).fetchone()
        if dup:
            log("save", id=dup[0], status="duplicate", chars=len(content))
            return SaveResult(id=dup[0], status="already stored")
        cur = d.execute(
            "INSERT INTO rfm_memories(content, created_at, embedding, scope) "
            "VALUES (?, ?, ?, ?)",
            (content, time.time(), vec, scope))
        d.commit()
    log("save", id=cur.lastrowid, status="saved", chars=len(content),
        scope=scope, content=_redact(content))
    return SaveResult(id=cur.lastrowid, status="saved")


def _update(memory_id: int, content: str) -> UpdateResult:
    """Rewrite a memory's content while keeping everything it has earned.

    Without this the only edit path is delete-then-save, which resets
    access_count, last_access, bla_cache, value_score and outcome_count --
    exactly the state the system exists to accumulate, discarded on the most
    common maintenance operation there is. The schema makes the fix trivial:
    content and embedding are host-owned, every scoring column is
    extension-maintained, so a plain UPDATE preserves all of them.

    Outcome history carries over deliberately. It is evidence about the slot
    ("agents keep needing this fact and it keeps working"), not about the
    exact wording. The trade-off is documented in docs/api.md: it means a
    memory can bank a reputation and then be rewritten, so updates are worth
    the same scrutiny as saves."""
    content = _check(content)
    vec = embed(content)                # before _lock: may load the model
    with _lock:
        d = db()
        row = d.execute(
            "SELECT access_count, value_score, outcome_count, scope "
            "FROM rfm_memories WHERE id = ?", (memory_id,)).fetchone()
        if row is None:
            raise ValueError(f"no memory with id {memory_id}")
        # Clash within the target's own scope only: the same text in another
        # scope serves different searches, and refusing the update with
        # 'delete one of the two' would destroy a valid memory's history.
        clash = d.execute(
            "SELECT id FROM rfm_memories WHERE content = ? AND id != ? "
            "AND scope IS ?", (content, memory_id, row[3])).fetchone()
        if clash:
            raise ValueError(f"memory {clash[0]} already has that exact content; "
                             f"delete one of the two rather than duplicating")
        d.execute("UPDATE rfm_memories SET content = ?, embedding = ? WHERE id = ?",
                  (content, vec, memory_id))
        d.commit()
    log("update", id=memory_id, chars=len(content), content=_redact(content),
        accesses=row[0], value=row[1], outcomes=row[2])
    return UpdateResult(id=memory_id, status="updated", accesses=row[0],
                        value_score=round(row[1], 4), outcomes=row[2])


@serialized
def _get(memory_id: int) -> MemoryRow:
    d = db()
    r = d.execute(
        """SELECT id, content, created_at, access_count, value_score,
                  outcome_count, rfm_score(id), scope
           FROM rfm_memories WHERE id = ?""",
        (memory_id,)).fetchone()
    if r is None:
        raise ValueError(f"no memory with id {memory_id}")
    return MemoryRow(id=r[0], content=r[1],
                     created=time.strftime("%Y-%m-%d", time.localtime(r[2])),
                     accesses=r[3], value=round(r[4], 3), outcomes=r[5],
                     score=round(r[6], 4), scope=r[7])


def _search(query: str, limit: int = 5, scope: str | None = None,
            min_score: float = 0.0) -> list[SearchHit]:
    # Same clamp as _list: SQLite reads LIMIT -1 as unlimited, so an
    # unclamped limit=-1 (or k=-1) dumped the whole store into context AND
    # recorded an access on every row outside the window.
    limit = max(1, min(int(limit), 200))
    qvec = embed(query)                 # before _lock: may load the model
    with _lock:
        d = db()
        # The FROZEN composition (PROTOCOL.md): clamped similarity x bounded
        # prior rfm_prior(id) = (1-beta) + beta*rfm_score(id), beta = 0.3.
        # The unbounded sim x rfm_score variant was falsified by the
        # pre-registered experiment. Split into a subquery only so the two
        # factors can be logged separately — the arithmetic and the ordering
        # are unchanged.
        rows = d.execute(
            f"""SELECT id, content, sim, prior, sim * prior AS score, last_access FROM (
                   SELECT id, content, last_access,
                          max(1.0 - vec_distance_cosine(embedding, ?), 0) AS sim,
                          rfm_prior(id) AS prior
                   FROM rfm_memories WHERE embedding IS NOT NULL {_scope_sql(scope)})
               WHERE score >= ? ORDER BY score DESC LIMIT ?""",
            (qvec, *_scope_args(scope), min_score, limit)).fetchall()

        # Retrieval IS usage: returned memories earn an access
        # (recency+frequency). But only genuine re-encounters count. A client
        # that retries, or fires speculative searches, would otherwise
        # manufacture frequency out of nothing -- and because activation
        # clamps the age of an access at EPS=1e-3 days, a burst of
        # near-instant re-accesses is not a small error but the largest
        # possible one. ACT-R's spacing effect is about genuine rehearsal;
        # suppressing a re-access inside the window keeps the measured
        # quantity the one the model is about.
        now = time.time()
        fresh = [r for r in rows
                 if r[5] is None or now - r[5] >= ACCESS_WINDOW]
        for r in fresh:
            d.execute("SELECT rfm_record_access(?)", (r[0],))
        d.commit()

        if LOG_ENABLED and rows:
            # The question that decides whether any of this is load-bearing:
            # would plain similarity have returned the same thing? Logged per
            # search so a long dogfooding run can answer it empirically
            # rather than by assertion. Stays under the lock deliberately:
            # the comparison is only meaningful against the same table
            # snapshot the main query saw.
            sim_only = [r[0] for r in d.execute(
                f"""SELECT id FROM rfm_memories WHERE embedding IS NOT NULL
                    {_scope_sql(scope)}
                    ORDER BY max(1.0 - vec_distance_cosine(embedding, ?), 0) DESC
                    LIMIT ?""", (*_scope_args(scope), qvec, limit))]
            got = [r[0] for r in rows]
            priors = [r[3] for r in rows]
            log("search", query=_redact(query), limit=limit, scope=scope,
                results=[{"id": r[0], "sim": round(r[2], 4),
                          "prior": round(r[3], 4), "score": round(r[4], 4)}
                         for r in rows],
                prior_spread=round(max(priors) - min(priors), 4),
                set_changed=set(got) != set(sim_only),
                order_changed=got != sim_only,
                accesses_recorded=len(fresh), accesses_suppressed=len(rows) - len(fresh),
                sim_only=sim_only)
    return [SearchHit(id=r[0], content=r[1], score=round(r[4], 4)) for r in rows]


@serialized
def _feedback(memory_id: int, helped: bool, score: float | None = None,
              note: str = "") -> FeedbackResult:
    """`helped` gives the ±1 the extension has always taken; `score` passes
    the rest of the [-1, 1] range it accepts, for a memory that was partly
    right or merely adjacent. `note` is not stored — outcomes are a scalar
    by design — but it is logged, which is what makes a surprising value
    score explicable weeks later."""
    outcome = float(score) if score is not None else (1.0 if helped else -1.0)
    if not -1.0 <= outcome <= 1.0:
        raise ValueError(f"score must be in [-1, 1], got {outcome}")
    d = db()
    try:
        _rfm.last_error = None
        # SessionStart injection surfaces a memory without recording an
        # access, so the one-outcome-per-retrieval guard needs a session
        # boundary to tell a new injection retrieval from a duplicate vote.
        # No access at all, or a latest access whose outcome predates this
        # server process: that loop was closed in a PREVIOUS session, and
        # the only retrieval this feedback can be about is this session's
        # injection — record the access it implies, exactly as
        # hooks/session_end.py does before writing an inferred outcome. An
        # outcome-bearing access from this session's lifetime still errors:
        # that is the duplicate the guard exists for.
        last = d.execute(
            "SELECT accessed_at, outcome FROM rfm_accesses "
            "WHERE memory_id = ? "
            "ORDER BY accessed_at DESC, rowid DESC LIMIT 1",
            (memory_id,)).fetchone()
        implied_access = last is None or (
            last[1] is not None and last[0] < _SERVER_START)
        if implied_access:
            d.execute("SELECT rfm_record_access(?)", (memory_id,))
        row = d.execute("SELECT rfm_record_outcome(?, ?)",
                        (memory_id, outcome)).fetchone()
        d.commit()
    except sqlite3.OperationalError as e:
        # stdlib sqlite3 masks a raising UDF as the generic 'user-defined
        # function raised exception'; the engine keeps the real rfm: message
        # (no such id / no recorded access / already has an outcome) on the
        # state object — relay that, so the model can self-correct.
        msg = _rfm.last_error or str(e)
        log("feedback", id=memory_id, outcome=outcome, error=msg)
        raise ValueError(msg) from e
    n = d.execute("SELECT outcome_count FROM rfm_memories WHERE id = ?",
                  (memory_id,)).fetchone()
    log("feedback", id=memory_id, helped=helped, outcome=outcome,
        note=_redact(note) if note else None, access_recorded=implied_access,
        value=round(row[0], 4), outcomes=n[0] if n else None)
    return FeedbackResult(id=memory_id, value_score=round(row[0], 4),
                          outcomes=n[0] if n else 0)


@serialized
def _status() -> StatusResult:
    d = db()
    n, accesses, outcomes = d.execute(
        "SELECT (SELECT count(*) FROM rfm_memories),"
        " (SELECT count(*) FROM rfm_accesses),"
        " (SELECT count(*) FROM rfm_accesses WHERE outcome IS NOT NULL)").fetchone()
    return StatusResult(memories=n, accesses=accesses, outcomes=outcomes,
                        db=DB_PATH)


@serialized
def _list(limit: int = 20, offset: int = 0) -> ListResult:
    d = db()
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    rows = d.execute(
        """SELECT id, content, created_at, access_count, value_score, outcome_count,
                  rfm_score(id) AS score, scope
           FROM rfm_memories ORDER BY score DESC LIMIT ? OFFSET ?""",
        (limit, offset)).fetchall()
    total = d.execute("SELECT count(*) FROM rfm_memories").fetchone()[0]
    # A bare list gives a paging agent no stopping condition.
    return ListResult(
        items=[MemoryRow(id=r[0], content=r[1],
                         created=time.strftime("%Y-%m-%d", time.localtime(r[2])),
                         accesses=r[3], value=round(r[4], 3), outcomes=r[5],
                         score=round(r[6], 4), scope=r[7]) for r in rows],
        total=total, has_more=offset + len(rows) < total)


@serialized
def _delete(memory_id: int) -> DeleteResult:
    d = db()
    gone = d.execute("DELETE FROM rfm_memories WHERE id = ?", (memory_id,)).rowcount
    d.execute("DELETE FROM rfm_accesses WHERE memory_id = ?", (memory_id,))
    d.commit()
    log("delete", id=memory_id, deleted=bool(gone))
    return DeleteResult(id=memory_id, deleted=bool(gone))


# Chars. Keeps a hostile or merely large store from flooding context — and
# stays under Claude Code's ~25k-token default tool result budget, above
# which the whole export is spilled to a file reference and the agent has to
# go and read it back.
EXPORT_CAP = 80_000


@serialized
def _export() -> str:
    d = db()
    rows = d.execute(
        "SELECT id, content, created_at, access_count, value_score, "
        "rfm_score(id) AS score, scope FROM rfm_memories ORDER BY score DESC").fetchall()
    if not rows:
        return "# mem-rfm export\n\n(no memories)"
    lines = ["# mem-rfm export", ""]
    used = 0
    for mid, content, created, acc, val, score, mscope in rows:
        day = time.strftime("%Y-%m-%d", time.localtime(created))
        scope_tag = f", scope {mscope}" if mscope else ""
        line = (f"- [{mid}] ({day}, {acc} uses, value {val:+.2f}, "
                f"score {score:.3f}{scope_tag}) {content}")
        if used + len(line) > EXPORT_CAP:
            lines.append(f"... truncated at {EXPORT_CAP} chars "
                         f"({len(rows)} memories total)")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


@mcp.tool(annotations=_ann("Save a memory", idempotent=True))
def memory_save(content: str, scope: str | None = None) -> SaveResult:
    """Store a durable memory: user preferences, project facts, decisions,
    hard-won debugging lessons. One self-contained fact per call. Don't store
    ephemera (current task state) or anything derivable from the repo.
    Saving identical content twice returns the existing memory.

    `scope` confines a memory to one project or context (a repo name, say).
    Leave it unset for facts that should apply everywhere, like preferences:
    a scoped search sees its own scope plus everything unscoped."""
    return _save(content, scope)


@mcp.tool(annotations=_ann("Search memories"))
def memory_search(query: str, limit: int = 5, scope: str | None = None,
                  min_score: float = 0.0, k: int | None = None
                  ) -> list[SearchHit]:
    """Search stored memories. Ranking = semantic similarity x usefulness
    (memories that were recently/frequently used and got positive feedback
    rank higher). Returns ids — after acting on a memory, report whether it
    helped via memory_feedback.

    `scope` restricts to that scope plus unscoped memories; `min_score`
    drops weak matches, which also stops them counting as usage.

    Not read-only: retrieval counts as usage, so returned memories record an
    access, which feeds the recency and frequency terms. Repeat retrievals
    of the same memory within a short window record only once, so retries
    don't inflate it."""
    return _search(query, k if k is not None else limit, scope, min_score)


@mcp.tool(annotations=_ann("Record whether a memory helped"))
def memory_feedback(memory_id: int, helped: bool, note: str = "",
                    score: float | None = None) -> FeedbackResult:
    """Record whether a retrieved memory actually helped (true) or was
    irrelevant/misleading (false). This trains the ranking: helpful memories
    rise, unhelpful ones fade. Call once per memory per retrieval.

    `score` overrides the implied ±1 with any value in [-1, 1], for a memory
    that was partly useful. `note` records why, for later diagnosis; it is
    written to the log, not stored on the memory.

    Feedback on a memory surfaced by session-start injection counts as its
    use, even when earlier sessions already used it: the access is recorded
    implicitly — no need to memory_search first. Only repeating feedback for
    the same retrieval within one session is rejected."""
    return _feedback(memory_id, helped, score, note)


@mcp.tool(annotations=_ann("Update a memory's content",
                           destructive=True, idempotent=True))
def memory_update(memory_id: int, content: str) -> UpdateResult:
    """Replace a memory's content, keeping its accumulated usage and value.
    Use this — not delete-then-save — when a stored fact is outdated or
    wrong but still the right thing to remember: a changed build command, a
    moved path, a superseded convention. Delete-then-save resets the usage
    history and outcome record; this preserves both."""
    return _update(memory_id, content)


@mcp.tool(annotations=_ann("Read one memory", read_only=True))
def memory_get(memory_id: int) -> MemoryRow:
    """Fetch a single memory by id with its usage and value stats — to read
    back what search returned, or to check a memory before updating it."""
    return _get(memory_id)


@mcp.tool(annotations=_ann("Memory store statistics", read_only=True))
def memory_status() -> StatusResult:
    """Memory store statistics: counts of memories, accesses, and outcomes."""
    return _status()


@mcp.tool(annotations=_ann("List memories", read_only=True))
def memory_list(limit: int = 20, offset: int = 0) -> ListResult:
    """List stored memories ranked by current usefulness score, with usage and
    value stats — for inspecting or auditing what is remembered. Returns
    total and has_more for paging."""
    return _list(limit, offset)


@mcp.tool(annotations=_ann("Delete a memory", destructive=True, idempotent=True))
def memory_delete(memory_id: int) -> DeleteResult:
    """PERMANENTLY delete a memory (and its access history) by id — not
    undoable. Use when a memory is wrong, stale, or the user asks to forget
    something. To correct a memory while keeping what it has earned, use
    memory_update instead. Clients should keep this behind a permission
    prompt."""
    return _delete(memory_id)


@mcp.tool(annotations=_ann("Export all memories", read_only=True))
def memory_export() -> str:
    """Export every memory as human-readable markdown (id, date, usage, value,
    content) — for review, backup, or migration."""
    return _export()


if __name__ == "__main__":
    mcp.run()
