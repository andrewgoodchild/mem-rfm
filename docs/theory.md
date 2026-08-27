# The model: what problem this is, where the math comes from, and how a memory lives

## The argument, in one page

1. **Choosing which memories to put in front of a model is half a cache
   problem.** For that half — will this item be needed again? — the right
   theory exists: cache replacement, whose best practical form (recency
   and frequency on a power-law kernel) turns out to be ACT-R's
   base-level activation, derived by Anderson & Schooler from the
   statistics of real information environments. That is the **R and F**
   axes.
2. **Cache theory cannot even pose the other half.** It assumes every hit
   is worth serving. Agent memories can be stale, inapplicable, or wrong
   — so mem-rfm adds a third axis, **M**: a signed, per-memory ledger of
   measured outcomes, updated by the same rule ACT-R uses for procedural
   utility learning.
3. **An outcome ledger must be condition-gated or it measures the wrong
   thing.** Our live program caught the failure at full scale: agents
   copy a suggested command, the copy succeeds, the ledger inflates —
   credit without need. A positive outcome now counts only when the
   condition the memory names actually fired, which is what "the
   production fired" means in ACT-R, restored.
4. **Every axis is bounded, because that is what measurement said.** The
   prior is a small, carefully bounded adjustment to similarity — raising
   its influence hurts, and which axis earns its place depends on the
   corpus. The bound is the finding, not a compromise.
5. Nothing here is asserted from the literature alone: the claim→runner→
   committed-rows mapping is the second-to-last section.

## Half a Belady problem

Strip away the language about agents and memory and half the problem is one
computer science has studied since 1966: far more items than you can put in
front of the model, and a choice of which. That is cache replacement.

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

### Where the cache analogy stops

Four of caching's assumptions fail for agent memory, each measured rather
than argued:

- **A hit can be worth less than a miss.** Caching's optimality proof
  counts misses; serving from cache is at worst neutral. An injected
  memory can be stale, inapplicable, or wrong — the ledgers hold memories
  driven to −1.0 by acted-on-and-failed outcomes, and Track 10
  (RESULTS.md) delivered five human-ratified memories in 13/13 sessions
  for no measured benefit.
- **A miss is not a fetch.** Caching's miss penalty is a known cost from a
  slower tier (GreedyDual-Size-Frequency weights evictions by it). An
  agent's alternative is *re-derivation*, and measured re-derivation cost
  does not predict realized usefulness (Spearman +0.146, n=19 —
  REVALIDATION.md, Track 5).
- **The reference stream is endogenous.** Belady's future references are
  given; injection changes what gets referenced next. Pilot 2's demoted
  memories were re-injected seven more times because each feedback's
  implied access refreshed their recency — a cache manufacturing its own
  hits.
- **Eviction may not even be binding.** An oracle deletion of every
  never-contributing memory — a perfect replacement policy, removing up
  to 49.5% of a store — moved accuracy by ~0. The binding constraints are
  formation and value, the two questions the cache frame takes as axioms.

What survives, intact, is the R/F half: recency and frequency as
estimators of re-use probability is genuinely the Belady story, and it is
where the frozen-corpus ablations say activation earns its keep. So:
**Belady is a good theory of the R and F axes and no theory at all of M.**
The caching literature answers "given that something will be needed, which
one is it?" and never asks "is having it better than not having it?" —
the counterfactual question the live tracks exist to measure, and one the
field's benchmarks (which score retrieval, not value) share its silence
on.

## The three axes

### R and F: base-level activation

ACT-R (Anderson & Lebiere, 1998) retrieves declarative chunks by
**base-level activation**:

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

The clock behind `tᵢ` is the **acted-on access event** — injection alone is
not use (lifecycle.md). Whether this axis earns its place depends on the
corpus; see "does each part earn its place" below before treating it as
the load-bearing half.

**Conformance.** The equations are checked against reference
implementations rather than asserted: `bla_exact` matches ACTRModels.jl's
published vectors to 1e-9 and pyactr to 1e-12; `bla_hybrid_k2` matches
**Petrov's own MATLAB** k-sweep. Two documented divergences: a 1ms lag
floor where Lisp ACT-R uses 50ms (never binds at our timescales), and we
quote our own measured approximation error because Petrov's poster
publishes none.

### M: the outcome ledger

The third axis has a name in another field. **RFM** is direct marketing's
customer-value model — **R**ecency, **F**requency, **M**onetary value —
born from the observation that the first two come free from transaction
logs but only measure *engagement*: someone who orders constantly and
returns everything is not a good customer, and no amount of recency and
frequency will say so. Same blind spot here, same fix: where marketing
puts money, mem-rfm puts **did acting on this memory help?** — a signed
outcome in [−1, 1] per use.

