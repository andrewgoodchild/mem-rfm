# Design notes

Deviations considered, tradeoffs taken, and known limitations. The brief's
architecture (Rust + `sqlite-loadable`, two tables, scalar-function API) was
followed without structural changes.

## Approved deviations from the brief

1. **Confidence shrink on the value axis.** A plain EWMA over one or two
   outcomes is noise presented as signal. `rfm_score` uses
   `value_score · n/(n + k)` (default `k = 3`, config `shrink_k`), which
   required one extra column, `rfm_memories.outcome_count`. `rfm_value(id)`
   still returns the raw EWMA. Set `shrink_k = 0` to disable.
2. **First outcome initializes the EWMA directly** (`value ← outcome`)
   instead of blending with a fake zero prior. With λ = 0.3, the alternative
   would leave a single strong "+1 this helped" signal at 0.3 forever until
   more feedback arrives.
3. **README positioning**: `rfm_score` is documented as a *prior* to compose
   with similarity search, not a standalone ranker. RFM knows what has been
   useful lately; only an embedding knows what is relevant *now*.

## bla_cache: what it actually stores

The brief describes `bla_cache` as "incremental base-level activation
(Petrov 2006 approximation)". Storing the activation *value* is impossible to
maintain incrementally: power-law decay `t^(-d)` does not factor across a time
shift (unlike exponential decay), so a stored B goes stale the moment the
clock moves. What Petrov's hybrid scheme actually needs is a small fixed
state: `{n, lifetime, k most recent access times}`.

`rfm_memories` already holds `access_count` (n), `created_at` (lifetime), and
`last_access` (t₁) — that is Petrov k = 1 for free. The single REAL
`bla_cache` buys exactly one more retained timestamp, so it stores **the wall
time of the second most recent access** (t₂), giving k = 2. The incremental
update in `rfm_record_access` is one assignment (`bla_cache ← old
last_access`), and scoring reads one row of `rfm_memories` and nothing else.
"No second access yet" is encoded as NULL, the same encoding `last_access`
uses. (An earlier draft used a 0.0 sentinel with NOT NULL; review caught that
it conflated "none" with a legitimate access at wall time ≤ 0 — reachable via
`rfm_config('now', t)` with relative or pre-1970 timestamps — so the column
became nullable.)
Petrov's own error analysis shows k = 1 already captures the recency-driven
spike; k = 2 also keeps the previous event exact. Measured against the exact
log-sum on the benchmark databases (random 20–200-access histories): mean
absolute error ≈ 0.05 activation units, max ≈ 0.4. A future k > 2 upgrade can
fetch additional lags from `rfm_accesses` via the provided index without a
schema change.

## Normalization choices in rfm_score

Activation is unbounded, value lives in [-1, 1]. Activation maps through
ACT-R's own retrieval-probability equation `P = 1/(1 + exp(-(B - θ)/s))` with
θ = 0, s = 1 fixed (named constants in `math.rs`; promotable to config keys
later without breaking anything). Value maps by `(v + 1)/2`, clamped. Custom
weights in `rfm_score_w` are *not* renormalized — the result range is
`[0, w_a + w_v]` — because silently rescaling user-supplied weights is more
surprising than a documented range.

## rfm_score_w's tau parameter is accepted but unused

The brief specifies `rfm_score_w(id, w_a, w_v, tau, decay)`. In this design
activation subsumes the exponential-recency term, and nothing in `rfm_score`
uses τ (it only parameterizes the standalone `rfm_recency`). The 5-arg form
accepts τ for signature compatibility and ignores it; a 3-arg form
`rfm_score_w(id, w_a, w_v)` is also registered. If a future version blends
`rfm_recency` into the score, τ is already plumbed.

## Executing SQL from scalar functions

SQLite cannot fire triggers on SELECT, so access logging is explicit —
`rfm_record_access` runs INSERT/UPDATE from inside a scalar callback against
the host connection (`sqlite3_context_db_handle`, the same pattern as
SQLite's own `ext/misc/eval.c`). sqlite-loadable 0.0.6-alpha.6 exposes the
raw prepare/step/finalize wrappers this needs; `src/sql.rs` is a ~100-line
safe shim over them. Two crate gaps worked around:

- No `bind_double`/`column_double`: REALs are read via `column_value` +
  `value_double`, and written by formatting the f64 into the SQL text with
  Rust's shortest-round-trip formatting (bit-exact through SQLite's
  text→REAL parse; only self-produced, finiteness-checked numbers are ever
  interpolated, so there is no injection surface).
