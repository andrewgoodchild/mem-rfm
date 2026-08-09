# Composition experiment log (per PROTOCOL.md)

## Dev phase (BEAM, both embedders) — complete

Full tables in `compose_minilm.log` / `compose_qwen3.log`; per-question rows
in `results-compose/`.

Feasibility (cost vs sim on overlap=False ≤ 0.010, CI midpoint, per embedder):

| candidate | MiniLM cost | Qwen3 cost | feasible | mean adaptivity |
|---|---|---|---|---|
| beta0.1 | −0.0000 | +0.0031 | yes | +0.0079 |
| beta0.2 | +0.0003 | +0.0042 | yes | +0.0091 |
| **beta0.3** | +0.0028 | +0.0081 | **yes** | **+0.0120** |
| beta0.5 | +0.0038 | +0.0172 | no (Qwen3) | — |
| rrf | +0.3826 | +0.4759 | no | — |
| shortlist | +0.3658 | +0.4488 | no | — |

rrf and shortlist fail feasibility by an order of magnitude: any composition
that gives the raw rfm ordering equal or unchecked authority is destroyed by
the prior's dynamic range. Only bounded multiplicative influence survives.

**Protocol-gap note (disclosed):** the rule-3 tie-break was written to prefer
across families; the three feasible candidates are one family within 0.005
adaptivity of each other, so rule 3 does not discriminate. Resolved by strict
rule-2 argmax. Sensitivity of conclusions to β ∈ {0.1, 0.2} is visible in the
committed curves.

## FROZEN CONFIGURATION (committed before any test-set run)

**beta-blend, β = 0.3**: `score = max(sim, 0) × (0.7 + 0.3 · rfm_score(id))`

Test plan (one shot, per PROTOCOL.md): LoCoMo (MiniLM, Qwen3) — primary;
knowledge-update (MiniLM), SWE-Bench-CL (MiniLM, Qwen3), and unseen-embedder
BAAI/bge-m3 (LoCoMo, SWE) — secondary. Results appended below after the runs;
no re-tuning regardless of outcome.

## Test phase — one shot, frozen beta=0.3 (logs: frozen_*.log; rows: results-frozen/)

| endpoint | pre-registered bar | result | verdict |
|---|---|---|---|
| LoCoMo cost, MiniLM | ≤ 0.010 | −0.0011 [−0.0045,+0.0022] | PASS |
| LoCoMo cost, Qwen3 (primary) | ≤ 0.010 | +0.0040 [−0.0007,+0.0087] | PASS |
| LoCoMo adaptivity, MiniLM | CI > 0 | +0.0234 [+0.0169,+0.0303] | PASS |
| LoCoMo adaptivity, Qwen3 | CI > 0 | +0.0323 [+0.0236,+0.0411] | PASS |
| SWE cost, MiniLM | n.s. | −0.0130 [−0.0423,+0.0082] | PASS |
| SWE cost, Qwen3 | n.s. | −0.0013 [−0.0082,+0.0043] | PASS |
| KU forgetting delta | > 0 | +0.0143 [+0.0000,+0.0429] | WEAK — point est. > 0, CI touches 0 |
| bge-m3 generalization | cost ≤ 0.010 | pending | — |

Interpretation committed with the numbers: bounding the prior eliminates the
retrieval cost on every setting and keeps feedback adaptivity (test deltas
LARGER than dev — anti-overfitting signature), but sacrifices most of the
knowledge-update forgetting effect (+0.229 unbounded → +0.014 at β=0.3).
β is a protection-vs-plasticity dial; forgetting-critical deployments should
raise β or apply penalties outside the bounded path.

## Unseen-embedder endpoint (BAAI/bge-m3, declared in PROTOCOL.md (d))

| setting | cost vs sim | adaptivity ON−OFF | verdict |
|---|---|---|---|
| LoCoMo | −0.0049 [−0.0103,+0.0005] | +0.0784 [+0.0677,+0.0898] | PASS (cost bar met; largest adaptivity of any embedder) |
| SWE | +0.0167 [−0.0289,+0.0626] n=48 | +0.0390 [+0.0121,+0.0666] | n.s. (passes the SWE bar as declared); point estimate above 0.010 disclosed — small n |

