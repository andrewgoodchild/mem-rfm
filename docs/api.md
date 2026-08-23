# API reference

`rfm.py` (repo root, stdlib-only) registers scalar SQL functions on a
sqlite3 connection. Registering it is the only setup:

```python
import sqlite3, rfm
db = sqlite3.connect("memories.db")
rfm.register(db)
db.execute("SELECT rfm_init()")
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
| `rfm_score_w(id, w_a, w_v[, decay])` | parameterised variant, for tuning |
| `rfm_prunable(id, max_unused_days)` | 1 when a memory is idle past the window AND never proved useful |
| `rfm_prior_of(access_count, created_at, last_access, bla_cache, value_score, outcome_count)` | same number as `rfm_prior(id)`, without the row lookup |
| `rfm_config(key[, value])` | read or set a per-connection setting |
| `rfm_version()` | engine version — `rfm_init()` migrates schemas, so hosts can check what they loaded |

### Three ways to compute the same number

`rfm_prior(id)` reads its own row, which costs a `prepare` per row because
the id is interpolated into the statement. That is right for scoring a
handful of candidates and wrong for ranking a whole table. `rfm_prior_of`
takes the columns instead, so the scan reads each row once, as it was going
to anyway. And the arithmetic is plain enough to write in SQL, which
matters because it means even the engine is an optimization rather than a
dependency.

Measured on 50,000 rows, `ORDER BY … DESC LIMIT 10` (Python engine; the
retired Rust extension's numbers live at the `rust-extension` tag):

| form | time | when |
|---|---|---|
| pure SQL (no UDFs) | **40.5 ms** | ranking a table — no per-row Python call |
| `rfm_prior_of(cols)` | 92.2 ms | ranking a table through the engine |
| `rfm_prior(id)` | 171.9 ms | scoring a few known ids; most readable |

All three agree exactly. `bench-quality/pure_sql_check.py` generates the SQL
and checks it against the engine over 2,000 rows covering every branch of
the hybrid activation and its boundaries: max difference 1.1e-16, identical
ranking. `rfm_prior_of` decodes through the same row logic as `rfm_prior`
and is pinned to it by `tests/test_rfm.py`.

The pure-SQL path is what makes this portable to places the engine cannot
go: hosted SQLite, or a host language with no UDF surface. It needs
`SQLITE_ENABLE_MATH_FUNCTIONS` (`ln`, `exp`, `pow`), which is present in
macOS's system SQLite 3.51, `node:sqlite` and better-sqlite3.

`rfm_prunable`'s window is in **days**, while every timestamp and `tau` is in
seconds. That is deliberate — a retention policy is a human-scale decision —
but it is the one unit discontinuity in the surface, so it is called out
here rather than discovered.

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
| `theta` | 0.0 | ACT-R retrieval threshold: where the activation→[0,1] squash is centred |
| `s` | 1.0 | ACT-R activation noise: how steep that squash is |
| `now` | unset | freeze the clock (tests and replay); `NULL` unfreezes |

`beta` deserves a note: it was frozen at 0.3 by a pre-registered experiment
and is the main safety property of the whole design
([theory](theory.md)). Raising it increases forgetting power and decreases
rank safety.

`theta` and `s` are exposed for fitting rather than for use. ACT-R fits both
per model — θ spans −60..+0.5 across ACT-R's own tutorial, and s is usually
recommended in [0.2, 0.8] — and ours sit at 0.0/1.0, which on second-scale
lags puts a whole store in the squash's left tail. They are configurable so
that can be measured; the defaults do not move until an experiment says so.

## Schema

Tables are host-owned; the engine maintains the marked columns.

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
sqlite-vec, tags, scopes, whatever. The engine only touches its own.

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

Two guarantees the implementation enforces, neither of them optional:

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
MCP client.

| tool | notes |
|---|---|
| `memory_save` | one self-contained fact; identical content de-duplicates; optional `scope` |
| `memory_search` | `limit`, `scope`, `min_score`. **Not read-only** — retrieval counts as usage |
| `memory_feedback` | signed outcome; optional `score` in [-1,1] and a `note` for the log |
| `memory_update` | rewrite content, keep accumulated usage and value |
| `memory_get` | read one memory back by id |
| `memory_list` | ranked, with `total` and `has_more` |
| `memory_delete` | permanent, including access history |
| `memory_export` | markdown dump |

All nine declare an `outputSchema` and return structured content, and all
carry explicit annotations. This matters more than it sounds: the MCP
defaults are the worst case — an unannotated tool advertises itself as
destructive *and* open-world — and a bare `-> dict` or `-> list` return
annotation silently disables structured output, so a three-result search
arrived as three unschema'd text blocks. Validation failures raise, so the
client sees `isError` and can correct itself, rather than an error string
wrapped in a success envelope.

### Scope

One database across many projects otherwise means one pool: a build quirk
from one repository competing for rank in every other. `scope` is a free
string (a repo name works) set on save; a search passing that scope sees its
own scope **plus everything unscoped**. So project facts stay put while
preferences saved without a scope remain visible everywhere.

### Retrieval and usage accounting

Retrieval records an access, which is what feeds recency and frequency, so
two things guard the signal:

- **`RFM_ACCESS_WINDOW`** (default 60s) suppresses a second access for the
  same memory inside the window. Without it a client that retries, or fires
  speculative searches, manufactures frequency out of nothing — and because
  activation clamps an access's age at `EPS = 1e-3` days, a burst of
  near-instant re-accesses is not a small error but the largest available
  one. ACT-R's spacing effect is about genuine rehearsal.
- **`min_score`** drops weak matches before they are returned, which also
  stops them counting as usage. A result that was never worth showing
  should not earn a frequency credit.

### Updating a memory

`memory_update` exists because the alternative destroys the thing this
project is about. Correcting a memory by deleting and re-saving it resets
`access_count`, `last_access`, `bla_cache`, `value_score` and
`outcome_count` — the entire accumulated record — on what is the single most
common maintenance operation. Because `content` and `embedding` are
host-owned and every scoring column is engine-maintained, a plain
`UPDATE` preserves all of it; only the embedding is recomputed.

Outcome history carries over deliberately: it is evidence about the slot
("agents keep needing this and it keeps working"), not about the exact
wording. The trade-off is that a memory can bank a reputation and then be
rewritten, so an update deserves the same scrutiny as a save. We have not
measured whether value evidence *should* decay on edit — no mechanism is
shipped for it, in keeping with not shipping unmeasured mechanisms.

Environment:

| variable | meaning |
|---|---|
| `RFM_MEMORY_DB` | database path (default `~/.sqlite-rfm/claude-code.db`) |
| `RFM_EMBEDDER` | embedding model id (default `sentence-transformers/all-MiniLM-L6-v2`); must be in fastembed's registry unless the sentence-transformers backend is installed |
| `RFM_EMBED_BACKEND` | `fastembed` (default) or `sentence-transformers` — the latter needs a separate `pip install sentence-transformers`; the documented install ships fastembed only |
| `RFM_MAX_TOKENS` | truncation length, default 256 — see below |
| `RFM_LOG` | log path (`0`/`off` disables; `1`/`on`/`true` keep the default path beside the DB) |
| `RFM_LOG_CONTENT` | `0` logs lengths and ids but not query/memory text |
| `RFM_ACCESS_WINDOW` | seconds before a repeat retrieval re-counts as usage (default 60; `0` disables) |
| `RFM_PRUNE_DAYS` | retention window for the SessionEnd prune pass — idle past this AND never useful is deleted (default 30; `<= 0` disables) |

### Checking it works

`integrations/claude-code/smoke_test.py` spawns the server and speaks MCP
over stdio against a temporary database — 39 checks covering every tool,
the output schemas, the annotations, `isError` on each failure path, and the
behaviours that are easy to break silently: that update preserves usage,
that a repeat retrieval inside the window does not re-count, that a weak
match under `min_score` earns nothing, that a scoped search excludes other
scopes, and that a second outcome without a new access is refused.

It is not an in-process test, and that is the point. The tool bodies were
correct at a moment when `pip install mcp` resolved to 2.0 and the server
would not import at all; the same upgrade moved tool handlers onto a worker
thread, which broke a module-level SQLite connection intermittently rather
than outright. Both are invisible without a real launch. The server now runs
green on recent mcp 1.x (tested on 1.28; the structured-output surface it
relies on needs ≥ 1.10) and 2.x.

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
