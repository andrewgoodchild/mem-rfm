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
  value_score, outcome_count,       -- maintained
)

rfm_accesses(memory_id, accessed_at, outcome)
```

You own `content` and any columns you add — an `embedding BLOB` for
sqlite-vec, tags, scopes, whatever. The extension only touches its own.

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
| `RFM_EMBEDDER` | sentence-transformers model id |


`capture.md` has a CLAUDE.md snippet telling the agent what is worth saving
(bias it toward operational facts — see [findings](findings.md)), and an
optional SessionStart hook injects top memories by pure `rfm_score` with no
query at all, capped at 1,500 characters.