The frozen configuration was never exposed to bge-m3 during development;
its LoCoMo adaptivity under bge-m3 exceeds both development embedders.

## Step H dev (BEAM) — FAILED the registered bar
No fusion beat the better single signal: hybrid_w0.7 ties sim on MiniLM
(0.4268) and loses on Qwen3 (0.4926 vs 0.5090); RRF loses on both; bm25
alone 0.3251. BM25 does not advance to conversational test sets. Full
numbers above committed logs (hybrid dev printed inline; per PROTOCOL
Amendment 1). Hypothesis for code domain registered as Amendment 2.

## Amendment 2 dev (SWE django+sympy, n=25) — hybrid_w0.3 FROZEN
On code, bm25 alone beats sim (0.546 vs 0.459 MiniLM / 0.534 Qwen3). Only
hybrid_w0.3 (0.3·norm(sim) + 0.7·norm(bm25)) beats the better single signal
under BOTH embedders (0.558 / 0.582). w0.5, w0.7, rrf fail on MiniLM.
Frozen before any test-repo run. Small dev n disclosed.

## Amendment 2 one-shot (6 held-out repos, n=63) — hybrid FAILED
hybrid_w0.3 is WORSE than sim on held-out repos: 0.486 vs 0.542 (MiniLM),
0.504 vs 0.602 (Qwen3, CI excludes 0). The n=25 dev win was repo-specific.
Step H is dead in both domains under the registered bars. BM25 hybrid is NOT
shipped. (Note: the rfm prior on top of hybrid was cost-safe — +0.003
[+0.000,+0.006] vs hybrid on Qwen3 — consistent with the frozen-β result.)

## Step P dev (BEAM) — FAILED
No (V, N) config passes the cost bar on both embedders: N=1 catastrophic
(+0.081/+0.146 — single bad outcomes exclude future evidence), N=2 fails
2-4x over, N=3 misses narrowly on Qwen3 (+0.0105/+0.0126 vs 0.010) and
cannot fire on KU's single-penalty protocol regardless. Conclusion:
candidate exclusion cannot be both retrieval-safe and forgetting-potent.
Confident-negative exclusion is NOT shipped. KU forgetting remains governed
by the documented beta dial (raise beta when forgetting > rank safety).

## Campaign summary (Amendments 1-3)
Both hypothesized benchmark improvements FAILED honest evaluation:
hybrid BM25 (failed conversational dev; dev win on 2 code repos reversed on
6 held-out repos) and negative-exclusion pruning (cost bars). The frozen
beta=0.3 composition from the main protocol remains the best known
configuration. Remaining roadmap features (capture, inspectability,
injection cap) are adoption/parity work and carry no benchmark claims.

## Post-review disclosure (Amendment 2 hybrid runs)
Code review found temporal leakage in swe_hybrid_dev/test: the FTS5 index was
built over ALL sequence tasks, so BM25 corpus statistics (IDF/avgdl) included
future task text in a sequential protocol. The leakage could only have
FLATTERED the bm25-bearing arms; since the registered verdict was that hybrid
FAILS on held-out repos, the negative conclusion stands a fortiori. Disclosed
for reproducibility; the scripts are archival and will not be re-run.

## Exploratory pilot (NOT pre-registered): live agent A/B on real pytest bugs
experiments/swe-ab/: 8 chronological SWE-Bench-CL pytest tasks, paired
headless Claude Code sessions (control vs rfm arm, separate clones, gold-test
scoring). Results: 8/8 resolved in BOTH arms (ceiling — tasks too easy to
differentiate); rfm overhead +21.8s/session [+0.8,+44.0] (mostly MCP server
startup, proportionally trivial in interactive sessions); tokens +808 n.s.;
edits identical. Mechanism verification in the wild: 7/8 rfm sessions used
memory tools unprompted, 7 specific codebase lessons captured, 20 retrievals,
and the agent gave NEGATIVE feedback to irrelevant retrieved memories — the
demotion loop operated end-to-end with no oracle. n=8: directional only.

