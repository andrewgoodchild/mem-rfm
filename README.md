# mem-rfm — agent memory that ranks itself by outcomes

**A SQLite extension, an MCP server for Claude Code, and ~20 experiments on
when agent memory actually helps — including the failures.**

> **TL;DR.** The deployable recipe is small: compose similarity search with a
> **bounded usage prior** — `max(sim,0) × ((1−β) + β·rfm_score(id))`, β=0.3,
> frozen by a pre-registered experiment after the unbounded version was
> falsified (−0.32 NDCG under a strong embedder) — and close the loop with
> **outcome feedback** (`rfm_record_outcome`: did the memory help?). What the
> experiments say: memory pays where **work recurs** — team-pooled support
> memory gained **+14.5 points** over per-agent stores, outcome-ranking beat
> similarity at rank-1 (+1.2→+2.0, growing with use), and feedback retired
> stale procedures markedly faster after a policy change (final-bin hit@1
> 0.56 vs 0.20) — and does NOT pay where work is episodic: on scattered
> real-bug fixing our own system honestly measured a **~6% lesson-transfer
> rate** (15 of 16 outcomes negative) and no resolution benefit. An authored
> knowledge base is a strong but STATIC baseline: accumulated experience
> beats the actual agent manual by **+12 points hit@1** (0.71 vs 0.59, the
> manual's curve flat while experience learns), and the layered system —
> manual + experience + outcomes — wins outright. Biggest caveats: the
> support results are exploratory (not yet pre-registered replications),
> outcome signals there are oracle evidence-hits, and the live coding A/B is
> n=27 with one executor model. One published number was corrected in
> pre-publication review (see RESULTS.md “Corrections”).

Memories are scored by **R**ecency and **F**requency (unified as ACT-R
base-level activation, O(1) per score) plus a **M**onetary-analog value axis:
an EWMA of outcome feedback — *did this memory actually help when it was
retrieved?* Search records usage; feedback records value; useful memories
rise and useless ones fade, all inside one SQLite file, no API keys, no LLM
calls in the scoring path.

```sql
SELECT id, content,
       max(1.0 - vec_distance_cosine(embedding, :query), 0) * rfm_prior(id) AS score
FROM rfm_memories ORDER BY score DESC LIMIT 5;

SELECT rfm_record_access(42);        -- retrieved it
SELECT rfm_record_outcome(42, 1.0);  -- ...and it helped
```

As far as we can determine, this is the only agent-memory system that closes
the loop from *memory access → task outcome → ranking weight* (a 2026 survey
of 13 coding-memory tools and 9 frameworks found zero others), and the only
one whose every claim — including the negative ones below — is
pre-registered, reproducible, and committed to git in auditable order.

---

## What we found: where memory helps coding agents, and where it doesn't

Everything below was measured, not asserted: three public retrieval
benchmarks (LoCoMo, LongMemEval, BEAM), a coding experience-selection
benchmark (SWE-Bench-CL), a pre-registered composition experiment across
three embedding models, and **70 live Claude Code sessions fixing real
pytest and sphinx bugs in a paired A/B** (control vs memory arm, separate
clones, gold-test scoring). Per-question results and run logs are committed;
live-session transcripts and memory databases stay local (they can contain
machine-specific detail), with a redacted audit of the memory stores
committed at `experiments/swe-ab/memory-audit.md` so the coding-A/B memory
numbers below are checkable.

### Memory helps when work RECURS

- **Feedback measurably improves retrieval where queries revisit earlier
  ground.** On sequential benchmarks, the value axis adds +0.02–0.08 NDCG on
  questions whose evidence had served earlier questions (CIs exclude zero,
  three embedders, replicated on chat and code corpora). Where evidence never
  recurs, memory can't help — and bounded correctly, it doesn't hurt.
- **Operational and environment knowledge transfers.** In the live A/B, the
  single memory that earned sustained positive value (+0.58 over 5 uses) was
  an environment gotcha — which pinned dependencies the sphinx checkout
  needs — not code knowledge. Facts about *how to work here* (build quirks,
  env pins, project conventions, user preferences) recur by nature.
- **Forgetting works.** With the value signal driving it, superseded facts
  get demoted: update-preference on LongMemEval's knowledge-update tasks
  rose 0.43 → 0.66 with no loss of fresh-fact recall (oracle-signal setting;
  the effect trades against rank-safety via the β dial — see below).
- **The stabilizer role is load-bearing.** Under sequential query load, a
  recency/frequency prior *alone* collapses retrieval (rich-get-richer,
  NDCG ≈ 0.01 in ablations). Negative outcome feedback is what breaks that
  loop. If you run any usage-based ranking, you need the value axis or
  something like it.

### Memory does NOT help when work is EPISODIC

- **Per-bug code lessons mostly don't transfer.** In the live A/B the agent
  saved 17 genuinely good pytest lessons — and then, bug after bug, honestly
  judged retrieved ones irrelevant: **15 of 16 recorded outcomes were
  negative**, because SWE-bench-style tasks deliberately scatter across
  unrelated subsystems. The demotion loop measured its own workload's
  transfer rate (~6%) with no oracle. That is the system working; the
  workload just has little to remember.
- **On hard tasks under a turn budget, memory is directionally a tax.**
  Resolution across 27 paired real-bug tasks: control 25/27, memory arm
  23/27 — both discordant pairs going to control. Stated precisely: those
  two are 2 of the 5 tasks rated above one hour (the other three hard tasks
  were solved by both arms), so this is consistent with noise (McNemar
  p = 0.5) as much as with a difficulty effect — though the mechanism is
  plausible: retrieval calls and irrelevant lessons
  consume budget that hard tasks need. Overhead: ~8–22s/session, dominated
  by embedding-model startup — trivia in a 30-minute interactive session,
  material in 90-second headless ones.
- **A usage prior does not beat a good retriever at one-shot relevance.**
  Against pure similarity search with a strong embedder, the *unbounded*
  prior was falsified outright (−0.32 NDCG; pre-registered robustness check),
  and the frozen bounded form reaches parity, not superiority. If your
  workload is "answer one question about a haystack," use similarity and
  skip the prior.

**The one-sentence takeaway:** memory for coding agents is not a lesson
journal — it's an *operational profile* that earns rank through outcomes.
Capture environment quirks, conventions, decisions, and preferences; let
per-task trivia fade; and bound how much any of it can override relevance.

### The favorable case, quantified: team memory for support work

If recurrence is what memory needs, maximum-recurrence workloads should show
maximum value — so we tested customer support on
[ABCD](https://github.com/asappresearch/abcd) (10k real support
conversations, 55 annotated procedures, MIT): 3,000-call streams, 8
simulated agents, no LLM anywhere (the dataset's own procedure annotations
judge whether memory surfaced the right playbook). Four results, all
exploratory (not pre-registered), all with per-condition curves committed:

1. **Team pooling is the headline: +14.5 points hit@5** [+13.0, +16.1] for
   one shared store vs per-agent solo stores. The shared store starts its
   first quintile at the hit-rate solo agents need most of the stream to
   reach — pooling multiplies effective recurrence by roughly team size.
2. **Outcome-ranking beat plain similarity in a live-shaped workload for
   the first time** — at rank-1, the position that matters when handing an
   agent one suggestion: +1.2 points overall, **+2.0 in the last thousand
   calls** [+0.7, +3.4], growing as feedback accumulates. At rank-5 the
   bounded-cost guarantee held yet again (−0.4 points, n.s.). Replicated in
   the combined-store variant (+1.1, CI > 0).
3. **Staleness is real, and outcomes are the only layer that fixes it.**
   After a simulated policy revision, similarity-only kept recommending
   dead procedures 1,500 calls later (hit@1 0.20 vs 0.76 pre-change) —
   stale entries stay semantically similar forever. With outcome feedback
   (the ticket-reopen signal) the recovery curve is above similarity's in
   every bin and the gap compounds: final-bin hit@1 **0.56 vs 0.20**
   (point-estimate ratio ~2.8× there, ~1.8–1.9× in earlier bins; per-bin
   n≈60–80, no CI — treat as a curve, not a rate constant). Production
   design: explicit invalidation for announced changes, outcome-driven
   forgetting as the safety net for unannounced ones.
4. **The authored knowledge base is a strong but static baseline — not a
   substitute for experience.** RAG over the actual ABCD agent manual (all
   55 entries) scores 0.59 hit@1 / 0.84 hit@5 — respectable, but *flat*:
   its curve never moves, while experience climbs to 0.75+ and beats it by
   **+12.0 points hit@1** [+10.0, +13.9]. The manual's distinctive value is
   the cold start: manual+experience beats experience-alone by **+7.0
   points hit@5 over the first 500 calls** [+4.8, +9.4], converging later.
   Outcome-ranking adds its rank-1 edge on top (+1.3 [+0.6, +2.1]), making
   manual+experience+outcomes the best condition overall (0.730 hit@1).
   *Correction disclosure:* the first published version of this experiment
   claimed a +42-point gap off a title-mapping bug that silently dropped 22
   of 55 manual entries (52.7% of calls uncovered). Pre-publication review
   caught it from the committed logs; the experiment was re-run with full
   coverage and un-aged manual timestamps. Details in RESULTS.md.

Layered conclusion for any support/ops deployment: **manual for day one,
shared experience for diagnosis, outcomes for maintenance** — and the
outcome layer is the part that is not "just RAG," and that no other memory
system ships. (Privacy note for shared stores: the team store should hold
delexicalized procedure patterns, never transcripts; customer-specific
context belongs in per-customer scoped stores where its recurrence lives —
one DB per scope, and erasure is deleting a file.)

---

## The composition that survived falsification

The naive composition `similarity × rfm_score` fails: activation's dynamic
range (~6×) overwhelms well-calibrated similarities, and the damage *grows*
with retriever quality (−0.05 NDCG under MiniLM → −0.32 under
Qwen3-Embedding). The shipped form is the **bounded prior**:

```
rfm_prior(id) = (1 − β) + β · rfm_score(id)        β = 0.3 (rfm_config('beta', …))
final = max(similarity, 0) × rfm_prior(id)
```

β was frozen by a pre-registered protocol (`PROTOCOL.md`: candidates,
dev/test split, selection rule, and falsification criteria committed before
any experiment ran; dev = BEAM only; rank-fusion and shortlist-rerank
alternatives failed feasibility by ~40×). One-shot test results with frozen
β=0.3:

| endpoint | result |
|---|---|
| Cost vs similarity ≤ 0.010 NDCG (LoCoMo, MiniLM / Qwen3) | **pass**: −0.001 / +0.004 |
| Feedback adaptivity CIs > 0 | **pass**: +0.023 / +0.032 (larger on test than dev) |
| SWE-Bench-CL cost n.s. | **pass**: −0.013 / −0.001 (slightly *ahead*) |
| Unseen embedder (bge-m3, never used in tuning) | **pass**: cost −0.005; largest adaptivity of any embedder (+0.078) |
| Knowledge-update forgetting | **weak**: +0.014 (was +0.229 unbounded — β trades forgetting power for rank safety; raise β when forgetting matters more) |

Also killed by their own pre-registered bars, and documented rather than
buried: BM25 hybrid fusion (a dev-set win on 2 repos reversed on 6 held-out
repos — the repo split caught the overfit), confident-negative pruning
(cannot be simultaneously retrieval-safe and forgetting-potent), and three
content-based value signals (semantic richness, diversity, demand-recurrence
— all weak or benchmark-dependent as priors; provenance/is-user was the only
content prior that beat similarity anywhere).

## The theory, in three equations

ACT-R base-level activation unifies recency and frequency over the access
history — `B = ln(Σ tᵢ^−d)` — and the Petrov (2006) hybrid approximation
makes it O(1): the two most recent access times are kept exactly (they live
in columns the schema already has; `bla_cache` stores the second-most-recent)
plus a closed-form tail. Scoring reads **one row**, never the access log
(measured: ~4.6µs/row flat whether a memory has 20 or 200 accesses; mean
approximation error 0.049 activation units). Value is an outcome EWMA in
[−1,1] — `v ← 0.3·outcome + 0.7·v`, first outcome initializes — with a
confidence shrink `v·n/(n+3)` so one lucky +1 doesn't outshout the prior.
`rfm_score = 0.7·P(B) + 0.3·v₀₁` with `P` the ACT-R retrieval-probability
squash. Every equation in the code cites its source.

## Install

Rust extension (needs a `.load`-capable SQLite ≥ 3.35 — Apple's CLI has
loading compiled out; use Homebrew's):

```sh
cargo build --release
sqlite3
.load ./target/release/librfm
SELECT rfm_init();
```

Claude Code memory server (local embeddings, one SQLite file):

```sh
cd integrations/claude-code && uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python mcp sqlite-vec sentence-transformers numpy
claude mcp add -s user rfm-memory -- "$(pwd)/.venv/bin/python" "$(pwd)/server.py"
```

Tools: `memory_save/search/feedback/list/delete/export/status` — search
records accesses automatically, feedback trains the ranking, list/export
give full inspectability. `capture.md` has the CLAUDE.md snippet for
agent-decided capture (per the findings above: bias it toward operational
facts). An optional SessionStart hook injects the top memories by pure
`rfm_score` — the prior ranking with no query at all — capped at 1,500
chars. `integrations/claude-code/ab/` is a ready-made A/B kit for measuring
the incremental value on your own work (arm-randomized launcher, transcript-
joining stats with bootstrap CIs).

## API

| function | returns |
|---|---|
| `rfm_init()` | creates tables + index (idempotent) |
| `rfm_record_access(id)` | logs an access; returns new activation |
| `rfm_record_outcome(id, o)` | feedback `o ∈ [-1,1]` for the latest access (once per access); returns value EWMA |
| `rfm_prior(id)` | `(1−β) + β·rfm_score(id)` — the bounded multiplier for composing with similarity |
| `rfm_score(id)` | `w_a·P(activation) + w_v·value₀₁` |
| `rfm_activation(id)` / `rfm_recency(id)` / `rfm_frequency(id)` / `rfm_value(id)` | individual components |
| `rfm_score_w(id, w_a, w_v[, tau, decay])` | parameterised variant |
| `rfm_config(key[, value])` | per-connection: `tau, decay, lambda, w_a, w_v, shrink_k, beta, now` |

`rfm_config('now', t)` freezes the clock (tests/replay). Inputs are strictly
typed: ids must be INTEGER, NULL/non-finite numerics error rather than
coerce. One outcome per access, enforced — the log always reproduces the
summary.

## Methodology, or: why you can trust the negative results

- Composition and feature experiments were **pre-registered** (`PROTOCOL.md`
  + amendments committed before their runs), with dev/test splits by
  benchmark, repo, and embedder, one-shot test evaluation, and full sweep
  curves published.
- **Per-question outputs are committed** (`bench-quality/results-*/`) so any
  table cell is auditable; run logs likewise.
- **Failures are reported at the same volume as successes** — see
  `bench-quality/RESULTS.md` for the complete ledger including everything
  that died.
- Benchmarks used: [LoCoMo](https://github.com/snap-research/locomo)
  (CC BY-NC), [LongMemEval](https://github.com/xiaowu0162/LongMemEval),
  [BEAM](https://github.com/mohammadtavakoli78/BEAM), and
  [SWE-Bench-CL](https://github.com/thomasjoshi/agents-never-forget)
  (heuristic gold links — disclosed). All evals run without LLM judges or
  API keys. Known limits: SWE-Bench-CL's file-overlap labels are noisy; the
  live A/B is n=27 with one executor model; retrieval metrics are proxies
  for task success except in the live A/B, where gold tests scored outcomes
  directly.

## Repository

```
src/                     the extension (lib, functions, math, sql shim, config, clock)
rfm_schema.sql           standalone schema
tests/                   unit + CLI integration tests (cargo test)
bench/                   O(1) throughput benchmark
bench-quality/           all retrieval benchmarks + RESULTS.md ledger
experiments/swe-ab/      the live paired A/B on real bugs (runner + results)
integrations/claude-code/ MCP server, hooks, capture snippet, A/B kit
PROTOCOL.md              pre-registrations and amendments
DESIGN_NOTES.md          design decisions, trade-offs, limitations
```

## License

Dual-licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at
your option. Datasets are downloaded, never redistributed — provenance and
terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (note LoCoMo is
CC BY-NC).
