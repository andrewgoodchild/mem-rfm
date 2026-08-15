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

### Post-hoc (NOT registered): hardened-mode cost vs team size

Amendment 6's U2 was registered at the 8-agent team size only. Because
`exclude_self` drops a memory's *own writer's* feedback, its cost should
scale inversely with team size — at a team of one, every legitimate memory
is self-authored and ALL legitimate feedback is discarded. Measured
(STAR, r=0.20, pump=50, `exploit_star_agents{1,2,4}.log`; agents=8 is the
registered run):

| team size | U2 clean-store h@1 (rfm_hard − rfm) | poison occupancy, rfm_hard |
|---|---|---|
| 1 (solo) | **−0.0080** [−0.0118,−0.0041] | 0.023 |
| 2 | −0.0016 [−0.0043,+0.0011] n.s. | 0.013 |
| 4 | −0.0009 [−0.0032,+0.0014] n.s. | 0.012 |
| 8 (registered) | +0.0009 [−0.0009,+0.0030] n.s. | 0.011 |

The footgun is real but small, and smaller than we predicted before
measuring: a solo store loses 0.80 points of hit@1 (CI excludes zero) —
which matches the size of the value axis's own rank-1 contribution on STAR
(+1.25, Amendment 4 P3), i.e. solo hardening costs roughly the whole value
signal, as the mechanism implies. It is NOT catastrophic, and the defense
still works solo (occupancy 0.023 vs 0.068 unhardened, ≈ similarity's
0.024). Guidance: leave `exclude_self` off for single-agent stores (the
Claude Code integration's default shape), turn it on from ~2 writers up,
where the cost is statistically indistinguishable from zero.

## Amendment 7 one-shot: downvote censorship, collusion, ballot-stuffing prevention

Runs 2026-08-09, STAR n=4,396, MiniLM, k=5, β=0.3, r=0.20, pump=50,
colluders=4. Logs: `adv_star_{upvote,downvote,collude}.log`. All three
registered predictions were confirmed.

| attack | A1: sim − rfm (is the attack real?) | best defense | defense vs sim |
|---|---|---|---|
| upvote (self-promotion) | **+0.0150** [+0.0082,+0.0221] real | rfm_self **+0.0359** | **+0.0209** (above baseline) |
| downvote (targeted censorship) | **−0.0136** [−0.0182,−0.0091] — **no attack effect** | none needed | rfm already +0.0136 above sim |
| collude (4 cross-endorsers) | **+0.0503** [+0.0419,+0.0589] severe | **none** | **−0.056 to −0.068** (all defenses below sim) |

**1. `one_vote` (ballot-stuffing prevention) does not work — rejected as
recommended guidance.** Against self-promotion it recovers nothing
(+0.0014 [−0.0030,+0.0057], n.s.) and leaves the store 1.36 points *below*
plain similarity, while costing real utility on a clean store (−0.0034
[−0.0059,−0.0009], CI excludes zero — inside the ±0.010 veto bar but
buying nothing for it). Mechanism: capping outcomes at one per (actor,
memory) throttles the *corrective* signal exactly as much as the abusive
one — an 8-agent team can now land at most 8 negatives on a bad memory
instead of one per wasted retrieval. It ships as an off-by-default option,
documented as not recommended. `exclude_self` remains the effective
single-actor defense (+0.0359 recovery at +0.0009 clean-store cost).

**2. Targeted censorship is structurally impossible under β-bounding
(prediction 2 confirmed).** An attacker burying every genuine memory of the
4 highest-volume labels achieved nothing: on the censored labels
themselves, outcome ranking beat similarity by **+0.0214**, and the
attacked store's overall hit@1 (0.944) equals its clean-store hit@1
(0.944) — full absorption. The bounded prior floors demotion at 0.7×,
which is smaller than the similarity gap between right-label and
wrong-label memories, so suppression cannot reorder retrieval. The bound
frozen for rank-safety in the original composition experiment turns out to
be a security property. Both hardening flags are unnecessary here and
slightly negative (−0.0016 to −0.0048).

**3. Collusion is a real, unmitigated hole (prediction 3 confirmed).** Four
attackers cross-endorsing each other's bait cost **5.0 points** of hit@1
and tripled poison occupancy (0.083 vs similarity's 0.024). No defense
recovers: `exclude_self` is blind by construction (nobody endorses their
own), `one_vote` is structurally powerless (colluders *are* distinct
endorsers), and every configuration lands 5.6–6.8 points *below* the
no-prior baseline — the defenses marginally worsen it by weakening
legitimate memories while leaving the attack untouched. **Under collusion,
do not run a usage prior on a shared store.** A trust/reputation layer
(per-origin weighting) is the candidate answer and is unbuilt and
unmeasured.

Bounds: single dataset (STAR), oracle outcomes, actor strings host-asserted
(impersonation is the host's auth problem, not defended here), and the
attacker count is fixed at 4 — the collusion damage curve vs colluder count
is unmeasured.

## Amendment 8 one-shot: writer-reputation trust cap, and collusion detection

Runs 2026-08-09. Logs: `adv8_star_{collude,upvote,downvote}.log`,
`adv8_abcd_collude.log`.

| endpoint | STAR collude | ABCD collude | verdict |
|---|---|---|---|
| A1 attack real (sim − rfm) | +0.0503 [+0.0419,+0.0589] | +0.0537 [+0.0417,+0.0657] | — |
| **T1 trust recovers** (rfm_trust − rfm) | +0.0039 [+0.0000,+0.0080] | **−0.0023** [−0.0093,+0.0047] | **FAIL** |
| T2 restores baseline (rfm_trust − sim) | −0.0464 | −0.0560 | fail (as predicted) |
| U utility veto (clean store) | −0.0005 [−0.0023,+0.0011] | +0.003 | pass (free) |
| **D1 detector** `concentration` precision@4 | **4/4**, sep +0.332 | **4/4**, sep +0.332 | **pass** |
| D2 `dissent` precision@4 | 0/4, sep −0.136 | 0/4, sep −0.356 | fails (inverts) |
| D2 `reciprocity` precision@4 | 1/4, sep +0.000 | 2/4, sep +0.000 | fails (no signal) |

**1. Writer reputation does NOT defend collusion — T1 fails.** It recovers
0.4 of the 5.0 points on STAR (CI lower bound at zero) and is flatly
negative on ABCD. Cause, read off the committed log: **a ring's
cross-endorsements are themselves third-party votes**, so colluders build
each other's *reputation* exactly as they build each other's memory scores
— ring member trust came out at +0.400 while an honest agent sat at −0.314.
Moving aggregation from memories to authors moves the attack up one layer
instead of defeating it. Recorded as a failed hypothesis.

**2. The same mechanism IS the best single-actor defense.** Against
self-promotion, `exclude_self`+trust reaches **0.941 hit@1 at 0.006 poison
occupancy** — a quarter of plain similarity's exposure and the best of any
configuration measured (trust alone +0.0259, with exclude_self +0.0366).
A lone attacker cannot build their own reputation (self-votes are excluded
by construction), so the cap binds hard. Cost is nil (U bar −0.0005). On
the downvote scenario trust is mildly unhelpful (−0.0045) — unnecessary
there, as β-bounding already absorbs censorship.

**3. Collusion is DETECTABLE even though it is not rankable.**
`concentration` (entropy deficit of the authors a voter praises) achieved
**4/4 precision on both datasets** from the access log alone — no scoring
state, so an auditor can run it post-hoc on committed data. Both intuitive
alternatives failed, and their failures are the more transferable lesson:
`dissent` (disagreeing with per-memory consensus) **inverts**, because a
ring that stuffs ballots *manufactures* the consensus and the detector then
flags the honest majority (separation −0.136/−0.356); `reciprocity` shows
no separation at all, because honest teammates also endorse each other's
memories in the normal course of work. Only a signal the ring cannot
manufacture — how *narrowly* its praise is distributed — separates.

Standing conclusion: **you cannot out-rank a ring, but you can spot one.**
The defense for colluding writers is detection plus governance, not
scoring.

## Amendment 9 one-shot: can any vote-aggregation defend a ring? No.

Runs 2026-08-09. Logs: `adv9_star_{collude,upvote}.log`,
`adv9_abcd_collude.log`. **Both registered candidates FAIL V1.**

| condition | STAR collude (V1) | ABCD collude (V1) | vs sim (V2) | clean-store U |
|---|---|---|---|---|
| C1 one_vote × trust | **−0.0057** [−0.0109,−0.0005] | **−0.0197** [−0.0277,−0.0117] | −0.056 / −0.073 | −0.0034 / −0.0090 |
| C2 voter-weighted trust | **+0.0032** [−0.0009,+0.0075] | **−0.0057** [−0.0120,+0.0010] | −0.047 / −0.059 | −0.0009 / +0.0000 |

**C1 was wrong in sign, not just magnitude.** The registered prediction was
"partial recovery that still fails V2"; it is significantly NEGATIVE on both
datasets. Combining the two flags compounds their weaknesses — each rations
honest signal (one_vote caps corrective downvotes; trust caps value by an
author reputation the ring also controls) while neither touches the ring.
It additionally carries one_vote's utility cost. Rejected outright.

**C2 beat C1 as predicted, and still failed.** Free on a clean store
(U ≈ 0) but recovery CIs include zero on STAR and are negative on ABCD.
Cause: a single EigenTrust iteration cannot break a mutually-reinforcing
cycle — crony A's standing is built from B's votes weighted by B's
standing, which is built from A's. Real EigenTrust breaks the cycle with
**pre-trusted seed peers**, which is a governance input, not something
derivable from the access log.

**Systematic negative, now with a unifying explanation.** Five
configurations have been measured against a 4-member ring — exclude_self,
one_vote, one_vote×trust, writer trust, voter-weighted trust — and none
recovers. They fail for one reason: **the ring controls votes at every level
of aggregation** (per memory, per author, per voter-weight), so
re-aggregating votes cannot escape it. Per Amendment 9's registration, the
standing conclusion is that **detection plus governance, not ranking, is
the answer for colluding writers** (the concentration detector reaches 4/4
precision on both datasets, Amendment 8).

**Single-actor guidance is unchanged and stable**: on the upvote scenario
both new conditions help (+0.0221 / +0.0243) but neither beats
`exclude_self`+`trust`, which remains the best measured configuration
(0.941 h@1, 0.006 poison occupancy vs similarity's 0.024).

## Amendment 10 one-shot: endorser liability (the prisoner's-dilemma mechanism)

STAR collude, n=4,396, C=4, r=0.20, pump=50. Log:
`adv10_star_collude.log`. Cross-checks (upvote, ABCD) were interrupted and
re-run separately; see below.

| endpoint (bar) | result | verdict |
|---|---|---|
| **L1 recovery** (rfm_liable − rfm, CI>0) | **+0.0080** [+0.0036,+0.0123] | **PASS** — first mechanism to clear it |
| L2 restoration (− sim ≥ 0) | −0.0423 [−0.0505,−0.0343] | fail (as predicted) |
| **L3 ring collapse** (separation > 0.3) | **+1.684** (attackers −0.734 vs honest +0.950) | **PASS** |
| U utility veto (clean store) | +0.0007 [−0.0011,+0.0025] | pass (free) |

**The incentive mechanism works exactly as theorised at the reputation
layer.** Making an endorsement a stake rather than a free favour collapses
ring standing to −0.734 while honest agents rise to +0.950 — the ring's
mutual praise becomes mutually destructive, because every failed retrieval
of a co-conspirator's bait now debits the voucher as well as the author.
Poison occupancy falls from 0.083 to 0.072 and it is free on a clean store.

**But reputation separation converts into only a modest retrieval gain**:
+0.8 points recovered of the 5.0 the ring costs (~16%), still 4.2 points
below the no-prior baseline. The registration anticipated this: bait
retrieved BEFORE the ring's standing collapses is damage no post-hoc
mechanism can undo. Liability changes the ring's incentives and its
eventual standing; it does not retroactively un-serve the bait.

**CORRECTION to Amendment 10's registration.** The registration claimed
"Amendment 8 measured NO separation: +0.400 attacker vs −0.314 honest".
That was wrong — those were two cherry-picked rows from a detector table,
not means. The correct baseline, printed alongside the liable store in this
run, is a MEAN separation of **+0.539** under plain trust. So L3's stated
premise was false, and its bar (>0.3) was already met without liability.
The defensible claim is the comparison, not the threshold: liability
**triples** reputation separation (+0.539 → +1.684). The endpoint is
recorded as passed on its literal terms with this premise error disclosed.

Standing conclusion, unchanged: incentive-shaping is the only mechanism of
six tried that recovers anything against a ring with CI > 0, and it still
leaves the store well below similarity-only. Detection plus governance
remains the answer; liability is a useful adjunct, not a fix.

### Amendment 10 cross-checks (completed after an interrupted batch)

Logs: `adv10_star_upvote.log`, `adv10_abcd_collude.log`.

| check | result |
|---|---|
| upvote: `exclude_self`+liability | **0.943 h@1 / 0.006 occupancy** — best configuration measured, edging `exclude_self`+trust (0.941/0.006); recovery +0.0380 |
| **ABCD collude: L1 replication** | **+0.0013 [−0.0060,+0.0087] — FAILS to replicate** (STAR was +0.0080, CI>0) |
| ABCD collude: L3 replication | **+1.695 separation** (attackers −0.981 vs honest +0.714) vs baseline +0.847 — replicates |
| ABCD collude: U | −0.0033 [−0.0090,+0.0023] — within bar |

**The retrieval gain does not replicate; the reputation collapse does.**
Liability's L1 recovery is significant on STAR and null on ABCD, so the
honest claim is that it does NOT reliably improve retrieval under
collusion. What replicates on both datasets is L3: ring standing collapses
to −0.734 / −0.981 while honest agents sit at +0.950 / +0.714, roughly
doubling the separation plain trust achieves.

That sharpens rather than weakens the standing conclusion. Liability's
value is that it makes a ring **identifiable and costly**, not that it
repairs ranking — which is exactly the "detect, don't rank" position the
concentration detector already supported. Liability also helps the
single-actor case (+0.0380) and is free on a clean store, so it is a
reasonable default for a shared store; it is not a collusion fix.

## Amendment 11 dev sweep: ACT-R parameters and decay kernels

BEAM dev only, MiniLM, paired NDCG@10 against the frozen configuration.
Runner: `model_eval.py`. No selection applied — freezing and the one-shot
test run come next.

**Runner bug found and fixed before these numbers.** A first version gave
never-accessed memories a sentinel activation instead of the extension's
creation-age fallback (`−d·ln(L)`). Because most BEAM memories are never
retrieved, every kernel collapsed to the same constant and all variants
scored identically — the tell was three exponential half-lives and the
count-only model returning byte-identical NDCG. The runner now carries a
`--selfcheck` that reconciles its in-process activation against the shipped
extension (exact for n ≤ 2; the n = 3 divergence is Petrov's approximation
working as designed).

**V3 decay kernel — the substantive result.** The power law wins:

| model | Δ NDCG@10 vs frozen |
|---|---|
| ACT-R power law | baseline |
| exponential, 1-day half-life | −0.029 [−0.041, −0.018] |
| exponential, 7-day half-life | −0.031 [−0.043, −0.020] |
| exponential, 30-day half-life | −0.027 [−0.037, −0.017] |
| Codex model (citation count, no decay) | −0.022 [−0.033, −0.012] |

This is, as far as we know, the first empirical comparison of decay kernels
in agent memory, and it replicates what the recommender-systems literature
found on human access streams (Kowald et al., WWW'17, rejecting the
exponential at p<.001). It also answers "should we just do what Codex does":
citation-count ranking with no decay is 2.2 NDCG points worse than ACT-R
activation on this dev set.

**V1 squash (theta, s).** The hardcoded default is essentially the best of
the grid: `theta=0, s=0.2` gives +0.0046 [−0.0001, +0.0094] (CI includes
zero) and every other setting is worse — lowering τ costs up to −0.063.
Lowering τ lifts P(B) toward saturation, i.e. increases the activation axis's
influence, and that **hurts** — the same conclusion the original composition
experiment reached from the other direction. The bound is the finding, not a
compromise.

**V2 procedural weighting.** +0.0033 to +0.0035, CIs at or barely above zero.
Not a result. BEAM is also the wrong dataset for it: its labels are evidence
turns, not procedures, and no outcome feedback accumulates there, so the
value axis is constant. Testing this properly needs the procedure-labelled
dialog datasets.

Caveats on all of the above: dev set, one embedder, value axis inert.