- The crate's optional `exec` feature can only read TEXT/INTEGER columns, so
  it is not used.

## Transactionality and statement structure of rfm_record_access

The function executes `INSERT INTO rfm_accesses ... SELECT ... WHERE id = ?`
(which doubles as the existence check — a bad id inserts nothing rather than
an orphan log row), then `UPDATE rfm_memories ... RETURNING` the post-update
summary row, from which the returned activation is computed. Using RETURNING
means the state transition is encoded exactly once, in SQL: the value
`rfm_record_access` returns is computed from the same bytes a subsequent
`rfm_activation(id)` will read. **This sets the extension's minimum host
SQLite to 3.35 (2021-03)**, documented in the README.

Opening a nested transaction inside an active statement callback is not
reliable, so the statements run sequentially. When the caller is already
inside a transaction they commit or roll back together. In autocommit mode
there is a one-statement crash window; the INSERT runs first deliberately, so
a crash between the two leaves an extra log row but a consistent (slightly
stale) summary — scoring trusts the summary, and the log row is recoverable
by an offline rebuild. A SAVEPOINT-based variant was probed and works in the
common case, but was rejected for v0.1: it changes behavior when the host has
its own SAVEPOINT stack active, and the failure mode it prevents is milder
than the complexity it adds.

## One outcome per access, strict input types

`rfm_record_outcome` refuses a second outcome for the same access (the UPDATE
carries `AND outcome IS NULL` and a `changes()` check): allowing it would
overwrite the log row while the EWMA absorbed both calls, making the summary
unreproducible from the log. Record a new access to give new feedback.

All SQL inputs are strictly typed: ids must be genuine INTEGERs (SQLite's
value_int64 would otherwise truncate 1.9 to row 1 and coerce text to row 0 —
silent wrong-row writes), and REAL arguments (outcome, weights, tau, decay)
reject NULL and non-finite values instead of letting value_double read them
as 0.0. tau in `rfm_score_w` remains unused (see above) but is validated like
every other argument.

## Actor tagging and hardened mode (shared stores)

`rfm_memories.created_by` and `rfm_accesses.actor` are both nullable TEXT,
set by the host — the extension never invents a principal, it only compares
the two. With `rfm_config('exclude_self', 1)`, an access or outcome whose
`actor` equals the memory's `created_by` is ignored **entirely**: no log
row, no summary change, no outcome slot consumed. That last part matters —
consuming the slot would let an attacker's ignored self-outcome block a
legitimate agent's real feedback on the same access.

Why the writer/reader identity comparison rather than rate-limiting or
anomaly detection: it is the only defense that is O(1), needs no history
scan, has no tunable threshold to overfit, and cannot be tuned wrong. It
closes the *entitled* attack — a team member using calls it is allowed to
make (self-access to pump R and F, self-feedback to pump M) — rather than
trying to distinguish suspicious usage from enthusiastic usage.

The design deliberately does NOT authenticate the actor string: a host that
lets a compromised component pass an arbitrary `actor` has already lost
that battle upstream. This is defense against a *principal* misbehaving
within its rights, not against principal impersonation, which belongs to
the host's auth layer.

Default is off (`exclude_self = 0`) for exact back-compat, and because the
protection is only meaningful when the host actually tags writers; on an
untagged store it is a no-op. `rfm_init()` runs idempotent `ALTER TABLE ...
ADD COLUMN` statements so pre-v0.3 databases gain the columns on next load
(the ALTERs fail harmlessly with "duplicate column" on current schemas).

The utility cost is measured, not asserted (PROTOCOL.md Amendment 6): the
registered U2 bar rejects the whole mechanism if excluding self-endorsement
degrades legitimate retrieval by more than 0.01 hit@1 on a clean store —
the same veto that killed confident-negative pruning in Step P. It passed
at +0.0009 h@1 on an 8-agent store.

