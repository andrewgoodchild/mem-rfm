# When agent memory helps, and when it doesn't

Everything here was measured. The benchmarks are public, per-question outputs
are committed under `bench-quality/results-*/`, and the experiments were
pre-registered — protocol, success bars and falsification criteria committed
to git before each run. See [methodology](methodology.md).

Reading the numbers: **hit@1** means the top-ranked result was correct,
**hit@5** means a correct result appeared in the top five, square brackets are
95% confidence intervals, and "points" are percentage points.

## The short version

Memory pays where **work recurs AND the environment forgets**. On
retrieval benchmarks with recurring evidence, outcome feedback reliably
helps. On live repository work with a frontier agent, the live program
ended (see "the terminal result" below) with the sharper finding: the
knowledge that recurs there is exactly the knowledge the agent never
needs to pay for — it re-derives or routes around it — while carrying
that knowledge costs measurable wall-clock. The repo is the memory.

The scoring prior's reliable jobs turned out to be **safety and
maintenance** rather than raw ranking quality: keeping a usage prior
from eating itself, retiring stale content, refusing unearned credit
(the condition gate), and making shared stores resistant to abuse.
Which of its two axes — recency/frequency, or outcome value — is doing
the work varies by corpus; ablating both is the one part of this nobody
else has published.

## Relevance is not value

The most transportable result in this repository, and it is about
retrieval in general, not this implementation. In our live pilots the
closest textual match to a new bug report in Sphinx's napoleon extension
was a stored lesson about a previous napoleon bug — injected on
similarity, never once confirmed useful. The era-pinned build
workaround, similar to no query in particular, earned its keep in nine
sessions of ten. (That sentence reports the outcome ledger. What those
credits were worth is the subject of "Use is not value" below — the
ledger turned out to measure something else.) That is the general pattern: per-bug content
surface-matches new bug reports but per-bug lessons don't transfer
(~6% measured), while the operational knowledge that helps session
after session matches nothing. So ranking injections by query
similarity *anti-selects* the memories that transfer — replayed against
outcome ground truth (the pilot-series section below), it dropped a
third of the confirmed-useful retrievals, while the outcome-ranked
prior retained 18 of 19 at 43% less injected context. Similarity
ranking was measured and rejected.

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

A caution, added 2026-08-27 after the causal tracks: "earned value" is
the outcome ledger's claim, and the "Use is not value" section below
shows what that ledger was actually counting — the workaround was
copied far more often than it was needed. What survives here is the
finding about *what recurs* (operational conditions, not per-task
lessons), not a proof of benefit.

Facts about *how to
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
that matters when you hand an agent one suggestion — on two datasets. On
ABCD, the maximal-recurrence workload, the edge was +0.012 hit@1
[95% CI +0.005, +0.020], growing to +0.020 [+0.007, +0.034] over the last
thousand calls as feedback accumulated. It **failed its pre-registered
replication bar on two others**. Cost was bounded everywhere it ran.

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
axes contributing roughly additively. The ACT-R half is doing real work there,
on equal terms.

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

## The live pilot series (August 2026)

Four paired-session runs on real sphinx/pytest bugs — headless Claude Code,
gold-test scoring, full injection/outcome traces committed under
`bench-quality/live-ab/` — turned the benchmark findings into a mechanism
story on live work:

- **Pilot 2**: with naive settings the ranking was *right* (the one
  operational gotcha earned helped-votes in 9 of 10 sessions and held rank
  1; per-bug lessons were demoted or sat inert) but the margin was
  negative — the machinery cost more than the reuse saved.
- **Pilot 3**: suppressing agent-volunteered saves (11 of 13 never earned
  an outcome) and inferring routine outcomes from the transcript removed
  the entire overhead — and exposed that Claude Code's own built-in memory
  had been quietly learning the same operational facts in both arms, a
  confound now handled by the clean-room protocol.
