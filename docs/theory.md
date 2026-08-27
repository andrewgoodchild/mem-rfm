# The model: what problem this is, where the math comes from, and how a memory lives

## At heart this is a Belady cache problem — for half of it

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

### Where the cache analogy breaks

Taking the frame seriously means naming where it stops. Four of its
assumptions fail for agent memory, and each failure is something this
project has measured rather than argued:

- **A hit can be worth less than a miss.** Caching's objective counts
  misses; serving from cache is at worst neutral, and the optimality proof
  rests on that. An injected memory can be stale, inapplicable, or wrong —
  a signed cost no miss-count can express. The ledgers already contain it:
  memories driven to value −1.0 by acted-on-and-failed outcomes (advice
  taken, and wrong), and Track 10 (RESULTS.md), where five true,
  human-ratified memories injected in 13/13 sessions left the metric of
  record unmoved at +24.9% wall.
- **A miss is not a fetch.** In caching the miss penalty is a known cost
  from a slower tier — GreedyDual-Size-Frequency weights evictions by
  exactly that retrieval cost. An agent's alternative to memory is
  re-derivation, and measured re-derivation cost does not predict realized
  usefulness (Spearman +0.146, n=19, the two costliest pairs junk
  artifacts — REVALIDATION.md, Track 5). The cost-weighted eviction
  literature imports a number that, here, correlates with nothing.
- **The reference stream is endogenous.** Belady's future references are
  given in advance; injection changes the agent's behaviour and therefore
  what gets referenced next. Pilot 2 caught the pathology directly: two
  demoted memories were re-injected seven more times because each
  feedback's implied access refreshed their recency — the policy feeding
  its own inputs. No replacement-theory result covers a cache that
  manufactures its own hits.