## Extended live A/B (NOT pre-registered): 27 paired tasks, pytest + sphinx
run_stream.py: 54 sessions, real bugs, gold-test scoring, era-pinned envs.
Resolution: control 25/27, rfm 23/27. Both discordant pairs (pytest-10356
1-4h; sphinx-7590 >4h) favor CONTROL — the two hardest tasks. McNemar p=0.5
(n.s.) but directionally negative on hard tasks. Wall overhead +8.5s/session.
Memory audit: pytest 17 memories/65 accesses/16 outcomes — 15 of 16 NEGATIVE
(bug-fix lessons rarely transfer across scattered subsystems; the demotion
loop measured that honestly). The ONLY memory earning sustained positive
value (+0.58 over 5 uses) was an ENVIRONMENT/operational fact (sphinx venv
gotcha), not code knowledge. Insight: in episodic bug-fixing, operational
memory transfers; per-bug code lessons mostly don't.

## Exploratory: ABCD team memory (support calls; NOT pre-registered)
abcd_eval.py: 3,000 real support calls (ABCD, MIT), 55 procedures, 8
simulated agents, sequential leakage-free protocol, no LLM (gold procedure
annotations judge retrieval). Findings:
1. POOLING: team-shared store beats per-agent solo stores +0.145 hit@5
   [+0.130,+0.161]; team reaches in Q1 (0.80) what solo needs ~3 quintiles
   to approach — the "team knowledge edge" quantified.
2. RANKING: rfm (frozen beta=0.3) vs similarity — hit@5 parity (-0.004
   n.s.: the bounded-cost guarantee holds), but hit@1 IMPROVES: +0.012
   [+0.005,+0.020] overall, growing to +0.020 [+0.007,+0.034] over the last
   1,000 calls as feedback accumulates. First live-workload setting where
   outcome-ranking beats similarity on a primary metric with CI > 0 — at
   rank-1, the position that matters when handing an agent ONE playbook.
Caveats: exploratory, oracle evidence-hit outcomes, imposed call ordering,
one embedder. Consistent with the recurrence law: ABCD is the
maximal-recurrence workload, and it is where memory finally pays.

## Exploratory: staleness under procedure change (ABCD, NOT pre-registered)
> SUPERSEDED in part — the "~2.8x" framing below is retracted; see
> CORRECTIONS #2 (2026-08-03).

abcd_staleness.py: at call 1,500 the 8 highest-volume procedures are
"revised" — all pre-change memories for them become wrong (retrieval = miss,
rfm arm receives -1, the ticket-reopen signal). Pre-revision hit@1 ~0.76
both arms. Recovery at hit@1 by +1,500 calls: similarity-only 0.197 vs
rfm 0.561 — outcome feedback retires stale procedures ~2.8x faster; at
hit@5 rfm is nearly recovered (0.894) vs sim 0.773. Similarity recovers
only by dilution; feedback demotion compounds. Honest note: neither arm
fully recovers within 1,500 calls — production wants explicit write-time
invalidation on announced policy changes (bulk demote/delete), with
outcome-driven forgetting as the safety net for unannounced ones.

## Exploratory: manual-RAG vs experience-memory vs both (ABCD)
> SUPERSEDED — the numbers below are the buggy v1 run (33/55 manual titles
> mapped, manual entries age-handicapped). See CORRECTIONS #1 (2026-08-03)
> for the corrected run: manual_sim 0.591 hit@1, experience advantage
> +0.120, cold-start +0.070.

abcd_manual.py, 3,000 calls, 5 conditions. The authored agent manual (55
procedure entries, guidelines.json) retrieved as a knowledge base scores
0.29 hit@1 — FLAT across the whole stream (no learning possible) — because
procedure docs describe agent actions, not customer phrasing: the
diagnosis mapping is not in the manual. Shared experience memory beats it
by +0.42 hit@1 [+0.40,+0.44]. Combining both wins the COLD START (+0.038
hit@5 over experience-only in the first 500 calls [+0.020,+0.056]) and
converges to experience at steady state. Outcome-ranking replicates its
rank-1 edge in the combined store (+0.011 [+0.004,+0.019]; manual entries
earn outcome scores like any memory). Layered conclusion: manual = day-one
scaffolding, experience = the diagnosis engine, outcomes = the maintenance
policy.

