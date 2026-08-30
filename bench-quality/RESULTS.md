# Composition experiment log (per PROTOCOL.md)

> Outcomes for the pre-registrations that govern them, which live in
> [`../PROTOCOL.md`](../PROTOCOL.md). Each entry names the amendment it
> answers, and failures are reported at the same length as successes.

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
bench-quality/live-ab/: 8 chronological SWE-Bench-CL pytest tasks, paired
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
4. **Validation provenance documented.** bench-quality/live-ab validation ran
   three times while era pins evolved (validation.v1/.v2/.jsonl are all
   committed); 8 sphinx tasks including sphinx-7590 (one of the two
   discordant tasks) validated only under the final pins. 7590's harness
   environment being marginal is an additional reason to treat the
   hard-task direction as suggestive, not established.
5. **Memory-audit artifact committed** (bench-quality/live-ab/memory-audit.md)
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


## Amendment 12: component ablation — does each part earn its place?

BEAM dev, 355 questions per arm, MiniLM, k=10, sequential protocol with
feedback so both scoring axes are live. Every arm scores through the shipped
extension's `rfm_prior()`. Runner: `ablation_eval.py`; rows in
`results-ablation/`.

| arm | NDCG@10 | Δ vs full | verdict |
|---|---|---|---|
| full | 0.4270 | — | baseline |
| **no_value** | 0.4215 | **−0.0055** [−0.0094,−0.0018] | **earns its place** |
| no_activation | 0.4290 | +0.0020 [−0.0022,+0.0061] | within noise |
| no_prior | 0.4268 | −0.0002 [−0.0031,+0.0029] | within noise |
| no_shrink | 0.4301 | +0.0031 [−0.0040,+0.0096] | within noise |
| no_decay | 0.4271 | +0.0001 [−0.0041,+0.0044] | within noise |
| fast_decay | 0.4291 | +0.0021 [−0.0019,+0.0062] | within noise |
| **plus_hebbian** | 0.3949 | **−0.0321** [−0.0445,−0.0197] | **adding it HURTS** |
| plus_consolidation | 0.4277 | +0.0007 [−0.0004,+0.0022] | no effect |
| plus_both | 0.3957 | −0.0312 [−0.0437,−0.0188] | adding it hurts |

**Only the value axis earns its place on this benchmark.** Removing outcome
feedback costs 0.55 NDCG points with a CI excluding zero; removing the
activation axis, the confidence shrink, or varying the decay rate all sit
within noise. That is an uncomfortable result about our own system and it is
consistent with everything else we have measured: activation-only retrieval
collapses (NDCG ≈ 0.01), raising the activation axis's influence hurts
(Amendment 11, up to −0.063), and the bounded prior reaches parity rather
than superiority. On BEAM, given similarity plus outcome feedback, ACT-R
activation adds nothing detectable.

`no_prior` doubles as the harness's **positive control**: β=0 makes the prior
a constant, the liveness check correctly reports the signal as dead, and the
NDCG delta is ~0 — exactly the published parity finding, reproduced by a
different code path.

**Hebbian co-retrieval association is actively harmful — 3.2 NDCG points.**
This was predicted before the run: association reinforces whatever was
already retrieved, which is precisely the rich-get-richer dynamic the value
axis exists to break. The `ln(fan)` discount from ACT-R's fan effect was not
enough to save it. Interleaved replay of valuable-but-cold memories had no
detectable effect over this horizon (BEAM's streams are likely too short for
a forgetting-recovery mechanism to matter).

Two harness bugs were found and fixed *during* this study, both of the class
that silently invalidates results:

1. `no_prior` initially returned **exactly** +0.0000 across all 355
   questions. `common.rank`'s `rfm_beta*` path recomputes the blend in Python
   with a literal β and never reads `rfm_config('beta', …)`, so the arm was
   measuring nothing. Fixed by adding `MemoryStore.priors()`, which calls the
   extension's own `rfm_prior()` so every config key actually applies. An
   exact zero across hundreds of paired questions is the signature to watch
   for.
2. The verdict labels were **sign-inverted for the additive arms** — a
   negative delta means "adding this hurts", not "this earns its place". The
   first render called Hebbian a success. Ablation and addition arms now use
   separate interpretation logic.

Caveats: one dev benchmark, one embedder, and BEAM's short feedback streams
are the least favourable setting for both the activation axis and
consolidation. This says these components are unproven *here*, not that they
are useless — but "unproven" is the honest status until something proves
them, and no comparable system has run this study at all.

### Amendment 12, stratified by recurrence

Pooling across recurring and non-recurring questions diluted the effect the
ablation exists to detect. BEAM labels each question `overlap` — whether its
evidence already served an earlier question, i.e. whether the memory is being
*re-used*. Splitting on it:

| arm | recurring (n=108) | fresh (n=247) |
|---|---|---|
| **no_prior** | **−0.0072** [−0.0141,−0.0013] | **+0.0028** [+0.0002,+0.0064] |
| **no_value** | **−0.0095** [−0.0171,−0.0026] | −0.0037 [−0.0083,+0.0005] |
| no_activation | +0.0020 [−0.0044,+0.0087] | +0.0021 [−0.0032,+0.0072] |
| no_shrink | +0.0134 [+0.0000,+0.0267] | −0.0014 [−0.0097,+0.0060] |
| no_decay | −0.0025 [−0.0096,+0.0043] | +0.0012 [−0.0040,+0.0065] |
| plus_hebbian | −0.0414 [−0.0646,−0.0189] | −0.0281 [−0.0429,−0.0141] |

**The usage prior earns its place exactly where the theory says it should,
and is mildly harmful where it says it shouldn't.** Removing the prior
entirely costs 0.72 points on recurring evidence and *gains* 0.28 points on
fresh evidence, both CIs excluding zero. This is the recurrence finding
appearing inside a single benchmark rather than across corpora, and it is a
sharper statement of the published cost result: the bounded prior's "cost
≈ 0 vs similarity" is a **net** of a real benefit on re-used evidence and a
real, smaller penalty on evidence seen once.

**The benefit is entirely the outcome axis.** Removing value costs 0.95
points on recurring evidence — nearly double the pooled figure — while
removing activation remains within noise **in both strata**. So the earlier
result was not an artifact of averaging over a hostile subset: even on the
slice where re-use actually happens, and where the prior as a whole is
demonstrably load-bearing, the recency/frequency axis contributes nothing
detectable.

Secondary, and unexpected: **the confidence shrink may be counterproductive
on recurring evidence** (+0.0134, CI lower bound at zero). Where outcomes
have accumulated, pulling value toward neutral appears to cost more than the
noise it suppresses. That is a testable hypothesis about `shrink_k`, not a
finding — n=108 and the interval touches zero.

`plus_consolidation` returns exactly +0.0000 on the fresh slice. Given that
replay refreshes *activation*, and activation is inert here, a null is the
expected outcome rather than a dead channel — the arm does move on the
recurring slice (+0.0023), so the mechanism is live. Noted because an exact
zero otherwise warrants suspicion.

Caveat: the recurring slice is 108 questions and the intervals are wide.

## Amendment 12b: the recurrence gradient — the flat-line prediction FAILED

Four corpora, stream length fixed at n=1500 so recurrence per label is the
only varying quantity. Runner: `gradient_eval.py`.

Δ hit@1 vs full (* = CI excludes zero):

| corpus | recurrence/label | no_value | no_activation | no_prior |
|---|---|---|---|---|
| FloDial | 150.0 | −0.0007 | −0.0007 | −0.0020 |
| **STAR** | 71.4 | **−0.0067\*** | **−0.0067\*** | **−0.0140\*** |
| ABCD | 27.3 | −0.0080 | −0.0040 | −0.0020 |
| MultiDoc2Dial | 3.5 | +0.0013 | +0.0020 | +0.0073 |

**The registered prediction was wrong, and the correction favours the
activation axis.** Amendment 12b predicted either a monotonic rise in
`no_activation`'s cost with recurrence, or a flat line falsifying the
recurrence defence. Neither happened. On STAR, **removing activation costs
exactly as much as removing outcome feedback** (both −0.0067, both CIs
excluding zero), and removing the prior entirely costs more than either
(−0.0140) — the two axes are contributing roughly additively.

So the Amendment 12 conclusion — "only the outcome axis earns its place" —
**was benchmark-specific and is hereby narrowed to BEAM.** On STAR the ACT-R
half earns its place on equal terms. The claim in `docs/findings.md` and
`docs/theory.md` has been corrected accordingly.

The relationship is not monotonic in recurrence, and the two nulls at the
ends have different causes:

- **FloDial (highest recurrence) is at ceiling.** With 10 labels its
  team-pooled baseline is hit@1 0.984 / hit@5 0.994 (Amendment 4). There is
  no headroom for any prior to demonstrate anything, so a null there measures
  the benchmark, not the mechanism.
- **MultiDoc2Dial (lowest recurrence) has no history to work with** — 3.5
  calls per label over 433 labels — and every arm is *positive*, i.e.
  removing the prior helps slightly. That matches the fresh-evidence stratum
  in Amendment 12 (+0.0028): with nothing recurring, the prior is a small net
  cost.
- ABCD sits between and is directionally consistent but not significant.

The honest shape is therefore a **recurrence sweet spot rather than a
gradient**: the prior needs enough history to differentiate candidates *and*
enough headroom left by the retriever to matter. Too little of either and it
measures nothing.

Caveat: one seed, one embedder, n=1500 per corpus, and no correction for
testing four corpora — STAR's result should be replicated before it is
leaned on.

## Amendment 13: does ACT-R earn its complexity? Not against rank-based RFM.

STAR, n=1500, k=5, MiniLM. Every arm shares the outcome axis, β and the
composition; only the activation term differs. Runner: `formula_eval.py`.

| arm | hit@1 | Δ vs actr | hit@5 | Δ vs actr |
|---|---|---|---|---|
| **actr** (frozen) | 0.9373 | baseline | 0.9640 | baseline |
| simple_rfm (weighted sum) | 0.9266 | **−0.0107\*** | 0.9586 | **−0.0053\*** |
| **quintile_rfm** (marketing) | 0.9346 | **−0.0027** [−0.0093,+0.0040] | 0.9640 | **+0.0000** |
| recency_only | 0.9306 | −0.0067\* | 0.9606 | −0.0033 |
| frequency_only | 0.9159 | −0.0213\* | 0.9600 | −0.0040 |

*(\* = CI excludes zero.)*

**Two findings, pointing in opposite directions.**

ACT-R **beats** the naive separate-axis form — a weighted sum of
`exp(−Δ/τ)` and `ln(1+n)` costs 1.07 points hit@1, CI excluding zero. So
unifying recency and frequency into one log-sum quantity is genuinely better
than adding two independently-scored axes. That much of the cognitive-science
formulation is doing real work.

But ACT-R **does not beat the classical marketing formula.** Per-query
quintile ranks of R, F and M, summed, land within noise at hit@1 and
*exactly equal* at hit@5. **Amendment 13 registered an asymmetric bar before
this ran — a tie goes to the simpler form, because it removes the
`bla_cache` column, the Petrov approximation and a conformance obligation. On
this evidence ACT-R has not earned its complexity.**

Two observations that shape what to do about it rather than explain it away:

1. **Recency carries the simple form; frequency alone is much worse**
   (−0.0067 vs −0.0213). Whatever the activation axis contributes here is
   mostly recency.
2. **The comparison is confounded in ACT-R's disfavour, and we knew about
   the confound beforehand.** `quintile_rfm` gets per-query rank
   normalisation for free, while `actr` passes activation through a logistic
   whose centre and width are *unfitted* — Amendment 11 measured P(B) sitting
   at 0.006–0.016, i.e. the squash operating in its far-left tail across the
   whole store. A fitted ACT-R and a rank-normalised RFM have not been
   compared; an unfitted ACT-R and a rank-normalised RFM have.

**Recommendation, and it is not "keep it because it's principled":** fit
`theta`/`s` (Amendment 11 V1 left this explicitly open, and the config keys
now exist) and re-run this comparison. If fitted ACT-R still ties with
quintile ranks, the honest response is to simplify — drop the Petrov
machinery and score the axes separately by rank. The provenance of an
equation is not a reason to keep it.

Caveats: one corpus, one embedder, one seed. The CI on quintile_rfm is
[−0.0093, +0.0040], which does not exclude a real ACT-R advantage of up to
~0.9 points — "within noise" is not "equal", and the registered bar treats it
as a tie by choice, not by demonstration of equivalence.

## Amendment 14: the value axis against REAL outcomes

terminalbench trajectory corpus, 89 tasks × ~586 test-verified binary trials,
streamed in real timestamp order through the shipped extension. Ground truth
is each task's empirical success rate. Runner: `calibration_eval.py`.
**Every other outcome number in this repo is oracle-derived; this is the
first test against real ones.**

### C2 — it works. Spearman 0.72–0.83.

| shrink_k | n=5 | n=10 | n=25 | n=50 |
|---|---|---|---|---|
| any | +0.723 | +0.809 | **+0.828** | +0.795 |

