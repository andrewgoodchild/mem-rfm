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