- **Selection eval** (offline, against pilot 2's outcome ground truth):
  prior top-3 plus a negative-value floor keeps 18 of 19 hits at 43% less
  injected context. Query-similarity ranking drops to 12–16 hits — it
  anti-selects transferable memories. Adopted and rejected respectively.
- **Pilot 4** (clean-room, seeded with the earned ledger): the first
  memory arm to beat control — wall −47..−130s, tokens below control, 17
  of 20 outcome-loop closures inferred free from the transcript, zero
  injection distractors, and the miner closed formation→ratification→
  injection→earned-value inside a single run.

The frozen stack's held-out revalidation is registered in
`bench-quality/live-ab/REVALIDATION.md` before its runs and scored in
RESULTS.md: Tracks 1–2 (pytest cold start, sphinx stale-era seed) went
5 PASS / 2 NOT TRIGGERED / 0 FAIL; Track 3 (xarray, a never-seen repo)
delivered the series' first registered FAIL and its most instructive
trace — see the cost accounting below.

### The registered FAIL, in detail

On `pydata/xarray` — a repository no pilot had touched — a registered
bound said the machinery would cost no more than +10% wall and +15%
output tokens against a no-memory control. Phase A came in at **+32.0%
wall and +35.5% tokens**, with the series' only resolution gap: control
resolved 11 of 11, the memory arm 7 of 11. It is scored FAIL and stays
that way.

What the trace rules out:

- **The memories in context.** Three of the four failed sessions ran
  with *empty injections* — no memory content reached the model — and
  0–2 memory tool calls each. Whatever cost those sessions, the
  retrieved memories were not in the room.
- **The attachment tax.** It was the leading hypothesis, so we
  registered an ablation (Track 4) while the failure stood unexplained,
  with a decision rule written in advance that could clear it. It did:
  an idle attached server costs +189 tokens of context, +1.0% wall, and
  no resolution difference. Excluded.

What we found afterwards, which is a defect in the instrument rather
than an explanation of the gap: two of the eight memories that run
mined were `python - <<'EOF'` heredoc artifacts — the correction miner
capturing a bare interpreter's head line, which renders as advice with
no reusable trigger. Between them they took **29 accesses and earned
zero positive outcomes**: one had to be dragged to −0.23 through three
negative outcomes, the other sat at 0.0 after 16 accesses, occupying an
injection slot every time. The other six all ended at value 1.0. The
miner has since been guarded (`informative_head`) and refuses both
artifacts while keeping all six earners — verified by replaying the
recorded transcripts.

So the honest state is: the bound broke, the memories didn't cause it,
the platform cost didn't cause it, and a quarter of the store was junk
the current miner would never create. That leaves variance at n=11, or
something we have not identified. A registered replication on the
repaired stack would settle which — and if it is ever run, this result
stays in the table beside it, because a bound that broke once on a
defective instrument is a fact about both.

### When the harness already ships memory

Claude Code, Cursor, Devin and Windsurf all ship native memory — no
attachment tax, better transcript access, the default slot. We measured
the overlap directly: in our own live pilots, the harness's built-in
memory silently captured the same operational lesson as our store, in
both arms. Running mem-rfm alongside a native memory adds cost without a
measured marginal benefit. What survives the overlap is what native
memory doesn't do: an outcome ledger with signed negatives, auditable
staleness demotion, a store that travels across harnesses.

### What the live program cost

196 headless Claude Code sessions and ~10 hours of agent wall clock, on
the order of a few million tokens end to end. Phase sizes of n=10–11
are a budget bound, not a choice — treat the live results as mechanism
evidence, not effect-size estimates. The causal-turn continuation
(Tracks 10–17, per-track counts in RESULTS.md) added roughly another
135 registered sessions under the same discipline.

## Use is not value: the causal turn (August 2026)

The pilot series established that the ranking *behaves*. The registered
tracks that followed asked the harder question — does having the store
change what the agent achieves? — and the answers reshaped this
document. Full entries in `bench-quality/RESULTS.md` (Tracks 10–17).

- **A store worth keeping did nothing.** Five human-ratified memories,
  injected in 13 of 13 held-out sessions: no effect in either
  direction (Track 10, corrected reading).
- **The best memory in the corpus did nothing, at home.** The era-pin
  workaround — value 0.998, 17 outcomes, the top earner ever — was
  delivered token-matched in four content forms on the very tasks that
  earned its ledger (40 sessions). It never beat the no-memory arm.
  Forensics explained why the ledger existed at all: the failure it
  guards against fired in 2 of 30 pilot memory-arm sessions, and 79% of
  the commands that "earned" its outcomes ran when nothing was at risk.
  Agents copied the suggested command; the loop credited every success.
  **Use is not value** — the sequel to "relevance is not value", and
  measured the same way.
- **Form drives copying, not results.** The corpus split (memories with
  a verbatim command average 3.2 outcomes, prose 0.5) reproduced
  causally as pure quotability: the command arm acted on its memory in
  4 of 8 sessions, the prose arm in 0 of 8 — with no difference in
  events-to-green or wall between them.
- **A weak model paid for a strong model's memory.** On haiku the same
  memory lost every decided pair (0 of 5, one-sided sign p = 0.031) at
  +27.6% wall — the token-tax result from the 2026 literature
  reproduced in our own harness, and the strong-to-weak transfer claim
  refuted in our setting.
- **The nulls are measured, not noise-blind.** A 20-repetition
  yardstick put within-condition spread at SD 0.5 events for the
  frontier model — the observed ties are real ties at ~1-event
  resolution — and SD 3.5 for haiku, which is why only sign
  consistency counts at that tier.

What changed because of this, beyond the record: **outcomes are now
condition-conditioned.** Every memory carries the condition class its
own text names; the session-end loop observes which classes actually
fired; a positive outcome only lands when the memory's condition was
live, while negatives always land (bad advice is bad advice
regardless). Under that rule, the 17-outcome ledger above could not
have been earned. Structured extraction was separately validated as
mechanically free — recall held, leakage fell — and as no substitute
for storage judgment.

### The terminal result (late August 2026)

The remaining hypotheses were then run to ground, and the program
closed with its clearest experiment.

**Formation-tier matching died at its gate** (Track 17): even the weak
model's own struggles do not condense into nameable recurring
conditions — its friction is per-task difficulty, the class that
doesn't transfer. **The manual formation gate was then removed
entirely** and replaced with a continuously running sweep — LLM
extraction per transcript, near-duplicates merged into a sightings
count instead of new rows, a two-sighting quarantine instead of human
review, an LLM outcome judge asked the conditioned question, a capped
store (Tracks 18/18b). Replayed over the very transcripts that built
the fossil ledger, the ungated stack captured the right fact,
consolidated 22 paraphrases into 2 rows, kept junk at 0%, and awarded
the fossil zero of the 17 credits the old loop had given it.

**Then the decisive test** (Track 19): a pool rebuilt from our own
validation exclusions so that the environment condition provably
blocks verification — the friction cannot be optional — with the full
ungated lifecycle live in one arm. Every mechanical stage worked: the
workaround memory formed itself, consolidated to one row with 26
sightings, promoted past quarantine, and was delivered in 19 of 20
sessions, ending at value 0.00 because nothing ever proved it helped.
It didn't help: the agent saw the blocking condition in **one control
session out of twenty** — it verified around it with repro scripts and
non-app tests, the fifth consecutive experiment in which a frontier
agent routed around friction rather than paying it, this time on a
workload engineered to prevent exactly that. Necessity was a coin flip
(8 wins, 9 losses); and carrying the memory cost **+25% wall-clock,
slower on 14 of 20 pairs (p = 0.03)** — a delivered memory about a
condition the session never meets is not neutral, it is an invitation
to investigate a problem you don't have.

**The finding this program ends on:** for a frontier agent doing
repository work, the knowledge that recurs is precisely the knowledge
it never needs to pay for — re-derived cheaply, routed around, or
never encountered — while carrying it has measurable cost. The failure
was never formation, gating, similarity, delivery, or the value
instrument; each was fixed or ruled out in turn, and the last
experiment ran with all of them working. What failed is the premise
that this workload class leaves anything for memory to save. Memory
pays where the environment forgets. A repository, read by an agent
strong enough to read it, never forgets — and the venues where the
environment does forget (user preferences and working style,
cross-repo and organizational knowledge, weak agents on high-friction
work, short sessions with real boundaries) are where everything built
here — the honest ledger above all — still waits to be tested.

## The cost of memory, itemized

Three separable costs emerged from the pilot and revalidation series,
and they behave differently:

1. **Machinery turns** — saves, feedback, reading injections. Measured,
   and removable: suppressing volunteered saves and inferring routine
   outcomes took it from +45s/+87% tokens per session (pilot 2) to below
   control (pilot 4, pytest Phase A −7.6%/−12.4%).
2. **Cold-start burden** — an empty store costs before it can pay.
   Sometimes near-zero (pytest Phase A), sometimes not: xarray Phase A
   broke its registered bound at +32% wall with a 7/11-vs-11/11
   resolution gap. Crucially, the trace acquits the memories themselves:
   three of four failures ran with empty injections and 0–2 memory
   calls.
3. **The attachment tax** — the cost of the memory server merely being
   attached, before the first memory is saved. MEASURED (Track 4,
   registered 5db11b0): a near-perfect constant +189 input tokens of
   first-turn context per session (9 of 10 pairs exactly; paired mean
   +218, 95% CI [+152, +284]), ~0.9% of baseline — with wall at +1.0%
   and resolution identical, i.e. context-cost-only at this scale. The
   size is the insight: an order of magnitude below the schemas' full
   text, because Claude Code defers MCP schemas and loads them on
   demand; the resident cost is the deferred-tool stub. The tax is
   therefore harness-dependent — a harness without schema deferral pays
   the schemas' full text. Consequence, per the registered decision
   rule: Track 3's cold-start gap attributes to variance-or-unknown,
   not the tax, and pilot 4's win loses its last unmeasured confound.

Until 3 is priced, the break-even law should be read as: memory must
recoup machinery turns (near zero now), plus its share of the
attachment tax, plus the cold-start investment — out of recurrence.

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
- **Similarity-ranked injection** — anti-selects the memories that
  transfer; the outcome prior out-selects semantic relevance on live
  telemetry (`bench-quality/live-ab/eval_selection.py`).
- **One published number that was wrong**, caught in pre-publication review
  and corrected in place, with the error disclosed. See "Corrections" in
  RESULTS.md.