## CORRECTIONS (pre-publication review, 2026-08-03)

1. **Manual-RAG experiment re-run — headline number corrected.** v1 of
   abcd_manual.py mapped only 33/55 manual titles (word-set matching missed
   22, e.g. 'Reset Two-Factor Auth' -> reset_2fa), leaving 52.7% of calls
   with no manual entry to retrieve, and aged manual entries 30 days,
   handicapping them in rfm arms via recency decay. The committed log
   disclosed "mapped: 33" on line 1; review caught it. Corrected run (55/55
   mapped, manual created at stream start; abcd_manual.log; buggy log kept
   as abcd_manual_v1_buggy.log): manual_sim 0.591 hit@1 / 0.844 hit@5
   (was 0.290/0.403); experience advantage +0.120 hit@1 [+0.100,+0.139]
   (was +0.435); cold-start value of manual+experience over experience
   +0.070 hit@5 first-500 [+0.048,+0.094] (was +0.038); outcome-ranking
   edge in combined store +0.013 [+0.006,+0.021], now free of the age
   confound; both_rfm best overall (0.730 hit@1). Qualitative conclusions
   (manual static, experience learns and wins, manual = cold-start value,
   outcomes on top) unchanged; the "+42 points" magnitude was an artifact.
2. **Staleness "2.8x" softened.** The multiplier was the final-bin
   point-estimate ratio (0.561/0.197 at +1,500 calls); earlier bins give
   1.8-1.9x, per-bin n≈60-80, no CI. Claims now describe the recovery
   curve, not a rate constant.
3. **"Both discordant pairs = the two hardest tasks" restated.** They are 2
   of the 5 tasks rated above one hour; the other three hard tasks were
   solved by both arms — consistent with noise (McNemar p=0.5).
4. **Validation provenance documented.** experiments/swe-ab validation ran
   three times while era pins evolved (validation.v1/.v2/.jsonl are all
   committed); 8 sphinx tasks including sphinx-7590 (one of the two
   discordant tasks) validated only under the final pins. 7590's harness
   environment being marginal is an additional reason to treat the
   hard-task direction as suggestive, not established.
5. **Memory-audit artifact committed** (experiments/swe-ab/memory-audit.md)
   so the 15-of-16-negative / ~6% transfer / +0.58 numbers are checkable;
   session transcripts and DBs remain untracked.

## Amendment 4 one-shot: team-memory replication (STAR, MultiDoc2Dial, FloDial)

Run 2026-08-08, MiniLM, frozen beta=0.3, k=5, oracle outcomes. Logs:
`star_full.log`, `md2d_full.log`, `flodial_full.log`; rows:
`results-{star,md2d,flodial}/per_call.jsonl`. Actual streams vs registered
caps (disclosed): STAR 4,396 qualifying single-task dialogs of the 6,500
cap (24 tasks, 115 real wizards — recurrence ≈ 183/task, not the ≈ 270
estimated at registration); MD2D 4,135 (451 of 488 doc labels appear);
FloDial 1,844 (10 of 12 flowcharts appear in the train dialogs; the manual
arm still carries all 12).

| endpoint (registered bar) | STAR | MultiDoc2Dial | FloDial | verdict |
|---|---|---|---|---|
| P1 pooling h@5 CI>0, all three | +0.261 [+0.247,+0.275] | +0.375 [+0.359,+0.391] | +0.040 [+0.032,+0.050] | **PASS 3/3** |
| P2 experience−manual h@1 CI>0 on STAR+FloDial | +0.211 [+0.198,+0.225] | +0.064 [+0.047,+0.082] (prediction was ≤0) | +0.017 [+0.008,+0.026] | **PASS** — see note |
| P3 rank-1 team_rfm−team_sim h@1 CI>0 on ≥2 of 3 | +0.0125 [+0.0084,+0.0166] | +0.0024 [−0.0039,+0.0090] | +0.0016 [−0.0005,+0.0043] | **FAIL (1 of 3)** |
| P3 rank-safety h@5 midpoint ≥ −0.010 | +0.005 | −0.004 | +0.000 | held 3/3 |
| P4 layered both_rfm−manual_sim h@1 CI>0 (STAR, FloDial) | +0.226 [+0.213,+0.239] | +0.127 [+0.112,+0.142] | +0.023 [+0.015,+0.032] | **PASS 3/3** |
| P4 cold-start both_rfm−team_rfm h@5 first-500 CI>0, all three | +0.032 [+0.018,+0.048] | +0.426 [+0.378,+0.472] | +0.016 [+0.006,+0.028] | **PASS 3/3** |

