# When agent memory helps, and when it doesn't

Everything here was measured. The benchmarks are public, per-question outputs
are committed under `bench-quality/results-*/`, and the experiments were
pre-registered — protocol, success bars and falsification criteria committed
to git before each run. See [methodology](methodology.md).

Reading the numbers: **hit@1** means the top-ranked result was correct,
**hit@5** means a correct result appeared in the top five, square brackets are
95% confidence intervals, and "points" are percentage points.

## The short version

Memory pays where **work recurs**, and the effect is largest when a *team*
shares one store. It does not pay where work is episodic — and on scattered
bug-fixing our own system measured itself as mildly counterproductive.

The scoring prior's reliable jobs turned out to be **safety and maintenance**
rather than raw ranking quality: keeping a usage prior from eating itself,
retiring stale content, and making shared stores resistant to abuse. Which of
its two axes — recency/frequency, or outcome value — is doing the work varies
by corpus; ablating both is the one part of this nobody else has published.

## Where memory helps

### Recurring work

On sequential benchmarks, outcome feedback added **0.02–0.08 NDCG** on
questions whose evidence had already served an earlier question — confidence
intervals excluding zero, across three different embedding models, on both
conversational and code corpora. Where evidence never recurs, feedback cannot
help; bounded properly, it also doesn't hurt.

### Operational knowledge, specifically

In 70 live Claude Code sessions fixing real pytest and sphinx bugs, exactly
one memory earned sustained positive value across repeated use: an
environment gotcha recording which pinned dependencies a checkout needs.

Not a code lesson. Not an algorithm insight. A build quirk.

That is the most practically useful finding in this repo. Facts about *how to
work here* — build quirks, dependency pins, project conventions, user
preferences — recur by their nature, and are exactly what an agent otherwise
rediscovers every session.

### Retiring stale facts

On LongMemEval's knowledge-update tasks, preference for the updated fact rose
from **0.43 to 0.66** with no loss of fresh-fact recall.

In a support-domain simulation, after a procedure changed, similarity-only
retrieval was still recommending the dead procedure 1,500 calls later —
hit@1 0.20 against 0.76 before the change — because a stale memory stays
semantically perfect forever. With outcome feedback driving demotion the
recovery curve beat it in every bin, ending at **0.56 versus 0.20**. *(One
dataset, exploratory, never pre-registered — treat as indicative.)*

### Keeping a usage prior from collapsing

Rank by recency and frequency alone and retrieval **falls apart**:
frequently-retrieved memories get retrieved more, which makes them more
frequent, and quality collapses to NDCG ≈ 0.01 in ablations.

Negative outcome feedback is what breaks the loop. If you build any
usage-based ranking, you need this or something like it — not for the gains,
but to stop the mechanism eating itself.

## Where memory does not help

### Per-task lessons mostly don't transfer

In the live A/B the agent saved 17 genuinely good debugging lessons, then
judged retrieved ones irrelevant bug after bug: **15 of 16 recorded outcomes
were negative.** The system measured its own workload's lesson-transfer rate
at roughly **6%**, with no oracle telling it so.

That is the mechanism working correctly on a workload with little worth
remembering. SWE-bench-style tasks deliberately scatter across unrelated
subsystems, so there is almost nothing for a lesson from one to say about the
next. Published work has since reported the same direction: low-level traces
tend to produce *negative* transfer, and only meta-knowledge moves.

### On hard tasks under a budget, memory is a mild tax

Across 27 paired real-bug tasks: control solved **25/27**, the memory arm
**23/27**, with both disagreements going to control.

Stated honestly, that is consistent with noise (McNemar p = 0.5) — but it is
certainly not a win, and the mechanism is plausible: retrieval calls and
irrelevant lessons consume budget that hard tasks need. Overhead was 8–22
seconds per session, dominated by embedding-model startup — irrelevant in a
30-minute interactive session, material in a 90-second headless one.

