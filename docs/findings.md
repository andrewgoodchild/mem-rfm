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

The value axis's reliable jobs turned out to be **safety and maintenance**
rather than raw ranking quality: keeping a usage prior from eating itself,
retiring stale content, and making shared stores resistant to abuse.

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
our own components, so we ablated each one through the shipped extension
(Amendment 12, BEAM dev, 355 questions per arm):

| removing | Δ NDCG@10 | verdict |
|---|---|---|
| **outcome feedback** | **−0.0055** [−0.0094, −0.0018] | **earns its place** |
| ACT-R activation | +0.0020 [−0.0022, +0.0061] | within noise |
| the confidence shrink | +0.0031 [−0.0040, +0.0096] | within noise |
| decay rate (→0, or →0.9) | +0.0001 / +0.0021 | within noise |

**Only the outcome axis earns its place**, and that is an uncomfortable
result about a project with R and F in its name.

It is also, on reflection, the same result we have been getting all along
from three other directions: ranking by activation *alone* collapses
retrieval to NDCG ≈ 0.01; *increasing* the activation axis's influence costs
up to −0.063 (Amendment 11); and the bounded prior reaches parity with
similarity-only rather than beating it. Every measurement has said the usage
prior is a small, carefully-bounded adjustment — the ablation just says which
half of it is doing the work.

The likely reason, in Belady's terms ([theory](theory.md)): activation
predicts *whether an item will be used again*, and outcome value predicts
*whether using it will be worth anything*. BEAM asks probing questions about
a conversation, where re-use is weak (only 108 of 355 questions revisit
earlier evidence) but usefulness is informative. The recency/frequency axes
may simply be answering a question this benchmark does not ask.

**Stratifying by recurrence sharpens this considerably.** BEAM labels whether
a question's evidence already served an earlier one. Split on that:

| arm | recurring (n=108) | fresh (n=247) |
|---|---|---|
| removing the whole prior | **−0.0072** [−0.0141,−0.0013] | **+0.0028** [+0.0002,+0.0064] |
| removing outcome feedback | **−0.0095** [−0.0171,−0.0026] | −0.0037 (n.s.) |
| removing activation | +0.0020 (n.s.) | +0.0021 (n.s.) |

The prior **earns its place exactly where the theory predicts and is mildly
harmful where it predicts it shouldn't help** — a benefit on re-used evidence,
a smaller penalty on evidence seen once, both significant. That is the
recurrence finding appearing *within* a single benchmark, and it refines the
published "cost ≈ 0 vs similarity" result: that zero is a net of two real and
opposite effects.

And the benefit is **entirely the outcome axis**. Removing value costs nearly
double on the recurring slice; removing activation stays within noise in
*both* strata. So the null is not an artifact of averaging over a hostile
subset — even where re-use demonstrably happens, recency and frequency add
nothing detectable.

The honest status is **unproven, not disproven** — one benchmark, one
embedder, 108 recurring questions. But it now survives the most obvious
defence of it, which is worth more than the pooled number was.

Two mechanisms mem-rfm does *not* have were also tested, by adding them:
**Hebbian co-retrieval association hurt by 3.2 points** (it reinforces
whatever was already retrieved — the rich-get-richer dynamic the outcome axis
exists to break, and ACT-R's `ln(fan)` discount did not save it), and
**interleaved consolidation had no effect**. Neither earns a place in the
extension on this evidence.

## The takeaway

Agent memory is not a lesson journal. It is an **operational profile** that
earns its rank through outcomes.

Capture environment quirks, conventions, decisions and preferences. Let
per-task trivia fade. Bound how far any of it can override relevance. And if
the work genuinely recurs across several agents, share the store — that is
where the effect stops being marginal.

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
