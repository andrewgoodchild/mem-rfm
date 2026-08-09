"""Shared machinery for the three benchmark evals (LongMemEval, LoCoMo, BEAM):
extension loading, a generic memory store wrapping librfm, ranking conditions,
and retrieval metrics. Datasets differ per eval; scoring must not."""
import math
import os
import sqlite3
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIM_RECENCY_TAU = 7 * 86_400.0


def resolve_dylib():
    """Env override, else the first candidate this Python can actually load
    (arch must match the interpreter, so probe rather than assume)."""
    if os.environ.get("RFM_DYLIB"):
        return os.environ["RFM_DYLIB"]
    candidates = [
        os.path.join(HERE, "..", "target", "release", "librfm.dylib"),
        os.path.join(HERE, "..", "target", "x86_64-apple-darwin", "release", "librfm.dylib"),
    ]
    for p in candidates:
        if not os.path.exists(p):
            continue
        probe = sqlite3.connect(":memory:")
        try:
            probe.enable_load_extension(True)
            probe.load_extension(p)
            check_fresh(p)
            return p
        except sqlite3.OperationalError:
            continue
        finally:
            probe.close()
    sys.exit("no loadable librfm.dylib found — run `cargo build --release` (or set RFM_DYLIB)")


def check_fresh(dylib):
    """Refuse to benchmark a dylib older than the Rust sources that built it.

    `cargo test` builds the x86_64 target (the .load-capable Homebrew CLI is
    Intel) while this arm64 harness loads target/release — so a green test
    run does NOT imply the benchmarked build is current. Publishing numbers
    from a stale extension would be unauditable, so this is fatal, not a
    warning."""
    src = os.path.join(HERE, "..", "src")
    newest = max(
        [os.path.getmtime(os.path.join(src, f)) for f in os.listdir(src)]
        + [os.path.getmtime(os.path.join(HERE, "..", "Cargo.toml"))]
    )
    if newest > os.path.getmtime(dylib):
        sys.exit(f"stale extension: {dylib} predates src/ — run `cargo build --release`")


DYLIB = resolve_dylib()


# Embedder is swappable via env for robustness runs, e.g.
#   RFM_EMBEDDER=Qwen/Qwen3-Embedding-0.6B
EMBEDDER_ID = os.environ.get("RFM_EMBEDDER", "sentence-transformers/all-MiniLM-L6-v2")


def cache_suffix():
    """Embedding caches are per-model; MiniLM keeps the original dirs."""
    if "MiniLM-L6-v2" in EMBEDDER_ID:
        return ""
    return "-" + EMBEDDER_ID.split("/")[-1].lower().replace("_", "-")


def get_embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBEDDER_ID)


def encode(embedder, texts, kind="doc"):
    """kind='query' applies the model's query prompt when it defines one
    (Qwen3-Embedding and friends embed queries and documents differently)."""
    kwargs = {}
    if kind == "query" and "query" in getattr(embedder, "prompts", {}):
        kwargs["prompt_name"] = "query"
    # Larger models need smaller MPS batches.
    batch = 128 if "MiniLM" in EMBEDDER_ID else 16
    return embedder.encode(
        [t[:2000] for t in texts], normalize_embeddings=True, batch_size=batch,
        show_progress_bar=False, **kwargs,
    ).astype(np.float32)


