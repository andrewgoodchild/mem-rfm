#!/usr/bin/env python3
"""sqlite-rfm memory MCP server — plug persistent, outcome-ranked memory into
Claude Code (or any MCP client).

Memories live in one SQLite database scored by librfm: retrieval relevance is
embedding similarity (MiniLM, local) x rfm_score (ACT-R recency+frequency
activation + outcome-feedback value). Searching records accesses; feedback
records outcomes; ranking improves as memories prove themselves.

Env:
  RFM_MEMORY_DB  database path   (default ~/.sqlite-rfm/claude-code.db)
  RFM_DYLIB      librfm path     (default: this repo's target/release build)
  RFM_EMBEDDER   embedding model id (default all-MiniLM-L6-v2)
  RFM_EMBED_BACKEND  'fastembed' (default, ONNX, ~137MB) or
                 'sentence-transformers' (pulls torch, ~988MB). Both produce
                 identical vectors for the same model; only install weight
                 differs.
"""
import json
import math
import os
import sqlite3
import struct
import time

import sqlite_vec
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.expanduser(os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))
EMBEDDER_ID = os.environ.get("RFM_EMBEDDER", "sentence-transformers/all-MiniLM-L6-v2")
MAX_TOKENS = int(os.environ.get("RFM_MAX_TOKENS", "256"))

mcp = FastMCP("sqlite-rfm-memory")
_db = None
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


def resolve_dylib():
    if os.environ.get("RFM_DYLIB"):
        return os.environ["RFM_DYLIB"]
    for p in (
        os.path.join(HERE, "..", "..", "target", "release", "librfm.dylib"),
        os.path.join(HERE, "..", "..", "target", "x86_64-apple-darwin", "release", "librfm.dylib"),
    ):
        if os.path.exists(p):
            return p
    raise RuntimeError("librfm.dylib not found — run `cargo build --release` or set RFM_DYLIB")


def db():
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db = sqlite3.connect(DB_PATH)
        _db.enable_load_extension(True)
        sqlite_vec.load(_db)
        _db.load_extension(resolve_dylib())
        _db.enable_load_extension(False)
        _db.execute("SELECT rfm_init()")
        _db.execute("PRAGMA journal_mode=WAL")
        cols = [r[1] for r in _db.execute("PRAGMA table_info(rfm_memories)")]
        if "embedding" not in cols:
            _db.execute("ALTER TABLE rfm_memories ADD COLUMN embedding BLOB")
    return _db


def embed(text: str) -> bytes:
    global _embedder
    if _embedder is None:
        _embedder = _load_embedder()
    vec = _embedder(text[:2000])
    return struct.pack(f"{len(vec)}f", *vec)


def _load_embedder():
    """fastembed by default: it runs the same model under ONNX and returns
    vectors identical to sentence-transformers, for 137MB of install instead
    of 988MB (torch alone is 505MB of that).

    The truncation length has to be matched explicitly. fastembed ships this
    model's tokenizer at 128 tokens while sentence-transformers uses 256, and
    the mismatch is invisible on short text -- the backends agree to
    1.000000 below the cut -- but silently halves anything longer."""
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
        except Exception:
            pass
    from sentence_transformers import SentenceTransformer
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
LOG_PATH = os.path.expanduser(os.environ.get(
    "RFM_LOG", os.path.join(os.path.dirname(DB_PATH), "rfm-log.jsonl")))
LOG_ENABLED = os.environ.get("RFM_LOG", "1") not in ("0", "off", "")
# Queries and memory content are the sensitive part. They sit in the same
# directory as the database, which already holds the memories themselves, so
# the default logs them; RFM_LOG_CONTENT=0 keeps lengths and ids only.
LOG_CONTENT = os.environ.get("RFM_LOG_CONTENT", "1") not in ("0", "off")


def log(op: str, **fields):
    if not LOG_ENABLED:
        return
    try:
        rec = {"t": round(time.time(), 3), "op": op, **fields}
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass          # logging must never break a tool call


def _redact(text: str) -> str:
    return text if LOG_CONTENT else f"<{len(text)} chars>"


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


