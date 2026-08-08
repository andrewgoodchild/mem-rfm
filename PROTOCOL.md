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

---

# Amendment 2 (registered before any SWE hybrid run)

Step H failed its bar on conversational dev (BEAM) — recorded in RESULTS.md.
The remaining hypothesis is domain-specific: BM25 helps CODE retrieval
(identifiers, error strings). To test it without contaminating the SWE test
set: **SWE-Bench-CL is split by repo — dev = django + sympy sequences (the
two largest); test = the remaining six repos.** No SWE hybrid number has
been computed before this registration. Dev selection: same rule as
Amendment 1, on dev repos, both embedders. If frozen, one-shot on the six
test repos; the claim, if earned, is scoped to code retrieval. LoCoMo remains
untouched by hybrid (failed its domain's dev).

---

# Amendment 3 (registered before any Step P run)

Discovered pre-run: the knowledge-update protocol records exactly ONE
penalty per stale memory, so the registered grid (N ≥ 2) can never fire
there — the KU success bar would be unreachable by construction. Corrected
grid, registered before any Step P number exists: V ∈ {−0.5, −0.8},
N ∈ {1, 2, 3}. Selection among BEAM-cost-safe configs (cost ≤ 0.010, both
embedders): the most aggressive (smallest N, then higher V threshold), since
the target effect is forgetting. One-shot test unchanged: KU (delta ≥ +0.10,
fresh recall unchanged) and LoCoMo cost bar.

---

# Amendment 4 — team-memory replication campaign (STAR, MultiDoc2Dial, FloDial)

**Status: registered before any full-stream run.** The four ABCD results
(team pooling, outcome-ranking at rank-1, staleness recovery, manual-vs-
experience) were exploratory. This amendment turns three of them into
pre-registered replications on datasets with independently authored manuals.
**Disclosure:** plumbing smoke runs at n ≤ 400 were executed before this
registration to verify the loaders (star_eval/md2d_eval/flodial_eval,
outputs in the session log, not committed); their small-n deltas were seen
by the authors. They are dev evidence, not confirmatory. No full-stream
number exists at registration time. The staleness result is NOT part of
this amendment (no revision port exists yet); it remains ABCD-exploratory.

## Datasets and fixed parameters (no tuning anywhere)

Frozen throughout: β = 0.3 bounded composition (`rfm_beta0.3`), k = 5,
MiniLM-L6-v2, oracle evidence-hit outcomes (+1 label match / −1 other),
leakage-free sequential protocol. Loaders as committed in
`bench-quality/{star,md2d,flodial}_eval.py` at this amendment's commit:

- **STAR** n = 6,500: real wizard IDs for the solo/team split (~90 wizards),
  real collection-time ordering (no shuffle), 24 tasks, manual = the 24
  authored task definitions. Per-class recurrence ≈ 270 calls/task.
- **MultiDoc2Dial** n = 4,700: seed-13 shuffle, 8 round-robin agents
  (disclosed: no natural IDs), 488 document labels, manual = the 488
  authored documents. Per-class recurrence ≈ 10 — the LOW-recurrence probe.
- **FloDial** n = 1,844: seed-13 shuffle, 8 agents, 12 flowchart labels,
  manual = the 12 authored flowcharts + FAQs. hit@5 saturates at 12 classes,
  so FloDial endpoints bind to hit@1 only. Recurrence ≈ 154.

## Pre-registered endpoints (per dataset unless stated)

- **P1 pooling**: team_sim − solo_sim hit@5 CI > 0 on ALL THREE datasets.
- **P2 recurrence hypothesis** (the load-bearing claim: experience beats
  the authored manual where work recurs): team_sim − manual_sim hit@1
  CI > 0 on STAR and FloDial (high recurrence); prediction: ≤ 0 on
  MultiDoc2Dial (recurrence ~10 cannot cover 488 classes). A positive MD2D
  delta would be a pleasant surprise, not a failure; a NEGATIVE STAR or
  FloDial delta falsifies the recurrence claim.
- **P3 rank-1 outcome-ranking**: team_rfm − team_sim hit@1 CI > 0 on at
  least TWO of three datasets, with rank-safety everywhere: team_rfm −
  team_sim hit@5 ≥ −0.010 (CI midpoint) on all three.
- **P4 layered system**: both_rfm − manual_sim hit@1 CI > 0 on STAR and
  FloDial; both_rfm − team_rfm hit@5 CI > 0 over the first 500 aligned
  calls (cold-start value of the manual) on all three.

Failures are published at full volume alongside successes, as always.
Secondary (reported, no bars): full quintile curves; a single robustness
re-run of STAR under Qwen3-Embedding-0.6B (declared now, compute-bounded).
Per-call outputs committed to `bench-quality/results-{star,md2d,flodial}/`.

## What would falsify the team-memory claims

P1 failing anywhere kills the pooling headline. P2 failing on a
high-recurrence dataset kills "experience outgrows the manual" (the README
would then scope it to ABCD). P3 failing everywhere reduces the value axis
to its bench-sequential evidence. P4 cold-start failing removes the
"manual for day one" layer of the deployment recipe.

---

# Amendment 5 — bad-actor poisoning of a pooled store (STAR primary, ABCD secondary)

**Status: registered before any full-stream poisoning run.** Question: when
a compromised team member injects plausible bait into a shared store, does
outcome feedback defend retrieval where similarity cannot? Runner:
`bench-quality/poison_eval.py` as committed with this amendment. Attack:
`mimic` — bait is a verbatim PAST customer query of a top-8-volume label
plus a bogus resolution (embedding-similar to future queries of that label
by construction; the attack a semantic admission gate cannot catch); one
poisoned write per genuine call at rate r. Poison is never a hit; in rfm
arms a retrieved poison earns −1 (oracle failure signal, as throughout).
Conditions: clean_sim / clean_rfm / pois_sim / pois_rfm, paired per call.

**Disclosures.** (a) A plumbing smoke run (STAR, n=500, r=0.05) was
executed and seen before this registration: damage was small at r=0.05
(+0.6 h@1) and the survival stat favored rfm (max 14 vs 9 retrievals per
poison). No full-stream number exists. (b) The originally drafted E2
(pois_rfm − pois_sim) was discovered pre-run to conflate the generic
rank-1 rfm gain with defense; E2 is registered as the
difference-in-differences below, corrected BEFORE any full run.

## Endpoints (STAR full stream, MiniLM, k=5, frozen β=0.3; bars at r=0.20)

- **E1 threat**: clean_sim − pois_sim hit@1 CI > 0 at r=0.20 (the attack
  must actually damage similarity retrieval to be worth defending against;
  if it doesn't, that null is the published finding).
- **E2 defense (DiD)**: [(clean_sim − pois_sim) − (clean_rfm − pois_rfm)]
  hit@1 CI > 0 at r=0.20 — outcome feedback absorbs more of the damage
  than similarity does, net of the generic rfm gain.
- **E3 exposure**: mean top-k poison occupancy, pois_sim − pois_rfm CI > 0
  at r=0.20.

Secondary (reported, no bars): r=0.05 sweep; ABCD replication at r=0.20;
`junk` attacker as attention check (expected ≈ harmless); `--noise 0.2`
robustness (each outcome sign-flipped with p=0.2); per-poison survival
distribution (retrievals sustained before dropping out of top-k).

## What would falsify the defense claim

E2 or E3 failing at r=0.20 kills "outcome feedback as pollution defense"
(the README/research notes would then say the value axis does not protect
pooled stores, and admission control is the only line). E1 failing means
the mimic attack does not damage this workload — publishable as its own
null, and the defense claim becomes untestable here rather than supported.

**Post-registration runner fix (2026-08-08, before any ledger entry):** the
first execution crashed the noise run and exposed hash-order
nondeterminism in `build_poison` (set iteration diverged the rng stream
across processes, so the injection plan was not exactly reproducible).
Fixed to a sorted-order deterministic plan + cache validation; endpoints,
bars, rates, and seeds unchanged. All five runs re-executed with the fixed
runner as the official numbers; the aborted first-execution logs are not
used. First-execution primary endpoints (E1 +0.0127, E2 +0.0084, E3
+0.0155, all CIs > 0) were seen before the fix — disclosed here; no
selection occurred (the fix changes only plan determinism, and the re-run
is one-shot regardless of outcome).
