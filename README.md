# mem-rfm — agent memory that ranks itself by outcomes

**A SQLite extension, an MCP server for Claude Code, and ~25 experiments on
when agent memory actually helps — including the failures.**

> **TL;DR.** The deployable recipe is small: compose similarity search with a
> **bounded usage prior** — `max(sim,0) × ((1−β) + β·rfm_score(id))`, β=0.3,
> frozen by a pre-registered experiment after the unbounded version was
> falsified (−0.32 NDCG under a strong embedder) — and close the loop with
> **outcome feedback** (`rfm_record_outcome`: did the memory help?). What
> the experiments say: memory pays where **work recurs** — feedback adds
> +0.02–0.08 NDCG where queries revisit earlier ground (CIs exclude zero,
> three embedders), operational knowledge (build quirks, env pins,
> conventions) earns sustained positive value in live use, and outcome
> feedback retires stale entries similarity keeps recommending forever —
> and memory does NOT pay where work is episodic: on scattered real-bug
> fixing our own system honestly measured a **~6% lesson-transfer rate**
> (15 of 16 outcomes negative) and no resolution benefit. The outcome
> axis's proven jobs are safety and maintenance more than raw ranking: its
> cost is bounded everywhere we measured, it is the stabilizer that keeps
> any usage prior from collapsing retrieval, and its rank-1 gains are real
> but narrow (confirmed on two datasets, failed a pre-registered
> replication bar on two others — published below). A four-dataset
> team-pooling campaign is included as **measurements, not a product**
> (§ team-pooled stores). Biggest caveats: outcome signals in the
> sequential evals are oracle evidence-hits, and the live coding A/B is
> n=27 with one executor model. One published number was corrected in
> pre-publication review (see RESULTS.md "Corrections").

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

