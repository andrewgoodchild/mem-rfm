# The model: what problem this is, where the math comes from, and how a memory lives

## At heart this is a Belady cache problem

Strip away the language about agents and memory and the problem is one
computer science has studied since 1966. You have far more items than you can
put in front of the model, and you must choose which ones. That is cache
replacement.

**Belady's optimal algorithm** evicts the item whose next use is furthest in
the future. It is optimal and unimplementable, because it requires knowing the
future. Every real policy approximates that oracle:

| policy | approximates "next use is far away" by |
|---|---|
| LRU | it hasn't been used recently |
| LFU | it isn't used often |
| LRFU (Lee et al. 2001) | `Σ 2^{−λ(t−tᵢ)}` — both, on an exponential kernel |
| **ACT-R base-level** | `ln(Σ (t−tᵢ)^{−d})` — both, on a **power-law** kernel |

The last two rows are the same functional form; `ln` is order-preserving, and
both degenerate to LFU as decay goes to zero. **ACT-R base-level activation is
LRFU with a power-law kernel** — and the power law isn't arbitrary. Anderson &
Schooler (1991) *derived* it by fitting real human information environments:
news headlines, child-directed speech, one person's email. Human memory
appears to approximate Belady using the statistics of how information actually
recurs.

But there is a dimension Belady doesn't have, and it is why this project
exists. **Belady assumes every hit is equally valuable.** For a CPU cache that
holds — a hit is a hit. For agent memory it emphatically doesn't: a memory can
be retrieved on every query and waste the agent's time every time. Predicting
*whether* an item will be used again is not the same as predicting whether
using it will be *worth anything*.

So mem-rfm is a cache policy with a quality axis: recency and frequency
predict re-use, and outcome feedback predicts worth.

## RFM: the name

That third axis has a name in another field. **RFM** is a customer-value model
from direct marketing: **R**ecency, **F**requency, **M**onetary value.
Marketers learned the first two come free from transaction logs but only
measure *engagement* — without the monetary axis you cannot tell a valuable
customer from a busy one. Someone who orders constantly and returns everything
is not a good customer, and no amount of recency and frequency will say so.

Same blind spot, same fix: swap the third axis for its analog — **did this
memory help when it was retrieved?**

We measured what happens without it. Ranked by recency and frequency alone, a
store **collapses** under sequential load: retrieved memories get retrieved
more, and quality falls to NDCG ≈ 0.01. The value axis breaks the
rich-get-richer loop.

---

## ACT-R, both halves

**ACT-R** (Anderson & Lebiere, 1998) is a cognitive architecture — a
computational model of human cognition. It has **two** memory systems, and
mem-rfm turns out to implement both.

### Declarative memory → R and F

Chunks are retrieved by **base-level activation**:

```
B = ln( Σᵢ tᵢ^−d )
```

`tᵢ` is time since the *i*-th use, `d` a decay rate (0.5 conventionally, our
default). Recency and frequency aren't blended — they are **one quantity**.
Each past use contributes a term decaying with age, so many old uses can equal
a few recent ones. The practice effect, the spacing effect and power-law
forgetting all fall out of it.

Computed literally this walks the whole history per score. **Petrov (2006)**
keeps the *k* most recent lags exactly and closes the tail in a form depending
only on count and age. We use k = 2, which the schema already stores, so
**scoring reads one row and never touches the access log** — ~4.6µs whether a
memory has 20 accesses or 200.

**Caveat, and it is a large one:** ablation could not show that this axis
earns its place. Removing activation entirely left retrieval unchanged within
noise on our dev benchmark. See "which half is load-bearing" below before
treating the ACT-R half as the thing that makes this work.

### Procedural memory → M

Production rules are selected not by activation but by a learned **utility**:

```
U ← U + α·(R − U)
```

Expand it: `U ← α·R + (1−α)·U`. That is **algebraically identical** to our
outcome EWMA `v ← 0.3·outcome + 0.7·v`, with α = λ. We reinvented ACT-R's
utility-learning rule without noticing.