Verdicts. **Pooling replicates on all three datasets** — the headline
holds, at +26.1/+37.5/+4.0 points, now including a split by the dataset's
own 115 human wizards on a naturally time-ordered stream (STAR), answering
both ABCD caveats. **Experience beats the authored manual on all three**,
including MultiDoc2Dial where the registered recurrence hypothesis
predicted it would NOT (≈9 recurrences/label sufficed at h@1) — the
prediction was falsified in experience's favor; the manual still dominated
the first 500 calls (h@5 0.808 vs 0.393), so the cold-start half of the
recurrence story stands. **The rank-1 outcome-ranking edge did not
replicate beyond STAR** — P3 fails its bar and is published as failed.
Post-hoc (marked as such, not registered): FloDial's team_sim h@1 is 0.984
(no headroom) and MD2D's last-1000 trend is positive but n.s.
(+0.010 [−0.005,+0.025]); neither excuse changes the verdict. The
bounded-cost guarantee held everywhere, again. **The layered system
(manual + experience + outcomes) wins on all three**, with the manual's
cold-start value largest exactly where recurrence is lowest (MD2D +42.6
points over the first 500 aligned calls).

## Amendment 4 secondary: STAR robustness under Qwen3-Embedding-0.6B

Declared in the registration; run 2026-08-08, log `star_qwen3.log`;
rows: `results-star/per_call-qwen3.jsonl`. All
four endpoint directions replicate under the stronger embedder: P1 pooling
+0.240 [+0.225,+0.255]; P2 experience−manual +0.060 [+0.049,+0.071]
(narrower than MiniLM's +0.211 — the authored manual gains more from the
stronger embedder, h@1 0.846 vs 0.720, but experience still wins); P3
rank-1 +0.0127 [+0.0080,+0.0175] (essentially identical to MiniLM's
+0.0125, and rank-safety is positive, +0.0077 h@5 — the bounded prior
stays safe in the exact regime that falsified the unbounded one); P4
layered +0.076 [+0.066,+0.087], cold-start +0.032 [+0.016,+0.048].

## Amendment 5 one-shot: bad-actor poisoning of a pooled store

Official runs 2026-08-08 with the deterministic runner (post-registration
fix disclosed in PROTOCOL.md; first-execution numbers also disclosed
there). Logs: `poison_star_r20.log` (primary), `poison_star_r05.log`,
`poison_abcd_r20.log`, `poison_star_junk.log`, `poison_star_noise.log`.

| run | E1 threat (h@1) | E2 defense (DiD, h@1) | E3 exposure (occupancy) |
|---|---|---|---|
| **STAR mimic r=0.20 (bars)** | **+0.0111** [+0.0082,+0.0143] **pass** | **+0.0086** [+0.0055,+0.0121] **pass** | **+0.0132** [+0.0113,+0.0152] **pass** |
| STAR mimic r=0.05 | +0.0027 [+0.0014,+0.0043] | +0.0009 [−0.0007,+0.0025] n.s. | +0.0051 [+0.0041,+0.0063] |
| ABCD mimic r=0.20 | +0.0210 [+0.0160,+0.0260] | +0.0140 [+0.0093,+0.0190] | +0.0193 [+0.0163,+0.0224] |
| STAR junk r=0.20 | +0.0000 | +0.0000 | −0.0000 |
| STAR mimic r=0.20 noise=0.2 | +0.0111 | +0.0055 [+0.0011,+0.0100] | +0.0102 [+0.0086,+0.0119] |

