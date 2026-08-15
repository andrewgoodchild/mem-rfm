# Where the model comes from

mem-rfm doesn't invent a scoring function. It borrows two well-established
models — one from marketing analytics, one from cognitive science — and
composes them in a way that had to be settled by experiment.

## RFM: the name, and the idea behind it

**RFM** is a customer-value model from direct marketing and database
analytics, in use since the 1990s. Faced with a customer list too large to
treat individually, marketers score each customer on three axes:

| axis | question it answers |
|---|---|
| **R**ecency | how recently did they last transact? |
| **F**requency | how often do they transact? |
| **M**onetary | how much value did those transactions produce? |

The insight that made RFM durable is that recency and frequency are cheap,
behavioural, and available for free from transaction logs — but they only
tell you about *engagement*. Without the monetary axis you cannot tell a
valuable customer from a busy one. A customer who orders constantly and
returns everything is not a good customer, and no amount of recency and
frequency data will say so.

Agent memory has exactly this shape. Retrieval logs give you recency and
frequency for free: which memories have been pulled, how often, how lately.
But they cannot distinguish a memory that keeps getting retrieved *because
it is useful* from one that keeps getting retrieved because it happens to sit
near a common query and wastes the agent's time every time.

So mem-rfm keeps the structure and swaps the third axis for its analog:

| RFM in marketing | mem-rfm |
|---|---|
| Recency of purchase | recency of retrieval |
| Frequency of purchase | frequency of retrieval |
| **Monetary** value of purchases | **outcome value**: did this memory help when retrieved? |

That third axis is the whole point of the project. It is also the axis that
no other shipped memory system maintains — see the comparison in the README.

We measured what happens without it: a memory store ranked by recency and
frequency alone **collapses** under sequential load. Frequently-retrieved
memories get retrieved more, which makes them more frequent, and retrieval
quality falls to NDCG ≈ 0.01 in ablations. The value axis is what breaks the
rich-get-richer loop. The marketing analogy holds right down to the failure
mode.

## ACT-R: recency and frequency as one number

The obvious way to build R and F is two counters — a timestamp and a count —
combined by some hand-picked weighting. We don't, because cognitive science
solved this more carefully and the solution is cheaper.

**ACT-R** (Adaptive Control of Thought—Rational; Anderson & Lebiere, 1998) is
a cognitive architecture: a computational model of human cognition, built to
predict what people actually remember and how fast. Its declarative memory
module assigns each chunk a **base-level activation** predicting how
retrievable it is:

```
B = ln( Σᵢ tᵢ^−d )
```

