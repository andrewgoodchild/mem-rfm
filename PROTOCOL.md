# Pre-registered protocol: bounded composition for rfm_score

**Status: registered BEFORE any composition experiment has run.** The commit
introducing this file predates every result it governs; per-question outputs
for all runs are committed for audit. Prior findings that motivated this
protocol (and are NOT evidence for it): under a strong retriever
(Qwen3-Embedding-0.6B) the default composition `sim × rfm_score` costs
−0.32/−0.15 NDCG vs similarity-only on LoCoMo/BEAM (vs −0.05/−0.06 under
MiniLM), while the value axis's isolated contribution is stable
(+0.17..+0.35). Diagnosis: the activation prior's ~6× multiplicative dynamic
range overwhelms well-calibrated similarities. Hypothesis: bounding the
prior's influence retains the adaptivity while eliminating the cost.

## Candidates (declared now; no others will be reported as primary)

For query embedding q, candidate ids C, similarity s(i), and p(i) = rfm_score(i):

1. **beta-blend**: score = max(s,0) × ((1−β) + β·p), β ∈ {0.1, 0.2, 0.3, 0.5}
2. **rrf**: score = 1/(60 + rank_s(i)) + 1/(60 + rank_p(i))  (standard k=60)
3. **shortlist**: top-N by s alone with N = 3k; within the shortlist order by
   p descending; below the shortlist order by s. (k = 10 throughout.)

Every candidate runs in two variants: feedback ON (accesses + oracle
evidence-hit outcomes, as in all prior sequential evals) and feedback OFF
(accesses only) — the ON−OFF paired delta is the adaptivity measure.

## Development set

BEAM 128K tier only (20 conversations, 355 scored questions), under BOTH
embedders already in use (MiniLM-L6-v2, Qwen3-Embedding-0.6B), cached
embeddings. LoCoMo, LongMemEval (incl. knowledge-update), and SWE-Bench-CL
are test sets and will not be touched until one configuration is frozen.

## Selection rule (applied to dev results, in this order)

1. **Feasibility**: mean paired NDCG@10 cost vs `sim` on overlap=False
   questions ≤ 0.010 under EACH embedder (95% CI midpoint).
2. Among feasible candidates: **maximize adaptivity** = mean over the two
   embedders of the paired ON−OFF NDCG@10 delta on overlap=True questions.
3. Tie-break (within 0.005 adaptivity): prefer fewer tunables:
   rrf > shortlist > beta-blend.
4. **One global configuration.** No per-benchmark or per-embedder settings.
   Full sweep curves are reported regardless of winner.

## Test evaluation (one shot, frozen configuration)

Primary endpoint: cost ≤ 0.010 vs `sim` on LoCoMo overlap=False, per
embedder (MiniLM, Qwen3). Secondary endpoints (reported with CIs, no
re-tuning regardless of outcome): (a) LoCoMo adaptivity (ON−OFF, overlap=True)
CI excluding 0; (b) knowledge-update update-preference delta (stale-penalty
protocol, MiniLM) > 0; (c) SWE-Bench-CL cost vs sim not significant;
(d) generalization to an embedder unseen during development —
**BAAI/bge-m3** — on LoCoMo and SWE-Bench-CL only (compute budget; declared
now). If any endpoint fails, the failure is published alongside the rest.

## What would falsify the hypothesis

No candidate passes feasibility on dev; or the frozen winner violates the
primary endpoint on test; or adaptivity CIs include 0 everywhere. In those
cases the README will state that bounding the composition does not rescue
the usage prior, and rfm's supported claims reduce to: outcome-driven
adaptation and forgetting within a shortlist supplied by the caller.

Runner: `bench-quality/compose_eval.py` (dev) and the frozen-config test
invocations recorded in `bench-quality/RESULTS.md` as they happen.

---

# Amendment 1 (registered before any hybrid/pruning run)

## Step H — hybrid retrieval (BM25 + vector)
Candidates: weighted fusion `w·norm(sim) + (1−w)·norm(bm25)`, w ∈ {0.3, 0.5,
0.7} (per-query min-max norm; non-matching FTS rows score 0), and RRF(k=60)
over the two rankings. BM25 = SQLite FTS5 over full turn text. Dev: BEAM,
both embedders. Selection: maximize NDCG@10 (all questions) subject to not
losing to the better single signal on either embedder. Frozen fusion then
composes with rfm_prior exactly as before. One-shot test: LoCoMo + SWE
(MiniLM, Qwen3). Success bar: hybrid×prior ≥ sim-only NDCG on both test
benches (CI-supported on at least one).

## Step P — confident-negative exclusion (pruning)
Rule: a memory is excluded from candidates when value_score ≤ V and
outcome_count ≥ N. Grid: V ∈ {−0.5, −0.8}, N ∈ {2, 3}. Dev: BEAM (cost on
overlap=False must stay ≤ 0.010) + tuning of nothing else. One-shot test:
knowledge-update (success: update-preference delta ≥ +0.10 with fresh recall
unchanged) and LoCoMo (cost bar as before). Motivation: restore forgetting
lost to the bounded prior via exclusion rather than score influence.

Parity features (capture skill, list/delete/export, injection cap) carry NO
benchmark claims; they are verified by unit/integration tests only.
