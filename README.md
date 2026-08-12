# mem-rfm

**Agent memory that learns which memories are actually worth keeping.**

A SQLite extension (plus an MCP server for Claude Code) that ranks stored
memories by whether they *helped* — not just whether they look relevant.
Bundled with ~30 pre-registered experiments on when agent memory pays off,
when it doesn't, and what happens when someone abuses it.

---

## The problem

Agent memory systems retrieve by similarity: you ask a question, they return
the memories whose embeddings sit closest to it. That works, but nothing in
the loop ever notices the outcome. A memory that was retrieved ten times and
wasted the agent's time on all ten still looks exactly as relevant on the
eleventh.

Two consequences follow. **Bad memories never leave** — a plausible-sounding
but wrong note keeps surfacing forever. And **stale memories never leave
either** — when a procedure changes, the old version is still semantically
perfect for the query that matches it.

## What this does

It closes the loop. After a memory is retrieved, you tell the store whether
it helped. That verdict becomes part of the ranking, so memories that keep
paying off rise and memories that keep disappointing fade.

```sql
-- Rank by similarity, adjusted by how well each memory has performed.
SELECT id, content,
       max(1.0 - vec_distance_cosine(embedding, :query), 0) * rfm_prior(id) AS score
FROM rfm_memories ORDER BY score DESC LIMIT 5;

SELECT rfm_record_access(42);        -- we retrieved memory 42
SELECT rfm_record_outcome(42, 1.0);  -- ...and it helped (-1.0 if it didn't)
```

That's the whole interface. Scoring is a single indexed row read, there are
no API keys, no network calls, and no LLM anywhere in the ranking path — it
is arithmetic over columns your database already has.

The name is the three signals it combines: **R**ecency and **F**requency
(how recently and how often a memory has been used) and a **M**onetary-analog
value axis (how well it has performed when used).

## Should you use this?

**Probably yes if** your agent does work that *recurs* — the same kinds of
problems, procedures, or environments coming back. That is where memory pays,
and where knowing what helped last time is worth something. Operational
knowledge is the sweet spot: build quirks, dependency pins, project
conventions, user preferences.

