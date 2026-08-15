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
    Intel) while this arm64 harness loads target/release — so a green test run
    does NOT imply the benchmarked build is current. Publishing numbers from a
    stale extension would be unauditable, so this is fatal, not a warning."""
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
    """fastembed (ONNX) by default, sentence-transformers if unavailable.

    These are not approximations of each other: fastembed running the same
    model produces vectors identical to sentence-transformers to 6 decimal
    places (cosine 1.000000, pairwise similarity matrices differing by 0.0),
    so every committed benchmark number holds under either. The difference is
    install weight — 137MB against 988MB, because sentence-transformers pulls
    torch (505MB on its own)."""
    if os.environ.get("RFM_EMBED_BACKEND", "fastembed") == "fastembed":
        try:
            from fastembed import TextEmbedding
            m = TextEmbedding(model_name=EMBEDDER_ID)
            _match_truncation(m)
            return _FastEmbedAdapter(m)
        except Exception:
            pass          # unsupported model id -> sentence-transformers
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBEDDER_ID)


# fastembed defaults this model's tokenizer to 128 tokens where
# sentence-transformers uses 256, so anything longer than a short paragraph
# gets silently half-truncated and embeds differently. Undetectable on short
# strings -- the two agree to 1.000000 below the cut -- but it moved BEAM's
# similarity NDCG by 2.4 points before this was matched up.
MAX_TOKENS = int(os.environ.get("RFM_MAX_TOKENS", "256"))


def _match_truncation(model):
    tok = model.model.tokenizer
    tok.enable_truncation(max_length=MAX_TOKENS)
    # Padding is pinned to the same 128 and must move with it, or batches
    # come out ragged. Padding to the batch maximum rather than a flat 256
    # is equivalent under the attention mask and avoids paying for padding
    # on the short strings that dominate a memory store.
    pad = dict(tok.padding or {})
    pad.pop("length", None)
    pad.pop("pad_to_multiple_of", None)
    tok.enable_padding(length=None, pad_to_multiple_of=8, **pad)
    if tok.truncation["max_length"] != MAX_TOKENS:
        raise RuntimeError("could not set fastembed truncation")


class _FastEmbedAdapter:
    """Presents fastembed through the sentence-transformers call shape the
    harness already uses, so no eval script changes."""

    def __init__(self, model):
        self.model = model
        self.prompts = {}          # fastembed has no query-prompt concept

    def encode(self, texts, normalize_embeddings=True, batch_size=128,
               show_progress_bar=False, **kwargs):
        v = np.array(list(self.model.embed(texts, batch_size=batch_size)))
        if normalize_embeddings:
            v = v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
        return v


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

    def __init__(self, rows, embs):
        self.db = sqlite3.connect(":memory:")
        self.db.enable_load_extension(True)
        self.db.load_extension(DYLIB)
        self.db.enable_load_extension(False)
        self.db.execute("SELECT rfm_init()")
        self.db.executemany(
            "INSERT INTO rfm_memories(id, content, created_at) VALUES (?,?,?)",
            [(m, t[:200], ts) for m, t, ts in rows])
        self.embs = embs
        self.row_of = {m: i for i, (m, _t, _ts) in enumerate(rows)}

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

    def priors(self, ids):
        """rfm_prior(id) computed BY THE EXTENSION, so every config key it
        reads (beta, w_a, w_v, decay, shrink_k, theta, s) actually applies.

        `rank(..., "rfm_betaX")` recomputes the blend in Python with a literal
        beta, which is right for the frozen-composition evals but silently
        ignores rfm_config('beta', ...) — an ablation arm that sets beta must
        use this path or it measures nothing."""
        placeholders = ",".join("?" * len(ids))
        got = dict(self.db.execute(
            f"SELECT id, rfm_prior(id) FROM rfm_memories WHERE id IN ({placeholders})",
            ids))
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

    def record_accesses(self, ids):
        for m in ids:
            self.db.execute("SELECT rfm_record_access(?)", (m,))

    def record_outcomes(self, pairs):
        for m, o in pairs:
            self.db.execute("SELECT rfm_record_outcome(?, ?)", (m, o))


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