Without it the store eats itself: ranked by recency and frequency alone
under sequential load, retrieved memories get retrieved more and quality
collapses to NDCG ≈ 0.01. The value axis breaks the rich-get-richer loop.

The update rule is an EWMA, `v ← 0.3·outcome + 0.7·v` — which is
**algebraically identical** to ACT-R's procedural utility learning
`U ← U + α·(R − U)` with α = λ. We reinvented it without noticing, and the
identity reframes the design: mem-rfm is not "ACT-R plus a marketing
model bolted on" but ACT-R's declarative retrieval *and* its procedural
utility learning — which also fits the central empirical finding that
memory pays for **procedural** knowledge (build quirks, conventions,
environment facts) and not episodic per-task lessons (~6% transfer).
One addition ACT-R doesn't have: a **confidence shrink**
`v_eff = v·n/(n+3)`, so one lucky success doesn't outrank a long record.

**The condition side (added 2026-08-27).** The analogy was incomplete in
a way that took a failed experiment to see. An ACT-R production is a
**condition→action pair**, and utility updates only when the production
*fires* — which requires its condition to match. Our loop had no
condition side: it updated `v` whenever a memory's action was *imitated*,
in any state. The live tracks measured what that permits: the corpus's
top memory earned 79% of its 17-outcome ledger in sessions where the
failure it guards against never occurred — copied commands, credited
successes. An EWMA over condition-blind rewards converges on *imitation
frequency*, not utility (RESULTS.md, Track 11 + C4). The fix restores
the production structure: each memory carries the condition class its own
text names; the session-end loop observes which classes fired; a
**positive** outcome lands only when the memory's condition was live,
while negatives always land (a failed action is evidence against the
memory in any state). Under this rule the ledger above could not have
been earned. Acceptance audit:
`integrations/claude-code/hooks/test_conditions.py`; fire-rate decay and
other ranking-visible uses of the fire clock stay behind a
registered-track gate (DESIGN_NOTES).

### Composition: the bound

Multiplying similarity by the raw score fails, and fails *worse* as the
retriever improves (−0.05 NDCG under a weak embedder, −0.32 under a strong
one): activation varies ~6× across a store while a good embedder separates
relevant from irrelevant by a few percent. The fix bounds the prior:

```
rfm_prior(id) = (1 − β) + β · rfm_score(id)        β = 0.3
final_score   = max(similarity, 0) × rfm_prior(id)
```

β = 0.3 was frozen by a pre-registered protocol and evaluated once. The
*nominal* range is [0.7, 1.0]; the **realised** range is narrower — with
lags in seconds over multi-day horizons, `B` sits deep in the negative
(ten uses, the last an hour ago, still gives `P(B) ≈ 0.03`), so the
achievable span is about **[0.700, 0.820], a ~15% ceiling**. Two
consequences: the rank-safety argument holds a fortiori (which is why
measured cost was within noise everywhere and censorship attacks failed
outright), and the modest forgetting effect has a second cause besides β.
The squash constants (θ, s) are ACT-R's retrieval threshold and noise
width, which ACT-R fits per model; they are exposed as config for exactly
that purpose (PROTOCOL.md, Amendment 11).

## Does each part earn its place?

We tried to replace or remove every component. The record, stated once:

**Alternatives that lost to ACT-R activation** (four corpora, two
embedders unless noted):

- Two separate axes, weighted and summed (`exp(−Δ/τ)` + `ln(1+n)`):
  −0.0107 hit@1, CI excluding zero. Unifying recency and frequency into
  one log-sum quantity does real work.
- Rank buckets — marketing's own RFM formula, tested four ways
  (quintiles, deciles, continuous percentiles, maintained row-local
  cutpoints): never beats ACT-R, loses significantly on two corpora.