The value axis **recovers true utility ordering from real, test-verified
outcomes**, reaching ρ=0.83 after 25 observations. That is the single most
important validation in this project: the mechanism was designed and tuned
entirely against oracle labels, and it transfers.

Note the ranking is **identical across every `shrink_k`**. That is not a bug:
shrink multiplies by `n/(n+k)`, so among memories with equal outcome counts it
is a monotone transform and cannot reorder them. Shrink only affects
comparisons between memories with *different* n. Worth knowing — it means the
parameter does nothing at all in the common case of comparing equally-observed
memories.

### C1 — the frozen λ is right for cold start and wrong at scale

Mean |effective value − true rate|:

| config | n=5 | n=10 | n=25 | n=50 |
|---|---|---|---|---|
| **λ=0.3, k=3 (frozen)** | **0.1484** (best) | 0.1496 | 0.1560 | 0.1870 |
| λ=0.1, k=10 | 0.1767 | 0.1493 | **0.1237** | **0.0977** |

The frozen configuration is the **best in the grid at n=5 and the worst
trajectory thereafter** — its error *grows* with more evidence (0.148 → 0.187)
while λ=0.1 halves (0.177 → 0.098).

**Mechanism, and it is a real design property rather than a tuning miss.** An
EWMA with fixed λ has a fixed effective window of roughly 1/λ samples. At
λ=0.3 the estimate is permanently a ~3-sample average: it never converges, it
tracks recent noise forever. That is exactly what you want for *adaptivity* —
it is why the staleness result works (update-preference 0.43 → 0.66 requires
forgetting the old value fast) — and exactly what you don't want for
*calibration*.

So the value axis has an unavoidable tension we had not named: **adaptivity
and calibration pull λ in opposite directions.** A memory store that must
notice a changed procedure wants high λ; one that must estimate stable utility
wants low λ. Ours is tuned for the former.

### C3 and the falsified prediction

The registered prediction — "the best shrink_k should fall with n" — is
**wrong**. Best k *rises* (3, 3, 10, 10), because with a fixed-λ EWMA the
estimate stays noisy no matter how much data arrives, so variance reduction
keeps paying. The prediction assumed the estimator converges. It doesn't.

λ=0.3 is not within noise of the grid's best beyond n≈10, so **C3 fails**. The
honest options are to expose λ with the tradeoff documented (done — it is a
config key), or to make λ decay with n so the estimator behaves like a running
mean early and an EWMA later. The latter is unbuilt and untested.

Caveats: one corpus; binary rewards from 49 different models attempting the
same tasks, so "true rate" is task difficulty averaged over model capability,
not the difficulty any single agent would experience; and no frequency
variance, so nothing here speaks to the R/F axis.

## Amendment 13b: fitted ACT-R still loses to the marketing formula

Squash fitted on **ABCD** (held out from the evaluation), then a single run on
STAR. Grid theta ∈ {0,−2,−4,−6} × s ∈ {0.5,1,2}; best on ABCD was
theta=−6, s=1.0 (hit@1 0.6681 against the frozen 0.6656).

**First result: fitting barely matters.** The whole grid spans 0.640–0.668 on
ABCD and the frozen default sits within 0.003 of the best. The confound raised
in ACT-R's defence in Amendment 13 — that its logistic was unfitted and
operating in its far-left tail — is real but **not load-bearing**.

**Second result: the fit did not transfer.** Applying ABCD's best (theta=−6)
to STAR gave hit@1 0.9300, *worse* than the unfitted 0.9373 in Amendment 13.
So ACT-R's squash wants per-corpus fitting, which is a further cost rather
than a defence.

Held-out evaluation on STAR:

| arm | hit@1 | Δ vs actr | hit@5 | Δ vs actr |
|---|---|---|---|---|
| actr (fitted) | 0.9300 | baseline | 0.9580 | baseline |
| **quintile_rfm** | 0.9346 | +0.0047 [−0.0020,+0.0113] | 0.9640 | **+0.0060\*** [+0.0013,+0.0107] |
| simple_rfm | 0.9266 | −0.0033 | 0.9586 | +0.0007 |

**The marketing quintile formula now beats fitted ACT-R at hit@5 with a CI
excluding zero, and leads at hit@1.** Amendment 13's asymmetric bar — ties go
to the simpler form — is no longer even needed; this is not a tie.

### What follows, and one honest complication

By the registered rule the conclusion is to **simplify**: per-query quintile
ranks of R, F and M rank at least as well as `ln(Σ tᵢ^−d)`, which would make
`bla_cache`, the Petrov k=2 approximation and the conformance suite against
three reference implementations all unnecessary machinery.

The complication is architectural rather than statistical, and it is not a
reason to ignore the result. **ACT-R's score is row-local; a quintile score is
set-relative.** `rfm_prior(id)` is a scalar function returning a value from
one row, which is what makes `ORDER BY sim * rfm_prior(id) DESC LIMIT 5`
work. Quintiles need the candidate set — implementable in SQLite with
`NTILE(5) OVER (...)`, since the set is materialised for similarity anyway,
but it is a different shape: a query-time window function rather than a
one-row read. The O(1)-per-row claim would go with it.

So the honest position is: **on ranking quality the cognitive-science
formulation is not earning its complexity, and we have now tested that twice
with the obvious defence closed.** Before removing it we would want
replication on a third corpus and a second embedder, because this is two
corpora and one model — but the burden of proof has shifted onto ACT-R, and
"it is principled" is not evidence.

## Amendment 13c: why the orderings came out that way (bucket sweep + diagnostics)

STAR, n=1500. Bucket count for the rank-normalised form, plus the dynamic
range each arm's prior actually uses.

| arm | hit@1 | prior spread |
|---|---|---|
| actr | **0.9373** | 0.1878 |
| binary_rfm (2 buckets) | 0.9246 | 0.2999 |
| tercile_rfm (3) | 0.9273 | 0.2805 |
| **quintile_rfm (5)** | **0.9346** | 0.2688 |
| decile_rfm (10) | 0.9306 | 0.2480 |
| percentile_rfm (continuous) | 0.9300 | 0.2304 |
| simple_rfm | 0.9266 | 0.2623 |

**Bucket count has an interior optimum at 5** — an inverted U, not monotone
in either direction. Too few buckets discard real signal; too many fit noise.
Standard bias–variance, and it means the marketing convention of *deciles*
is worse here (−0.0040 against quintiles) even though it is finer.

**Two mechanistic explanations were tested and falsified**, both recorded
because the failures are the informative part:

1. *"simple_rfm's axes saturate to near-constants."* Wrong — its prior spread
   (0.2623) is **larger** than ACT-R's (0.1878). It varies plenty; it varies
   about the wrong thing.
2. *"Coarser bucketing wins by suppressing noise."* Wrong — binary bucketing
   has the largest spread and the worst score, and quintiles beat deciles
   despite a larger spread. Prior dynamic range does not predict performance
   in either direction.

**What the diagnostics do support: both parametric transforms are
mis-calibrated for this corpus, in opposite directions.** Candidate ages at
mid-stream are p10 0.0 / median 0.2 / p90 1.3 days. Against that:

- `exp(−Δ/τ)` with τ = 1 day compresses at the **top** — median 0.80, p90
  0.97, nothing below 0.01. Nearly all candidates are "recent", so the axis
  spends its resolution on distinctions that barely exist.
- ACT-R's activation runs −5.8 to −3.9, which lands in the logistic's
  **far-left tail** where the slope is ~0.007, compressing a 1.9-unit spread
  into ~0.013 of output.

Both fixed-constant forms are wrong for this data, in opposite directions.
Rank buckets have no constants to get wrong — they are calibrated to the
empirical distribution by construction, which is why they need no per-corpus
tuning and why fitting θ/s (Amendment 13b) barely helped.

**What we cannot cleanly explain**: why ACT-R still beats `simple_rfm`
despite both being mis-calibrated and despite ACT-R's output being the more
compressed of the two. Spread does not account for it, and neither surviving
story predicts it. Recorded as unexplained rather than given a third
post-hoc rationalisation.

## Amendment 13d: which rank-bucket implementations actually work

The quintile result is only useful if it survives an implementation that fits
the architecture. Three candidates tested on STAR, n=1500, against `actr`:

| arm | hit@1 | Δ vs actr | hit@5 | Δ vs actr |
|---|---|---|---|---|
| actr | 0.9373 | baseline | 0.9640 | baseline |
| quintile_rfm (per-query, full set) | 0.9346 | −0.0027 | 0.9640 | +0.0000 |
| **A — buckets over a similarity shortlist** | 0.9313 | **−0.0060\*** | 0.9640 | +0.0000 |
| **B — maintained cutpoints, refresh/100** | 0.9320 | −0.0053 | 0.9653 | +0.0013 |
| **B — refresh/500** | 0.9346 | −0.0027 | 0.9673 | +0.0033 |
| **B — computed once, never refreshed** | 0.9333 | −0.0040 | **0.9706** | **+0.0067\*** |
| **C — logistic on maintained median/IQR** | 0.9280 | **−0.0093\*** | 0.9600 | **−0.0040\*** |

**B works, and staleness is not the problem I expected.** All three refresh
schedules land within noise of `actr` at hit@1 and at or above it at hit@5 —
and the *least* frequently refreshed arm is the best at hit@5 (+0.0067, CI
excluding zero). Cutpoints computed once from an early store and never
updated beat cutpoints refreshed every 100 calls. So maintained global
cutpoints reproduce the per-query quintile result while staying a row-local
lookup, which is the architectural question this set out to answer.

That the ordering runs *against* refresh frequency is unexplained and we are
not going to invent a mechanism for it — plausibly noise (the three B arms sit
within 0.005 of each other at hit@1), plausibly that stale coarse cutpoints
throttle the prior further. Worth a seed sweep before anyone leans on it.

**A is measurably worse.** Bucketing over a similarity shortlist is a
different quantity from bucketing over the store: shortlist membership is
query-dependent, so a memory's bucket shifts with the query. −0.0060 hit@1
with the CI excluding zero. The zero-code SQL recipe does *not* inherit the
measured result.

**C fails, as predicted before the run.** A logistic on maintained median/IQR
is significantly worse on both metrics, and its prior spread (0.1813) is the
narrowest of any arm bar `actr` (0.1878) — it reintroduces exactly the
fixed-parametric-form problem that Amendment 13c identified as the reason
`exp(−Δ/τ)` and the ACT-R squash are both mis-calibrated. Rank buckets win
by having no functional form to get wrong, and C puts one back.

**Practical upshot**: if the rank-bucket direction is pursued, the design is
a small `rfm_axis_cuts` table plus an `rfm_refresh_cuts()` maintenance call
and a `rfm_prior_ranked()` scalar function — O(1) scoring preserved,
`ORDER BY … LIMIT` unchanged, refresh interval evidently forgiving. Not built;
this measured whether it is worth building.

## Amendment 13e: the bake-off REVERSES Amendments 13–13d. ACT-R stays.

Four corpora × two embedders, n=1500, arms `actr` / `B_cuts_500` /
`quintile_rfm`. Δ hit@1 vs `actr` (\* = CI excludes zero):

| corpus | MiniLM: B | MiniLM: quintile | Qwen3: B | Qwen3: quintile |
|---|---|---|---|---|
| STAR | −0.0027 | −0.0027 | −0.0013 | −0.0033 |
| **ABCD** | **−0.0267\*** | **−0.0200\*** | **−0.0307\*** | **−0.0420\*** |
| FloDial (ceiling) | +0.0020 | −0.0013 | — | — |
| **MultiDoc2Dial** | **−0.0207\*** | **−0.0327\*** | — | — |

**ACT-R is never beaten and wins significantly on two of four corpora, under
both embedders.** The registered bar required the challenger to be at or above
`actr` in a clear majority of cells. It is not. **ACT-R keeps its place, and
the Petrov machinery, `bla_cache` and the conformance suite stay.**

### What went wrong in Amendments 13–13d

Every one of those amendments ran on **STAR alone**, and STAR turns out to be
the single corpus where ACT-R and rank bucketing tie. Generalising from it
produced a published conclusion — "on this evidence ACT-R has not earned its
complexity", and a claim in `docs/theory.md` that the burden of proof had
shifted onto ACT-R — that replication falsifies.

This is precisely the failure mode **Amendment 2 already caught in this same
repository**: BM25 hybrid fusion won on two development repos and reversed on
six held-out ones, and the repo split is what saved it. That lesson was
written down, in this file, and the ACT-R comparison was run single-corpus
anyway. A methodology is only worth what it is applied to.

The intermediate findings survive on their own terms and are not retracted:
ACT-R genuinely does beat the naive weighted-sum form (13); fitting θ/s
barely matters and does not transfer across corpora (13b); bucket count has an
interior optimum at 5 and both parametric transforms are mis-calibrated for
their corpora (13c); maintained cutpoints are a workable row-local
implementation of bucketing (13d). What does **not** survive is the conclusion
drawn from them.

Worth noting what the STAR tie is *not* evidence of: Amendment 12b found STAR
is the corpus where the activation axis most clearly earns its place. So
ACT-R's advantage over rank bucketing is largest where activation matters
*least* (ABCD, MultiDoc2Dial). We have no mechanism for that and are not
proposing one.