**All three registered bars pass.** Outcome feedback absorbs ~77% of the
attack's hit@1 damage on STAR (sim loses 1.11 pts, rfm 0.25) and ~67% on
ABCD; poison's mean top-5 occupancy roughly halves (2.4%→1.1% STAR,
grows over the stream under sim, held flat under rfm). Survival is the
starkest view: a poisoned memory sustains up to **29 retrievals under
similarity vs 6 under outcome ranking** on STAR (38 vs 13 on ABCD).
The defense survives 20% sign-flipped feedback (E2 +0.0055, CI > 0; max
survival 7). The junk attacker is completely inert (3 of 869 ever
retrieved) — damage requires semantic mimicry, which is also why
admission gates can't stop it. Honest bounds: absolute damage is small on
these dense stores even at r=0.20 (hit@5 barely moves — abundant genuine
recurrence is itself a defense), the low-rate r=0.05 DiD is n.s. (exposure
defense still CI-positive), and outcome signals are oracle throughout;
first-use damage before feedback lands is inherent to the mechanism and
visible in the survival floor.

## Amendment 6 one-shot: score-gaming (R/F/M) and the hardened defense

Runs 2026-08-09, MiniLM, k=5, frozen β=0.3, mimic injection r=0.20. Logs:
`exploit_star_both.log` (primary), `exploit_star_{rf,m}.log`,
`exploit_abcd_both.log`, `exploit_star_pump{10,200}.log`.

| endpoint (bar) | STAR (pump=50) | ABCD (pump=50) | verdict |
|---|---|---|---|
| X1 exploit real: occ rfm − sim CI>0 | **+0.0444** [+0.0409,+0.0479] | **+0.0491** [+0.0447,+0.0539] | **pass** |
| X2 hardening removes lift: occ rfm − rfm_hard CI>0, and rfm_hard ≤ sim | **+0.0571** [+0.0533,+0.0610]; 0.011 ≤ 0.024 | **+0.0671** [+0.0615,+0.0726]; 0.035 ≤ 0.053 | **pass** |
| U1 utility under attack: h@1 rfm_hard − rfm CI ≥ 0 | **+0.0562** [+0.0494,+0.0632] | **+0.0650** [+0.0553,+0.0750] | **pass** |
| U2 utility on clean store: \|Δ\| ≤ 0.010 (veto bar) | **+0.0009** [−0.0009,+0.0030] | **+0.0020** [−0.0020,+0.0060] | **pass** |

**The headline is a warning about our own mechanism: under score-gaming an
unhardened usage prior is WORSE THAN NO PRIOR.** At pump=50 the attacker
lifts poison occupancy to 0.068 vs similarity's 0.024 and drives legitimate
hit@1 *below* the similarity baseline (0.884 vs 0.920); at pump=200,
0.127 occupancy and 0.822 hit@1 — a 9.8-point utility loss inflicted by an
attacker doing nothing but calling `rfm_record_access`/`rfm_record_outcome`
on its own memories. The bounded prior caps the gain (multiplier ceiling
1.0 vs a demoted 0.7 — a 1.43× reorder advantage, enough precisely because
mimic bait has near-identical similarity by construction) but does not
remove it.

**Hardening is complete, not partial.** `rfm_hard` is bit-identical across
every exploit mode and pump level (h@1 0.941, occupancy 0.011 on STAR) —
self-endorsement exclusion makes the attack a no-op, so gaming harder buys
nothing. It also lands *below* the similarity baseline on exposure, i.e.
the value axis returns to being an asset. (U2 is likewise identical across
STAR runs: the clean baseline does not depend on exploit parameters — a
consistency check, not a copy-paste.)

**Which axis is the soft target: M, not R/F.** At equal pump, value-EWMA
gaming yields +0.0234 occupancy lift vs +0.0075 for recency/frequency
gaming — activation is logarithmic in access count (diminishing returns),
while the value EWMA saturates toward +1 within a few self-reports. Pump
sweep: +0.0048 (10) → +0.0444 (50) → +0.1029 (200); gaming scales with
attacker effort, hardened mode does not move.

Bounds: oracle outcomes throughout; the attacker is a single principal
(collusion between principals is not modeled and would defeat
self-exclusion); actor strings are host-asserted, so this defends against a
principal misbehaving within its rights, not impersonation.