- Recency alone / frequency alone: −0.0067 / −0.0213 hit@1.
- Exponential kernels at 1-, 7-, and 30-day half-lives, and the
  count-only model Codex ships: all lose to the power law by 0.022–0.031
  NDCG (dev set), replicating Kowald et al. (WWW'17) in agent memory.
- Re-weighting the axes by memory type: no effect in any of eight cells.

**Component ablation** (Amendment 12, BEAM):

| removing | Δ NDCG@10 | verdict |
|---|---|---|
| **the outcome axis** | **−0.0055** [−0.0094, −0.0018] | **earns its place** |
| ACT-R activation | +0.0020 [−0.0022, +0.0061] | within noise |
| the confidence shrink | +0.0031 [−0.0040, +0.0096] | within noise |
| decay rate (→0, or →0.9) | +0.0001 / +0.0021 | within noise |

On BEAM only the outcome axis measurably earns its place — in a project
with R and F in its name. That conclusion did **not** survive other
corpora: on STAR, removing activation costs exactly as much as removing
outcome feedback (both −0.0067 hit@1, CIs excluding zero), and removing
the prior entirely costs more than either. The general claim is the
duller one: **each axis earns its place on some corpora and not
others.** The prior needs a *sweet spot* — enough recurrence to build
history, and enough retriever error to leave room. FloDial has 150
repetitions per label but a 0.984 baseline (nothing can show); MultiDoc2Dial
has recurrence 3.5 and no history; STAR has both and the axis earns its
place; BEAM sits at the unfavourable end (only 108 of its 355 questions
revisit evidence, so re-use is nearly uninformative there — the Belady
framing predicts exactly this split: activation answers "will it be used
again", the outcome axis answers "was using it worth anything").

**Also measured, pointing the same way:** activation *alone* collapses
retrieval to NDCG ≈ 0.01; *raising* activation's influence (lowering τ)
costs up to −0.063; the bounded prior reaches parity with
similarity-only rather than beating it. Everything says the usage prior
is a small, carefully bounded adjustment — the bound is the finding.

**Two mechanisms tested by adding them, both rejected:** Hebbian
co-retrieval association hurt by 3.2 NDCG points (it reinforces whatever
was already retrieved — the rich-get-richer dynamic the outcome axis
exists to break — and `ln(fan)` did not save it); interleaved
consolidation had no detectable effect.

**A process lesson this section carries, once:** single-corpus wins do
not generalise, and we published wrong conclusions from them twice —
Amendments 13–13d ran on STAR alone and claimed the burden of proof had
shifted onto ACT-R (replication reversed it), and BEAM alone supported
"R and F are the wrong prior for agent memory" (the gradient run
corrected it). The same failure mode Amendment 2 caught for BM25 hybrid
fusion. Both retractions stay in RESULTS.md.

What ACT-R buys, net: one quantity instead of two hand-weighted ones, a
log-scale transform spanning seconds to months, O(1) scoring from a
single row, and equations checkable against three reference
implementations. What it costs: a `bla_cache` column, a measured
approximation error, and a conformance obligation. On four corpora the
cost is earned.

## What we deliberately do not model

**Memory types.** The standard taxonomy (working; semantic / episodic /
procedural) is a reasonable map — see
[memory-types.md](memory-types.md) for it applied to what ChatGPT users
actually experience — but mem-rfm scores none of its distinctions, and
that is a measured decision: a `kind` column routing procedural rows to
utility-weighted parameters showed no significant effect in any cell
(Δ hit@1 between −0.0053 and +0.0040) and was removed. What survives is
the *capture* finding: procedural knowledge transfers (build quirks,
pins, conventions), per-task episodic lessons don't (~6%) — with the C4
caveat that "transfers" is a claim about which content recurs, not
proven causal benefit. Type belongs in the capture policy, not the
ranking function; if it ever returns to scoring it should be a
**cold-start prior that evidence washes out** (the confidence shrink
already implements the handoff, and cold start is where priors measurably
matter: +42.6 points from an authored manual over MultiDoc2Dial's first
500 interactions) or a per-type **retention window** — never a permanent
weight. Working memory is out of scope on principle: it isn't a store,
it's the context window, and managing it is the harness's job.

**ACT-R machinery for modelling humans, not ranking documents:** partial
matching (embedding similarity is already graded and strictly more
expressive), retrieval latency (predicts how long a *person* takes),
activation noise (stochasticity would cost the determinism our
pre-registered methodology depends on — our `S` is a squash width, not
sampled noise), production compilation, finsts. One skipped mechanism is
genuinely interesting and remains unbuilt: **spreading activation**
(`Sji = S − ln(fan)`) as co-retrieval association, whose fan discount
would attack the "busy but not valuable" problem from the context side.

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
| condition-blind credit: 79% of the top ledger; the gate | `condition_value.py`, Tracks 10–16 | RESULTS.md, `hooks/test_conditions.py` |
| pooling beats per-agent stores | `star_eval.py`, `md2d_eval.py`, `flodial_eval.py`, `abcd_eval.py` | `results-star/`, `results-md2d/`, `results-flodial/` |
| experience out-ranks the authored manual | `abcd_manual.py` | RESULTS.md |
| staleness recovery under a procedure change | `abcd_staleness.py` | RESULTS.md |
| scoring is O(1): ~3.5µs/row (4.6µs in the retired Rust extension); hybrid-vs-exact max error ≤ 0.4 on synthetic histories | `throughput.py` | RESULTS.md |
| hybrid BM25, pruning, content-value signals — all failed | `hybrid_eval.py`, `prune_eval.py`, `signal_screen.py` | RESULTS.md |
| only the outcome axis earns its place on BEAM; Hebbian hurts | `ablation_eval.py` | `results-ablation/` |

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