The cost is workload-shaped, and measured (RESULTS.md, post-hoc team-size
sweep): a *solo* store — where every memory is self-authored, so hardening
discards all legitimate feedback — pays **−0.80 points hit@1**, about the
size of the value axis's entire rank-1 contribution, as the mechanism
implies. That cost vanishes by two-to-four writers (−0.16, −0.09, both
n.s.). Hence the guidance: leave `exclude_self` off for single-agent
stores (the Claude Code integration's shape), enable it from ~2 writers
up. The defense itself still works solo (poison occupancy 0.023 vs 0.068
unhardened) — you just pay for it there and not in a team.

## one_vote: implemented, measured, not recommended

`rfm_config('one_vote', 1)` caps outcomes at one per (actor, memory) so
`value_score` counts distinct endorsers rather than repetitions. It is the
obvious ballot-stuffing defense and it does not work (Amendment 7): against
a self-promoting attacker it recovers nothing measurable and still trails
plain similarity, while costing −0.34 hit@1 on a clean store.

The reason is symmetric and worth stating plainly: **a vote cap throttles
the corrective signal exactly as much as the abusive one.** Unhardened, a
bad memory earns a negative every single time it wastes someone's time —
that is what makes demotion converge. With one vote per actor, an
eight-agent team can land at most eight negatives on it, ever. The attack
is capped and so is the immune response, and in a recurring workload the
immune response was doing more work.

It ships off by default and stays in the surface because the measurement is
worth more than the feature: "we tried the obvious defense and it backfired
for this reason" is a result. `exclude_self` is the primitive that actually
defends (it removes an *illegitimate* signal rather than rationing a
legitimate one), which is the general lesson — asymmetric defenses beat
symmetric caps.

## Other known limitations

- **Per-connection config, no cross-process coherence.** `rfm_config` lives
  in extension memory keyed to the connection (one shared state per `.load`).
  Two connections (or two processes) can score with different parameters.
  Persisting config to a table was rejected for v0.1: it turns every score
  call into an extra read, and per-connection defaults are the SQLite norm.
- **`SELECT rfm_record_access(id) FROM rfm_memories WHERE ...`** — calling a
  mutating function while scanning the table it mutates has undefined
  row-visitation order in SQLite. Recommended usage is per-id calls after the
  ranking query returns.
- **Mutators are DIRECTONLY**: `rfm_init`, `rfm_record_access`,
  `rfm_record_outcome`, and 2-arg `rfm_config` cannot be invoked from views,
  triggers, or generated columns.
- **The value axis needs the host to supply outcomes.** The extension stores
  and aggregates feedback; deciding whether a retrieval "helped" is the
  caller's job. The benchmark harness shows one label-free heuristic
  (evidence-hit) and the demo shows a simulated one; production agents might
  use task success, user reaction, or an LLM self-critique.
- **Reading the w_v = 0 ablation carefully.** In the main LongMemEval
  protocol no outcomes accumulate (one labeled question per instance), so
  every memory's value term is the neutral constant 0.5·w_v. The gap between
  `rfm` (0.708) and `rfm_wv0` (0.379) is therefore not "value signal helps" —
  it is the *floor effect*: the constant term keeps the multiplicative prior
  bounded away from zero, damping an activation signal that is (on this
  dataset) uncorrelated with the question. Value-as-signal is only measured
  by the feedback-demo experiment. Both facts are stated in the README; do
  not quote the ablation as evidence that outcome feedback improves recall.
- **Rosetta note**: benchmark timings in the README were measured with an
  x86_64 build running under Rosetta 2 (the only `.load`-capable sqlite3 CLI
  on the dev machine was Intel Homebrew). Native arm64 numbers will be
  faster; the *shape* (O(1) vs O(history)) is architecture-independent.

## Proposed design update (2026-08-27): config-driven extraction and value, and the three clocks

Status: **PROPOSAL, unmeasured** — written down before any implementation,
per house discipline. Motivated by the Zep architecture review
(fact-extraction ontologies, write-time ratings, bi-temporal edges) read
against what Tracks 10/11/13 and Correction C4 measured. The Zep ideas
are adopted where our data supports the shape and inverted where it
convicts them.

### 1. Configuration-driven extraction (a formation ontology)

Formation currently mines free prose and stores free prose. The update:
the extractor emits **structured rows against a per-deployment ontology
config** — default schema `{condition_class, scope, action, evidence,
era}`. This is Zep's custom-entity-types idea with our measured default
ontology: recurring operational conditions in, per-bug episodic content
excluded *by schema* rather than by judgment. The
harness-proposes/human-ratifies contract is untouched — config governs
what the extractor is asked for, never who admits the result.

Why structure pays three times (Track 11 + C4): the `condition_class`
field makes condition-conditioned value mechanical instead of
regex-crafted; `acted_on()` can match the `action` field instead of the
backtick heuristic that Track 11 convicted of measuring quotability; and
`era`/`scope` gives validity metadata a declared home (the Track 2
instinct, honored structurally).

### 2. Configuration-driven value: config sets priors, evidence stays sovereign

M becomes explicitly two-layered:

- **Posterior (unchanged, the core):** the signed outcome EWMA with
  confidence shrink. No configuration touches it.
- **Priors (config):** a cold-start initial value per type/class — the
  one place write-time judgment has measured support (+42.6 points,
  MultiDoc2Dial authored manual) — eroded by the existing `n/(n+k)`
  shrink. Priors decay; they never gate. Zep's `minRating`-style
  permanent relevance filter is explicitly rejected: it is write-time
  importance (Track 8's dispute, causally unvalidated anywhere) made
  load-bearing forever.
- **Conditioning (new, the C4 fix):** an outcome counts toward the
  posterior only when the session exhibited the memory's
  `condition_class`. The flagship earned 79% of its ledger
  condition-silent (C4); Track 13 delivered it 8/8 and lost 0/5/3 at
  +27.6% wall. An M that cannot tell "helped" from "was copied while
  nothing was at risk" is the instrument all three live tracks indicted.

### 3. The three clocks, named

The engine runs on wall-clock time (`time.time()`, freezable via
`rfm_config('now')`), and today every R/F quantity derives from one
event stream. The update names what is actually three:

- **t_formed** (`created_at`) — ingestion time. Exists.
- **t_used** (access events; acted-on only, injection is not access —
  lifecycle.md) — today's R/F substrate, feeding ACT-R activation via
  Petrov k=2. Exists.
- **t_fired** — when the world last exhibited the memory's
  `condition_class`. **Does not exist, and it is the theoretically
  correct clock.** Anderson & Schooler ground retention in the
  statistics of environmental *need*; access history is our proxy for
  need, and C4 measured the proxy diverging in both directions (use
  without need: the copied flagship; need without use: the prose arm).
  For operational memories, activation computed over condition-fire
  history is the A&S-faithful R/F, and fire-rate decay is the staleness
  mechanism the silent fossil needs — contradiction-invalidation
  (Zep's) only catches facts that get *denied*, not conditions that
  stop *occurring*. For preference/procedural-about-you memories
  (CLAUDE.md-shaped), use IS need and t_used remains the right clock —
  the clock choice itself belongs in the ontology config.
- Plus one non-clock axis: **validity scope** (`era`, checkout ranges)
  — repo-time, not wall-time; declarative, from the schema.

### Cost and gates

t_fired needs a condition-event log — the PostToolUse hook already
classifies exactly these error-class events (Track 5/6 machinery), so
the observation side exists; storage is one event kind, and the
conditioned-outcome rule lands in `rfm_record_outcome`. The extractor
upgrade is next-work 6.5. Adoption gates, fixed now: the
condition_value audit re-run as acceptance on the new fields, and any
ranking-visible change ships only behind a registered track. Nothing
here alters the two-table scalar-function shape beyond the event kind.

### Implemented (2026-08-27): the conditioning layer, hook-side

The condition-conditioned value piece of the proposal above shipped in
the integration layer, not the engine — the two-table scalar-function
shape is untouched. `condition_class` is a host-owned column added and
lazily stamped by session_end.py (derivation: the classes the memory's
own text names; explicit stamps are never overwritten). t_fired's
observation side is `fired_classes()` over the session's arrived command
output, logged per session. The gate, with one refinement the proposal
left open and the implementation fixed: **only positive outcomes are
conditioned.** A copied command that fails is evidence against the
memory whether or not its condition fired; a copied command that
succeeds proves nothing unless the condition was live (C4's exact
failure mode). `RFM_CONDITIONED_OUTCOMES=0` disables. Acceptance audit:
hooks/test_conditions.py, 9 checks, including the C4 case verbatim —
silent-condition +1 records nothing. Fire-rate decay and any
ranking-visible use of t_fired remain unimplemented behind the
registered-track gate.