class MemoryStore:
    """One benchmark item's memories in a fresh in-memory DB with librfm.

    rows: list of (mem_id, text, created_at); embs: matrix aligned with rows.
    """

    def __init__(self, rows, embs, fts=False, creators=None):
        self.db = sqlite3.connect(":memory:")
        self.db.enable_load_extension(True)
        self.db.load_extension(DYLIB)
        self.db.enable_load_extension(False)
        self.db.execute("SELECT rfm_init()")
        # creators: optional {mem_id: writer} for actor-tagged stores
        # (hardened-mode evals; None keeps the untagged schema behavior).
        self.db.executemany(
            "INSERT INTO rfm_memories(id, content, created_at, created_by) "
            "VALUES (?,?,?,?)",
            [(m, t[:200], ts, (creators or {}).get(m)) for m, t, ts in rows])
        self.embs = embs
        self.row_of = {m: i for i, (m, _t, _ts) in enumerate(rows)}
        if fts:
            # Full-text index over the FULL turn text (rfm_memories.content is
            # truncated); rowid = mem_id so scores join trivially.
            self.db.execute("CREATE VIRTUAL TABLE fts USING fts5(content)")
            self.db.executemany(
                "INSERT INTO fts(rowid, content) VALUES (?,?)",
                [(m, t) for m, t, _ts in rows])

    def bm25_scores(self, query_text, ids):
        """Positive BM25 per candidate (0 = no match). SQLite's bm25() is
        negated (smaller = better), so flip sign. Query text is sanitized to
        an OR of bare tokens — FTS5 syntax characters would otherwise error."""
        import re
        tokens = re.findall(r"[A-Za-z0-9_]+", query_text)[:32]
        if not tokens:
            return np.zeros(len(ids))
        match = " OR ".join(f'"{t}"' for t in tokens)
        got = {}
        try:
            for rowid, s in self.db.execute(
                    "SELECT rowid, bm25(fts) FROM fts WHERE fts MATCH ?", (match,)):
                got[rowid] = -s
        except sqlite3.OperationalError:
            return np.zeros(len(ids))
        return np.array([got.get(m, 0.0) for m in ids])

    def close(self):
        self.db.close()

    def freeze(self, t: float):
        self.db.execute("SELECT rfm_config('now', ?)", (t,))

    def sims(self, query_emb, ids):
        idx = [self.row_of[m] for m in ids]
        return self.embs[idx] @ query_emb

    def rfm_scores(self, ids, w=None):
        fn = "rfm_score(id)" if w is None else f"rfm_score_w(id, {w[0]}, {w[1]})"
        placeholders = ",".join("?" * len(ids))
        got = dict(self.db.execute(
            f"SELECT id, {fn} FROM rfm_memories WHERE id IN ({placeholders})", ids))
        return np.array([got[m] for m in ids])

    def activations(self, ids):
        placeholders = ",".join("?" * len(ids))
        got = dict(self.db.execute(
            f"SELECT id, rfm_activation(id) FROM rfm_memories WHERE id IN ({placeholders})", ids))
        return np.array([got[m] for m in ids])

    def value_state(self, ids):
        """(value_score, outcome_count) per id — for harness-side prior blends."""
        placeholders = ",".join("?" * len(ids))
        got = {r[0]: (r[1], r[2]) for r in self.db.execute(
            f"SELECT id, value_score, outcome_count FROM rfm_memories WHERE id IN ({placeholders})",
            ids)}
        return (np.array([got[m][0] for m in ids]),
                np.array([got[m][1] for m in ids], dtype=float))

    def access_state(self, ids):
        placeholders = ",".join("?" * len(ids))
        got = {r[0]: (r[1], r[2]) for r in self.db.execute(
            f"SELECT id, created_at, last_access FROM rfm_memories WHERE id IN ({placeholders})",
            ids)}
        return [got[m] for m in ids]

    def set_exclude_self(self, on):
        self.db.execute("SELECT rfm_config('exclude_self', ?)", (1 if on else 0,))

    def set_one_vote(self, on):
        self.db.execute("SELECT rfm_config('one_vote', ?)", (1 if on else 0,))

    def set_created_by(self, pairs):
        """Tag memories with their writer (host principal); enables hardened
        mode's self-endorsement check. pairs: list of (mem_id, actor)."""
        for m, a in pairs:
            self.db.execute("UPDATE rfm_memories SET created_by = ? WHERE id = ?", (a, m))

    def record_accesses(self, ids, actor=None):
        for m in ids:
            if actor is None:
                self.db.execute("SELECT rfm_record_access(?)", (m,))
            else:
                self.db.execute("SELECT rfm_record_access(?, ?)", (m, actor))

    def record_outcomes(self, pairs, actor=None):
        for m, o in pairs:
            if actor is None:
                self.db.execute("SELECT rfm_record_outcome(?, ?)", (m, o))
            else:
                self.db.execute("SELECT rfm_record_outcome(?, ?, ?)", (m, o, actor))


def rank(store: MemoryStore, condition: str, query_emb, candidate_ids, now: float, k: int):
    """Order candidates under a named ranking condition; return top-k ids.

    sim          cosine similarity only
    sim_recency  sim * exp(-age/7d)
    genagents    min-max normalized recency+relevance (Park et al. 2023)
    rfm          sim * rfm_score(id)      (M on: value axis live)
    rfm_wv0      sim * rfm_score_w(id, 0.7, 0.0)  (value axis off)
    """
    ids = list(candidate_ids)
    sims = store.sims(query_emb, ids)
    if condition == "sim":
        scores = sims
    elif condition == "sim_recency":
        state = store.access_state(ids)
        age = np.array([now - c for c, _ in state])
        scores = np.maximum(sims, 0.0) * np.exp(-age / SIM_RECENCY_TAU)
    elif condition == "genagents":
        state = store.access_state(ids)
        anchor = np.array([la if la is not None else c for c, la in state])
        recency = 0.995 ** (np.maximum(now - anchor, 0.0) / 3600.0)
        def norm(x):
            span = x.max() - x.min()
            return (x - x.min()) / span if span > 0 else np.zeros_like(x)
        scores = norm(recency) + norm(sims)
    elif condition == "rfm":
        scores = np.maximum(sims, 0.0) * store.rfm_scores(ids)
    elif condition == "rfm_wv0":
        scores = np.maximum(sims, 0.0) * store.rfm_scores(ids, w=(0.7, 0.0))
    elif condition.startswith("rfm_beta"):
        # Bounded blend (PROTOCOL.md frozen composition): sim × ((1−β) + β·rfm).
        b = float(condition[len("rfm_beta"):])
        scores = np.maximum(sims, 0.0) * ((1.0 - b) + b * store.rfm_scores(ids))
    else:
        raise ValueError(condition)
    top = np.argsort(-scores, kind="stable")[:k]
    return [ids[i] for i in top]


def recall_ndcg(retrieved, evidence_ids, k):
    """Turn-level recall@k, hit@k, NDCG@k against a set of gold ids."""
    ev = set(evidence_ids)
    got = [m for m in retrieved if m in ev]
    dcg = sum(1.0 / math.log2(i + 2) for i, m in enumerate(retrieved) if m in ev)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(ev), k)))
    return {
        "recall": len(set(got)) / len(ev) if ev else None,
        "hit": 1.0 if got else 0.0,
        "ndcg": dcg / ideal if ideal > 0 else None,
    }


def bootstrap_ci(deltas, n=10_000, seed=7):
    """95% CI on the mean of paired deltas."""
    rng = np.random.default_rng(seed)
    arr = np.asarray(deltas, dtype=float)
    if len(arr) == 0:
        return (float("nan"), float("nan"))
    means = rng.choice(arr, size=(n, len(arr)), replace=True).mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))