def _save(content: str) -> SaveResult:
    content = _check(content)
    d = db()
    dup = d.execute("SELECT id FROM rfm_memories WHERE content = ?", (content,)).fetchone()
    if dup:
        log("save", id=dup[0], status="duplicate", chars=len(content))
        return SaveResult(id=dup[0], status="already stored")
    cur = d.execute(
        "INSERT INTO rfm_memories(content, created_at, embedding) VALUES (?, ?, ?)",
        (content, time.time(), embed(content)))
    d.commit()
    log("save", id=cur.lastrowid, status="saved", chars=len(content),
        content=_redact(content))
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
    d = db()
    row = d.execute(
        "SELECT access_count, value_score, outcome_count FROM rfm_memories "
        "WHERE id = ?", (memory_id,)).fetchone()
    if row is None:
        raise ValueError(f"no memory with id {memory_id}")
    clash = d.execute(
        "SELECT id FROM rfm_memories WHERE content = ? AND id != ?",
        (content, memory_id)).fetchone()
    if clash:
        raise ValueError(f"memory {clash[0]} already has that exact content; "
                         f"delete one of the two rather than duplicating")
    d.execute("UPDATE rfm_memories SET content = ?, embedding = ? WHERE id = ?",
              (content, embed(content), memory_id))
    d.commit()
    log("update", id=memory_id, chars=len(content), content=_redact(content),
        accesses=row[0], value=row[1], outcomes=row[2])
    return UpdateResult(id=memory_id, status="updated", accesses=row[0],
                        value_score=round(row[1], 4), outcomes=row[2])


def _get(memory_id: int) -> MemoryRow:
    d = db()
    r = d.execute(
        """SELECT id, content, created_at, access_count, value_score,
                  outcome_count, rfm_score(id) FROM rfm_memories WHERE id = ?""",
        (memory_id,)).fetchone()
    if r is None:
        raise ValueError(f"no memory with id {memory_id}")
    return MemoryRow(id=r[0], content=r[1],
                     created=time.strftime("%Y-%m-%d", time.localtime(r[2])),
                     accesses=r[3], value=round(r[4], 3), outcomes=r[5],
                     score=round(r[6], 4))


def _search(query: str, k: int = 5) -> list[SearchHit]:
    d = db()
    qvec = embed(query)
    # The FROZEN composition (PROTOCOL.md): clamped similarity x bounded prior
    # rfm_prior(id) = (1-beta) + beta*rfm_score(id), beta = 0.3. The unbounded
    # sim x rfm_score variant was falsified by the pre-registered experiment.
    # Split into a subquery only so the two factors can be logged separately —
    # the arithmetic and the ordering are unchanged.
    rows = d.execute(
        """SELECT id, content, sim, prior, sim * prior AS score FROM (
               SELECT id, content,
                      max(1.0 - vec_distance_cosine(embedding, ?), 0) AS sim,
                      rfm_prior(id) AS prior
               FROM rfm_memories WHERE embedding IS NOT NULL)
           ORDER BY score DESC LIMIT ?""", (qvec, k)).fetchall()
    # Retrieval IS usage: returned memories earn an access (recency+frequency).
    for r in rows:
        d.execute("SELECT rfm_record_access(?)", (r[0],))
    d.commit()

    if LOG_ENABLED and rows:
        # The question that decides whether any of this is load-bearing: would
        # plain similarity have returned the same thing? Logged per search so
        # a long dogfooding run can answer it empirically rather than by
        # assertion.
        sim_only = [r[0] for r in d.execute(
            """SELECT id FROM rfm_memories WHERE embedding IS NOT NULL
               ORDER BY max(1.0 - vec_distance_cosine(embedding, ?), 0) DESC
               LIMIT ?""", (qvec, k))]
        got = [r[0] for r in rows]
        priors = [r[3] for r in rows]
        log("search", query=_redact(query), k=k,
            results=[{"id": r[0], "sim": round(r[2], 4),
                      "prior": round(r[3], 4), "score": round(r[4], 4)}
                     for r in rows],
            prior_spread=round(max(priors) - min(priors), 4),
            set_changed=set(got) != set(sim_only),
            order_changed=got != sim_only,
            sim_only=sim_only)
    return [SearchHit(id=r[0], content=r[1], score=round(r[4], 4)) for r in rows]


