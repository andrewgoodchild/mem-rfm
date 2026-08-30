
## Amendment 13e — maintained-cutpoint bucketing: full bake-off

Amendment 13d showed maintained global cutpoints (form B) reproduce the
per-query quintile result while staying a row-local lookup, on one corpus with
one embedder and deltas around 0.005 hit@1. That is not enough to replace a
default scoring path. This is the replication.

**Matrix**: four corpora (STAR, ABCD, FloDial, MultiDoc2Dial) × two embedders
(MiniLM-L6-v2, Qwen3-Embedding-0.6B) × three arms (`actr`, `B_cuts_500`,
`quintile_rfm` as the upper bound B is trying to reach). Stream length fixed
at n=1500 throughout, as in Amendment 12b.

Two corpora are included as boundary cases with their limitations known in
advance: FloDial is at ceiling (hit@1 ≈ 0.98, no headroom for any prior to
show anything) and MultiDoc2Dial has ~3.5 calls per label (no history to build
on). Nulls there measure the benchmark, not the mechanism, and will be
reported as such rather than counted against either arm.

**Endpoint**: paired Δ hit@1 and hit@5, B vs actr, per cell.

**The bar, and it is deliberately demanding of the challenger**: B should be
**at or above `actr` in the clear majority of cells, across both embedders**,
before it is worth changing the default. A result that holds on MiniLM and
reverses on Qwen3 means we found an embedder-specific artifact, which is
exactly what the Amendment 2 repo-split caught for hybrid retrieval — and the
honest response would be to keep ACT-R and report the artifact.

## Amendment 17 (2026-08-30): Track 12 — the M-rule comparison, registered before the run

Unblocked by Track 22's positive causal panel (memory demonstrably helps
when the source is unreachable), so "does the M axis rank the helpful
memories well" is finally a meaningful question. track12_eval.py compares
ranking rules on LoCoMo's sequential-feedback protocol (where M is
genuinely earned), late-third hit@1 the adaptivity metric. The decisive
pair is EARNED-outcome M (rfm) vs a WRITE-TIME importance prior
(Generative Agents poignancy / Zep fact ratings, haiku 0-1 per memory,
cached); also per-token value and the genagents baseline.

Registered prediction:
  T12-P1 (earned beats write-time): rfm late hit@1 >= importance late
        hit@1. The project's thesis is that MEASURING what helped beats
        JUDGING importance at write time; if write-time importance ranks
        as well or better, the outcome loop's central premise is weaker
        than claimed. Reported with the delta; a tie (<0.005) is
        disclosed as a tie, not a win.
  T12-P2 (earned beats per-token): rfm >= pertoken late hit@1 — value
        density does not beat raw earned value for ranking.
Uses oracle evidence labels for the hit metric (LoCoMo standard); the
Track 22 causal panel motivates the question, it is not the label source.