- **Eviction may not even be binding.** Replacement policy is the entire
  subject of caching theory, and an oracle experiment made it moot at this
  scale: deleting every never-contributing memory — a perfect filter,
  removing up to 49.5% of a store — moved accuracy by ~0 (cited at Track
  5's registration). When the *optimal* eviction policy buys nothing, the
  binding constraints are formation (what to write down) and value
  (whether having it helps) — the two questions the cache frame takes as
  axioms.

What survives is the R/F half, intact. Recency and frequency as estimators
of the probability of re-use is genuinely the Belady-approximation story;
it is what Anderson & Schooler validated against real environments, and it
is where the frozen-corpus ablations say activation earns its keep. The
honest form of this section's title is therefore: **Belady is a good
theory of the R and F axes and no theory at all of M.** The caching
literature answers "given that something will be needed, which one is it?"
and never asks "is having it better than not having it?" — the
counterfactual question the live tracks (REVALIDATION.md) exist to
measure, and the one on which the field at large is similarly silent: its
benchmarks score retrieval, not value.

So mem-rfm is a cache policy with a quality axis — recency and frequency
predict re-use, and outcome feedback predicts worth — with the standing
caveat that the quality axis is the half no cache theory supplies.

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
noise on our dev benchmark. See "which half does the work" below before
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

### The condition side of the production (added 2026-08-27)

The analogy above was incomplete in a way that took a failed experiment
to see. An ACT-R production is a **condition→action pair**, and its
utility updates only when the production *fires* — which, by
construction, can only happen when its condition matches the current
state. Our outcome loop had no condition side: it updated `v` whenever a
memory's action was *imitated*, whether or not the state the memory
describes was present. The live tracks measured what that permits — the
corpus's highest-value memory earned 79% of its 17-outcome ledger in
sessions where the failure it guards against never occurred; agents
copied the suggested command, every copy succeeded (nothing was at
risk), and the loop credited each one. An EWMA over
condition-blind rewards converges on *imitation frequency*, not utility
(RESULTS.md, Track 11 and Correction C4).

The fix restores the production structure rather than adding machinery:
each memory carries the **condition class** its own text names
(`condition_class`, a host-owned column, stamped by derivation); the
session-end loop observes which classes actually fired in command
output; and a **positive** reward is recorded only when the memory's
condition was live — the analog of "the production fired". Negative
rewards are never gated, because an action that failed is evidence
against the memory in any state. Under this rule the ledger above could
not have been earned. Acceptance audit:
`integrations/claude-code/hooks/test_conditions.py`; the observation
side is the `t_fired` clock of DESIGN_NOTES' three-clock proposal,
whose ranking-visible uses (fire-rate decay) remain behind a
registered-track gate.

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
psychology, and it is a reasonable map of the territory. (For the same
taxonomy mapped onto what a ChatGPT user actually experiences — and why
consumer memory and agent memory occupy nearly disjoint rows of it — see
[memory-types.md](memory-types.md); this section stays concerned with
scoring.)

mem-rfm models **neither distinction in its scoring**, and that is a measured
decision rather than an omission.

We did implement it: a `kind` column routing `'procedural'` rows to
utility-weighted parameters, on the reasoning that ACT-R scores its two memory
systems differently and our clearest empirical result is exactly
procedural-versus-episodic. Then we tested it on all four corpora whose labels
*are* procedures. **No significant effect in any cell** (Δ hit@1 between
−0.0053 and +0.0040). The column and its weights were removed.

What survives is the *knowledge* finding, which is well supported and is what
matters in practice: **procedural knowledge is what transfers** — build
quirks, dependency pins, conventions — while per-task episodic lessons do not
(~6% transfer rate). That should shape **what you capture**, not how the
scorer weights it. Type belongs in the capture policy, not the ranking
function.

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
operational procedure. Type predicts worth — with the caveat the
condition-side section above adds: that memory's ledger was later shown
to be largely condition-blind credit (C4), so "predicts worth" here
means predicts *which content recurs*, the capture-policy claim, not a
proven causal benefit.

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

So the position is: the one distinction we implemented was measured, showed
nothing, and was removed — which is what this document said in advance would
be the honest response. The other three were never implemented, and nothing
here suggests they would fare differently. Memory type is a capture concern.

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

### Is ACT-R earning its complexity? Yes — but we got this wrong first

The activation half exists to compute `ln(Σ tᵢ^−d)`, which needs the Petrov
approximation, a `bla_cache` column and a conformance suite. Classical RFM
scores the axes separately — in marketing, as quintile ranks. Is the
complexity earned?

**Tested across four corpora and two embedders: yes.** ACT-R is never beaten
by rank bucketing and wins significantly on two of four corpora (ABCD,
MultiDoc2Dial) under both embedders. It also beats the naive separate-axis
form — a weighted sum of `exp(−Δ/τ)` and `ln(1+n)` — by 0.0107 hit@1, so
unifying recency and frequency into one quantity is doing real work.

**We published the opposite conclusion first, and it is worth saying why.**
Amendments 13–13d all ran on STAR alone, which turns out to be the one corpus
where ACT-R and rank bucketing tie. On that basis this document claimed the
burden of proof had shifted onto ACT-R. Replication reversed it. The failure
mode — a single-corpus win that does not generalise — is the same one
`PROTOCOL.md` Amendment 2 caught for BM25 hybrid fusion, where a two-repo win
reversed on six held-out repos. The lesson was in the repository and got
applied late.

What survives from that line of work, because it is independently useful:
fitting the squash (θ, s) barely matters and does **not** transfer across
corpora, so the parameters want per-corpus tuning if you tune them at all;
rank-bucket granularity has an interior optimum around 5 buckets, so finer is
not better; both `exp(−Δ/τ)` and the ACT-R logistic are mis-calibrated for
these corpora in opposite directions; and maintained global cutpoints are a
perfectly workable **row-local** implementation of bucketing, which means the
architectural objection to rank scoring was never the real obstacle — the
ranking quality was.

### Why we use ACT-R for R and F

Short version: **we tried to replace it and failed.**

The activation half is not there because cognitive science is appealing. It is
there because every simpler alternative was tested and lost:

- **Two separate axes, weighted and summed** (`exp(−Δ/τ)` + `ln(1+n)`) — loses
  by 0.0107 hit@1, CI excluding zero. Unifying recency and frequency into one
  log-sum quantity is doing real work, and this is the cleanest evidence for
  it: same inputs, same combination step, different functional form.
- **Rank buckets, the marketing RFM formula** — never beats ACT-R across four
  corpora and two embedders, and loses significantly on two of them. This was
  tested four different ways (per-query quintiles, deciles, continuous
  percentiles, and maintained row-local cutpoints) after an early single-corpus
  result suggested the opposite.
- **Recency alone / frequency alone** — −0.0067 and −0.0213 hit@1.
- **Re-weighting the two ACT-R axes by memory type** — no significant effect in
  any of eight cells.

What ACT-R buys, concretely: one quantity instead of two hand-weighted ones,
a log-scale transform that handles ages spanning seconds to months, O(1)
scoring via Petrov's approximation from a single row, and equations that
match three reference implementations to 1e-9 so the maths can be checked
rather than trusted.

What it costs, stated plainly: a `bla_cache` column, an approximation whose
error we measure rather than inherit from the paper, and a conformance
obligation. On four corpora that cost is earned. On STAR alone it isn't — and
we published the wrong conclusion from exactly that before replicating.

### Which half does the work

An ablation of every component (Amendment 12) produced an uncomfortable
result about this design:

| removing | Δ NDCG@10 | verdict |
|---|---|---|
| **the outcome axis** | **−0.0055** [−0.0094, −0.0018] | **earns its place** |
| ACT-R activation | +0.0020 [−0.0022, +0.0061] | within noise |
| the confidence shrink | +0.0031 [−0.0040, +0.0096] | within noise |
| decay rate (→0, or →0.9) | +0.0001 / +0.0021 | within noise |

**On this benchmark, only the outcome axis measurably earns its place** — in
a project with R and F in its name.

That conclusion did **not** survive contact with other corpora. Repeating the
ablation at fixed stream length across four datasets (Amendment 12b) found
that on STAR, removing activation costs exactly as much as removing outcome
feedback (both −0.0067 hit@1, CIs excluding zero), and removing the prior
entirely costs more than either. The ACT-R half earns its keep there. The
result below is therefore specific to BEAM, and the general claim is the
duller one: **each axis earns its place on some corpora and not others.**

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

Honest status, after the gradient run: **it depends on the corpus.** The
prior appears to need a *sweet spot* — enough recurrence to build history,
and enough error left by the retriever to have room to help. FloDial has
150 repetitions per label but a 0.984 baseline, so nothing can be shown;
MultiDoc2Dial has 3.5 and no history; STAR has both and the axis earns its
place. BEAM sits at the unfavourable end.

The stronger reading — that recency and frequency are simply the wrong prior
for agent memory — was available on the BEAM result alone and is **no longer
supported**. It is recorded here because it was published before the gradient
run corrected it.

Two mechanisms this system does *not* have were tested by adding them.
**Hebbian co-retrieval association hurt by 3.2 NDCG points** — it reinforces
whatever was already retrieved, which is the rich-get-richer dynamic the
outcome axis exists to break, and ACT-R's `ln(fan)` discount did not save it.
**Interleaved consolidation had no detectable effect.** Neither earns
extension surface on this evidence.

---

## The lifecycle of a memory

Four stages — formation, retrieval, outcome, retention — each a decision
with evidence behind it. The full treatment is
[lifecycle.md](lifecycle.md): who decides at each stage, the survey of
shipped systems, why discretionary formation under-fires, and the design
rules that follow. The short version: formation and outcome recording must
be harness-owned and post-hoc (mid-task discretion measurably fails — 15 of
16 agent-chosen lessons had negative outcomes); retrieval feeds the recency
and frequency terms; retention is guarded by `rfm_prunable`, where a
positive outcome record makes a memory unprunable however idle.

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
| ~6% lesson transfer; memory as a mild tax on hard tasks | `bench-quality/live-ab/` | `results.jsonl`, `memory-audit.md` |
| pooling beats per-agent stores | `star_eval.py`, `md2d_eval.py`, `flodial_eval.py`, `abcd_eval.py` | `results-star/`, `results-md2d/`, `results-flodial/` |
| experience out-ranks the authored manual | `abcd_manual.py` | RESULTS.md |
| staleness recovery under a procedure change | `abcd_staleness.py` | RESULTS.md |
| scoring is O(1): ~3.5µs/row (4.6µs in the retired Rust extension); hybrid-vs-exact max error ≤ 0.4 on synthetic histories | `throughput.py` | RESULTS.md |
| hybrid BM25, pruning, content-value signals — all failed | `hybrid_eval.py`, `prune_eval.py`, `signal_screen.py` | RESULTS.md |
| only the outcome axis earns its place; Hebbian hurts | `ablation_eval.py` | `results-ablation/` |

Adversarial results (attacks, defences, the six that failed) live in
[team-memory](team-memory.md); their runners are preserved at the
`archive/team-experiments` tag rather than on `main`.

Two habits worth stating because they are cheap and they catch real
problems. Every engine change is checked for **retrieval regression** by
re-running a committed benchmark and diffing per-question rows, not just by
running unit tests — adding the `kind` column and `rfm_prunable` was verified
bit-identical across all 1,065 BEAM rows. And `model_eval.py` carries a
`--selfcheck` that reconciles its in-process activation against the shipped
engine, after an early version of that runner scored every decay kernel
identically because never-accessed memories took a sentinel value instead of
the creation-age fallback. A silent dead channel invalidates every number
downstream of it, so the harness is built to fail loudly instead.

## Sources

Every equation is cited in the code implementing it (`rfm.py`; originally
`src/math.rs`, preserved at the `archive/rust-extension` tag).

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
