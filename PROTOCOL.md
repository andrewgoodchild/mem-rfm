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

---

# Amendment 6 — score-gaming (R/F/M exploits) and the hardened defense

**Status: registered before any full-stream exploit run.** Amendment 5's
attacker gamed *content* (semantic mimicry). This one games the *scoring
function*: a compromised team member self-accesses its own poison to pump
Recency/Frequency (→ activation) and self-reports +1 outcomes to pump the
value EWMA (M), using calls it is entitled to make. Question: does
score-gaming help the attacker beyond mimicry, and does a `created_by`-based
hardening remove it **without degrading legitimate memories** — the
overzealous-protection failure mode.

Extension change under test (committed with this amendment): a nullable
`created_by` column on rfm_memories, an `actor` column on rfm_accesses,
optional actor args on `rfm_record_access(id[, actor])` /
`rfm_record_outcome(id, o[, actor])`, and `rfm_config('exclude_self', 1)`
— when set, an access/outcome whose actor equals the memory's created_by is
ignored (no log row, no summary change, no slot consumed). Default 0
(exact back-compat; verified by the pre-existing integration suite plus a
new `hardened_mode_ignores_self_endorsement` test). Runner:
`bench-quality/exploit_eval.py` as committed.

Design honesty: EVERY memory is authored — legit memories by their handling
agent, poison by the attacker — so hardened mode also excludes an agent
re-endorsing its OWN past memory. A version tagging only poison would rig
the utility bars; this does not.

## Conditions & endpoints (STAR primary, r=0.20, pump=50, exploit=both,
## MiniLM, k=5, frozen β=0.3)

sim (no prior — gaming can't touch it), rfm (prior, gaming allowed),
rfm_hard (prior + exclude_self). Measured on the same injected stream.

- **X1 exploit is real**: poison top-k occupancy, rfm − sim CI > 0 — i.e.
  under score-gaming the value axis becomes a *liability*, admitting more
  poison than plain similarity. (If this is ≤ 0, the bounded prior already
  neutralized gaming and hardening is unnecessary — that null is the
  finding.)
- **X2 hardening removes the lift**: occupancy rfm − rfm_hard CI > 0, and
  rfm_hard occupancy ≤ sim occupancy (CI midpoint) — the defense returns
  exposure to at least the no-prior baseline.
- **U1 utility preserved under attack**: legit hit@1, rfm_hard − rfm CI ≥ 0
  (hardening must not cost clean-label ranking on the attacked store).
- **U2 utility preserved on a clean store**: legit hit@1 on an
  unattacked, fully-authored store, rfm_hard − rfm — **|Δ| ≤ 0.010 is the
  pass; a drop below −0.010 FAILS and vetoes the defense** regardless of
  X1/X2. This is the anti-overzealous bar: protection that degrades good
  memories is rejected even if it stops the attack.

Secondary (reported, no bars): exploit=rf and exploit=m alone (which axis
is the hole); ABCD replication at r=0.20; a pump ∈ {10,50,200} sweep
(does more gaming buy more exposure, or does β cap it?).

**Disclosure:** plumbing smoke runs (STAR n≤600, r=0.08, pump=20) were run
and seen before registration to build the runner; small-n directions
(X1>0, X2>0, U2≈0) were visible. No full-stream number exists. Bars are set
at the stronger r=0.20/pump=50 regime, one-shot.

## What would falsify

X1 ≤ 0: score-gaming doesn't beat the bounded prior — hardening is
motivated only defensively, not empirically, and the README says so. X2
failing: created_by-exclusion doesn't stop gaming (some other channel
remains). U2 failing: the defense degrades legitimate memories — it is
rejected and stays off by default with a documented warning, exactly as
confident-negative pruning (Step P) was.

---

# Amendment 7 — adversary matrix: downvote censorship, collusion, and ballot-stuffing prevention

**Status: registered before any full-stream run.** Amendment 6 covered one
attacker promoting its own memories. This registers the two attacks that
`exclude_self` cannot see by construction, plus a second hardening
primitive.

New extension surface (committed with this amendment):
`rfm_config('one_vote', 1)` — an actor-tagged outcome is ignored if that
actor already recorded an outcome for that memory, so `value_score`
reflects DISTINCT endorsers rather than repetitions. Default 0; untagged
callers unaffected; served by a new `rfm_accesses(memory_id, actor)` index.
Verified by `one_vote_per_actor_blocks_ballot_stuffing`. Note the migration
ordering fix in `rfm_init` (ALTERs now precede the schema script, because
the new index references a column older databases lack).

Runner: `bench-quality/adversary_eval.py`. Attacks: **upvote** (Amendment 6
baseline), **downvote** (inject nothing; bury every genuine memory of the
4 highest-volume labels — targeted censorship), **collude** (C=4 attackers
inject bait and endorse EACH OTHER's, so no endorsement is ever
self-endorsement). Defenses: rfm, rfm_self (exclude_self), rfm_vote
(one_vote), rfm_both; `sim` is the ungameable control. STAR primary,
r=0.20, pump=50, k=5, frozen β=0.3, MiniLM.

