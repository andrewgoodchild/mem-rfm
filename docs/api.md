# API reference

The extension registers scalar SQL functions. Loading it is the only setup:

```sql
.load ./target/release/librfm
SELECT rfm_init();
```

`rfm_init()` creates the tables and indexes and is idempotent — it also
migrates older databases by adding columns introduced later.

## Functions

| function | returns |
|---|---|
| `rfm_init()` | creates/migrates schema; `'ok'` |
| `rfm_record_access(id)` | logs a retrieval; returns the new activation |
| `rfm_record_outcome(id, o)` | records feedback `o ∈ [−1,1]` against the latest access; returns the new value EWMA |
| `rfm_prior(id)` | `(1−β) + β·rfm_score(id)` — the bounded multiplier to compose with similarity |
| `rfm_score(id)` | `w_a·P(activation) + w_v·value₀₁` |
| `rfm_activation(id)` | ACT-R base-level activation |
| `rfm_recency(id)` / `rfm_frequency(id)` / `rfm_value(id)` | individual components |
| `rfm_score_w(id, w_a, w_v[, tau, decay])` | parameterised variant, for tuning |
| `rfm_prunable(id, max_unused_days)` | 1 when a memory is idle past the window AND never proved useful |
| `rfm_config(key[, value])` | read or set a per-connection setting |

### Typical use

```sql
-- retrieve
SELECT id, content,
       max(1.0 - vec_distance_cosine(embedding, :query), 0) * rfm_prior(id) AS score
FROM rfm_memories
ORDER BY score DESC LIMIT 5;

-- record what happened
SELECT rfm_record_access(42);
SELECT rfm_record_outcome(42, 1.0);   -- it helped
SELECT rfm_record_outcome(43, -1.0);  -- it didn't
```

Call `rfm_record_access` per id *after* the ranking query returns. Calling a
mutating function while scanning the table it mutates has undefined
row-visitation order in SQLite.

## Configuration

`rfm_config` is per-connection: settings are visible to every function on
that connection and never cross connections or processes.

| key | default | meaning |
|---|---|---|
| `decay` | 0.5 | ACT-R decay `d`; must be in (0,1) |
| `lambda` | 0.3 | EWMA weight for new outcomes |
| `w_a` / `w_v` | 0.7 / 0.3 | weights of activation and value in `rfm_score` |
| `shrink_k` | 3.0 | confidence shrink: effective value = `v·n/(n+k)` |
| `beta` | 0.3 | how far the prior may move a ranking; **frozen by experiment** |
| `tau` | 86400 | time constant for `rfm_recency` only |
| `now` | unset | freeze the clock (tests and replay); `NULL` unfreezes |

`beta` deserves a note: it was frozen at 0.3 by a pre-registered experiment
and is the main safety property of the whole design
([theory](theory.md)). Raising it increases forgetting power and decreases
rank safety.

## Schema

Tables are host-owned; the extension maintains the marked columns.

```sql
rfm_memories(
  id, content, created_at,          -- yours
  access_count, last_access,        -- maintained
  bla_cache,                        -- maintained (2nd-most-recent access)
  value_score, outcome_count        -- maintained
)

rfm_accesses(memory_id, accessed_at, outcome)
```

You own `content` and any columns you add — an `embedding BLOB` for
sqlite-vec, tags, scopes, whatever. The extension only touches its own.

## Retention

`rfm_prunable(id, days)` encodes a retention policy borrowed from Codex,
where citing a memory refreshes it and uncited rows age out — usage driving
*retention*, not just ranking. mem-rfm previously had no GC at all.

```sql
SELECT id FROM rfm_memories WHERE rfm_prunable(id, 30);
```

It is a read-only predicate, not a delete: the tables are host-owned, and
dropping someone's memories is your decision. Note the guard — anything with
a positive outcome record is never prunable however long it has been idle,
because a memory retrieved rarely but successfully is exactly what this
system exists to keep.

## Invariants

Two guarantees the implementation enforces, both load-bearing:

**One outcome per access.** A second `rfm_record_outcome` without an
intervening access is refused. This means the access log always reproduces
the summary state — anyone can recompute a score from first principles, which
is what makes the audit queries trustworthy.

**Strict input types.** Ids must be genuine INTEGERs (SQLite would otherwise
silently truncate `1.9` to row 1 and coerce text to row 0), and numeric
arguments reject NULL and non-finite values rather than reading them as 0.0.

Mutating functions are `DIRECTONLY`: they cannot be invoked from views,
triggers or generated columns.

## MCP server

`integrations/claude-code/server.py` wraps the above for Claude Code or any
MCP client. Tools: `memory_save`, `memory_search`, `memory_feedback`,
`memory_list`, `memory_delete`, `memory_export`, `memory_status`.

Environment:

| variable | meaning |
|---|---|
| `RFM_MEMORY_DB` | database path (default `~/.sqlite-rfm/claude-code.db`) |
| `RFM_DYLIB` | path to `librfm` (default: this repo's release build) |
| `RFM_EMBEDDER` | embedding model id (default `all-MiniLM-L6-v2`) |
| `RFM_EMBED_BACKEND` | `fastembed` (default) or `sentence-transformers` |
| `RFM_MAX_TOKENS` | truncation length, default 256 — see below |
| `RFM_LOG` | log path, or `0` to disable |
| `RFM_LOG_CONTENT` | `0` logs lengths and ids but not query/memory text |

### Embedding backend

`fastembed` runs the same model under ONNX for a 163 MB install against
769 MB for `sentence-transformers`, which pulls torch. The two produce
identical vectors — verified not by inspection but by re-running a committed
benchmark end-to-end and diffing: all 1,065 BEAM rows bit-identical.

That equality is conditional on `RFM_MAX_TOKENS` matching the model's
`max_seq_length`. fastembed ships this model's tokenizer truncating at 128
tokens where sentence-transformers uses 256, so anything longer than a short
paragraph silently embeds from half its text. Short strings agree to
1.000000 either way, which is what makes it dangerous. If you change
`RFM_EMBEDDER`, set `RFM_MAX_TOKENS` to that model's real limit.

### Logging

The server appends one JSON line per operation to `RFM_LOG` (default
`rfm-log.jsonl` beside the database). Searches record each result's
similarity and prior separately, plus what plain cosine ranking would have
returned — so a dogfooding run can answer whether the prior changed anything
rather than assuming it did.

```sh
integrations/claude-code/log_stats.py [--days 7]
```

reports loop closure (what fraction of retrieved memories ever got an
outcome), prior liveness, and how often RFM changed the returned set or its
order. It flags an open loop and a dead prior explicitly, because both look
like normal operation from the outside.

`capture.md` has a CLAUDE.md snippet telling the agent what is worth saving
(bias it toward operational facts — see [findings](findings.md)), and an
optional SessionStart hook injects top memories by pure `rfm_score` with no
query at all, capped at 1,500 characters.