**Independently replicated.** An ETH Zurich study
([arXiv:2602.11988](https://arxiv.org/abs/2602.11988)) tested context files
across SWE-Bench Lite and 138 tasks in 12 repositories with four models:
LLM-generated context files **reduced** success by ~3% while raising cost
over 20%; developer-written ones helped only ~4%, still costing up to 19%
more. Value appeared only when repository documentation was stripped — the
benefit was redundant pre-caching. Different group, different tasks, same
conclusion as the A/B below. Our negative result was not a quirk of our
setup.

**What this comparison was and wasn't.** The control arm had *no memory*, not
Claude Code's built-in memory. We have never run mem-rfm head-to-head against
a built-in memory feature, so nothing here supports a claim about relative
performance against one. What it supports is narrower and still useful: for
single-agent coding work, we could not measure a benefit from adding this
memory at all. The large, replicated effects in this project are all in
shared/multi-agent settings ([team memory](team-memory.md)).

### A usage prior doesn't beat a good retriever at one-shot relevance

The obvious version of this idea — multiply similarity by the usage score —
was **falsified outright**: −0.32 NDCG against a strong embedder, in a
pre-registered robustness check. The bounded form that ships reaches parity,
not superiority.

If your workload is "answer one question about a big pile of documents", use
similarity search and skip all of this.

### The top-slot gain is real but narrow

Outcome ranking beat plain similarity for the *first* result — the position
that matters when you hand an agent one suggestion — on two datasets. It
**failed its pre-registered replication bar on two others**. Cost was bounded
everywhere it ran.

Treat rank-1 improvement as a possible bonus, not the reason to deploy.

## Which parts of the system actually earn their place

A mechanism can be **implemented** (the code runs), **connected** (something
reads its output), and **earn its place** (removing it makes results worse).
Most memory systems claim the first. We had never measured the third about
our own components, so we ablated each one through the shipped engine.

### On BEAM: only the outcome axis

Amendment 12, 355 questions per arm:

| removing | Δ NDCG@10 | verdict |
|---|---|---|
| **outcome feedback** | **−0.0055** [−0.0094, −0.0018] | **earns its place** |
| ACT-R activation | +0.0020 [−0.0022, +0.0061] | within noise |
| the confidence shrink | +0.0031 [−0.0040, +0.0096] | within noise |
| decay rate (→0, or →0.9) | +0.0001 / +0.0021 | within noise |

Splitting by whether a question's evidence had already served an earlier one
sharpens it, because pooling dilutes the very effect the ablation looks for:

| arm | recurring (n=108) | fresh (n=247) |
|---|---|---|
| removing the whole prior | **−0.0072** [−0.0141,−0.0013] | **+0.0028** [+0.0002,+0.0064] |
| removing outcome feedback | **−0.0095** [−0.0171,−0.0026] | −0.0037 (n.s.) |
| removing activation | +0.0020 (n.s.) | +0.0021 (n.s.) |

The prior earns its place exactly where the theory predicts and is mildly
harmful where it predicts it shouldn't help — a benefit on re-used evidence,
a smaller penalty on evidence seen once, both significant. That refines the
published "cost ≈ 0 versus similarity" result: the zero is a **net of two
real and opposite effects**, not an absence of them.

But on BEAM the benefit is entirely the outcome axis. Activation stays within
noise in *both* strata, so the null is not an artifact of averaging over a
hostile subset.

### Across corpora: it depends on the corpus

That looked like it might generalise, so Amendment 12b repeated the ablation
on four corpora with stream length fixed at 1,500 calls, leaving recurrence
per label as the only varying quantity. The registered prediction was that
activation's contribution would rise with recurrence, or be flat. **Neither
happened, and the correction favours the activation axis:**

| corpus | recurrence/label | no_value | no_activation | no_prior |
|---|---|---|---|---|
| FloDial | 150 | −0.0007 | −0.0007 | −0.0020 |
| **STAR** | 71 | **−0.0067\*** | **−0.0067\*** | **−0.0140\*** |
| ABCD | 27 | −0.0080 | −0.0040 | −0.0020 |
| MultiDoc2Dial | 3.5 | +0.0013 | +0.0020 | +0.0073 |

*(Δ hit@1; \* = CI excludes zero.)*

On STAR, **removing activation costs exactly as much as removing outcome
feedback**, and removing the prior entirely costs more than either — the two
axes contributing roughly additively. The ACT-R half is load-bearing there on
equal terms.

The shape is a **sweet spot, not a gradient**, and the two nulls at the ends
have different causes. FloDial has the most recurrence but a 0.984 hit@1
baseline, so there is no headroom for any prior to demonstrate anything — a
null there measures the benchmark, not the mechanism. MultiDoc2Dial has 3.5
calls per label and no history to build on, and there the prior is a small net
cost, matching BEAM's fresh-evidence stratum exactly. The prior needs **both**
enough recurrence to differentiate candidates **and** enough error left by the
retriever to have room to help.

### What we actually believe now

**Each axis earns its place on some corpora and not others.** That is duller
than either "ACT-R is the foundation" or "only outcomes matter", and it is
what the evidence supports.

Worth recording that we published the second of those before the gradient run
existed — the BEAM result alone permitted reading recency and frequency as
simply the wrong prior for agent memory, and that reading is now withdrawn.

Everything still points the same way about *magnitude*, though: ranking by
activation alone collapses retrieval to NDCG ≈ 0.01, raising the activation
axis's influence costs up to −0.063, and the bounded prior reaches parity
rather than superiority. Whichever half is doing the work on a given corpus,
the prior remains a small, deliberately bounded adjustment to similarity
search.

### Does the value axis work on real outcomes, not just oracle labels?

Every result above uses oracle outcomes — a memory "helped" if its label
matched — which our [methodology](methodology.md) flags as the largest
standing caveat. Amendment 14 tested the machinery against 89 tasks × ~586
**test-verified** binary trials, where each task's empirical success rate is
ground truth.

**It transfers.** Effective value recovers true utility ordering at Spearman
**0.83** after 25 observations. The mechanism was designed and tuned entirely
against oracle labels and still ranks real utility correctly.

Two things we learned that we had not named before:

- **λ trades adaptivity against calibration.** A fixed-λ EWMA has a fixed
  effective window (~1/λ samples), so it never converges — it tracks recent
  noise forever. At our λ=0.3 the estimate is permanently a ~3-sample
  average. That is *why* staleness detection works (you must forget the old
  value fast) and why calibration error *grows* with more evidence
  (0.148 → 0.187 by n=50, while λ=0.1 halves to 0.098). Our default is tuned
  for adaptivity, and that is a choice rather than an oversight — but it was
  an unexamined one.
- **The confidence shrink cannot reorder equally-observed memories.** It
  multiplies by `n/(n+k)`, a monotone transform at fixed n, so ranking is
  identical for every `shrink_k`. It only matters when comparing memories
  with different outcome counts.

### Simpler formulas, tested and rejected

The scoring prior could be much simpler than ACT-R's base-level activation, so
we tried: a weighted sum of separate recency and frequency terms; the classical
marketing RFM formula as rank buckets (quintiles, deciles, continuous
percentiles, and a row-local maintained-cutpoint form); each axis alone; and
re-weighting the two axes by memory type.

**None beat ACT-R.** Across four corpora and two embedders it is never beaten
and wins significantly on two. The separate-axis weighted sum loses by 0.0107
hit@1, which is the cleanest single piece of evidence that *unifying* recency
and frequency into one quantity — rather than scoring them independently — is
where the value is.

Two process notes, because they matter more than the result. We first ran this
comparison on **one corpus** and published the opposite conclusion; replication
reversed it, and it was the same single-corpus failure this repository had
already caught once for BM25 hybrid fusion. And rank-bucket granularity turned
out to have an interior optimum around five buckets — finer is not better, so
marketing's decile convention would have been worse here than quintiles.

### Two mechanisms we don't have, tested by adding them

**Hebbian co-retrieval association hurt by 3.2 NDCG points.** It reinforces
whatever was already retrieved — the rich-get-richer dynamic the outcome axis
exists to break — and ACT-R's `ln(fan)` discount did not save it.
**Interleaved consolidation had no detectable effect.** Neither earns
extension surface on this evidence.

## The takeaway

Agent memory is not a lesson journal. It is an **operational profile** that
earns its rank through outcomes.

Capture environment quirks, conventions, decisions and preferences. Let
per-task trivia fade. Bound how far any of it can override relevance. And if
the work genuinely recurs across several agents, share the store — that is
where the effect stops being marginal.

One caution against over-reading any of the above: the prior only has room to
help where a workload both **repeats** and leaves the retriever making
mistakes. On a corpus with 150 repetitions per label but a 0.98 baseline,
nothing we could add or remove moved the number at all.

## What died along the way

Reported at the same length as the successes, in
`bench-quality/RESULTS.md`:

- **BM25 hybrid fusion** — a dev-set win on two repositories reversed on six
  held-out ones. The repo split caught the overfit.
- **Confident-negative pruning** — cannot be simultaneously retrieval-safe and
  potent at forgetting.
- **Three content-based value signals** (semantic richness, diversity,
  demand-recurrence) — all weak or benchmark-dependent as priors.
- **The rank-1 replication bar** — passed on one of three datasets.
- **Six collusion defences** — see [team-memory](team-memory.md).
- **One published number that was wrong**, caught in pre-publication review
  and corrected in place, with the error disclosed. See "Corrections" in
  RESULTS.md.
