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
  RFM_EMBEDDER   sentence-transformers model id (default all-MiniLM-L6-v2)
"""
import os
import sqlite3
import struct
import time

import sqlite_vec
from mcp.server.fastmcp import FastMCP

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.expanduser(os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))
EMBEDDER_ID = os.environ.get("RFM_EMBEDDER", "sentence-transformers/all-MiniLM-L6-v2")

mcp = FastMCP("sqlite-rfm-memory")
_db = None
_embedder = None


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
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(EMBEDDER_ID)
    # show_progress_bar must stay off: the MCP transport is stdio and any
    # stray stdout output corrupts the protocol.
    vec = _embedder.encode([text[:2000]], normalize_embeddings=True,
                           show_progress_bar=False)[0]
    return struct.pack(f"{len(vec)}f", *vec.tolist())


def _save(content: str) -> dict:
    content = content.strip()
    if not content:
        return {"error": "empty content"}
    d = db()
    dup = d.execute("SELECT id FROM rfm_memories WHERE content = ?", (content,)).fetchone()
    if dup:
        return {"id": dup[0], "status": "already stored"}
    cur = d.execute(
        "INSERT INTO rfm_memories(content, created_at, embedding) VALUES (?, ?, ?)",
        (content, time.time(), embed(content)))
    d.commit()
    return {"id": cur.lastrowid, "status": "saved"}


def _search(query: str, k: int = 5) -> list:
    d = db()
    rows = d.execute(
        """SELECT id, content,
                  (1.0 - vec_distance_cosine(embedding, ?)) * rfm_score(id) AS score
           FROM rfm_memories WHERE embedding IS NOT NULL
           ORDER BY score DESC LIMIT ?""",
        (embed(query), k)).fetchall()
    # Retrieval IS usage: returned memories earn an access (recency+frequency).
    for mid, _c, _s in rows:
        d.execute("SELECT rfm_record_access(?)", (mid,))
    d.commit()
    return [{"id": mid, "content": c, "score": round(s, 4)} for mid, c, s in rows]


def _feedback(memory_id: int, helped: bool) -> dict:
    d = db()
    try:
        row = d.execute("SELECT rfm_record_outcome(?, ?)",
                        (memory_id, 1.0 if helped else -1.0)).fetchone()
        d.commit()
        return {"id": memory_id, "value_score": round(row[0], 4)}
    except sqlite3.OperationalError as e:
        return {"error": str(e)}


def _status() -> dict:
    d = db()
    n, accesses, outcomes = d.execute(
        "SELECT (SELECT count(*) FROM rfm_memories),"
        " (SELECT count(*) FROM rfm_accesses),"
        " (SELECT count(*) FROM rfm_accesses WHERE outcome IS NOT NULL)").fetchone()
    return {"memories": n, "accesses": accesses, "outcomes": outcomes, "db": DB_PATH}


@mcp.tool()
def memory_save(content: str) -> dict:
    """Store a durable memory: user preferences, project facts, decisions,
    hard-won debugging lessons. One self-contained fact per call. Don't store
    ephemera (current task state) or anything derivable from the repo."""
    return _save(content)


@mcp.tool()
def memory_search(query: str, k: int = 5) -> list:
    """Search stored memories. Ranking = semantic similarity x usefulness
    (memories that were recently/frequently used and got positive feedback
    rank higher). Returns ids — after acting on a memory, report whether it
    helped via memory_feedback."""
    return _search(query, k)


@mcp.tool()
def memory_feedback(memory_id: int, helped: bool) -> dict:
    """Record whether a retrieved memory actually helped (true) or was
    irrelevant/misleading (false). This trains the ranking: helpful memories
    rise, unhelpful ones fade. Call once per memory per retrieval."""
    return _feedback(memory_id, helped)


@mcp.tool()
def memory_status() -> dict:
    """Memory store statistics: counts of memories, accesses, and outcomes."""
    return _status()


if __name__ == "__main__":
    mcp.run()