This reframes the design. mem-rfm is not "ACT-R plus a marketing model bolted
on" — it is ACT-R's declarative retrieval *and* its procedural utility
learning. It also explains our central empirical finding, that memory pays for
**procedural** knowledge (build quirks, conventions, environment facts) and
not for episodic per-task lessons: utility learning is the procedural module's
mechanism. And it explains why a July 2026 review names "activation with
**action utility**" as the bundle not yet migrated to language agents.

One thing we have that ACT-R doesn't: a **confidence shrink**
`v_eff = v·n/(n+3)`, so one lucky success doesn't outrank a long record. ACT-R
uses noise instead; the shrink is the better choice for a deterministic
ranker.

### Conformance

The equations are checked against reference implementations rather than
asserted: `bla_exact` matches ACTRModels.jl's published vectors to 1e-9 and
pyactr to 1e-12; `bla_hybrid_k2`/`bla_optimized` match **Petrov's own MATLAB**
k-sweep. Two divergences we document rather than fix: our lag floor is 1ms
where Lisp ACT-R uses 50ms (nobody agrees, and on seconds-to-days timescales
it never binds), and Petrov's two-page poster publishes **no error bounds**,
so we quote our own measured error rather than a figure from the paper.

---

## Memory types: what we model, and what we don't

The usual agentic-AI taxonomy has five entries: **short-term/working** memory,
and **long-term** memory split into **semantic** (facts), **episodic** (events
tied to a time), and **procedural** (skills). That is Tulving's and Squire's
psychology, and it is a reasonable map of the territory.

mem-rfm models **one distinction** from it: procedural versus everything else.
The `kind` column tags a row `'procedural'`, which scores it with
`w_a_proc`/`w_v_proc` (default 0.3/0.7), weighting outcomes higher. Untagged
rows are unaffected, so this changes nothing until you opt in. The effect is
**sensitivity, not inflation** — the gap between a procedural memory that keeps
working and one that keeps failing is wider. (With few outcomes the shrink
pulls value toward neutral, so weighting it more can *lower* a score; an early
test of ours asserted otherwise and was wrong.)

### Why that one and not the others

**Short-term / working memory is out of scope, and not because it's
unimportant.** It isn't a *store*: it has no retrieval ranking, no
accumulation, and it resets. It is the context window, and managing it is the
harness's job. A `kind` value for it would be a label with no mechanism behind
it.

**We don't split semantic from episodic**, for two reasons. First, ACT-R
doesn't: its declarative module holds both, and the episodic/semantic
distinction is Tulving's, not part of the architecture we implement. Second
and more practically, we haven't measured that the split would change any
decision.

**But that distinction is the one our data most nearly justifies**, so it is
the obvious next candidate rather than a closed question. Our clearest
empirical result is exactly episodic-versus-procedural: per-bug lessons tied
to a single event transferred at **~6%** (15 of 16 outcomes negative), while
the one memory that earned sustained positive value across 70 sessions was an
operational procedure. Type predicts worth.

### Why types are a prior, not a permanent weight

There is a design subtlety here worth stating, because our current
implementation arguably has it wrong.

Does a type tell the system anything the outcome loop doesn't eventually
learn by itself? Mostly no: if an episodic memory doesn't transfer, it gets
retrieved, fails to help, earns negatives and sinks. **Type is a prior; the
outcome EWMA is the posterior.**

