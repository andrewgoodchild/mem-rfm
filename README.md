# sqlite-rfm

**RFM-scored agent memory as a SQLite extension.** Ranks memories by
**R**ecency and **F**requency — unified as ACT-R base-level activation — plus
a **M**onetary-analog value axis fed by retrieval-outcome feedback:

```sql
SELECT id, content, rfm_score(id) AS score
FROM rfm_memories
ORDER BY score DESC
LIMIT 5;

-- after the agent uses a retrieved memory:
SELECT rfm_record_access(42);
SELECT rfm_record_outcome(42, 1.0);  -- the memory helped
```

Zero dependencies, loads into a stock `sqlite3` CLI, one summary-row read per
score (O(1) regardless of access-history length).

`rfm_score` is a **prior, not a ranker**: it knows what has been useful
lately, and only an embedding knows what is relevant *now*. Compose it with
any similarity search via `rfm_prior(id)` — the bounded multiplier
`(1−β) + β·rfm_score(id)` (β = 0.3 by default, `rfm_config('beta', …)`), so
usage history adjusts a similarity ranking but can never overwhelm it — here
with [sqlite-vec](https://github.com/asg017/sqlite-vec) in the same
connection:

```sql
SELECT id, content,
       max(1.0 - vec_distance_cosine(embedding, :query), 0) * rfm_prior(id) AS score
FROM rfm_memories
ORDER BY score DESC
LIMIT 5;
-- max(sim, 0) is part of the frozen formula: without it, a larger prior
-- LOWERS the score of negative-similarity candidates.
```

(Why bounded, and why β = 0.3: chosen by a pre-registered experiment —
`PROTOCOL.md` — after an embedder-robustness check showed the unbounded
composition penalizes strong retrievers. Results below.)

## Why

Agent memory frameworks (Mem0, LangMem, MemoryBank, Generative Agents) keep
rediscovering fragments of the same scoring problem: recency decay is common,
frequency boosts are rare, and outcome feedback — *did retrieving this memory
actually help?* — is the acknowledged gap. RFM is the 60-year-old
database-marketing framework that names exactly these three signals: how
recently, how often, how much value. This extension packages the combination
where lightweight agent state actually lives: SQLite.

## The theory

### Recency and frequency are one number

ACT-R (Anderson & Lebiere 1998), the cognitive architecture, models the
usefulness of a memory as **base-level activation** over its access history:

```
B = ln( Σᵢ tᵢ^(−d) )        tᵢ = seconds since the i-th access, d = 0.5
```

Every access adds a term; every term decays as a power law. A memory accessed
often ranks high (frequency); a memory accessed recently ranks high (recency);
the trade-off between "used 50 times last month" and "used twice today" falls
out of one principled equation rather than two tuned knobs. Power-law decay
also matches the human forgetting curve, which is why ACT-R's form has held up
for decades of cognitive modeling.

### The Petrov approximation makes it O(1)

Exact activation needs the full access history — O(history) per score, which
is what makes most implementations give up and use `exp(-age/τ)`. Petrov
(2006) showed the sum splits into the k most recent accesses kept *exactly*
plus a closed-form tail for the older n−k, assumed uniform over the memory's
lifetime L:

```
B ≈ ln( t₁^(−d) + t₂^(−d) + (n−2)·(L^(1−d) − t₂^(1−d)) / ((1−d)·(L − t₂)) )    [k = 2]
```

The recency spike that matters for ranking is driven almost entirely by the
most recent access (Petrov's own analysis: k = 1 already captures it). This
extension uses k = 2, and the schema already holds everything the formula
needs: `access_count` (n), `created_at` (L), `last_access` (t₁), and
`bla_cache` stores the second-most-recent access time (t₂), updated by a
single assignment on each access. **Scoring reads one row and never scans the
access log.** Measured against the exact log-sum on randomized 20–200-access
histories: mean absolute error ≈ 0.05 activation units, max ≈ 0.4 (see
benchmark below; error concentrates in bursty histories, exactly where Petrov
predicts).

### The third axis: value

Activation says *attended-to*; it cannot say *helped*. The M axis is an
exponentially weighted moving average of outcome feedback in [-1, 1]:

```
value ← λ·outcome + (1−λ)·value        λ = 0.3, first outcome initializes
```

with a confidence shrink `value · n/(n+3)` so one lucky "+1" doesn't outshout
an unproven memory's neutral prior. The headline score is then

```
rfm_score = w_a · P(B) + w_v · (value_eff + 1)/2      P(B) = 1/(1+e^(−B)), w_a = 0.7, w_v = 0.3
```

where `P(B)` is ACT-R's own retrieval-probability squash. Who decides the
outcome is deliberately out of scope — task success, user reaction, an LLM
self-critique, or evidence-hit as in our benchmark harness. Storing and
aggregating it is the part every framework was missing; this does that part.

## Install / load

Requires a `.load`-capable SQLite **3.35+** (RETURNING). Apple's
`/usr/bin/sqlite3` has extension loading compiled out — use Homebrew's:
`brew install sqlite` (keg-only; `/opt/homebrew/opt/sqlite/bin/sqlite3` on
Apple silicon, `/usr/local/opt/sqlite/bin/sqlite3` on Intel prefixes).

```sh
cargo build --release
sqlite3   # Homebrew build, e.g. /opt/homebrew/opt/sqlite/bin/sqlite3
```

```sql
.load ./target/release/librfm
SELECT rfm_init();      -- creates rfm_memories + rfm_accesses (see rfm_schema.sql)
```

From Python (needs a build with `enable_load_extension`, e.g. uv/Homebrew
Python — macOS system Python compiles it out):

```python
db = sqlite3.connect("agent.db")
db.enable_load_extension(True)
db.load_extension("./target/release/librfm")
```

## API

| function | returns |
|---|---|
| `rfm_init()` | creates the two tables + index (idempotent) |
| `rfm_record_access(id)` | logs an access, updates summary state; returns new activation |
| `rfm_record_outcome(id, o)` | records feedback `o ∈ [-1,1]` for the latest access (once per access); returns new value EWMA |
| `rfm_recency(id)` | `exp(−Δt/τ)`, τ = 86400; never-accessed falls back to creation age |
| `rfm_frequency(id)` | `ln(1 + access_count)` |
| `rfm_activation(id)` | ACT-R base-level activation (Petrov k = 2) |
| `rfm_value(id)` | raw outcome EWMA in [-1, 1] |
| `rfm_score(id)` | `w_a·P(activation) + w_v·value₀₁`, defaults 0.7 / 0.3 |
| `rfm_prior(id)` | `(1−β) + β·rfm_score(id)` — the bounded multiplier to compose with similarity (β config, default 0.3) |
| `rfm_score_w(id, w_a, w_v[, tau, decay])` | parameterised variant (τ reserved; see DESIGN_NOTES) |
| `rfm_config(key[, value])` | get/set per-connection defaults: `tau, decay, lambda, w_a, w_v, shrink_k, beta, now` |

`rfm_config('now', t)` freezes the clock for tests and replay;
`rfm_config('now', NULL)` unfreezes. All state changes are explicit — SQLite
cannot trigger on SELECT, so call `rfm_record_access` for the memories your
agent actually uses (per-id, not inside a scan of `rfm_memories`). Inputs are
strictly typed: ids must be INTEGER (no silent truncation of `1.9` to row 1),
and NULL or non-finite numeric arguments error instead of coercing to 0.

## Benchmarks

### Scoring throughput (O(1) claim)

`sum(rfm_score(id))` over every row vs. exact ACT-R recompute scanning
`rfm_accesses`. x86_64 build under Rosetta 2 on an Apple-silicon Mac
(SQLite 3.50.4); native builds are faster, the shape is what matters:

| rows | accesses/row | rfm_score | exact recompute | rfm_score µs/row | max \|B err\| |
|---|---|---|---|---|---|
| 10k | 20 | 0.048 s | 0.046 s | 4.8 | 0.35 |
| 100k | 20 | 0.455 s | 0.350 s | 4.6 | 0.40 |
| 1M | 20 | 4.59 s | 4.32 s | 4.6 | 0.41 |
| 100k | **200** | **0.462 s** | **4.09 s** | 4.6 | 0.25 |

Per-row cost is flat at ~4.6 µs whether a memory has 20 accesses or 200; the
exact recompute grows ~12× when history grows 10×. That is the `bla_cache`
design doing its job: scoring never touches the access log.
(Mean approximation error on the 100k db: 0.049 activation units.)

### Retrieval quality (LongMemEval)

Replay harness over [LongMemEval](https://github.com/xiaowu0162/LongMemEval)
(500 questions, ~53 timestamped sessions each; gold evidence annotations, so
recall needs no LLM judge — see `bench-quality/`). Sessions are ingested in
timestamp order; each new session simulates agent usage (retrieve top-5 prior
memories for its opening turn, record the accesses); the final question is
retrieved at `question_date` with the clock frozen to dataset time. Same
embedder (all-MiniLM-L6-v2) and store everywhere; only the ranking varies.

| condition | turn recall@10 | turn hit@10 | session recall@10 | NDCG@10 |
|---|---|---|---|---|
| similarity only | **0.728** | **0.818** | **0.908** | **0.522** |
| sim × exp-recency (Mem0-platform-style) | 0.558 | 0.720 | 0.709 | 0.397 |
| Generative Agents (Park et al. 2023) | 0.429 | 0.586 | 0.584 | 0.312 |
| **sim × rfm_score (ours)** | 0.708 | 0.800 | 0.896 | 0.506 |
| ablation: rfm with w_v = 0 | 0.379 | 0.504 | 0.599 | 0.189 |

Three honest findings:

1. **On this benchmark, every usage prior loses to pure similarity** — by
   construction: LongMemEval hides evidence anywhere in the haystack,
   uncorrelated with simulated usage, so any non-relevance signal can only
   subtract. The right question is *how much a prior costs when it can't
   help*: RFM costs **2 points** of turn recall; the common exponential
   recency multiplier costs 17; the Generative-Agents formula costs 30.
   The bounded form (`w_a·P + w_v·value₀₁` never reaches zero) is what makes
   RFM safe to leave on.
2. **The value floor is load-bearing, not decoration.** The w_v = 0 ablation
   collapses (0.379): unshrunk activation alone is an aggressive, wrong prior
   here. The neutral value term keeps the prior gentle until outcomes earn a
   stronger opinion.
3. **Outcome feedback works as designed.** No public benchmark ships outcome
   labels (that's the gap this extension targets), so the M axis is measured
   as a mechanism experiment: give gold outcomes for one retrieval round,
   re-rank the same question. NDCG rises 0.506 → 0.582, improving 249/479
   questions and hurting 4. When your agent *can* say "that memory helped,"
   one round of feedback is already visible in the ranking.

The harness is deterministic (dataset timestamps via `rfm_config('now', …)`,
no RNG): `bench-quality/replay.py --instances 500 --k 10 --feedback-demo`.

### The value axis, measured without leakage (LoCoMo · BEAM · knowledge-update)

The experiment above can't cleanly test M — LongMemEval has one labeled
question per haystack, so there's no feedback stream. Two sequential-feedback
evals fix that: questions are asked in sequence, retrieval for question *k*
earns evidence-hit outcomes (+1/−1), and every metric is computed **before**
that question's feedback lands — feedback and evaluation never touch the same
question. LoCoMo (~1.5k questions over 10 conversations, ~49% of questions
share evidence with an earlier one) and BEAM's 128K tier (20 conversations,
~18 questions each) both have message-level gold evidence, so no LLM judge.

Paired NDCG@10 deltas, mean [95% bootstrap CI]:

| comparison | LoCoMo (n=1531) | BEAM (n=355) |
|---|---|---|
| M on vs M off (isolates the value axis) | **+0.240** [+0.223, +0.256] | **+0.357** [+0.319, +0.394] |
| full rfm vs similarity-only — all questions | −0.053 [−0.067, −0.039] | −0.061 [−0.080, −0.042] |
| full rfm vs similarity-only — evidence recurred | −0.030 [−0.053, −0.007] | **−0.002** [−0.041, +0.034] |

Three cross-benchmark findings:

1. **Under sequential query load, the activation prior alone collapses**
   (M-off NDCG ≈ 0.01 on both benchmarks): every retrieval feeds activation
   back into the ranking, and early winners snowball. The value axis is what
   breaks the loop — negative outcomes on retrieved-but-useless memories undo
   the rich-get-richer effect. On LongMemEval the neutral value term was a
   passive floor; here it earns its weight actively.
2. **Feedback closes the gap exactly where theory says it can.** Against pure
   similarity, rfm's deficit shrinks from −0.09 to ~0 (BEAM) and from −0.07
   to −0.03 (LoCoMo) on questions whose evidence had already served an
   earlier question. Where usage history predicts future queries, the prior
   pays for itself; where it can't, it costs a few points.
3. **Forgetting works** (`ku_eval.py`, LongMemEval's 78 knowledge-update
   instances, oracle contradiction signal): a single −1 outcome on the
   superseded fact at ingestion time lifts update-preference from 0.43 to
   **0.66** (paired +0.229 [+0.129, +0.343]) and halves stale-fact retrievals
   (0.79 → 0.50) with **no loss** of fresh-fact recall (0.80 both ways) — the
   value axis removes the outdated memory without collateral damage.

### Embedder robustness and the bounded composition (pre-registered)

Re-running the sequential evals with a strong retriever
(Qwen3-Embedding-0.6B) exposed a real flaw in the original composition:
`sim × rfm_score`'s cost vs similarity-only inflated from −0.05/−0.06
(MiniLM) to **−0.32/−0.15** (LoCoMo/BEAM) — the activation prior's ~6×
multiplicative range overwhelms well-calibrated similarities — while the
value axis's isolated contribution stayed stable (+0.17…+0.35). The fix was
chosen by a **pre-registered protocol** (`PROTOCOL.md`: candidates, dev/test
split, selection rule, and falsification criteria committed to git before
any experiment ran; dev = BEAM only): rank-fusion and shortlist-rerank
failed feasibility by ~40×; the bounded blend passed, frozen at **β = 0.3**
— now shipped as `rfm_prior()`. One-shot test results (never touched during
development):

| endpoint | result |
|---|---|
| LoCoMo cost vs sim ≤ 0.010 (MiniLM / Qwen3) | **pass**: −0.001 / +0.004 |
| LoCoMo adaptivity (feedback ON−OFF, recurred qs) | **pass**: +0.023 / +0.032, CIs > 0 |
| SWE-Bench-CL cost vs sim n.s. | **pass**: −0.013 / −0.001 (frozen slightly *ahead*) |
| knowledge-update forgetting delta | **weak**: +0.014 [+0.000, +0.043] — bounding the prior sacrifices most of the forgetting power (was +0.229 unbounded); raise β when forgetting matters more than rank safety |

The trade-off is the finding: β is a dial between protecting relevance and
empowering feedback. On coding experience-selection (SWE-Bench-CL, 88 tasks,
heuristic file-overlap gold links — disclosed), the frozen composition is
the first configuration to edge ahead of similarity-only.

Protocols, dataset licenses (LoCoMo is CC BY-NC), and disclosed caveats (BEAM
evidence is model-generated + human-reviewed) are in `bench-quality/README.md`.

## Comparison to Mem0 / Generative-Agents scoring

**Mem0 (OSS)** ranks by relevance signals only — vector similarity, plus BM25
keyword and entity boosts in recent versions; no recency, frequency, or
outcome term appears in its OSS ranking path. sqlite-rfm is complementary:
`similarity × rfm_score(id)` adds the usage-history prior Mem0 doesn't model.
**Generative Agents** (Park et al. 2023) is the closest published scorer —
`recency + importance + relevance`, min-max normalized, equal weights, with
recency = `0.995^hours` since last retrieval. Its recency term is exponential
(one access matters), its importance is a static LLM rating at write time,
and it has no outcome feedback. RFM activation upgrades recency+frequency to
a power-law over the *whole* access history, and replaces write-time
importance with earned, updatable value. The demo (`examples/agent_demo.py`)
shows the resulting dynamic: memories that keep helping climb; early-buzz
memories decay to mid-ranking.

**Environment overrides** (honored by the tests, `bench/`, `bench-quality/`,
and `examples/`): `RFM_DYLIB` points at the extension artifact to load;
`SQLITE3_BIN` points at a `.load`-capable sqlite3 CLI. Without them, each
harness probes the standard build paths and Homebrew prefixes.

## Repository

```
src/                lib.rs, functions.rs, math.rs (pure), sql.rs, config.rs, clock.rs
rfm_schema.sql      standalone schema
tests/              CLI integration test (cargo test)
bench/              throughput benchmark (gen.py + bench.sh)
bench-quality/      LongMemEval retrieval-quality harness (replay.py)
examples/           agent_demo.py — 50 memories, 200 accesses, before/after top-5
DESIGN_NOTES.md     deviations, tradeoffs, known limitations
```

Equations in code cite their sources (ACT-R base-level learning; Petrov 2006;
standard EWMA). Tests: `cargo test` runs pure-math unit tests (approximation
vs. exact log-sum on synthetic histories) plus the end-to-end CLI test.