## Amendment 11 V2, properly run: procedural weighting shows nothing

Amendment 11 registered the procedural-weighting question but ran it on BEAM,
whose labels are evidence turns rather than procedures — the wrong venue. All
four dialog corpora ARE procedure-retrieval tasks, so this is the test that
was owed. n=1500, MiniLM, Δ vs the frozen 0.7/0.3 weights:

| corpus | balanced 0.5/0.5 | procedural 0.3/0.7 | utility only 0/1 |
|---|---|---|---|
| FloDial | +0.0007 | +0.0000 | −0.0020 |
| STAR | +0.0027 | +0.0013 | −0.0013 |
| ABCD | −0.0053 | −0.0027 | −0.0067 |
| MultiDoc2Dial | +0.0040 | +0.0033 | −0.0080 |

*(Δ hit@1; no cell reaches significance.)*

**Nothing is significant anywhere.** Shifting weight toward the utility axis —
which is exactly what `kind='procedural'` does — has no measurable effect on
corpora whose labels are procedures. The frozen 0.7/0.3 is fine.

One directional signal worth noting: **utility-only (w_a=0) is negative in all
eight cells** across both metrics. Individually none is significant, but eight
of eight in the same direction is weak corroboration that the activation axis
contributes something everywhere, consistent with Amendment 13e.

**Consequence for the `kind` column.** `docs/theory.md` stated in advance: "if
typing shows nothing on the procedure-labelled dialog datasets, the honest
response is to *remove* `kind` rather than extend it." Typing shows nothing.
The mechanism is implemented, connected and tested, and it fails the third bar
— it does not earn its place. **It was removed** — the column, the `w_a_proc`/`w_v_proc` config keys, the
kind-aware scoring branch and its test. Verified behaviour-neutral: BEAM
re-run and diffed against committed rows, 1,065 rows identical.

The *knowledge* finding it was built on survives and is unaffected:
procedural knowledge transfers and episodic per-task lessons don't (~6%).
That belongs in the capture policy — what you choose to store — rather than
in the ranking function, which is what the null established.

## Pilot 2 (exploratory, NOT pre-registered): hooks-era stack, live paired A/B