def _feedback(memory_id: int, helped: bool) -> FeedbackResult:
    d = db()
    try:
        row = d.execute("SELECT rfm_record_outcome(?, ?)",
                        (memory_id, 1.0 if helped else -1.0)).fetchone()
        d.commit()
    except sqlite3.OperationalError as e:
        log("feedback", id=memory_id, helped=helped, error=str(e))
        raise ValueError(str(e)) from e
    n = d.execute("SELECT outcome_count FROM rfm_memories WHERE id = ?",
                  (memory_id,)).fetchone()
    log("feedback", id=memory_id, helped=helped,
        value=round(row[0], 4), outcomes=n[0] if n else None)
    return FeedbackResult(id=memory_id, value_score=round(row[0], 4),
                          outcomes=n[0] if n else 0)


def _status() -> StatusResult:
    d = db()
    n, accesses, outcomes = d.execute(
        "SELECT (SELECT count(*) FROM rfm_memories),"
        " (SELECT count(*) FROM rfm_accesses),"
        " (SELECT count(*) FROM rfm_accesses WHERE outcome IS NOT NULL)").fetchone()
    return StatusResult(memories=n, accesses=accesses, outcomes=outcomes,
                        db=DB_PATH)


def _list(limit: int = 20, offset: int = 0) -> ListResult:
    d = db()
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    rows = d.execute(
        """SELECT id, content, created_at, access_count, value_score, outcome_count,
                  rfm_score(id) AS score
           FROM rfm_memories ORDER BY score DESC LIMIT ? OFFSET ?""",
        (limit, offset)).fetchall()
    total = d.execute("SELECT count(*) FROM rfm_memories").fetchone()[0]
    # A bare list gives a paging agent no stopping condition.
    return ListResult(
        items=[MemoryRow(id=r[0], content=r[1],
                         created=time.strftime("%Y-%m-%d", time.localtime(r[2])),
                         accesses=r[3], value=round(r[4], 3), outcomes=r[5],
                         score=round(r[6], 4)) for r in rows],
        total=total, has_more=offset + len(rows) < total)


def _delete(memory_id: int) -> DeleteResult:
    d = db()
    gone = d.execute("DELETE FROM rfm_memories WHERE id = ?", (memory_id,)).rowcount
    d.execute("DELETE FROM rfm_accesses WHERE memory_id = ?", (memory_id,))
    d.commit()
    log("delete", id=memory_id, deleted=bool(gone))
    return DeleteResult(id=memory_id, deleted=bool(gone))


EXPORT_CAP = 200_000  # chars; keeps a hostile/huge store from flooding context


def _export() -> str:
    d = db()
    rows = d.execute(
        "SELECT id, content, created_at, access_count, value_score, "
        "rfm_score(id) AS score FROM rfm_memories ORDER BY score DESC").fetchall()
    if not rows:
        return "# mem-rfm export\n\n(no memories)"
    lines = ["# mem-rfm export", ""]
    used = 0
    for mid, content, created, acc, val, score in rows:
        day = time.strftime("%Y-%m-%d", time.localtime(created))
        line = (f"- [{mid}] ({day}, {acc} uses, value {val:+.2f}, "
                f"score {score:.3f}) {content}")
        if used + len(line) > EXPORT_CAP:
            lines.append(f"... truncated at {EXPORT_CAP} chars "
                         f"({len(rows)} memories total)")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


@mcp.tool(annotations=_ann("Save a memory", idempotent=True))
def memory_save(content: str) -> SaveResult:
    """Store a durable memory: user preferences, project facts, decisions,
    hard-won debugging lessons. One self-contained fact per call. Don't store
    ephemera (current task state) or anything derivable from the repo.
    Saving identical content twice returns the existing memory."""
    return _save(content)


@mcp.tool(annotations=_ann("Search memories"))
def memory_search(query: str, k: int = 5) -> list[SearchHit]:
    """Search stored memories. Ranking = semantic similarity x usefulness
    (memories that were recently/frequently used and got positive feedback
    rank higher). Returns ids — after acting on a memory, report whether it
    helped via memory_feedback.

    Not read-only: retrieval counts as usage, so every returned memory
    records an access, which feeds the recency and frequency terms."""
    return _search(query, k)


@mcp.tool(annotations=_ann("Record whether a memory helped"))
def memory_feedback(memory_id: int, helped: bool) -> FeedbackResult:
    """Record whether a retrieved memory actually helped (true) or was
    irrelevant/misleading (false). This trains the ranking: helpful memories
    rise, unhelpful ones fade. Call once per memory per retrieval."""
    return _feedback(memory_id, helped)


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