**Probably not if** each task is unrelated to the last, or if your workload is
"answer one question about a big pile of documents." We measured both cases
and memory did not help; on scattered bug-fixing it was mildly *negative*.
Details in [What we found](#what-we-found), including the numbers that argue
against using this.

**Definitely not if** you want a turnkey team memory service. This is a
scoring primitive plus evidence, not a product: no access control, no
tenancy, no admission control on writes.

## Install

The extension needs a SQLite that can load extensions (≥ 3.35). Apple's
bundled CLI has loading compiled out — use Homebrew's.

```sh
cargo build --release
sqlite3
.load ./target/release/librfm
SELECT rfm_init();
```

For Claude Code, an MCP server with local embeddings and one SQLite file:

```sh
cd integrations/claude-code && uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python mcp sqlite-vec sentence-transformers numpy
claude mcp add -s user rfm-memory -- "$(pwd)/.venv/bin/python" "$(pwd)/server.py"
```

It exposes `memory_save`, `memory_search`, `memory_feedback`, plus
`list`/`export`/`delete`/`status` for inspection. Searching records the
access automatically; feedback is what trains the ranking. `capture.md` has a
CLAUDE.md snippet telling the agent what's worth saving, and
`integrations/claude-code/ab/` is a ready-made A/B kit if you want to measure
whether any of this helps *your* work before believing ours.

---

## What we found

Everything below is measured. The benchmarks are public, the per-question
outputs are committed, and the experiments were pre-registered — the protocol,
the success bars, and what would count as failure were all written down and
committed to git *before* each run. The failures are reported at the same
length as the successes, because a memory system that only publishes its wins
is not telling you when to use it.

A note on the numbers: **hit@1** means "the top-ranked result was correct" and
**hit@5** means "a correct result appeared in the top five." Square brackets
are 95% confidence intervals. "Points" are percentage points.

### Memory helps when work recurs

- **Outcome feedback improves retrieval on repeat ground.** Where a question's
  evidence had served an earlier question, feedback added 0.02–0.08 NDCG
  across three different embedding models, on both chat and code corpora.
  Where evidence never recurs it can't help — and, bounded properly, it
  doesn't hurt either.
- **Operational knowledge is what actually transfers.** In 70 live Claude Code
  sessions fixing real bugs, exactly one memory earned sustained positive
  value: an environment gotcha about which dependencies a checkout needs. Not
  code knowledge. Facts about *how to work here* recur by their nature.
- **Stale memories get retired.** On knowledge-update tasks, preference for
  the updated fact rose from 0.43 to 0.66 without losing recall of fresh
  facts.
- **The value axis is load-bearing, not decorative.** Rank memories by usage
  alone and retrieval collapses — rich-get-richer drives NDCG to about 0.01.
  Negative feedback is what breaks that loop. If you build any usage-based
  ranking, you need something like this or it will eat itself.

### Memory does not help when work is episodic

- **Per-bug lessons mostly don't transfer.** The agent saved 17 genuinely good
  debugging lessons, then judged retrieved ones irrelevant bug after bug:
  **15 of 16 recorded outcomes were negative**. The system measured its own
  workload's transfer rate at roughly 6%, with no oracle telling it so. That
  is the mechanism working correctly on a workload that has little worth
  remembering.
- **On hard tasks under a time budget, memory is a mild tax.** Across 27
  paired real-bug tasks, the control arm solved 25 and the memory arm 23, with
  both disagreements going to control. That is consistent with noise
  (McNemar p = 0.5), but it is certainly not a win. Overhead was 8–22s per
  session, mostly model startup — irrelevant in a 30-minute session, material
  in a 90-second one.
- **A usage prior doesn't beat a good retriever at one-shot relevance.** The
  obvious version of this idea — multiply similarity by the usage score — was
  falsified outright: −0.32 NDCG against a strong embedder. The bounded form
  we ship reaches parity, not superiority. If your workload is one-shot
  lookup, just use similarity search.
- **The rank-1 gain is real but narrow.** Outcome ranking beat plain
  similarity for the top result on two datasets, and **failed its
  pre-registered replication bar on two others**. Cost was bounded everywhere.
  Treat top-slot improvement as a possible bonus, not the reason to deploy.

**The one-line takeaway:** agent memory is not a lesson journal, it's an
*operational profile*. Capture environment quirks, conventions, decisions and
preferences; let per-task trivia fade; and bound how far any of it can
override relevance.

### Pooling memory across a team

If recurrence is what memory needs, then sharing experience across several
agents should multiply it — one agent's solved problem becomes everyone's
candidate memory. It does, consistently:

| dataset | domain | shared vs per-agent stores (hit@5) |
|---|---|---|
| STAR | task-oriented dialog, 115 real human agents | **+26.1** [+24.7, +27.5] |
| MultiDoc2Dial | government-policy Q&A | **+37.5** [+35.9, +39.1] |
| FloDial | technical troubleshooting | **+4.0** [+3.2, +5.0] |
| ABCD | customer support | **+14.5** [+13.0, +16.1] |

The first three were pre-registered replications of the fourth. STAR is the
strongest evidence: the split follows the dataset's own 115 human agents on
the real collection timeline, so nothing about the grouping is our invention.

Accumulated experience also **out-performs each dataset's authored manual** —
the "just use RAG over the docs" baseline — by 12.0 / 21.1 / 6.4 / 1.7 points
at hit@1. But the manual owns the cold start, and by a lot: on
MultiDoc2Dial's first 500 interactions, having it is worth 42.6 points. The
best configuration everywhere was all three layers together — manual for day
one, accumulated experience for depth, outcomes for maintenance.

> **These are measurements, not a product.** A real shared memory service owes
> its users access control, tenancy isolation, a threat model, and deletion
> guarantees. This repo has none of those and doesn't currently intend to. If
> you build on the finding anyway: pool delexicalized patterns rather than
> transcripts, keep customer-specific context in per-customer stores, and use
> one database file per scope so that erasure is deleting a file.

### What a bad team member can do

Once memory is shared, ranking becomes something worth attacking. We measured
four attacks with an attacker injecting at 20% of traffic. This is, as far as
we know, the only quantified attack/defense evidence for memory ranking
anywhere — including the failed defenses.

| attack | what happens without defense | defense |
|---|---|---|
| **Write convincing junk** | self-correcting: two-thirds to three-quarters of the damage absorbed; the same fake gets served 6 times instead of similarity's 29, and exposure stays flat where similarity's *grows* | inherent — the demotion loop |
| **Self-promote** (inflate your own memories' usage and ratings) | **worse than having no ranking at all**: −1.5 points, up to −9.8 under heavy gaming | `exclude_self` — full recovery, ending 2.1 points *above* plain similarity, free on a team |
| **Censor a rival** (bury a procedure with negative votes) | **fails outright** — the censored procedures scored 2.1 points *better* than under plain similarity | none needed (see below) |
| **Collude** (four members endorsing each other's junk) | **−5.0 points, unfixed** | detection and governance, not ranking |

Two of these are worth understanding rather than just noting.

**Censorship fails for a structural reason.** The ranking multiplier is
bounded — usage history can move a memory's score by at most 30% — and that
bound is smaller than the similarity gap an attacker would need to close. The
constraint we adopted to stop the ranking from being *too helpful* turns out
to be exactly what stops it from being weaponized.

**Collusion is not solvable at the ranking layer, and we have six failed
attempts to show it.** We tried excluding self-endorsement, capping votes at
one per person, writer reputation, voter-weighted reputation, combinations,
and making endorsement a liability that costs the endorser when it fails.
None restores the baseline. They fail for a single reason: **every one of them
aggregates votes, and a ring manufactures votes.** Moving the aggregation from
memories to authors to voter-weights just moves the attack up with it.

Notably, the obvious defense backfires. Capping each person to one vote per
memory throttles the *corrective* signal exactly as hard as the abusive one —
a team can then land at most one negative on a bad memory instead of one per
wasted retrieval. It ships off by default and is documented as **not
recommended**, with the measurement behind that judgement.

What does work is **detection**. A colluding ring praises only its own
members, and that concentration is a signal it cannot manufacture — it
identified all four colluders on both datasets, using nothing but the access
log. Run [`integrations/audit.sql`](integrations/audit.sql) against your
store for writer reputation, endorsement concentration and mutual-endorsement
pairs, plus the governance actions (quarantine, freeze, revoke, scope
erasure) written out as SQL. Those are deliberately manual: automatically
acting on a detector is its own attack surface, since one false positive
silently deletes a colleague's work.

**Practical guidance.** For a shared store, turn on `exclude_self` and
`trust`. It's the best measured configuration against single bad actors and
costs nothing on a healthy store. Leave both **off for a single-agent store**,
where every memory is self-authored and excluding self-endorsement would throw
away all your feedback (measured cost: −0.80 points). And note the honest
boundary: the trust boundary is the deployment boundary. If your writers are
colleagues or systems you operate, this is genuinely resistant. If they're
anonymous, don't run a usage prior at all.

---

## How it works

Three ideas, each borrowed from published work and cited in the code.

**Recency and frequency, unified.** Rather than tracking them separately, both
fall out of ACT-R base-level activation — `B = ln(Σ tᵢ^−d)` over a memory's
access history. The Petrov (2006) approximation makes this O(1): keep the two
most recent access times exactly, add a closed-form tail for the rest.
Scoring reads one row and never touches the access log — measured at ~4.6µs
regardless of whether a memory has 20 accesses or 200, with mean
approximation error of 0.049 activation units.

**Value.** An exponentially-weighted moving average of outcomes in [−1, 1]:
`v ← 0.3·outcome + 0.7·v`, with a confidence shrink of `n/(n+3)` so that one
lucky success doesn't outshout everything else.

**Composition — the part that needed an experiment.** The naive approach,
multiplying similarity by the combined score, fails badly and fails *worse*
as your retriever improves (−0.05 NDCG with a weak embedder, −0.32 with a
strong one) because the activation term's dynamic range overwhelms
well-calibrated similarities. What ships is a bounded prior:

```
rfm_prior(id) = (1 − β) + β · rfm_score(id)          β = 0.3
final_score   = max(similarity, 0) × rfm_prior(id)
```

β = 0.3 was frozen by a pre-registered protocol — candidates, dev/test split,
selection rule and falsification criteria all committed before any run — and
then tested once. It passed on cost against similarity, on feedback
adaptivity, on an embedding model never used during tuning, and it was weak
on one endpoint (forgetting power, which β trades away for rank safety; raise
β if forgetting matters more to you than stability).

## API

| function | what it does |
|---|---|
| `rfm_init()` | create tables and indexes (idempotent) |
| `rfm_record_access(id[, actor])` | log a retrieval; returns new activation |
| `rfm_record_outcome(id, o[, actor])` | record feedback `o ∈ [−1,1]` for the latest access; returns the value EWMA |
| `rfm_prior(id)` | the bounded multiplier to compose with similarity |
| `rfm_score(id)` | the combined score, `w_a·P(activation) + w_v·value` |
| `rfm_activation/recency/frequency/value(id)` | individual components |
| `rfm_score_w(id, w_a, w_v[, tau, decay])` | parameterised variant for tuning |
| `rfm_config(key[, value])` | per-connection settings (below) |

Config keys: `tau`, `decay`, `lambda`, `w_a`, `w_v`, `shrink_k`, `beta`,
`now`, plus the shared-store flags `exclude_self`, `one_vote`, `trust`,
`trust_weighted`, `endorser_liability` (all default off; see the guidance
above — `one_vote` is not recommended).

Two invariants worth knowing. `rfm_config('now', t)` freezes the clock for
tests and replay. And exactly one outcome is accepted per access, enforced —
which means the access log can always reproduce the summary state, so an
auditor can verify any score from first principles.

For shared stores, tag memories with a writer via the `created_by` column and
pass the acting principal as `actor`. In the Claude Code server, set
`RFM_ACTOR` to the agent's identity and `RFM_HARDEN=exclude_self,trust`.

## How this compares

An August 2026 survey of 22 memory systems found the access → outcome →
ranking loop shipping in exactly one other open-source system:
[Cognee](https://docs.cognee.ai/guides/feedback-system), where it is off by
default and rates answers rather than task outcomes. Two others implement
pieces: [ReMe](https://github.com/agentscope-ai/ReMe) uses outcome utility
only to prune, and a [MemOS plugin](https://github.com/MemTensor/MemOS)
credits an episode's new traces rather than the memories that were retrieved.

So as far as we can determine, this is the only system where outcome feedback
is a default-on term in the retrieval score, attributed to the memory that
was actually retrieved, with negative outcomes carrying weight — and the only
one shipped as an embeddable primitive rather than a service. Concurrent 2026
research is converging on the same loop ([RoMeRL](https://arxiv.org/abs/2608.02508),
[Chen & Cheng](https://arxiv.org/abs/2606.12945)), and a July 2026
mechanism-level review ([arXiv:2607.23942](https://arxiv.org/abs/2607.23942))
still lists cognitive activation combined with utility as not yet migrated
from cognitive architectures into language agents.

## Why you can trust the negative results

- Experiments were **pre-registered**: `PROTOCOL.md` plus Amendments 1–10,
  each committed before the runs it governs, with dev/test splits, one-shot
  evaluation, and declared falsification criteria. Where a smoke run happened
  before registration, the registration says so.
- **Per-question outputs are committed** under `bench-quality/results-*/`, so
  any table cell above can be recomputed rather than taken on faith.
- **Failures are published in full** in `bench-quality/RESULTS.md` — the
  complete ledger, including a hybrid-retrieval approach that overfit, a
  pruning rule that couldn't be safe and useful at once, a rank-1 claim that
  failed replication on two of three datasets, and six collusion defenses
  that didn't work.
- **One published number was wrong and was corrected.** An early result
  claimed a 42-point gap that turned out to rest on a mapping bug silently
  dropping 22 of 55 manual entries. Pre-publication review caught it from the
  committed logs; the experiment was re-run and the corrected number is what
  appears above. Details under "Corrections" in RESULTS.md.
- Benchmarks: [LoCoMo](https://github.com/snap-research/locomo) (CC BY-NC),
  [LongMemEval](https://github.com/xiaowu0162/LongMemEval),
  [BEAM](https://github.com/mohammadtavakoli78/BEAM),
  [SWE-Bench-CL](https://github.com/thomasjoshi/agents-never-forget),
  [ABCD](https://github.com/asappresearch/abcd),
  [STAR](https://github.com/RasaHQ/STAR),
  [MultiDoc2Dial](https://doc2dial.github.io/multidoc2dial/),
  [FloDial](https://dair-iitd.github.io/FloDial/). No LLM judges and no API
  keys anywhere — retrieval is scored against each dataset's own annotations.

**Known limits**, stated plainly: outcome signals in the benchmark
experiments come from those annotations rather than real task success, so
they are cleaner than production feedback would be; the live coding A/B is
n=27 with a single executor model; two of the four dialog datasets lack
natural agent identities and ordering, so those were simulated (disclosed in
the protocol); and the staleness result is from one dataset and was never
pre-registered. Retrieval metrics are proxies for task success everywhere
except the live A/B, where gold tests scored outcomes directly.

## Repository

```
src/                      the extension (lib, functions, math, sql shim, config, clock)
rfm_schema.sql            standalone schema
tests/                    unit + CLI integration tests (cargo test)
bench/                    O(1) throughput benchmark
bench-quality/            retrieval benchmarks + RESULTS.md, the full ledger
experiments/swe-ab/       the live paired A/B on real bugs
integrations/claude-code/ MCP server, hooks, capture snippet, A/B kit
integrations/audit.sql    shared-store forensics + governance recipes
PROTOCOL.md               pre-registrations and amendments 1–10
DESIGN_NOTES.md           design decisions, trade-offs, limitations
```

## License

Dual-licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at
your option. Datasets are downloaded, never redistributed — provenance and
terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (note LoCoMo is
CC BY-NC).
