-- sqlite-rfm schema. Created by rfm_init(); provided standalone for hosts that
-- prefer to manage their own migrations. Tables are host-owned; the extension
-- only maintains the columns marked below.

CREATE TABLE IF NOT EXISTS rfm_memories (
  id            INTEGER PRIMARY KEY,
  content       TEXT NOT NULL,
  created_at    REAL NOT NULL,              -- unix epoch seconds
  -- maintained by the extension:
  access_count  INTEGER NOT NULL DEFAULT 0,
  last_access   REAL,                       -- unix epoch seconds of most recent access (t1)
  bla_cache     REAL,                       -- unix epoch seconds of SECOND most recent access (t2);
                                            -- NULL = none (same encoding as last_access). Petrov (2006)
                                            -- hybrid k=2 state: together with access_count, created_at,
                                            -- last_access this is everything rfm_activation needs —
                                            -- no scan of rfm_accesses.
  value_score   REAL NOT NULL DEFAULT 0.0,  -- EWMA of outcome feedback in [-1, 1]
  outcome_count INTEGER NOT NULL DEFAULT 0  -- number of outcomes received; drives confidence shrink
);

CREATE TABLE IF NOT EXISTS rfm_accesses (
  memory_id   INTEGER NOT NULL REFERENCES rfm_memories(id),
  accessed_at REAL NOT NULL,
  outcome     REAL              -- NULL = no feedback; else [-1, 1]
);

-- Not on the scoring hot path (scoring reads one rfm_memories row). Serves the
-- exact-recompute audit/baseline and rfm_record_outcome's most-recent-access lookup.
CREATE INDEX IF NOT EXISTS rfm_accesses_mem_time
  ON rfm_accesses(memory_id, accessed_at DESC);

-- The ledger's path-dependent parameters, stamped at the first recorded
-- outcome. value_score
-- is an EWMA — a function of the lambda it was built under — so
-- rfm_record_outcome refuses to extend a ledger under a mismatched lambda.
-- Re-stamping (UPDATE rfm_meta SET value = ... WHERE key = 'lambda') is the
-- deliberate override.
CREATE TABLE IF NOT EXISTS rfm_meta (
  key   TEXT PRIMARY KEY,
  value REAL NOT NULL
);