Run 2026-08-17. run_pilot2.py: 10 validated sphinx tasks (2020–2021,
era-coherent so operational gotchas CAN recur), chronological, paired
headless sessions, fresh store under live-ab/pilot2/. First run of the
harness-owned pipeline under load: SessionStart injection, SessionEnd
correction mining + inferred outcomes, ratify_staged.py standing in for
/memory-review (approve-all) between tasks. Arm isolation verified: 0/11
control transcripts carry the injection marker; 9/10 rfm transcripts do
(the first session's store was empty).

Task performance: memory did NOT help. Resolution 9/10 in BOTH arms
(sphinx-7462 failed in both — the task, not the arms). rfm slower on
every task (+13..+258s, median ~+45s), +45% assistant messages (42 vs
29), +87% output tokens (14.2k vs 7.6k). Net value on this workload:
negative — the savings the memories produced were real but smaller than
the machinery's per-session overhead.

Mechanism: every stage fired, and the ranking was RIGHT about what
mattered. The environment gotcha (era-pinned clone needs the PYTHONPATH
stubs workaround) earned helped=true in 9/10 sessions, value 0.965,
prior 0.21→0.41, rank 1 throughout — the July operational-fact finding
(+0.58 over 5 uses) replicating at +0.96 over 9. One of the two
hook-MINED candidates (the stubs pytest invocation) became the store's
#2 earner (9 accesses, 8 closed outcomes, value 0.80): the deterministic
miner out-earned nearly everything the agent saved deliberately.
Demotion operated live: two per-bug code lessons took negative feedback
(values −1.0 / −0.7) and sank; 8 more agent-saved per-bug lessons ended
at 0 outcomes (inert — rfm_prunable's signal). The two outcome channels
composed correctly: 15 explicit feedback calls (driven by the injection
trailer alone; the CLAUDE.md instruction block was stripped for the whole
run) plus 3 session_end-inferred outcomes landing exactly where explicit
feedback was missing. Formation staged only in session 1 and then went
quiet; feedback notes say the injected advice made later sessions pass
"on first try", so the failed-then-fixed pattern the miner needs stopped
occurring — the intended steady state.

Reading: consistent with the recurrence law, and it sharpens it into a
break-even bar — memory pays where the recurring cost it eliminates
exceeds per-session overhead (here ~45s wall + ~7k output tokens). These
1–8-minute episodic tasks sit under that bar; ABCD sits far above it.
Caveats: n=10, exploratory, resolution ceilinged by design; the
top-earning gotcha is partly an artifact of the harness's era pins (the
recurrence is real but the workload manufactured it); and overhead is
dominated by agent-VOLUNTEERED per-bug saves (11 of 13 saves, all
inert) that the harness-owned formation design says should not exist —
the cost side is reducible, and that is the next lever.

Trace committed: live-ab/pilot2/rfm-log.jsonl (full injection/feedback/
outcome log), live-ab/pilot2/results.jsonl (per-session rows),
live-ab/pilot2/pending-reviewed.md (what the miner staged). Session
transcripts and DBs stay untracked, per live-ab policy.

## Pilot 3 (exploratory, NOT pre-registered): cost interventions, and a confound

Run 2026-08-17, same 10 tasks, rfm arm only (the interventions do not
touch the control arm, so pilot 2's control rows remain the baseline).
Interventions: no volunteered saves (trailer + task prompt), injection
floor (outcome-demoted memories are never re-injected — pilot 2 re-
injected two demoted memories seven more times because feedback's implied
access kept refreshing their recency), feedback-on-surprise trailer with
session_end inference carrying routine outcomes, and the miner widened
with the environment-error class. The inference and miner changes were
validated OFFLINE first by replaying pilot 2's 21 transcripts
(miner_replay.py): two real bugs found and fixed — headless transcripts
carry the injection block in attachment records the parser never scanned,
and signatures were built from injection text truncated at the char
budget, cutting exactly the spans that identify acted-on commands.
Post-fix, inference recovers 9/15 of pilot 2's explicit outcomes with 0
sign flips; the 6 misses are relevance judgments, which is what the
trailer still asks for. The widened miner recovers pilot 2's top-value
gotcha with zero added noise; a generic *Error class stages ordinary test
failures (rejected); a frequency miner is confirmatory, not formative
(rejected — its only recurring invocation recurred BECAUSE injection
suggested it).

Overhead: GONE. Wall 1,055s total vs control 1,117s (pilot 2 rfm:
1,983s); 6.4k output tokens/session vs control 7.6k (pilot 2 rfm:
14.2k); 29.6 assistant messages vs 29 (42). Resolution 9/10 — sphinx-7462
fails in every arm of every pilot; it is the task.

Formation: ZERO. The store ended empty — no volunteered saves (by
design), nothing staged, no searches, no outcomes. 7/10 sessions still
mentioned the era-pin env error, yet no correction pair ever formed.

The confound that explains both: Claude Code's BUILT-IN auto-memory.
Present in both arms by design (ab-claude: control = built-in only, rfm =
built-in + mem-rfm), it captured the same era-pin stubs lesson during
pilot 2 in BOTH arms independently — project-scoped markdown notes whose
timestamps match the pilot-2 sessions; the rfm-side note is near-verbatim
mem-rfm's memory 2, same origin session — and it persists keyed to the
clone directory, so it crossed into pilot 3, whose agents opened with
"Check if PYTHONPATH env stubs still exist." The /tmp stubs artifact
itself also survived between pilots. Pilot 3's speed is therefore partly
inherited state, and the miner had nothing to catch because the failure
never recurred in mineable form.

Consequences:
1. Methodological. The live A/B has always measured mem-rfm's MARGINAL
   value on top of built-in memory (deliberate in July; the pilots show
   built-in now captures the same operational class well). Future pilots
   must declare which design they run — marginal-over-built-in or
   clean-room (fresh per-run project-memory dir + /tmp reset + isolated
   CLAUDE_CONFIG_DIR) — and clean cross-run state either way.
2. Strategic. On single-repo coding, the harness's own auto-memory
   already owns the operational-facts niche these pilots measured —
   without outcome ranking, and well enough for tasks this short.
   mem-rfm's differentiators are what built-in does not do: a signed
   outcome ledger (provable value, honest negatives), cross-repo and
   team-pooled stores, and staleness demotion under procedure change
   (ABCD). The pilot series' verdict stands and sharpens: mem-rfm is not
   a single-repo coding accelerator; that seat is taken by the harness
   itself.

Committed: pilot3/{results.jsonl, rfm-log.jsonl}; miner_replay.py (the
offline harness the interventions were validated on). Transcripts, DBs,
and the built-in-memory dirs stay untracked.

## Pilot 4 (exploratory, NOT pre-registered): clean-room paired A/B, seeded ledger

Run 2026-08-22, same 10 tasks, both arms, pilot 3's stack plus the
selection policy chosen OFFLINE first: eval_selection.py replayed pilot
2's ten rfm sessions against outcome ground truth — prior top-3 + the
negative-value floor keeps 18/19 of the as-run hits at 43% less injected
context and half the distractors, while query-similarity ranking (the
"obvious" improvement) drops to 12–16 hits because it ANTI-SELECTS
transferable memories: per-bug content surface-matches new bug reports;
the operational gotchas that actually help match nothing in particular.
Relevance is not value; the outcome prior out-selects semantic search on
its own telemetry. A query-aware injection hook was therefore not built.

Design: clean-room (both clones' built-in auto-memory archived, pilot
/tmp artifacts removed — the pilot-3 confound handled), rfm store SEEDED
with pilot 2's earned ledger for ids 1–4 only (per-bug memories dropped
against same-task leakage; one demoted memory kept to exercise the
floor). This measures the steady state — the value of an ACCUMULATED
store — not cold start, and clean-room control is a harsher baseline
than real usage, which has built-in memory. One resume mid-run re-ran
the clean-room step (now guarded); the 8056 pair is flagged
boundary-compromised and excluded totals are reported alongside.

Result — the first rfm arm to beat control:
* Wall: rfm 1,382s vs control 1,512s (−130s); excluding the flagged
  pair, 1,190s vs 1,237s (−47s). rfm wins big exactly on the
  env-heavy tasks (7757 −47s, 9658 −103s) and pays small on short ones —
  the break-even structure made visible in a single table.
* Tokens: rfm 9.7k/session vs control 10.9k — memory guidance now SAVES
  tokens net. Messages at parity (42 vs 43). Resolution 9/10 both arms
  (7462 fails everywhere, fourth run in a row).
* Selection: 33 injected / 17 hits / 0 distractors (pilot 2: 44/19/2) —
  precision up, distractors gone, and the seeded demoted memory was
  floor-excluded until session 1's evidence contradicted its demotion
  (inferred positive), after which it was readmitted and ended at value
  0.02 with 3 outcomes: the ladder self-corrects in both directions.
* Feedback economics: 17 inferred outcomes vs 3 explicit feedback calls
  — the loop closed 20 times at the cost of 3 LLM turns.
* Formation, clean-room: the widened miner staged one correction pair in
  the 9281 session (a stubs-invocation variant), the ratifier admitted
  it, it was injected in the final session and earned value 1.0 —
  formation → ratification → injection → outcome closed end-to-end,
  deterministically, with volunteered saves disabled. Store end state:
  the two seeded earners at value 0.998 (17 outcomes) and 0.992 (14).

Caveats: n=10, exploratory; the seed gives the rfm arm knowledge control
lacks BY DESIGN (steady-state question, stated above); wall deltas on
short tasks are noise-scale individually. Trace committed:
pilot4/{results.jsonl, rfm-log.jsonl, pending-reviewed.md}.

## Registered revalidation: scored (REVALIDATION.md, frozen stack)

Runs 2026-08-22, registration committed before any session (65027d8).
Score: 5 PASS, 2 NOT TRIGGERED, 0 FAIL. Resolution: pytest 9/10 both arms
(10356, July's discordant hard task, now fails in both); sphinx 6/6 both.

Track 1 — pytest two-phase (empty store, ledger earned in-protocol):
* T1-P1 machinery cost: PASS. Phase A rfm wall −7.6% vs control (bound
  +10%); rfm mean output tokens −12.4% (bound +15%).
* T1-P2 formation: PASS. Named-cause failures occurred; the miner staged
  2 correction pairs, both ratified (one live during the 6197 session).
* T1-P3 steady state: NOT TRIGGERED. No memory earned value > 0 in
  Phase A — the store ended at three memories, all value 0.0, zero
  outcomes across 12 injections. July's finding that pytest bug-work
  doesn't transfer, replicating under the new stack, exactly as the
  registration anticipated by declining to predict a wall advantage.
* T1-P4 selection discipline: PASS (weak form — no memory ever went
  negative, so the floor was never exercised on this track).

Track 2 — sphinx hold-out era (pilot-4 seed vs 2022–2023 pins):
* T2-P1 absence of harm: PASS. rfm total +3.0% (bound +10%) — and rfm
  won 4 of 6 pairs outright (−8, −121, −103, −119s); the hardest task
  (11510, +356s) swung the total positive.
* T2-P2 staleness exclusion: NOT TRIGGERED — no value went negative. The
  era-specific stubs memory took two explicit partial negatives (−0.3,
  notes saying its claim does not hold at 5.x checkouts) and the EWMA
  held at 0.77, so the floor's exclusion clause never fired. What DID
  happen: it fell from injection rank 1 to rank 3 as the invocation
  memories out-earned it, and the agent issued a memory_update scoping
  its claim to the old checkout states — content self-correction on top
  of score demotion.
* T2-P3 ledger adjusts downward: PASS. The stubs memory's value fell
  0.998 → 0.77 under new-era evidence while the track stayed at +3.0% —
  no fabricated wins, no harm.

Also observed, disclosed:
* Feedback economics held: sphinx closed 11 outcomes by inference vs 2
  explicit calls; pytest closed 0 — correctly, since nothing was acted
  on (inference abstains rather than inventing outcomes).
* Cold-start formation on unseen pins works: the sphinx track mined and
  ratified a NEW-era candidate that ended at value 1.0 (2 outcomes).
* A policy coverage hole: the no-volunteered-saves instruction rides the
  injection trailer, which does not render when the store is empty, so
  cold-start sessions ran policy-blind and one pytest agent volunteered
  a save (1 of 20 sessions). Fixed post-scoring — the hook now states
  the policy even with nothing to inject; the fix is outside the frozen
  claims (no prediction touched trailer rendering).

Traces committed: reval-pytest/ and reval-sphinx/ {results.jsonl,
rfm-log.jsonl}.

## Track 3 scored: xarray, the first never-seen repo — and the first FAIL

Runs 2026-08-22/23, registration 0dfd6e5 before any session. Score:
2 PASS, 1 FAIL, 1 ambiguous-as-registered. Resolution: Phase A control
11/11 vs rfm 7/11 (the series' first arm gap); Phase B 9/11 both arms
(6992 and 7229 fail in both).

* T3-P1 machinery cost: FAIL, both clauses — Phase A rfm wall +32.0%
  (bound +10%), rfm mean output tokens +35.5% (bound +15%). The
  pilot-3/4 overhead removal did NOT transfer to this workload. No
  causal story is established; what the trace rules OUT is the obvious
  one — see the resolution note below.
* T3-P2 formation: PASS. 8 candidates staged and ratified, all
  miner-mined (pending-reviewed.md count matches saves exactly — zero
  volunteered saves, the empty-store trailer fix validated live).
* T3-P3 steady state: AMBIGUOUS AS REGISTERED, disclosed as a
  registration defect — "IF >=1 memory earns value > 0 in Phase A, its
  Phase-B injections earn positive outcomes in >=50% of injected
  sessions" does not say whether "its" quantifies existentially or
  universally. Existential reading: PASS (memory 6: 8/8 Phase-B
  sessions). Universal reading: FAIL (memories 3 and 4: 1/7 each).
  Both are reported; neither is claimed. The per-memory split is the
  real finding: the memories that kept earning through Phase B
  (6: 8/8, 7: 5/5, 8: 3/3) are invocation patterns; the ones that died
  (3, 4: 1/7) are early-era patterns that stopped applying at the
  disclosed 2022 era shift inside Phase B — the staleness observation
  the registration promised in passing, delivered on schedule.
* T3-P4 selection discipline: PASS, and mechanically verified end to
  end: the first mined memory (a heredoc head-line artifact — the miner
  precision gap this track exposed) took an inferred −1.0 in session 3,
  was floor-excluded from session 4 onward, then took two +0.5 explicit
  rehabilitations via search — EWMA −1 → −0.55 → −0.235, matching the
  stored value to three decimals — and correctly stayed excluded.

Resolution-gap note, disclosed without a causal claim: three of the
four Phase-A rfm failures (2905, 3677, 3993) ran with EMPTY injections —
no memory content was in context — so bad mined memories cannot explain
them. The systematic differences in those sessions reduce to the MCP
server's presence, per-session memory searches against a thin store,
and the prompt's memory clause. Failed sessions also run long, which
couples the resolution gap to the wall/token FAIL. n=11 per phase;
this is the strongest argument yet for the next run being larger.

What Track 3 adds to the ledger: the honest boundary. On a
scientific-stack repo with heredoc-heavy repro workflows, the current
miner stages head-line artifacts (the "suspected tier" from the
formation survey is now directly motivated), the machinery is NOT free
the way it was on pytest/sphinx, and one prediction failed its bar in
public. The demotion floor, formation-without-volunteering, and the
staleness adjustment all worked exactly as designed while it happened.

Traces committed: reval-xarray/{results.jsonl, rfm-log.jsonl,
pending-reviewed.md}.

## Track 4 scored: the attachment tax, measured

Runs 2026-08-23, registration 5db11b0 before any session. Two arms over
the 10 pilot sphinx tasks: control (no MCP server) vs idle (rfm-memory
server attached; store empty — in fact never initialized, the DB file
holds no tables, so not one memory operation occurred; hooks inert).

* T4-P1: PASS, and the number is better than the prediction dared —
  the idle server's context cost is a near-perfect constant: +189 input
  tokens of first-turn context in 9 of 10 pairs (one +481 outlier;
  paired mean +218, 95% CI [+152, +284]), ~0.9% of the ~25k baseline.
  The size is the finding: an order of magnitude below the full text of
  the nine tool schemas, because Claude Code DEFERS MCP schemas and
  loads them on demand — the resident cost is the deferred-tool stub.
  The attachment tax is therefore harness-dependent: a harness without
  schema deferral pays the schemas' full text; Claude Code pays ~189
  tokens.
* T4-D1 (registered decision rule): resolves to CONTEXT-COST-ONLY.
  Idle wall +1.0% vs control (rule: within ±10%); resolution identical,
  9/10 both arms (7462 fails in both, as in every run of every
  experiment). Consequences, as registered: Track 3's Phase-A gap is
  attributed to variance-or-unknown, NOT to the attachment tax — and
  pilot 4's win loses its last unmeasured confound.

Per-arm output tokens at parity (10.9k vs 11.1k). Trace committed:
tax/{results.jsonl}; transcripts and the never-initialized DB stay
untracked.

## Track 5 scored: struggle-triggered synthesis — the knowledge was produced, the capture failed

Run 2026-08-23, registration 52686c2 before any session. 10 pytest tasks,
rfm arm only, synthesis channel on, baseline reval-pytest's own rfm arm.
Score: 3 PASS, 1 FAIL.

* T5-P1 capture: **FAIL**. The trigger fired in 2 of 10 sessions and
  produced **zero** synthesized memories. All 6 memories in the store carry
  the miner's `In this project, X fails (err); use Y instead` template —
  the synthesis channel contributed nothing. The condition fired, so this
  is a genuine FAIL, not NOT TRIGGERED.
* T5-P2 no-op discipline: **PASS**. Zero volunteered saves in any session,
  nudged or not. (The scorer initially read this as FAIL by counting
  ratified *miner* candidates as volunteered saves — the miner runs at
  session end regardless of nudges. Corrected before scoring.)
* T5-P3 over-extraction bound: **PASS**. Zero volunteered saves per session.
* T5-P4 cost: **PASS**. 2,988s vs the baseline arm's 3,191s (−6.4%,
  bound +15%). The channel is affordable; it just did not fire usefully.

**The diagnostic is the finding, and it is not what the score suggests.**
The nudge reached the model both times, and both times the model went on
to write exactly the synthesized root-cause explanation the nudge asked
for — into its user-facing response text, and never into memory:

> "The regression came from `unique_path()` (added in 5.1.2), which ran
> `os.path.normcase()` over every conftest path — on Windows that
> lowercases the whole path, and the lowercased path was then used to
> *import* the module..."

> "**Cause.** The 5.2.3 fix for #5830 added an unconditional
> `self._mount_obj_if_needed()` at the top of `Package.collect()` — that
> call imports the package's `__init__.py`, so *every* directory..."

That is the artifact this experiment exists to capture. The synthesis
capability is not the bottleneck; **the write is.**

Two contributing defects, both ours:

1. **The trigger has no generic-program guard.** Nudge 1 fired on
   `command not found` with `program=cd` — a spurious trigger. The
   correction miner already excludes generic programs via
   `informative_head`; the hook does not, and the research that motivated
   this design named the guard list (cd/tail/cat/ls/echo) explicitly. One
   of two triggers was junk.
2. **The knowledge synthesized was about the BUG, not the ENVIRONMENT.**
   Both root causes are per-bug code explanations — exactly the class this
   project measured at ~6% transfer and does not want stored. So the model
   arguably made the *right* call in declining, and the nudge asked the
   wrong question: it fires on an environment-error class but then asks
   for "the root cause" of whatever the session was working on.

**What this rules in and out.** It does not refute synthesis: the channel
was never given a session where an environment root cause was both
understood and un-captured. It does establish that (a) an in-session
trigger reaches the model and costs nothing measurable, (b) the no-op line
holds — no invented memories, in ten sessions, under an explicit
invitation to save, and (c) the gap is now narrower and more specific than
"formation misses expensive knowledge": the model *produces* the
explanation and does not *store* it.

Next iteration, if run, should add the generic-program guard and make the
nudge name the environment class it fired on rather than asking for "the
root cause" in the abstract. Registered as a new track before running.

Trace committed: synth/{results.jsonl, rfm-log.jsonl, pending-reviewed.md}.

## Track 6 scored: NOT TRIGGERED — the workload, not the mechanism

Run 2026-08-23, registration 2434bca before any session. Same 10 pytest
tasks as Track 5, both Track 5 defects fixed (generic-program guard at the
trigger; nudge retargeted at the environment cause and explicitly refusing
per-bug lessons). Score: 2 NOT TRIGGERED, 2 PASS.

* T6-P1 capture: **NOT TRIGGERED**. No nudge fired in any of 10 sessions.
* T6-P2 trigger precision: **NOT TRIGGERED**. Same reason.
* T6-P3 no-op discipline: **PASS**. Zero synthesized memories; all 4 stored
  memories are miner-mined. Nothing leaked, in 20 sessions across both
  tracks.
* T6-P4 cost: **PASS** on the number (2,466s vs Track 5's 2,988s, −17.5%)
  but **not meaningful** — the whole run was lighter, and the delta is
  session variance rather than an effect of the change. Reported, not
  claimed.

**The diagnosis, and it is not the guard.** Counting failures directly
from the transcripts, excluding generic programs exactly as the trigger
does:

| run | sessions reaching threshold (>=2 non-generic failures of one class) | failure classes seen |
|---|---|---|
| Track 5 | 2 of 10 | importerror 6, command-not-found 2, no-matches 2, modulenotfounderror 1 |
| Track 6 | **0 of 10** | importerror 3, modulenotfounderror 2 |

Track 6's sessions simply failed less — 5 qualifying failures against
Track 5's 11 — and none concentrated enough in a single session to reach
a threshold of two. The guard did not suppress a legitimate trigger;
there was no legitimate trigger to suppress.

**What this establishes about the experiment, not the hypothesis.** Across
20 sessions on pytest, the qualifying struggle fired **twice, one of them
spurious** — an effective n of 1, dominated by run-to-run variance. This
workload cannot test the capture hypothesis at any sample size we can
afford. Registering a third pytest run would be spending sessions to
re-measure variance.

**The fix is the workload, and we already know which one.** The sphinx
clones carry a genuinely broken environment — the sphinxcontrib/alabaster
version mismatch requiring the PYTHONPATH stub workaround — where the
environment cause is both reliably encountered and worth writing down.
It is where the project's single highest-earning memory (22 outcomes)
came from, and reval-sphinx's control arm needed 6 events to reach a green
test where the memory arm needed 1, with 2 of 6 control sessions never
getting there. pytest was the right venue to isolate Track 6's nudge
change against Track 5's baseline; it is the wrong venue to observe
struggle.

**Standing result across both tracks:** an in-session trigger reaches the
model and costs nothing measurable, and the no-op line holds — zero
invented memories in 20 sessions under an explicit invitation to save.
The capture question remains open and untested.

Traces committed: synth6/{results.jsonl, rfm-log.jsonl, pending-reviewed.md}.

### Addendum: Track 7 was not run, because the trigger — not the workload — is wrong

Track 6's write-up proposed re-running the synthesis experiment on the
sphinx clones, where the environment is genuinely broken. Before
registering it, the trigger rate was measured across every sphinx session
this project has recorded, using the trigger's own threshold and
generic-program exclusion:

| run / arm | sessions | would fire | classes seen |
|---|---|---|---|
| pilot2 control / rfm | 10 / 10 | 0 / 0 | versionrequirementerror 2 · mixed 3 |
| pilot3 rfm | 10 | 0 | none |
| pilot4 control / rfm | 10 / 10 | 0 / 0 | versionrequirementerror 2 · no-such-file 2 |
| reval-sphinx control / rfm | 6 / 6 | 0 / 0 | 2 · 3 |
| tax control / rfm | 10 / 10 | 0 / **1** | versionrequirementerror 4 · 5 |

**1 firing in 82 sphinx sessions.** With pytest's 2 in 20 (one spurious),
the trigger fires in **3 of 102 sessions across every workload we own**.
Sphinx is not a better venue; there is no better venue. Registering Track
7 would have spent a run to re-learn Track 6's lesson.

**Why it fails, and it is diagnosable.** The trigger requires the same
error class to fail twice *within one session*. Agents adapt too fast for
that — `versionrequirementerror` appears 2, 4 and 5 times in various runs,
but spread across sessions, not repeated inside one. The struggle is real
and this project has already measured it: reval-sphinx's control arm
needed 6 events to reach a green test against the memory arm's 1, and 2 of
6 control sessions never got there. **We chose a struggle signal we never
validated, while holding one we did.**

The trigger should fire on the signal the counterfactual instrument
already proved discriminates — elapsed events with no passing test — not
on repeated identical error classes. That is a different experiment with a
different mechanism, and it needs its own registration and its own
pre-flight rate check before any session runs.

**Method note.** The rate check that produced this table costs nothing and
would have prevented Track 6 as well. Any future trigger design gets it
before registration: measure on recorded transcripts how often the
proposed trigger would fire, and refuse to register anything that fires in
under ~20% of sessions — below that, a 10-session run cannot distinguish
the mechanism from variance.

## Track 8 — prose harvest: deterministic vs LLM (2026-08-24)

Registered in REVALIDATION.md, then corrected mid-run (C2) when the arm
disproved the ground truth. Scored 4/8. Both headline numbers below are
about FORMATION QUALITY ONLY — no session was run against these memories,
so nothing here claims a task-performance benefit.

**Ground truth, corrected.** Each SWE-bench task ships a `gold_patch`
naming the files and functions that held the real bug. Neither arm saw it;
both classified from prose alone. First labelling reported 100% of
harvested blocks as pure per-bug and called the channel dead — an artifact
of detecting environment trouble only when named as an error class. Agents
write "this venv's packages are too new for this 2020-era checkout", not
"ModuleNotFoundError". Corrected: **71% of blocks (61/86) carry durable
environment knowledge, always as a nugget inside a fix summary.**

| | Arm A (regex) | Arm B haiku | Arm B sonnet |
|---|---|---|---|
| recall on env-bearing | 49% | 31% | 34% |
| specificity on pure fix summaries | 100% | 100% | 84% |
| stored | 30 | 19 | 25 |
| **stored text leaking gold-patch code** | **100%** | **26%** | 40% |
| clean memories produced | **0** | **14** | 14 |

**The result that matters is the last row.** Arm A classifies whole blocks,
so when it stores, it stores an entire fix summary — every one of its 30
memories is polluted with the task's own bug code, by construction and not
by bad luck. Arm B excises the nugget: haiku produced 14 clean, durable
environment memories, e.g. *"This 2020-era Sphinx checkout has a venv
compatibility issue: sphinxcontrib.* and alabaster are too new and cause
app-based tests to error at startup. Workaround: stub packages on
PYTHONPATH."* That is the era-pin stub workaround, this project's
highest-value memory, recovered by a cheap model from prose the miner has
never read. **A block-level classifier cannot produce that text at all.**

**Where it fails.** Recall was predicted >=70% and came in at 31-34%: both
models miss two-thirds of the nuggets that are demonstrably present.
Sonnet is worse than haiku on both leakage (40% vs 26%) and specificity
(84% vs 100%) — bigger is not better here, and the deployment question
"can formation run on the cheap model" answers yes for the wrong reason.
Agreement was 60/86 = 69.8%, a hair under the registered 70%.

**Free finding from a harness accident.** Three runner processes raced and
re-scored 49 blocks with the identical model and prompt. **3 disagreed with
themselves — a 6% flip rate**, all on blocks where the environment content
is real but marginal. LLM formation is not deterministic, and a memory's
existence depends partly on which sampling it got.

**Yield.** 14/86 sessions (16%) produce a clean memory from haiku, 21/86
(24%) from the union of both models. Against the struggle trigger's 3%
firing rate this is a large improvement in raw formation, and 7 of haiku's
14 clean memories are the same PYTHONPATH/stub fact re-derived — real
recurrence, and a dedup requirement before any of this ships.

**Verdict.** The first formation strategy in four attempts that produces
memories worth storing. It is not validated: recall is poor, output is
nondeterministic, a quarter of stores still leak per-bug text, and no
downstream benefit has been measured. Traces: track8/{arm-haiku,
arm-sonnet,nondeterminism-raw}.jsonl, harvest-labelled.jsonl.

## Track 9 — extraction framing (2026-08-24) — 4/5 PASS

One change from Track 8: the prompt asks the model to EXTRACT a durable
fact from a block that is mostly about a bug, instead of judging whether
the block IS durable knowledge. Same 86 blocks, same models, same
gold-patch truth neither arm sees.

| arm | recall (tight) | specificity | stored | leak | clean memories |
|---|---|---|---|---|---|
| haiku v1 | 39% | 93% | 19 | 26% | 14 |
| **haiku v2** | **88%** | 62% | 53 | **19%** | **43** |
| sonnet v1 | 39% | 80% | 25 | 40% | 15 |
| sonnet v2 | 100% | 24% | 75 | 33% | 50 |

**T9-P1 recall >=65%: PASS (88%, from 39%).** The framing was the binding
constraint, as diagnosed. **T9-P2 leakage <26%: PASS (19%).** The
stand-alone instruction cut identifier leakage while recall more than
doubled. **T9-P4 yield >=25: PASS (43 clean, from 14).** **T9-P5: PASS** —
haiku leaks 19% against sonnet's 33%, so the cheap model stays ahead and
v1's ordering was not a prompt artifact.

**T9-P3 specificity >=80%: FAIL (62%, down from 93%).** The registered
guard did its job: part of the recall gain was bought by storing more. Of
45 blocks that name no environment condition, haiku v2 stored 17. Sonnet
v2 is the pathological version of the same effect — 100% recall at 24%
specificity, storing 75 of 86 blocks, which is barely a filter at all.

**Whether 62% is acceptable is not a judgement call here, because this
project already measured it.** The oracle-subtraction result — perfectly
removing every memory that never contributes buys ~0 — means false-positive
memories are close to free in this system: they sit unused and unranked
rather than crowding anything out. A formation stage facing a cheap-FP,
expensive-FN asymmetry should prefer recall, which is what v2 does. That
argument is only as good as the oracle result it rests on, and it is
recorded here as reasoning, not as a new measurement.

Cost: 86 calls per arm on haiku, well under a cent per session at
SessionEnd. Still no downstream benefit measured — the next step is a
store built from these 43 and a live A/B against it.

## Track 10 — live A/B on a harvest-built store (2026-08-24) — 2/4 PASS

13 held-out xarray tasks, paired arms, store frozen at the 5 consolidated
memories from Track 9. The first A/B this project has run against a store
whose contents a human would actually keep.

| | control | rfm |
|---|---|---|
| resolved | 13/13 | 13/13 |
| first green: better on | **7** | 3 (3 tied) |
| never reached green | 0 | **2** |
| total wall | 1315s | **1642s (+24.9%)** |
| injections landed | — | 13/13 |

**T10-P1 counterfactual: FAIL.** The registered claim was that rfm reaches
its first green test in fewer events more often than not. It lost 3-7. A
sign test on the 10 non-tied pairs gives two-sided p = 0.344, so this is
not evidence of harm either — it is an absence of the predicted benefit,
at the sample size the registration admitted was small.

**T10-P3 utilisation: PASS, and it is what makes P1 meaningful.** All 13
rfm sessions received an injection. This was not a plumbing failure. The
store was consulted and did not help.

**T10-P2 resolved-rate: PASS by ceiling.** Every task resolved in both
arms. Registered as predicted-null in advance precisely so this could not
be read as "memory did no harm to completion" — the workload cannot
discriminate on completion at all.

**T10-P4 no harm: FAIL, +24.9% wall.** Mechanism visible in the commands:
control used `-k` on 7 of 19 pytest invocations, rfm on 3 of 18, and rfm
ran multi-file invocations. That is memory [5] — *"the full suite runs in
~5s, no need to use -k filters"* — doing exactly what it says. True when
harvested, durable, human-keepable, and it made the agent slower.

### The finding that outlives this track: the outcome loop cannot tell saved work from caused work

Memory [3] warns that `import xarray` fails without a pkg_resources shim.
In the rfm arm the agent ran **3 bare import smoke checks; control ran 0**.
All three succeeded — the failure never occurred, because
`run_stream.prepare()` already mitigates it. The outcome loop recorded all
three as **positive outcomes for memory [3]**.

From the loop's vantage, "the agent ran a command related to this memory
and it worked" is identical whether the memory prevented a debugging
detour or merely prompted a redundant check. It cannot separate them, and
it credits both. That signal is what the entire RFM value axis is built
on, so a memory that generates busywork accrues value exactly like one
that saves it. Nothing in this project has previously tested that
distinction, and no amount of better formation fixes it.

### What this means

Formation was not the binding constraint. Tracks 8-9 produced memories
worth keeping — that is real and it stands. Track 10 shows that injecting
them reliably, on held-out tasks, changed nothing for the better and cost
25% more wall time.

Limits, stated so the negative is not overclaimed either: 13 tasks in one
repository; a resolved-rate ceiling; and the store's strongest memory
partly neutralised by a harness fix that postdates its harvest, which was
registered as a weakness before the run rather than discovered after it.

### Correction C3 to Track 10 (2026-08-25) — the harm claim was mine, not the data's

The Track 10 entry above says a true memory made the agent worse. Asked to
explain the mechanism, I checked it and it does not hold. Three claims in
that entry are wrong or unsupported, and the entry stands uncorrected above
so the error is legible.

**1. "rfm never reached green in 2 sessions" — false, a metric artifact.**
`first_green` required the literal string "N passed" in the captured tool
output. The agent pipes pytest through `| tail -15`; on a broader run the
warnings section is long enough to push the summary line out of the tail
window. Both "never green" rfm sessions exited 0 — the tests passed, my
detector could not see it. Rescored as "first pytest run that exited 0",
never-green is 0 for both arms.

**2. "+24.9% wall time" — true as a total, meaningless as a finding.** The
paired sign test is p = 0.774: rfm was faster on 5 tasks and slower on 7.
The whole gap is one task, xarray-6461 at +438s, which is 134% of the
total; drop it and rfm is faster in aggregate. Reporting a sum over 13
paired tasks without checking its distribution is the same mistake as
quoting a rate without its baseline, which this project already made once
in August with the 64% harvest number.

**3. "Memory [5] made the agent slower by suppressing -k" — unsupported.**
The behavioural difference is real but small (control used -k on 7 of 19
pytest invocations, rfm on 3 of 18; 2.3 vs 2.0 test files per run), and I
never tested the link from that difference to any cost. Inspecting the
outlier that carried the entire wall gap: control solved 6461 in 3 events,
rfm in 16, of which 14 are the agent exploring a hard attrs-propagation
bug with heredoc repro scripts and 2 are memory-induced. That task is
variance in approach, not memory.

**What the corrected result is.** Counterfactual rescored: rfm better on
2, control on 7, 4 tied, sign test p = 0.180. Directionally negative,
not significant. Wall: no consistent difference (p = 0.774). Resolved:
13/13 both, a ceiling. Injection landed 13/13. **Track 10 detects no
effect in either direction on 13 pairs.** That is a weaker and more
honest statement than the entry above, and it does not rescue the store —
memories a human would keep, delivered reliably, still bought nothing
measurable.

**What survives unchanged.** The outcome-loop finding. Memory [3] prompted
3 bare `import xarray` smoke checks in the rfm arm against 0 in control;
all 3 succeeded because prepare() already mitigates that failure, and the
loop recorded all 3 as positive outcomes. That is verified, independent of
the metric bug and of the wall-time question, and it is the finding worth
carrying forward: the value axis cannot distinguish work a memory saved
from work it caused. A second instance sits in the same outlier — the
agent ran `black --check` and `flake8` even though the injected memory
says both are not installed, so that memory failed to prevent the very
work it describes.

## Track 11 — same fact, four forms (2026-08-27) — 5/7 PASS, and the pass count is not the finding

40 sessions, complete: 8 in-era sphinx tasks × 5 arms (none / placebo /
prose / verbatim / abstract), the flagship era-pin memory delivered under
a cloned 17-outcome ledger, texts token-matched within ±10%
(REVALIDATION.md Track 11; store-track11.json). Injection landed 32/32
(T11-P6 PASS). Resolution 7/8 in every arm — a near-ceiling, again.
Scored by score_track11.py, which reports the registered detector AND
the C3-corrected one, because the registration pointed at the shipped
`first_green` after C3 had already recorded its defect. That was a
registration error and it is owned here rather than discovered later.

**T11-P1 necessity: FAIL under both detectors.** Registered instrument
(events to first "N passed"): verbatim 3 / none 3 / tied 2. C3-corrected
(first pytest exit 0): verbatim 1 / none 3 / tied 4. The corpus's
highest-value memory, delivered reliably on the very tasks its ledger
was earned on, does not beat no-memory under any available reading.

**Why, mechanically: the condition no longer fires.** The registration
predicted the control arm would pay the VersionRequirementError storm.
It never came: the class appears in 3 of 8 control sessions, roughly one
mention each, and under the corrected detector 30 of 40 sessions across
ALL arms reach a passing pytest run by event 2 — the instrument has
almost no dynamic range left on these tasks. The storm that was
ubiquitous in the mid-August pilots on these same tasks is absent ten
days later under a frozen harness and frozen pins. Candidate causes,
unresolved: drift in how current sessions verify (targeted tests first,
app-fixture tests avoided), or pilot-era approach variance. What it
means for M is not ambiguous: value_score has no term for a condition's
fire rate. A ledger decays on acted-and-failed; on
inapplicable-and-ignored it sits at 0.998 forever. lifecycle.md's
"absence of use is not negative evidence" is the right retention rule
and the wrong value rule.

**T11-P4 form: the finding of the track.** Registered: verbatim 1 /
prose 2 / tied 5 (FAIL). Corrected: 3 / 1 / 4 (would pass). Either way,
noise around ties — but the transcripts say what form actually does. The
stubs/PYTHONPATH workaround was ACTED ON in 4 of 8 verbatim sessions,
4 of 8 abstract sessions, and 0 of 8 prose sessions, and the acting
bought nothing measurable in events or wall (verbatim wall −10.4% vs
none, faster on 5 of 8, all deltas small). The backtick form determines
whether a memory gets USED, not whether it HELPS. That is the corpus's
3.2-vs-0.5 backtick split measured causally: quotability. The command
form drives copying, copying drives `acted_on()` outcomes, outcomes
drive M — and none of that chain touches task performance.

**The controls behaved (P2, P3, P5, P7).** Verbatim over placebo 4/3/1:
registered PASS, direction only — 4-3 on 8 tasks claims nothing.
Placebo under none 1/4/3: true-but-inapplicable content costs a little
in events and nothing in wall (741s vs 821s). Abstract did not beat
verbatim (1/4/3) and was the only expensive arm: +47.9% wall vs none,
slower on 6 of 8 tasks (not an outlier artifact), 22 events on 7757 —
Memp's within-repo prediction (verbatim over abstraction on
near-identical recurrence) holds, and the generalized recipe reads as an
invitation to explore. T11-P7 no-harm: PASS at −10.4%.

**One anomaly, recorded not explained.** On 7889 the three informative
arms show "never" under the registered detector yet all resolved, and
none of the three acted on the memory there; the corrected detector has
them green by event 2–3. The detector artifact C3 documented, recurring
exactly as documented.

**What Track 11 establishes.** (1) Track 10's shape, reproduced at the
ceiling: a true memory, reliably delivered, on its home tasks, causally
inert — and this time it was the best memory the project has ever
produced. (2) The executable-form advantage in the corpus is causally
quotability, not value. Formation should stop reading a quotable command
as evidence of worth; it is evidence the `acted_on()` matcher will fire.
(3) M as constituted cannot distinguish "helped" from "was copied while
the task succeeded anyway", and cannot see a condition that stopped
firing. Per the registration, Track 12's M-rule comparison is blocked:
it was conditioned on P1 passing. The productive next instrument is
condition-conditioned value — outcomes counted only in sessions where
the memory's trigger class actually fired — computable retroactively
from every committed transcript.

### Correction C4 to Track 11 (2026-08-27) — the storm was never there, and the ledger was manufactured

The entry above explains P1's failure as a condition that "was
ubiquitous in the mid-August pilots" and later stopped firing. Measured,
that claim is false in both halves. The entry stands uncorrected above
so the error is legible.

**1. Pilot control arms never paid the storm.** On the same 8 tasks,
control sessions hit the VersionRequirementError/ExtensionError class
once in all of pilot 2 and three times in pilot 4. There was no storm to
save anyone from; the class bit hard exactly once, in the mint session
(7454 — excluded from Track 11 by provenance).

**2. The 17-outcome ledger was earned condition-silent.**
condition_value.py, committed with this correction: across the 30
pilot-era memory-arm sessions on these tasks, the class fired in 2, and
79% of all acted-on stub/PYTHONPATH commands (61 of 77) ran in sessions
where it never fired. Agents prepended the suggested PYTHONPATH
ritually to commands that were never at risk, and the outcome loop
credited every success. This is Track 10's outcome-loop finding — the
value axis cannot distinguish work a memory saved from work it caused —
measured at scale, on the corpus's top memory.

**3. Track 11's own firing pattern is endogenous.** The class fired in
13 of 24 delivery-arm sessions against 2 of 30 in the pilots, because
Track 11's registered per-session /tmp clean removed the stubs directory
the pilots built once and amortized ever after. Acting on the memory
forced its recreation, which is when the class surfaces: 64 of 76 acted
commands sit in fired sessions because acting causes firing, not the
reverse. condition_value.py carries this as an explicit caveat — it
audits where a ledger was earned and is not a causal estimator.

**4. The reval-sphinx lore is also wrong.** Track 10's registration
called the counterfactual "the instrument that discriminated on
reval-sphinx: control 6 events, memory arm 1". Audited: zero era-class
events in any reval-sphinx session, either arm. The memory arm was
genuinely faster to green there (5 of 6 tasks under the corrected
detector), but whatever produced that, it was not the era-pin mechanism.

**5. One heterogeneity disclosed late.** Model ids read from
transcripts: pilots 2–4, reval-sphinx, and Track 11 all ran
claude-fable-5; Track 10 ran claude-opus-5. No cross-model confound
inside Track 11, but Track 10's null and Track 11's null come from
different models and neither entry said so until now.

What stands, stronger: P1's FAIL, and the quotability finding — the
form split (acted on in 4 of 8 verbatim sessions, 0 of 8 prose, no
benefit) and the ledger audit (79% silent) are the same mechanism seen
twice. What falls: the "condition-fire drift" framing. The condition
never drifted; it was never load-bearing.

## Track 13 — the weak-agent arm (2026-08-27) — 1/4 PASS, and the first clean harm signal

16 sessions, complete, no timeouts: the 8 Track 11 tasks, arms none and
verbatim, model pinned to claude-haiku-4-5-20251001 in both arms and —
for the first time in this project — stamped into every results record.
Injection landed 8/8 (T13-P3 PASS). Metric of record was registered as
the C3-corrected detector; the legacy detector agrees directionally
where it fires at all.

**T13-P1 condition liveness: FAIL — 2 of 8 control sessions.** The gate
did not open: haiku sidesteps the era class almost exactly as fable-5
does. Per the registration, the reading is now closed: **the condition
is dead at both capability tiers, the flagship is a fossil of one
August session, and no workload in this project's task pool can make it
pay.** That retires the last within-pool causal hypothesis.

**T13-P2 necessity: FAIL, at zero.** Verbatim 0 wins / none 5 / tied 3
— the memory arm was never faster to green, on any task. This is not a
tie-dominated null like Track 11; it is directional harm on the metric
of record.

**T13-P4 no harm: FAIL, +27.6% wall, slower on 7 of 8 tasks.** Reported
with its distribution per the C3 lesson: this is not an outlier — the
cost is spread across nearly every task. For a weak model, carrying a
true-but-unneeded 1,214-char memory is a measurable distraction tax,
which is the token-budget result (arXiv 2606.15017) reproduced at n=8
in our own harness.

**Resolution: none 4/8, verbatim 5/8 — noise range, recorded not
claimed.** Two things worth separating: the +1 does not survive the
counterfactual or wall evidence (verbatim resolved one more task while
being slower to green everywhere it can be measured), and — the useful
observation — haiku restores the pool's dynamic range (fable-5 sat at
7/8 with green-by-event-2; haiku genuinely struggles). The testbed is
not ceiling-bound for weak agents.

**What Track 13 establishes.** (1) The fossil verdict, registered in
advance, now measured: both remaining causal hypotheses from the
2026-08-27 sweep — "the condition must fire" and "memory helps weaker
agents" — are dead in this pool. (2) Memp's strong-to-weak transfer
claim is refuted in our setting: the weak agent paid for the strong
agent's memory, it did not profit from it. (3) Third independent
measurement of the engagement/value split: perfect delivery (8/8), zero
wins. (4) The constructive residue: a weak-agent testbed discriminates,
but the memory tested here was formed from a *strong* agent's struggle
with an environment class the weak agent never meets. Haiku's friction
is somewhere else (2 era events in 16 sessions; its failures were
capability-shaped, not environment-shaped). If a future formation track
mines memories from haiku's OWN failure classes and tests them on
haiku, that is the one within-reach design this result does not
foreclose — formation-tier matching, noted in next-work.

## Track 16 — structured extraction (2026-08-27) — 3/5: structure is free, and it is not a filter

86 blocks replayed through the v3 schema prompt
({condition_class, scope, era, action, evidence}), haiku, zero parse
failures, 54 stored (v2: 53). Bars were anchored to Track 9's achieved
haiku-v2 numbers.

**What passed — emitting structure costs nothing and cleans the
output.** Recall vs tight truth 85% (bar 80, v2 achieved 88): the
schema did not induce refusal-by-formality. Leakage fell to 13% from
v2's 19%: fields enforce stand-alone-ness better than prose
instructions did. Condition validity 89% (16 of 18 stored blocks that
name an error class got a matching condition_class): where the
condition is checkable, the model names it correctly. The mechanical
benefits the design proposal wanted — a declared condition for
condition-conditioned M, a declared action for acted_on() matching —
are available at no recall cost.

**T16-P4 completeness: FAIL at 52%, and the bar was wrong, not the
model.** The prompt permitted an empty action when the block gives no
runnable step; the bar then demanded both fields anyway. Half the
corpus's durable conditions simply carry no executable action
("dask-not-installed" does: `pip install dask`; a pre-existing
warning-assertion interaction doesn't). Design consequence, recorded
prospectively: **condition_class is the mandatory field; action is
optional** — which also matches Track 11's finding that the action's
executable form drives copying, not value.

**T16-P5 structure-as-filter: FAIL at 58% (v2: 62%), the hypothesis is
refuted.** Requiring a nameable condition does not suppress per-bug
stores — the model obligingly names pseudo-conditions for per-bug
blocks. Schema does not substitute for judgment; per the registration,
the extraction half of the design proposal loses its cheapest argument
and keeps its mechanical ones.

**Observation recorded for the design, not scored: actions are
composed, not quoted.** Sample stores include
`pip install 'sphinxcontrib-applehelp<5.0' 'alabaster<3.4'` (a
downgrade fix the transcripts never ran — plausible, unverified) and
"ensure Sphinx >= 5.0 is installed" (for an era-pinned checkout,
plausibly the WRONG direction). The extractor invents actions the
session never executed. Any schema adoption needs a provenance bit on
the action field — quoted-from-session vs composed — because a
composed action carries invention risk the outcome loop would then
score as if it were experience.

## Track 17 — formation-tier matching (2026-08-28) — dead at the gate, and the pool is closed

Phase A ran complete: 11 haiku control sessions on xarray's first half,
9/11 resolved, walls 40–298s, model and CLI stamped. The formation pass
(mine_track17.py, committed with its output) then terminated the track
exactly where the registration said a quiet Phase A would:

**T17-P1 (friction exists): FAIL — condition classes fired in 1 of 11
sessions** (gate: >= 4; the one firing was a command-not-found +
modulenotfounderror pair in 3305). **T17-P2 (yield): zero.** The
deterministic miner staged nothing — no named-cause failed→fixed pair in
eleven transcripts — and the v3 extractor, over the 7 causal prose
blocks Phase A produced, stored nothing that named a condition. **T17-P3
(necessity): NOT TRIGGERED**, and per the registration Phase B does not
run: there is no store to test, and seeding one from nothing would
manufacture the experiment it was meant to be.

What this establishes, and it is the pool's closing entry: Track 13
showed haiku's sphinx friction was capability-shaped rather than
environment-shaped; Phase A shows the same on xarray — the weak agent
mostly just solves these tasks (9/11), and where it struggles, the
struggle does not condense into nameable recurring conditions. It is
per-task difficulty, the ~6%-transfer class, exactly what this project's
own capture policy says not to store. Formation-tier matching had
nothing tier-specific to mine.

**The within-pool causal program is now closed at four terminals:**
Track 10 (ratified store, no effect), Track 11 (best memory,
token-matched, no effect; ledger 79% condition-silent), Track 13 (weak
agent, measured harm), Track 17 (weak agent's own struggles,
unmineable). Every further causal question this project wants to ask
requires a workload with measured, recurring, condition-shaped friction
— the testbed rebuild — and the honest summary of the pool is: for
frontier and near-frontier agents on era-pinned SWE-bench-class Python
repos, operational memory had nothing to pay for, because the agents do
not pay the costs the memories describe.

## Track 18 — the open-throttle replay (2026-08-28) — 4/5 as registered, and two of those numbers are not what they look like

50 pilot transcripts swept into a fresh store: 65 admits, leakage 15%
(T18-P4 PASS with room), 0.8 LLM calls per transcript (T18-P5 PASS),
and the era-pin fact captured without any human gate (T18-P1 PASS —
emphatically: 22 rows of it). The two headline bars need honest
reading:

**T18-P2 dedupe-as-frequency: FAIL, and the diagnosis is the
instrument.** Twenty-two paraphrases of the same fact, zero merges. The
shipped similarity was token Jaccard at 0.5 — a shortcut standing in
for the embedding similarity the design specified — and paraphrase
rarely clears 0.5 Jaccard. The maintainer's spec was right as written;
the approximation was the failure. (The flood also shows the extractor
finding the era-pin fact in nearly half the sessions — the recurrence
signal is strong; it just wasn't being consolidated.)

**T18-P3 fossil refusal: PASS BY VACUITY, not scored as evidence.**
Zero judged positives because zero judge operations ran: judge_in_play
rehydrated the transcripts' in-play memory ids against the sweep's OWN
store, where those ids collide with unrelated rows — wrong content,
dead signatures, silent skips. The conditioned judge was never tested.

Both defects are mechanical and fixed in the same commit as this entry:
similarity upgraded to embeddings (fastembed when available, Jaccard
fallback), and replay judging matched to the sweep store by similarity
instead of by id. Track 18b re-registers the same five bars on the
repaired stack (the Track 6 pattern — same experiment, defects fixed,
so 18b-vs-18 is an A/B on the instrument, not the workload).

## Track 19 — the rebuilt testbed (2026-08-29) — 2/5, and the agent routes around the friction a fifth time

Scored at 20 of 21 registered pairs (the run was externally stopped
three times; the shortfall is one pair, disclosed). Model fable-5, CLI
stamped, no timeouts, resolution near ceiling in both arms.

**T19-P1, the gate: FAIL at 5% — one control session in twenty ever
saw the era class.** The pool was engineered so that verification
through the fail-to-pass tests dies on VersionRequirementError, and the
probe triple proved it at scoring time on all 21 tasks. It did not
matter: the agents fixed the bugs by reading code and verified through
repro scripts and non-app tests, reaching a passing pytest run in 0–6
events, and almost never touched the app fixture bare. The friction is
real for the HARNESS — scoring needs the stubs — and absent from the
AGENT'S path. This is the fifth time a frontier agent has routed
around the condition (pilots, Tracks 11, 13, 17, 19), and this time it
was against a workload built specifically to prevent it.

**The lifecycle itself worked end to end — the first full live
validation of the open-throttle stack.** T19-P2 PASS: the era memory
formed from session prose, consolidated to ONE row that ended at
26 sightings / 25 accesses, and the quarantine promoted it without any
human review. T19-P5 PASS: injection delivered in 19 of 18 eligible
sweep sessions. And the conditioned ledger held: **value 0.00,
outcomes 0** — twenty-six sightings of engagement, zero unearned
credit. The instrument that would have minted a 0.998 fossil from this
exact trace now records the honest number.

**T19-P3 necessity: FAIL as a coin flip** — sweep 8 / control 9 /
tied 3, one-sided sign p = 0.69. Per the interpretation fixed at
registration, a P3 null under a P1 gate failure reads as
condition-absent-from-path, NOT as the
condition-fires-cure-delivered-no-benefit terminal negative.

**T19-P4 no harm: FAIL at +25.2%, and this one is significant.**
Sweep slower on 14 of 20 pairs (one wall tie; one-sided sign
p = 0.032 over 19 decided) — distributed, not an outlier, surviving
the C3 distribution check. With delivery at 19/18, the mechanism is
visible in pairs like 7748 (228s vs 450s) and 9230 (54s vs 197s): the
injected memory about the venv problem invites investigation of a
problem the session was never going to hit. This is Track 13's
weak-model tax reproduced on the frontier model at n=20: **delivered
memory about unencountered conditions is not neutral — it costs.**

**What Track 19 settles.** The rebuilt testbed was the program's last
design for making the condition bind, and the agent declined to be
bound. The final shape of the finding, now measured six ways: the
knowledge that recurs on this workload class is knowledge a frontier
agent never needs to pay for — it re-derives cheaply, routes around,
or never encounters it — while carrying that knowledge costs real
wall-clock. The open-throttle formation stack is validated as
machinery (forms, consolidates, quarantines, delivers, and keeps an
honest ledger, with no human in the loop) and remains without a
workload, in this class, where what it carries can matter. The
substrate thesis ends the program as its one standing positive claim:
memory pays where the environment forgets, and a repository never
forgets.

## Track 22 — substrate removal (2026-08-30) — the boundary found: memory helps when the source is unreachable (38/38 pairs, FINAL)

The experiment every prior causal track lacked: a venue where the control
genuinely CANNOT read the source. Enforced (T22-P1, adversarial probe) by
giving both arms NO code execution — one budgeted `query_events` MCP tool
(5 results/query, 6 queries/session) and nothing else, so the timeline
cannot be read or enumerated. The rfm arm additionally holds the
instance's digested store. Scored at 33 of 38 pairs (run stopped near
completion; disclosed), judge-adjudicated arm-blind.

**T22-P2: PASS, and it is the program's first causal benefit.**
(Final, all 38 pairs; the 33-pair preliminary read p=0.002 at 12/1,
strengthened on completion.)
- judged correct: control 80, rfm **95** of ~130 (~62% -> ~73%).
- per-instance: rfm higher on **13**, control higher on **1**, tied 24;
  one-sided sign **p = 0.001**.
- mechanism (T22-P3 confirmed descriptively): rfm spent **13% fewer
  query turns** (338 vs 387) — the digest supplied facts the 6-query
  budget could not cheaply reach, and saved retrievals doing it.

**What this establishes, and its exact scope.** Every prior causal track
returned null or a small tax (Tracks 10-21), and all of them shared one
feature: the control could reach the source (the repo on disk, the raw
events as files). Track 22 removes that, and the null becomes a large,
significant benefit. So the finding that organizes the entire program is
now measured on BOTH signs:

  **Memory helps a frontier agent when, and only when, the environment
  does not already hand it the answer.** Substrate present (repo, readable
  timeline) -> no benefit, memory is a shortcut the agent doesn't need.
  Substrate removed (source unreachable within budget) -> clear benefit,
  memory supplies what the agent cannot otherwise get.

**Honest scope, stated so this is not over-read.**
- The substrate removal is ENGINEERED: the 6-query budget is a design
  parameter, not a natural constant. A looser budget would shrink the
  benefit (the control could query its way to more); a tighter one would
  grow it. What is robust is the DIRECTION and its significance at this
  operating point, not a universal effect size. The honest claim is
  conditional: "when retrieval from the source is budget-limited below
  the enumeration threshold, the digest helps."
- Judge-adjudicated (haiku, arm-blind); the same judge was calibrated at
  100% agreement with exact-match hits in Track 21a, but it is an LLM
  judge, not test-verified ground truth. **Non-LLM check (hardening):**
  under exact/substring match the DIRECTION holds (rfm 18 > control 15)
  but exact-match catches only ~17 of 98 answers (most correct answers
  are paraphrased), so it is too sparse to confirm significance (per
  instance 1/0/32 tied, p=0.5). The benefit's direction is judge-
  independent; its significance rests on the judge recognizing
  paraphrase. Stated, not hidden.
- 33 of 38 pairs; the remaining 5 cannot plausibly overturn p = 0.002 at
  12-vs-1, but the run can be completed for the record.
- This is the venue (organizational knowledge) and the condition
  (source withheld) the substrate thesis predicted. It confirms the
  thesis; it does not rescue operational memory for open repository
  coding, where the substrate is always present (Tracks 10-19 stand).

Track 12 (the M-rule comparison) unblocks against this panel — the first
positive causal panel the project has produced. The productization
reading also sharpens: memory's value is real and bounded — it is for
work where the source is expensive, rate-limited, or withheld (tool-gated
APIs, large corpora, cross-session context the agent cannot re-fetch),
not for work where a capable agent can simply read the environment.

## Track 21b — per-turn judged retrieval (2026-08-30) — FINAL 43/43: null, and half of the boundary's cleanest demonstration

Completed: perturn 29 vs control 33 judged-correct, per-instance 4 up /
6 down, sign p = 0.83, delivery 63%, wall −3.1%. The preliminary null
(13 pairs) holds at full n — per-turn judged retrieval does not help.

**But read together with Track 22, 21b is the control half of the
cleanest boundary demonstration the program produced.** Same benchmark
(MEMTRACK organizational questions), same digested stores, same
judge-adjudicated scoring. The ONLY difference: in 21b the control has
the raw event timeline as readable files in its workspace; in Track 22
the timeline is behind a budgeted query tool with no code execution.
That single change — whether the control can read the source — flips the
result from null (21b: 29 vs 33, p=0.83) to significant benefit (Track
22: 95 vs 80, p=0.001) on otherwise identical material. It is the
substrate thesis isolated to one variable: memory helps iff the source
is unreachable, and nothing else about the setup changed.



Scored at 13 of 43 pairs (the run was stopped repeatedly; this is a
disclosed partial, judge-adjudicated with the 21a arm-blind judge). It
is the fresh causal test of the mechanism 21a's retrospective signal
pointed to — per-question applicability-judged retrieval, precomputed
and delivered in-prompt (the live hook path being architecturally dead,
DESIGN_NOTES). The preliminary answer is a null that walks 21a back.

- **Aggregate: parity.** Judged-correct control 25, perturn 24 of 43;
  per-instance perturn up on 2, control up on 2, tied on 9; sign
  p = 0.69. No tax (wall −0.8%). Delivery 39% (17 of 43 turns got a
  fact; P1's 40% floor just missed).
- **The decisive cut — restricted to turns where a fact was actually
  delivered** (removing the 61% of turns where perturn = control by
  construction): of 17 delivered turns, memory **helped on 0, hurt on
  2**, both-correct on 5, both-wrong on 10. Where the applicability
  judge picked the right fact and it was placed in front of the model,
  it produced no correct answer the control missed, and cost two.

**What this means, stated carefully at partial n.** Track 21a found
memory helped under retrospective adjudication (rfm 108 vs 101,
p=0.055), delivered as one whole-store SessionStart injection. 21b
delivers the *judge-selected* fact *per question* in a fresh run — the
mechanism the applicability finding endorsed — and the benefit does not
appear: not in aggregate, and not even on the delivered turns where it
had every chance. The most likely reading is that 21a's marginal signal
was retrospective-judge variance or an artifact of whole-store
injection, and that per-turn judged delivery does not convert it. The
10-of-17 both-wrong turns say something sharper: on hard MEMTRACK
questions the delivered fact was necessary but not sufficient — the
agent still had to reason over it and often failed, so handing it the
fact did not move the outcome.

**Status: PRELIMINARY.** 13 pairs is a third of the design; the full
run can complete it, but the direction is clean (0 helped / 2 hurt on
delivered turns) and unlikely to reverse. Pending completion, the honest
program-level statement returns to: no fresh causal benefit of memory
has been demonstrated on any venue — 21a was the one hint, and its own
follow-up does not reproduce it. If the completed run changes this, it
is recorded here; nothing about 21a is edited, both stand.

## Track 21a — judge adjudication of Track 20 (2026-08-29) — the first time memory HELPED, stated at its true size

Track 20's exact-match parity (31 = 31) was a scoring artifact: strict
exact-match caught only ~31 of the ~100 answers that were actually
correct. A haiku judge, arm-blind, adjudicating the committed answers
from the session logs (no new sessions) resolves it:

- **judged correct: control 101, rfm 108 of 134** (P1 PASS — both arms
  lift far above exact-match, confirming exact-match undercounted).
- **per-instance: rfm higher on 8, control higher on 2, tied on 33;
  sign p = 0.055** (P2 PASS against the registered <= 0.10 bar).
- **judge reliability: 100% agreement on the 62 exact-match hits**
  (P3 PASS — the judge never overturned a known-correct answer, so the
  lift is not a miscalibrated judge inventing credit).

**This is the first positive result for memory in the entire program**,
and every qualifier matters:
- It is **modest**: +7 of 134 (~80% vs ~75%).
- It is **marginally significant**: sign p = 0.055, over the 0.05 line
  most would want, under the 0.10 bar registered in advance. A signal,
  not a settled win.
- It is a **retrospective judge rescoring**, not a fresh causal A/B —
  the answers were already produced; adjudication only re-graded them.
  An LLM judge graded them, mitigated by arm-blindness and the perfect
  exact-hit agreement, but it is not test-verified ground truth.

**What it changes.** Track 20's entry argued parity was expected
because the timeline fits in context, so the control already has
everything. 21a partially refutes that: memory helped **even though the
control held the raw timeline** — because having 36 raw events is not
the same as extracting the right decision, owner, or superseded status
from them, and the pre-digested memory surfaced facts the control
sometimes failed to derive. So the benefit is real and does not require
a beyond-context timeline; it comes from *digestion*, not *capacity*.
That is a better result than the Track 20 entry anticipated, and it is
the first evidence that ranked-by-helpfulness memory earns its keep in
the organizational venue — evidence at the strength of one marginal,
retrospective, judge-scored signal, which is what a Track 21b (fresh
paired A/B, adjudicated, ideally beyond-context) exists to confirm or
dissolve. Nothing here is claimed beyond that.

## Track 20 — MEMTRACK replay (2026-08-29) — 5/5, the tool-tax avoided, and honestly what that is and isn't

43 of 46 usable MEMTRACK instances, 86 sessions complete, all on CLI
2.1.251 (the update landed between the smoke on 2.1.246 and the full
run; no within-run heterogeneity — stamping confirmed). This is the
first externally-grounded result on a benchmark this project did not
build, in the tribal-knowledge venue, and every registered bar passed.

**The formation lifecycle worked on non-coding material** (the coding
pool never gave it this): 42 of 43 stores hold a promoted memory
(P1), extraction cost 4.3 LLM calls per instance (P5), delivery landed
in 44 of 43 rfm sessions (P2 — organizational timelines recur, so
dedupe-as-frequency promotes). The venue premise the coding pool
lacked is real here: teams repeat themselves.

**T20-P4, the claim — the tool tax is avoided, stated precisely.**
Registered bar: rfm wall within +10% of control, because the authors'
own Mem0/Zep backends made agents WORSE. Result: **+3.7%, PASS.** That
is the differentiated finding — injection-based delivery does not incur
the large redundancy tax that memory-as-tools did in Patronus's harness.
But the honest reading, reported because the C3 lesson demands the
distribution before the total: rfm was slower on 26 of 43 pairs (sign
p = 0.017), so injection is **not free** — there is a small,
statistically real per-pair slowdown, far under the bound and far under
the tool tax, but present. "No tax" is wrong; "a small tax, an order
below memory-as-tools" is right.

**T20-P3 correctness parity: PASS, exactly — control 31, rfm 31 of
134.** Two things this is NOT: it is not a correctness comparable to
the paper's 60% (that used GPT-5 in their live harness with LLM-judge
adjudication; ours is fable-5 in a replay under strict exact-match, so
23% absolute is a different, stricter measurement — the number to read
is parity, not the level), and it is not a benefit. Parity means memory
did not HURT correctness and cost little to carry; it does not show
memory HELPED. On MEMTRACK, the timeline fits in context, so the
control arm already has everything — exactly the condition under which
a repository "already persists it" and memory cannot lift.

**What Track 20 establishes, and the line it draws.** The open-throttle
stack is validated end to end on organizational data with no human in
the loop, and it clears the bar the benchmark's authors set as the
memory-tool failure mode. That is a real, external, positive result —
about the DELIVERY MECHANISM. It is not yet a causal-benefit result:
correctness parity on a fits-in-context benchmark shows the stack is
cheap and harmless, not helpful. The benefit question needs a venue
where the timeline does NOT fit in context (so the control arm cannot
hold everything) and adjudicated scoring — registered as the Track 21
question: MEMTRACK-scale timelines beyond the context window, correctness
LIFT rather than parity, judge-adjudicated. Until then the honest
summary is: on the tribal-knowledge venue, mem-rfm's ungated stack
delivers organizational memory at a small fraction of the tool tax and
without harming correctness — the first venue where it is not a net
negative, and not yet the venue where it is a net positive.

## Track 18b — the repaired replay (2026-08-28) — 5/5, and the ledger the fossil cannot re-form

Same 50 transcripts, same order, both instrument defects fixed. The
18b-vs-18 A/B isolates the instrument, and the differences are the
design working:

**The flood consolidated exactly as the dedupe-as-frequency idea
predicted.** 13 rows where Track 18 had 65; 43 dedupe-hits where it had
zero. The era-pin family is now 2 rows — the general fact at
**17 sightings / 16 accesses** and a test-specific variant at 8 — 25
combined sightings across 50 sessions (T18b-P1, P2 PASS). Recurrence is
captured as frequency instead of being discarded at review or smeared
across 22 paraphrases. Leakage fell to 0% of 13 admitted rows
(T18b-P4), cost held at 0.8 calls/transcript (T18b-P5).

**The fossil refusal is real this time, and thinner than the bar
suggests — both facts reported.** The judge executed 6 times (4 matched
to the era-pin row, 2 unmatched); every matched verdict was "unclear",
zero positives (T18b-P3 PASS, 0 vs the 17 the condition-blind loop
awarded on these same sessions). One judgment had condition_present =
true and still declined "helped" — which is correct calibration: a
transcript excerpt rarely proves counterfactual benefit, and that
epistemic humility is consistent with every causal measurement this
project has made. Coverage is the honest caveat: 6 judge executions
where the old loop closed ~17 outcomes, bounded by signature matching
between the store's consolidated text and session commands — the seam
the Track 16 schema's first-class action field exists to close.

**The state the store ends in is the design's thesis in one row:** the
era-pin fact, sightings 17, value 0.00, outcomes 0. Under the
conditioned regime the fact is *held* and *ranked by its recurrence*
(R and F carry the need-probability), while M stays silent until real
evidence arrives — the fossil structurally cannot re-form by being
copied. That is what "helped-when-needed is the signal" looks like in
a database.

## LongMemEval retrieval-stage port (2026-08-27) — NOT RUN, measured impossible

The planned generalization of the LoCoMo sequential-feedback result
(adaptivity +0.02..0.08, RESULTS above) to LongMemEval was probed
against the data before any code was written, and the probe closes it:
LoCoMo shares one store per conversation across ~200 questions, with
~49% of questions revisiting evidence that served an earlier one —
recurrence is what outcome feedback learns from. LongMemEval gives
every question a PRIVATE haystack: 500 questions, 500 disjoint stores,
so cross-question feedback transfer is impossible by construction (and
only 8 of 940 evidence sessions appear in more than one question even
across stores — 0.9%, in different haystacks besides). The value axis
is structurally inert there except within a single haystack, which is
precisely the slot ku_eval.py already occupies with the oracle
contradiction protocol (knowledge-update preference 0.43 → 0.66,
committed under results-ku/). LongMemEval's testable contribution to
this project is therefore already complete; the adaptivity claim keeps
LoCoMo as its only conversational corpus, disclosed as such wherever it
is quoted. No run spent — the probe is the finding, the Track 14
pattern applied to a bench eval.

## Track 15 — the yardstick (2026-08-27) — deliverables, and the D1 notes to Tracks 10/11/13

20 sessions, complete (a cosmetic exit-1 in the runner's pipe tail;
every record present): sphinx-7757, control arm, 10 reps each on
claude-fable-5 and claude-haiku-4-5-20251001, model and CLI (2.1.246)
stamped per record. All 20 resolved — resolution on this task is
deterministic across both tiers; the variance lives in the path.

**Deliverables.**
  fable: corrected events-to-green min 1 / med 1.5 / max 2, SD 0.5,
         range 1. Wall med 112.5s, SD 21.4s, range 72s. The legacy
         detector fired in only 8 of 10 sessions and tripled the
         spread (1–6, SD 2.3) — the legacy instrument is itself a
         noise source, which is C3 vindicated a third way.
  haiku: corrected events-to-green min 6 / med 11.5 / max 16, SD 3.5,
         range 10. Wall med 175.5s, SD 22.6s. The legacy detector
         fired in 1 of 10 sessions (unusable at this tier). Same task,
         same resolutions: the capability-tier friction gap is
         med 11.5 vs 1.5 events.

**T15-D1, applied.** The fable within-condition range (1 event) does
NOT cover the registered 13-event comparator, so the notes below state
the measured spread rather than a blanket underpowered qualifier:

- **Track 11 (fable):** on the corrected metric the yardstick is TIGHT
  (SD 0.5). Track 11's corrected between-arm differences were 0–2
  events — at noise scale individually, but a real shift of >= 2
  events would have been visible and was not. The corrected-metric
  null is a measured null at ~1-event resolution, not noise-blindness.
  Track 11's LEGACY-scored table inherits the legacy detector's 20%
  no-fire rate and 5-event spread; conclusions should rest on the
  corrected numbers, as its entry already does.
- **Track 13 (haiku):** per-pair differences (3–5 events) sit within
  haiku's within-condition SD (3.5) — no single pair is evidence. What
  carries the entry's harm reading is sign consistency: 0 wins in 5
  decided pairs (one-sided sign test p = 0.031) and wall slower on 7
  of 8 (p = 0.035). The direction is established; the per-task effect
  size is not. The entry's claims survive as written.
- **Track 10 (opus-5, xarray):** the yardstick transfers only
  qualitatively (different model AND repo). Its C3-corrected reading —
  2 wins / 7 losses / 4 ties, one-sided sign p = 0.09, "directionally
  negative, not significant" — is unchanged by these numbers.

**Design consequence for future tracks, stated now:** at n=8 pairs on a
haiku arm, only effects around one within-condition SD (~3.5 events)
that shift most pairs will clear wins-vs-losses; smaller claimed
effects need more pairs or paired reps. On a fable arm the corrected
metric resolves ~1-event effects at n=8. Registration thresholds
should be set from these numbers.

## PrefEval profile-scale eval (2026-08-29) — 3/3, and the successor venue's real problem has a familiar shape

The first successor-venue measurement (PROTOCOL.md Amendment 15,
registered before the run): all 1,000 explicit PrefEval preferences as
one user's profile store, 1,000 questions streamed against it, oracle
outcomes from the gold mapping. Structure probed first: gold evidence
never recurs (one preference, one question — LongMemEval's verdict
again), so the only learnable channel is DISTRACTOR recurrence, and
that is what was registered and measured.

**PE-P1 rank-safety: PASS at exactly +0.0000** [−0.007, +0.007] — the
composition bound holds untouched in a domain it was never tuned on.
**PE-P3: PASS** — the usage prior alone is harmless at profile scale
(−0.002). **PE-P2 distractor demotion: PASS on the registered sign
bar, honestly small** — late-third hit@1 rfm − rfm_wv0 = +0.0060
[+0.0000, +0.0150]: positive, direction-consistent, CI touching zero.
The demotion channel exists; at this corpus size it is a whisper.

**The descriptive finding that matters more than the bars:** profile-
scale preference retrieval is HARD — similarity-only hit@5 is 24.6%,
hit@1 8.8%, because "restaurants in Rome" and "I strictly avoid
gluten" share almost no surface. The retrieval problem in the
substrate-less venue is APPLICABILITY, not similarity — which
preference constrains this request — and that is the same shape as the
condition-matching problem the live program ended on (a memory is a
condition→consequence pair; text similarity cannot see the condition).
Whatever retrieves memories in this venue needs an applicability
judgment where the live program needed a condition gate. The two
programs converge on one lesson from opposite ends.

MEMTRACK (the org/tribal-knowledge agentic benchmark) needs its own
feasibility pass — it is a live multi-platform environment, not a
frozen corpus — and is queued, not started.

## Track 12 — the M-rule comparison (2026-08-30) — NOT VALIDATED: harness fails its own baseline check

Registered as Amendment 17 and run: earned-outcome M vs write-time
importance (Generative Agents poignancy / Zep fact-rating style, haiku
1-10 per memory, 1,451 cached) vs per-token value, on LoCoMo.

**The result is withheld because the harness does not reproduce the
committed baseline.** Two bugs and one design flaw, in order of
discovery:

1. **Dead activation channel** (fixed): the eval clock was hardcoded to
   1e9 (2001) while LoCoMo memories carry 2023 timestamps, so "now"
   preceded every memory's creation and ages went negative. Caught by
   the dead-signal rule this project already carries (methodology.md):
   `sim` and `genagents` returned byte-identical numbers, which two
   genuinely different rules cannot.
2. **Metric/protocol mismatch** (not fixed): with the clock corrected,
   the shipped `rfm` rule scores 0.0234 late hit@1 in this harness while
   the committed `locomo_eval.py` scores it 0.455 NDCG@10 on the same
   three conversations. The cause is the interaction of hit@1 with the
   outcome protocol: at k=10 roughly nine of every ten retrieved
   memories earn a -1, so frequently-retrieved (and therefore often
   relevant) memories are driven negative while never-retrieved ones
   keep a neutral score and float into the top-1 slot. NDCG@10 absorbs
   this; hit@1 is maximally exposed to it. The metric was my choice, not
   the registered protocol's.

As measured, write-time importance ranked above earned-M in this harness
(0.0781 vs 0.0234 late hit@1) — **and that number is not reportable as a
finding**, because the same harness places our own validated rule an
order of magnitude below its committed behaviour. Publishing it would be
the single-corpus mistake this project has already made twice, with a
broken instrument added.

**What the committed runner does say, on the same subset:** `rfm` beats
`rfm_wv0` (identical system, value axis switched off) by **+0.269 NDCG
[+0.235, +0.304]**. The earned-M axis contributes enormously against its
own ablation. That is evidence about M earning its place; it is not the
head-to-head against write-time importance, which remains unanswered.

**What would answer it:** add `importance` and `pertoken` as conditions
inside `locomo_eval.py` itself — reusing the validated protocol, NDCG@10,
and the overlap=True restriction — rather than scoring them in a parallel
harness. The importance scores are cached (results-track12/), so that
run is cheap. Registered as the open form of Track 12.