That locates precisely where typing earns its keep — **cold start**, before a
memory has any outcome history, which is also where we have measured that
priors matter most (an authored manual was worth +42.6 points over
MultiDoc2Dial's first 500 interactions). And it implies the right mechanism is
an *initial* value that evidence washes out, not a permanent weight that keeps
overriding evidence forever. The confidence shrink `n/(n+k)` already
implements exactly that handoff.

The second place types could plausibly earn their keep is **retention** rather
than ranking: an episodic memory is tied to an event and should age out, while
a procedural one shouldn't. That is a per-type window on `rfm_prunable`, and
it is where the 6% transfer finding would actually cash out.

### Current status: honest

The procedural weights are **theoretically motivated and unmeasured**. A dev
sweep (Amendment 11, V2) gave +0.003 with the confidence interval sitting on
zero — no evidence yet that typing helps at all, though BEAM is the wrong
venue to judge it (its labels are evidence turns, and no outcome feedback
accumulates there, so the value axis is inert).

So the position is: one distinction implemented because ACT-R draws it and our
data supports it, three more left out until something measures them. If typing
shows nothing on the procedure-labelled dialog datasets, the honest response is
to *remove* `kind` rather than extend it.

---

## Composition: the part that needed an experiment

Multiplying similarity by the score fails, and fails *worse* as the retriever
improves (−0.05 NDCG under a weak embedder, −0.32 under a strong one).
Activation varies ~6× across a store while a good embedder separates relevant
from irrelevant by a few percent, so the prior overwhelms the signal it was
meant to adjust. The fix bounds it:

```
rfm_prior(id) = (1 − β) + β · rfm_score(id)        β = 0.3
final_score   = max(similarity, 0) × rfm_prior(id)
```

β = 0.3 was frozen by a pre-registered protocol and evaluated once.

### How much can the prior actually move a ranking?

The *nominal* range is [0.7, 1.0] — a 30% demotion ceiling. **The realised
range is narrower, and this document previously overstated it.** `rfm_score`
reaches 1.0 only if the logistic saturates, and with lags in seconds over
multi-day horizons `B` sits deep in the negative: ten uses, the last an hour
ago, still gives `B ≈ −3.5` and `P(B) ≈ 0.03`. On a realistic store the
achievable span is about **[0.700, 0.820] — a ~15% ceiling**.

Two consequences. The **rank-safety argument holds a fortiori**: the prior
perturbs rankings even less than designed, which is why measured cost was
within noise everywhere, and why censorship attacks failed outright. And the
**modest forgetting effect has a second cause besides β** — the activation
axis is using about a sixth of its range.

The squash constants (`THETA`, `S`) are ACT-R's retrieval threshold τ and
noise s, which ACT-R **fits per model**. They are now exposed as config for
exactly that purpose (PROTOCOL.md Amendment 11).

### What the kernel comparison showed

Dev-set result (BEAM, MiniLM, paired NDCG@10 against the frozen
configuration) — the first empirical test of the LRFU kernel question in agent
memory:

| model | Δ NDCG@10 |
|---|---|
| **ACT-R power law (frozen)** | — baseline |
| exponential, 1-day half-life | −0.029 [−0.041, −0.018] |
| exponential, 7-day half-life | −0.031 [−0.043, −0.020] |
| exponential, 30-day half-life | −0.027 [−0.037, −0.017] |
| **Codex model** (citation count, no decay) | −0.022 [−0.033, −0.012] |

The power law wins — at every exponential half-life tried, and against the
count-only model Codex actually ships. That replicates in agent memory a
result the recommender literature established on human access streams (Kowald
et al., WWW'17, who reject the exponential at p<.001).

Also measured, pointing the same way as everything else here: **raising the
activation axis's influence hurts.** Lowering τ, which lifts P(B) toward
saturation, cost up to −0.063 NDCG. The bound isn't a compromise; it's the
finding.

Caveats: dev set only, one embedder, and no outcome feedback accumulates on
BEAM, so the value axis is constant there. A dev observation under the
Amendment 11 protocol, not a frozen-then-tested result.

### Which half is load-bearing

An ablation of every component (Amendment 12) produced an uncomfortable
result about this design:

| removing | Δ NDCG@10 | verdict |
|---|---|---|
| **the outcome axis** | **−0.0055** [−0.0094, −0.0018] | **earns its place** |
| ACT-R activation | +0.0020 [−0.0022, +0.0061] | within noise |
| the confidence shrink | +0.0031 [−0.0040, +0.0096] | within noise |
| decay rate (→0, or →0.9) | +0.0001 / +0.0021 | within noise |

**Only the outcome axis measurably earns its place** — in a project with R
and F in its name, and with the ACT-R half carrying all the pedigree and all
the O(1) engineering.

It is, however, the same answer three earlier measurements gave from other
directions: activation *alone* collapses retrieval to NDCG ≈ 0.01; *raising*
activation's influence costs up to −0.063; and the bounded prior reaches
parity with similarity-only rather than beating it. Everything has said the
usage prior is a small, carefully-bounded adjustment. The ablation says which
half of it does the work.

The Belady framing explains why plausibly. Activation predicts **whether an
item will be used again**; the outcome axis predicts **whether using it will
be worth anything**. Our dev benchmark asks probing questions about a
conversation, and only 108 of its 355 questions revisit evidence that served
an earlier one — so re-use is nearly uninformative there while usefulness is
not. The recency and frequency axes may simply be answering a question that
benchmark does not ask.

Honest status: **unproven here, not disproven.** One dev benchmark, one
embedder, and short feedback streams are the least favourable setting for an
activation signal, and recurrence-heavy workloads are the obvious place to
look next. But the stronger reading deserves stating, because the evidence
currently permits it: it may be that for agent memory in general, recency and
frequency are the wrong prior and outcome is the right one — that the ACT-R
machinery here is elegant rather than load-bearing.

Two mechanisms this system does *not* have were tested by adding them.
**Hebbian co-retrieval association hurt by 3.2 NDCG points** — it reinforces
whatever was already retrieved, which is the rich-get-richer dynamic the
outcome axis exists to break, and ACT-R's `ln(fan)` discount did not save it.
**Interleaved consolidation had no detectable effect.** Neither earns
extension surface on this evidence.

---

## The lifecycle of a memory

Four stages. Each is a decision with evidence behind it.

### 1. Formation — how a memory gets made

The usual design asks the agent mid-task whether something is worth
remembering. We measured that going badly: across 70 live sessions the agent
saved 17 sincerely-chosen lessons and **15 of 16 later outcomes were
negative**. Judging durability while working means predicting the future.

Post-hoc formation is what Hermes and Codex both do instead — review the
session afterwards, when what mattered is visible. `hooks/session_end.py`
implements the cheap deterministic slice: it extracts the one signal
objectively present in a transcript, **a command that failed followed by a
variant that worked**. That is a gotcha the session paid for, and it lands in
the category our A/B says transfers.

A frequency-based miner over the same transcripts surfaced only `pytest -q`
and `git stash` — generic behaviour the model already knows. **Repetition
finds what agents do; correction finds what they had to learn.**

It **proposes, never writes**. Unreviewed accumulation is what every retreating
vendor had in common, and an ETH Zurich study (arXiv:2602.11988) found
LLM-generated context files *reduced* task success.

### 2. Retrieval — what surfaces

Similarity picks candidates; the bounded prior reorders among plausible ones.
Retrieval is itself an event: it feeds recency and frequency, which is what
makes the cache analogy live rather than decorative.

### 3. Outcome — what it was worth

`rfm_record_outcome` supplies the dimension Belady lacks. Exactly one outcome
is accepted per access, enforced, so the access log always reproduces the
summary state and any score can be recomputed from first principles.

This stage is also what makes forgetting possible. A memory that stops being
useful — because a procedure changed, not because it grew less similar — can
only be detected here. Similarity cannot see staleness: a stale memory stays
semantically perfect forever.

### 4. Retention — what stays

Ranking decides what surfaces, not what stays, and stores grew forever.
`rfm_prunable(id, max_unused_days)` borrows Codex's policy, where citation
refreshes a memory and uncited rows age out — usage driving *retention*, not
just rank:

```sql
SELECT id FROM rfm_memories WHERE rfm_prunable(id, 30);
```

A read-only predicate, not a delete: the tables are host-owned. The guard is
the substantive part — **anything with a positive outcome record is never
prunable**, however idle. A memory retrieved rarely but successfully is
exactly what this system exists to keep, and exactly what a pure cache policy
would evict. That guard is the Belady framing's limit showing through:
optimal caching drops the rarely-used item, and here that would be the wrong
call.

---

## What we deliberately did not take from ACT-R

A cognitive architecture carries machinery for modelling humans, not ranking
documents:

- **Partial matching** exists because ACT-R retrieval is exact slot matching.
  We retrieve by embedding similarity, already graded and strictly more
  expressive. Adopting it would reimplement the embedder, worse.
- **Retrieval latency** (`Time = F·e^{−f·A}`) predicts how long a *person*
  takes to answer.
- **Activation noise** reproduces human variability; stochasticity would cost
  the determinism our pre-registered methodology depends on. (Our `S` is a
  squash *width*, not sampled noise — the shared symbol is a trap.)
- **Production compilation**, permanent noise, declarative finsts — no ranking
  payoff.

One skipped mechanism is genuinely interesting: **spreading activation**
(`Sji = S − ln(fan)`), which boosts memories associated with the current
context. The natural analog is co-retrieval — memories fetched together are
associated — and the `ln(fan)` term automatically penalises promiscuous
memories that co-occur with everything, attacking the "busy but not valuable"
problem from the context side. A co-occurrence association strength rather
than an embedding distance, which no agent-memory system appears to have
tried. Unbuilt.

## Where each claim was measured

Nothing above is asserted from the literature alone. `bench-quality/` holds
every runner, the committed per-question outputs, and `RESULTS.md` — the full
ledger including what died. The mapping:

| claim in this document | runner | committed rows |
|---|---|---|
| the naive composition fails; β=0.3 frozen | `compose_eval.py` | `results-compose/` |
| frozen β passes its one-shot test | `frozen_eval.py` | `results-frozen/` |
| power law beats exponential and beats Codex's count-only model | `model_eval.py` | Amendment 11, RESULTS.md |
| activation-only collapses to NDCG ≈ 0.01 | `signal_screen.py`, `phase2_eval.py` | RESULTS.md |
| feedback adds 0.02–0.08 NDCG on recurring evidence | `locomo_eval.py`, `beam_eval.py` | `results-locomo/`, `results-beam/` |
| stale facts get retired (0.43 → 0.66) | `ku_eval.py` | `results-ku/` |
| ~6% lesson transfer; memory as a mild tax on hard tasks | `experiments/swe-ab/` | `results.jsonl`, `memory-audit.md` |
| pooling beats per-agent stores | `star_eval.py`, `md2d_eval.py`, `flodial_eval.py`, `abcd_eval.py` | `results-star/`, `results-md2d/`, `results-flodial/` |
| experience out-ranks the authored manual | `abcd_manual.py` | RESULTS.md |
| staleness recovery under a procedure change | `abcd_staleness.py` | RESULTS.md |
| scoring is O(1): ~4.6µs flat, error 0.049 | `throughput.sh` | RESULTS.md |
| hybrid BM25, pruning, content-value signals — all failed | `hybrid_eval.py`, `prune_eval.py`, `signal_screen.py` | RESULTS.md |
| only the outcome axis earns its place; Hebbian hurts | `ablation_eval.py` | `results-ablation/` |

Adversarial results (attacks, defences, the six that failed) live in
[team-memory](team-memory.md); their runners are preserved at the
`team-experiments` tag rather than on `main`.

Two habits worth stating because they are cheap and they catch real
problems. Every extension change is checked for **retrieval regression** by
re-running a committed benchmark and diffing per-question rows, not just by
running unit tests — adding the `kind` column and `rfm_prunable` was verified
bit-identical across all 1,065 BEAM rows. And `model_eval.py` carries a
`--selfcheck` that reconciles its in-process activation against the shipped
extension, after an early version of that runner scored every decay kernel
identically because never-accessed memories took a sentinel value instead of
the creation-age fallback. A silent dead channel invalidates every number
downstream of it, so the harness is built to fail loudly instead.

## Sources

Every equation is cited in the code implementing it (`src/math.rs`).

- Belady, L. A. (1966) — the optimal replacement algorithm.
- Lee, D. et al. (2001). *LRFU: a spectrum of policies subsuming LRU and LFU*.
- Anderson, J. R. & Lebiere, C. (1998). *The Atomic Components of Thought* —
  ACT-R; base-level learning and utility learning.
- Anderson, J. R. & Schooler, L. J. (1991) — the environmental derivation of
  the power law.
- Petrov, A. A. (2006) — the hybrid k-term approximation.
- Kowald, D. et al. (WWW 2017) — power-law vs exponential on human access
  streams.
- Hughes, A. M. (1994). *Strategic Database Marketing* — RFM.
- Park, J. S. et al. (2023). *Generative Agents* — a benchmark comparison
  condition, not a dependency.