**Disclosures.** (a) Smoke runs at n≤500 were executed and seen before this
registration. (b) The downvote attack was REDESIGNED after a smoke run
showed uniform suppression is a mathematical no-op (a penalty applied to
every memory leaves relative order unchanged); it now targets specific
labels and is scored separately on targeted vs untargeted calls. That
redesign happened before any full-stream number existed.

## Endpoints (per attack, STAR full stream)

- **A1 attack is real**: legit hit@1, `sim − rfm` CI > 0 (the attack must
  make the unhardened prior worse than no prior). For downvote, also
  **A1t** on targeted-label calls only.
- **A2 a defense recovers**: for each of rfm_self / rfm_vote / rfm_both,
  hit@1 `defense − rfm` CI > 0, and `defense − sim` ≥ 0 (returns the prior
  to at least the no-prior baseline).
- **U utility bar (veto)**: clean-store hit@1 (no attacker present),
  `defense − rfm`. **|Δ| ≤ 0.010 to be recommendable; a drop below −0.010
  means that defense is rejected as default-recommended guidance**
  regardless of A2 — the Step P rule. `one_vote` is expected to be the
  expensive one: it discards repeat-use evidence, which is the value axis's
  main signal in recurring workloads.

## Registered predictions (falsifiable, from mechanism + smoke)

1. **upvote**: rfm_self recovers fully; rfm_vote recovers partially.
2. **downvote**: A1 ≤ 0 — no defense needed, because the bounded prior
   caps demotion at 0.7× while the similarity gap between right-label and
   wrong-label memories is larger. Censorship should be structurally
   impossible under β-bounding. If A1 > 0, that prediction is falsified and
   β-bounding is not the protection we claim.
3. **collude**: A1 > 0 and **no defense recovers** — one_vote counts
   distinct endorsers, and colluders ARE distinct endorsers, so it is
   structurally powerless here. If this holds, collusion is an open,
   unmitigated hole and the README must say so.

## What would falsify

Prediction 2 failing means bounded composition does not protect against
suppression — a security claim would be withdrawn. Prediction 3 failing
(some defense does recover) would be a welcome surprise, reported as such.
A U-bar failure rejects that defense from recommended guidance even where
it works; if `one_vote` fails U and defends nothing collusion-wise, it
ships as an off-by-default option documented as not recommended.

---

# Amendment 8 — writer reputation (trust cap) and collusion detection

**Status: registered before any full-stream run.** Amendment 7 left collusion
unmitigated: per-memory rules cannot see a ring because colluders are
genuinely distinct endorsers. This registers a per-WRITER defense and a
log-only detector.

## Mechanism under test

New extension surface: table `rfm_actors(actor, value_score, outcome_count)`
maintained by `rfm_record_outcome` — the EWMA of THIRD-PARTY outcomes on
memories that actor wrote (the author's own votes and untagged votes never
contribute). `rfm_config('trust', 1)` then caps a memory's effective value
at its author's shrunk trust: `min(v_eff, trust_eff)`. One-sided by
construction — trust can only pull an over-endorsed memory DOWN toward its
author's record, never lift one above its own measured value. Adds no
tunable (reuses shrink_k, w_v, β) and keeps scoring a one-row read.
Rationale: a ring inflates each memory's own EWMA, but every failed
retrieval by an outsider accumulates against the ring member's IDENTITY,
which no amount of cross-endorsement can launder.

Detector (harness-side, `common.collusion_signals()`, pure log forensics —
runnable by an auditor on a committed log, no scoring state):
`dissent`, `concentration`, `reciprocity` as documented in that function.

## Endpoints (STAR full stream, collude C=4, r=0.20, pump=50, k=5, β=0.3)

- **T1 (primary) trust recovers**: h@1 `rfm_trust − rfm` CI > 0.
- **T2 (secondary, reported, no bar) full restoration**: h@1
  `rfm_trust − sim` ≥ 0. Smoke suggests partial recovery only; reported
  either way.
- **U (veto) utility**: clean-store h@1 `rfm_trust − rfm`, |Δ| ≤ 0.010.
  A defense that protects by degrading normal operation is rejected.
- **D1 detector**: `concentration` precision@C = 4/4 with positive
  attacker/honest separation.
- **D2 (reported)** the failing detectors, as negative results.
- **Cross-checks**: trust must not damage the upvote or downvote scenarios
  (h@1 `rfm_trust − rfm` ≥ −0.010 in each). ABCD collude replication.

## Disclosures

Smoke runs at n=600, pump=20 were executed and seen before registration.
The detector was REDESIGNED after two failures observed there, both of which
are registered as reportable negative results rather than discarded: (a)
`dissent` (disagreement with per-memory consensus) INVERTS — a ring that
stuffs ballots manufactures the consensus, so honest voters get flagged
(separation −0.178, precision 0/4); (b) `reciprocity` shows no separation
because honest teammates also endorse each other's memories in the normal
course of work (precision 0/4). Only `concentration` (entropy deficit of
the authors a voter praises) separated (4/4, +0.314). No full-stream number
exists at registration.

## What would falsify

T1 failing means writer reputation does not defend collusion either, and
the README's open-problem statement stands unchanged. U failing rejects
the trust cap as recommended guidance regardless of T1 (the Step P rule).
D1 failing means collusion is not detectable from the log by this signal —
reported as such, with the two other failures.