where `tᵢ` is the time since the *i*-th time that memory was used, and `d` is
a decay rate (ACT-R's conventional 0.5, which is our default). This is a
model of human forgetting fitted to human recall data, and it is doing
something subtle: recency and frequency are not two signals being blended,
they are **one quantity**. Each past use contributes a term that decays with
age. Many old uses can equal a few recent ones. Frequency is just the sum;
recency is just which terms haven't decayed yet.

That is a better model than any weighting we would have invented, and it
comes with decades of empirical fit to how memory actually behaves — the
practice effect (repeated exposure helps, with diminishing returns), the
spacing effect, and power-law forgetting all fall out of the same equation.

### Making it O(1)

Computed literally, `B` requires walking a memory's entire access history on
every score — unusable for ranking.

**Petrov (2006)** gives a hybrid approximation: keep the *k* most recent
access times exactly, and replace the long tail with a closed form that
depends only on the total count and the memory's age. We use k = 2, which the
schema already stores — `last_access`, plus `bla_cache` holding the
second-most-recent — alongside `access_count` and `created_at`.

The result: **scoring reads one row and never touches the access log.**
Measured at ~4.6µs per row whether a memory has 20 accesses or 200, with mean
approximation error of 0.049 activation units against the exact computation.

## The value axis — which is also ACT-R

ACT-R has **two** memory systems, and we ended up implementing both without
initially noticing. Declarative memory holds chunks retrieved by the
base-level activation above. **Procedural** memory holds production rules,
selected by a learned **utility** updated from reward:

```
U ← U + α·(R − U)
```

Expand that and it is `U ← α·R + (1−α)·U` — algebraically identical to our
outcome EWMA `v ← 0.3·outcome + 0.7·v`, with α = λ. We reinvented ACT-R's
utility learning rule.

That reframes the whole design. mem-rfm is not "ACT-R plus a marketing model
bolted on"; it is ACT-R's declarative retrieval *and* ACT-R's procedural
utility learning, in one score. It also explains our central empirical
finding — that memory pays for **procedural** knowledge (build quirks,
conventions, environment facts) and not for episodic per-task lessons —
because that is what the architecture predicts: utility learning is the
procedural module's mechanism. And it explains why the July 2026
mechanism-level review names "activation with **action utility**" as the
bundle not yet migrated to language agents: utility *is* the procedural half.

The `kind` column ([api](api.md)) makes the split explicit, scoring
procedural rows with utility-weighted parameters.

Outcome feedback is an exponentially-weighted moving average in [−1, 1]:

```
v ← 0.3·outcome + 0.7·v        (the first outcome initialises v)
```

with a confidence shrink applied when the value is used:

```
v_effective = v · n / (n + 3)
```

so that a memory with one lucky success doesn't outrank one with a long
positive record. Both constants are configurable (`lambda`, `shrink_k`).

The combined score is a weighted sum of the two axes, with activation passed
through ACT-R's own retrieval-probability curve to put it on [0, 1]:

```
rfm_score = 0.7 · P(B) + 0.3 · value₀₁
```

## Composing with similarity: the part that needed an experiment

The obvious composition is to multiply. It fails, and understanding why
shaped the design.

`similarity × rfm_score` degrades retrieval, and — counter-intuitively —
degrades it *worse* as your retriever gets better: −0.05 NDCG under a weak
embedder, −0.32 under a strong one. The cause is dynamic range. Activation
varies by roughly 6× across a store, while a well-calibrated embedder puts
relevant and irrelevant documents within a few percent of each other. The
usage prior simply overwhelms the similarity signal it was meant to adjust.

The fix is to bound how far the prior can move anything:

```
rfm_prior(id) = (1 − β) + β · rfm_score(id)        β = 0.3
final_score   = max(similarity, 0) × rfm_prior(id)
```

With β = 0.3 the multiplier lives in [0.7, 1.0]: usage history can demote a
memory by at most 30% and can never promote one above its own similarity.
It is a tiebreaker among plausible candidates, not a ranking in its own right.

β was frozen by a pre-registered protocol — candidates, dev/test split,
selection rule and falsification criteria all committed to git before any
number existed — and then evaluated once. See
[methodology](methodology.md) for how that was run and what it cost.

Two consequences of the bound worth knowing, one intended and one not:

- **Intended:** the value axis can never wreck a good retriever. Measured cost
  against similarity-only was within noise on every benchmark and embedder.
- **Unintended:** it makes the ranking almost impossible to weaponise. An
  attacker trying to bury a rival memory can move it by at most 30%, which is
  less than the similarity gap they would need to close. Censorship attacks
  failed outright for exactly this reason — see [team-memory](team-memory.md).

The same bound is also why the forgetting effect is modest: β trades
forgetting power for rank safety. Raise it if retiring stale content matters
more to you than stability.

## Sources

Every equation is cited in the code that implements it (`src/math.rs`).

- Anderson, J. R. & Lebiere, C. (1998). *The Atomic Components of Thought* —
  ACT-R, base-level learning equation.
- Petrov, A. A. (2006). *Computationally efficient approximation of the
  base-level learning equation in ACT-R* — the hybrid k-term approximation.
- Hughes, A. M. (1994). *Strategic Database Marketing* — RFM as customer
  scoring.
- Park, J. S. et al. (2023). *Generative Agents* — implemented as a
  comparison condition in the benchmarks, not as a dependency.