An August 2026 survey of 22 memory systems found the loop from *memory
access → task outcome → ranking weight* shipping in exactly one other OSS
system — [Cognee](https://docs.cognee.ai/guides/feedback-system)'s feedback
weights, off by default and rating answers rather than task outcomes — plus
two partial takes ([ReMe](https://github.com/agentscope-ai/ReMe) uses outcome
utility only to prune; a [MemOS plugin](https://github.com/MemTensor/MemOS)
credits the episode's new traces, not the memories retrieved). As far as we
can determine, this remains the only system where outcome feedback is a
**default-on term in the retrieval score**, attributed to **the retrieved
memory itself**, with **signed negative outcomes** as a ranking force — and
the only one shipped as an embeddable primitive rather than a service.
Concurrent 2026 research is converging on the same loop
([RoMeRL](https://arxiv.org/abs/2608.02508),
[Chen & Cheng](https://arxiv.org/abs/2606.12945)); a Jul 2026
mechanism-level review ([arXiv:2607.23942](https://arxiv.org/abs/2607.23942))
still lists activation-plus-utility as unmigrated from cognitive
architectures to language agents. And this is, as far as we know, the only
memory system whose every claim — including the negative ones below — is
pre-registered, reproducible, and committed to git in auditable order.

---

## What we found: where memory helps agents, and where it doesn't

Everything below was measured, not asserted: three public retrieval
benchmarks (LoCoMo, LongMemEval, BEAM), a coding experience-selection
benchmark (SWE-Bench-CL), a pre-registered composition experiment across
three embedding models, **70 live Claude Code sessions fixing real pytest
and sphinx bugs in a paired A/B** (control vs memory arm, separate clones,
gold-test scoring), and a pre-registered four-dataset dialog campaign.
Per-question results and run logs are committed; live-session transcripts
and memory databases stay local (they can contain machine-specific
detail), with a redacted audit committed at
`experiments/swe-ab/memory-audit.md`.

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
- **Staleness is where outcomes earn their keep** (ABCD support corpus,
  exploratory). After a simulated policy revision, similarity-only kept
  recommending dead procedures 1,500 calls later (hit@1 0.20 vs 0.76
  pre-change) — stale entries stay semantically similar forever. With an
  outcome signal driving demotion, the recovery curve beats similarity's in
  every bin: final-bin hit@1 **0.56 vs 0.20**. Production design: explicit
  invalidation for announced changes, outcome-driven forgetting as the
  safety net for unannounced ones.

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
  23/27 — both discordant pairs going to control, consistent with noise
  (McNemar p = 0.5) as much as with a difficulty effect. Overhead:
  ~8–22s/session, dominated by embedding-model startup — trivia in a
  30-minute interactive session, material in 90-second headless ones.
- **A usage prior does not beat a good retriever at one-shot relevance.**
  Against pure similarity search with a strong embedder, the *unbounded*
  prior was falsified outright (−0.32 NDCG; pre-registered robustness
  check), and the frozen bounded form reaches parity, not superiority. If
  your workload is "answer one question about a haystack," use similarity
  and skip the prior.
- **Rank-1 gains from outcome-ranking are real but narrow — and we
  published the miss.** The outcome-ranked store beat plain similarity at
  rank-1 on ABCD (+1.2 → +2.0 as feedback accumulated) and STAR (+1.25;
  +1.27 under Qwen3, embedder-robust). The pre-registered replication bar
  required CI > 0 on two of three datasets; it hit only one
  (MultiDoc2Dial +0.24 [−0.39,+0.90]; FloDial +0.16 [−0.05,+0.43]) — the
  failure is recorded in RESULTS.md. The bounded-cost guarantee held on
  every dataset and embedder: outcome-ranking never cost more than −0.4
  points hit@5 (n.s.). Treat rank-1 lift as a possible bonus, not the
  reason to deploy the value axis.

**The one-sentence takeaway:** memory for agents is not a lesson journal —
it's an *operational profile* that earns rank through outcomes. Capture
environment quirks, conventions, decisions, and preferences; let per-task
trivia fade; and bound how much any of it can override relevance.

### Team-pooled stores: measurements, not a product

If recurrence is what memory needs, pooling experience across agents
multiplies effective recurrence. We measured this on
[ABCD](https://github.com/asappresearch/abcd) (exploratory), then
pre-registered a replication (PROTOCOL.md Amendment 4) on three datasets
with genuinely authored manuals:

| dataset (domain) | agents | labels | team − solo, hit@5 | pre-reg |
|---|---|---|---|---|
| ABCD (customer support) | 8 (imposed) | 55 procedures | **+14.5** [+13.0,+16.1] | exploratory |
| STAR (task-oriented dialog) | **115 real wizards**, real time-order | 24 flowcharts | **+26.1** [+24.7,+27.5] | **pass** |
| MultiDoc2Dial (gov-policy QA) | 8 (imposed) | 451 documents | **+37.5** [+35.9,+39.1] | **pass** |
| FloDial (troubleshooting) | 8 (imposed) | 10 flowcharts | **+4.0** [+3.2,+5.0] | **pass** |

Accumulated experience also out-ranks each dataset's authored manual at
hit@1 (**+12.0 / +21.1 / +6.4 / +1.7**, CIs > 0 — MultiDoc2Dial against
our own registered prediction, disclosed in RESULTS.md), while the manual
owns the cold start (layering it in is worth **+42.6 points** over
MultiDoc2Dial's first 500 calls); the layered store — manual + experience
+ outcomes — was the best condition everywhere it ran. A stronger embedder
narrows the experience-vs-manual gap (STAR: +21.1 → +6.0 under Qwen3) but
does not close it.

> **These are measurements, not a product.** A production shared memory
> store owes its users access control, tenancy isolation, a poisoning
> threat model, and deletion guarantees — none of which this repo provides
> or currently intends to. The numbers say pooling is worth engineering
> for; the engineering is future work. If you experiment anyway: pool
> delexicalized procedure patterns, never transcripts; keep
> customer-specific context in per-customer scoped stores; one DB per
> scope, so erasure is deleting a file.

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
(cannot be simultaneously retrieval-safe and forgetting-potent), the
rank-1 replication bar above (1 of 3), and three content-based value
signals (semantic richness, diversity, demand-recurrence — all weak or
benchmark-dependent as priors; provenance/is-user was the only content
prior that beat similarity anywhere).

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
| `rfm_record_access(id[, actor])` | logs an access; returns new activation. optional `actor` (host principal) enables hardened mode |
| `rfm_record_outcome(id, o[, actor])` | feedback `o ∈ [-1,1]` for the latest access (once per access); returns value EWMA |
| `rfm_prior(id)` | `(1−β) + β·rfm_score(id)` — the bounded multiplier for composing with similarity |
| `rfm_score(id)` | `w_a·P(activation) + w_v·value₀₁` |
| `rfm_activation(id)` / `rfm_recency(id)` / `rfm_frequency(id)` / `rfm_value(id)` | individual components |
| `rfm_score_w(id, w_a, w_v[, tau, decay])` | parameterised variant |
| `rfm_config(key[, value])` | per-connection: `tau, decay, lambda, w_a, w_v, shrink_k, beta, exclude_self, now` |

**Hardened mode (shared stores).** Tag memories with a writer via the
`created_by` column and pass the accessing principal as `actor`; then
`rfm_config('exclude_self', 1)` makes the extension ignore any
access/outcome whose actor equals the memory's writer — closing the
self-endorsement channel by which a compromised writer inflates its own
memories' R, F, or M. Off by default (exact back-compat).
`rfm_config('one_vote', 1)` additionally caps outcomes at one per (actor,
memory); it is **not recommended** — see below.

### What a bad team member can and cannot do

Measured, not asserted (PROTOCOL.md Amendments 5–7; STAR + ABCD, attacker
injecting at 20% of call volume):

| attack | unhardened outcome ranking | defense |
|---|---|---|
| **Write convincing junk** (bait copied from real queries) | damaged but self-correcting: absorbs ~⅔–¾ of the hit@1 damage, holds exposure flat where similarity's *grows*, same fake served 6× instead of 29× | inherent — the demotion loop |
| **Self-promote** (self-access to pump R/F, self-rate to pump M) | **worse than no prior at all** (−1.5 pts vs similarity; −9.8 at heavy pumping) | `exclude_self` — full recovery, +2.1 pts *above* similarity, ≈free on a team |
| **Censor** (bury a rival procedure with negative votes) | **fails outright** — β-bounding floors demotion at 0.7×, smaller than the similarity gap it would need to close; censored labels scored +2.1 pts *better* than similarity | none needed |
| **Collude** (4 members cross-endorsing each other's junk) | **−5.0 pts**; six defenses tried, best recovers 16% | **detect, don't rank** — see below |

**Recommended for a shared store: `exclude_self` + `trust`.** Best measured
configuration against single bad actors — 0.941 hit@1 at 0.006 poison
occupancy, a quarter of plain similarity's exposure, free on a clean store.

**Rejected on evidence, and shipped off by default so you can check the
claim.** `one_vote` (ballot-stuffing prevention) throttles the *corrective*
signal as hard as the abusive one — a team can then land at most one
negative per member on a bad memory, instead of one per wasted retrieval —
so it defends nothing measurable and costs −0.34 pts on a clean store.
Symmetric caps ration the immune response along with the attack; asymmetric
defenses (which remove an *illegitimate* signal) do not.

**Collusion: you cannot out-rank a ring, but you can spot one.** Six
mechanisms were measured against four cross-endorsing writers —
`exclude_self`, `one_vote`, both together, writer trust, voter-weighted
trust, and endorser liability. Only liability recovers anything with a CI
above zero (+0.8 of the 5.0 points lost, and it collapses ring reputation
to −0.734 against honest agents' +0.950), and none restores the baseline.
They fail for one reason: **the ring controls votes at every level of
aggregation**, so re-aggregating votes cannot escape it. Detection is the
part that works — endorsement concentration identified all four colluders
on both datasets, from the log alone. Run
[`integrations/audit.sql`](integrations/audit.sql) against your store: it
reports writer reputation, endorsement concentration, and mutual-endorsement
pairs, and documents the governance actions (quarantine, freeze, revoke,
scope erasure) as explicit SQL. Those are deliberately manual — an automated
response to a detector is itself an attack surface, since a false positive
silently deletes an honest colleague's work.

Scope: `exclude_self` costs −0.80 pts on a *single-agent* store (where
every memory is self-authored, so all feedback is discarded) and nothing
measurable from ~2 writers up; actor strings are host-asserted, so this
defends against a principal misbehaving within its rights, not against
impersonation.

To turn any of this on in the Claude Code server, set `RFM_ACTOR` to this
agent's principal id (which tags writes and votes) and `RFM_HARDEN`, e.g.
`RFM_HARDEN=exclude_self,trust`. Both default to unset — correct for a
single-user store, where the flags would be inert at best and costly at
worst.

`rfm_config('now', t)` freezes the clock (tests/replay). Inputs are strictly
typed: ids must be INTEGER, NULL/non-finite numerics error rather than
coerce. One outcome per access, enforced — the log always reproduces the
summary.

## Methodology, or: why you can trust the negative results

- Composition, feature, and replication experiments were **pre-registered**
  (`PROTOCOL.md` + Amendments 1–4 committed before their runs), with
  dev/test splits by benchmark, repo, and embedder, one-shot evaluation,
  and full sweep curves published. The replication campaign's smoke runs
  (n ≤ 400) are disclosed inside Amendment 4 itself.
- **Per-question outputs are committed**
  (`bench-quality/results-*/`, incl. `results-{star,md2d,flodial}/`) so any
  table cell is auditable; run logs likewise.
- **Failures are reported at the same volume as successes** — see
  `bench-quality/RESULTS.md` for the complete ledger including everything
  that died (most recently the rank-1 replication bar, 1 of 3).
- Benchmarks used: [LoCoMo](https://github.com/snap-research/locomo)
  (CC BY-NC), [LongMemEval](https://github.com/xiaowu0162/LongMemEval),
  [BEAM](https://github.com/mohammadtavakoli78/BEAM),
  [SWE-Bench-CL](https://github.com/thomasjoshi/agents-never-forget)
  (heuristic gold links — disclosed),
  [ABCD](https://github.com/asappresearch/abcd) (MIT),
  [STAR](https://github.com/RasaHQ/STAR) (MIT),
  [MultiDoc2Dial](https://doc2dial.github.io/multidoc2dial/) (CC BY 3.0),
  and [FloDial](https://dair-iitd.github.io/FloDial/) (CDLA-Sharing-1.0).
  All evals run without LLM judges or API keys — retrieval hits are judged
  by each dataset's own procedure/document annotations (oracle outcomes,
  disclosed). Known limits: SWE-Bench-CL's file-overlap labels are noisy;
  the live A/B is n=27 with one executor model; MultiDoc2Dial and FloDial
  lack natural agent IDs and ordering (round-robin + seeded shuffle,
  disclosed); retrieval metrics are proxies for task success except in the
  live A/B, where gold tests scored outcomes directly.

## Repository

```
src/                     the extension (lib, functions, math, sql shim, config, clock)
rfm_schema.sql           standalone schema
tests/                   unit + CLI integration tests (cargo test)
bench/                   O(1) throughput benchmark
bench-quality/           all retrieval benchmarks + RESULTS.md ledger
experiments/swe-ab/      the live paired A/B on real bugs (runner + results)
integrations/claude-code/ MCP server, hooks, capture snippet, A/B kit
integrations/audit.sql   shared-store forensics + governance recipes
PROTOCOL.md              pre-registrations and amendments (1–4)
DESIGN_NOTES.md          design decisions, trade-offs, limitations
```

## License

Dual-licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at
your option. Datasets are downloaded, never redistributed — provenance and
terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (note LoCoMo is
CC BY-NC).
