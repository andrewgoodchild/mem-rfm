# How mem-rfm compares

An August 2026 survey of 22 memory systems found the access → outcome →
ranking loop shipping in only two others.
[Cognee](https://docs.cognee.ai/guides/feedback-system) has one, off by
default, rating answers rather than task outcomes.
[Codex](https://github.com/openai/codex) has a real one — citing a memory
bumps a usage counter that drives both consolidation ordering and retention —
but at whole-session granularity, with no decay and no negative signal.
[ReMe](https://github.com/agentscope-ai/ReMe) uses outcome utility only to
prune. [MemOS](https://github.com/MemTensor/MemOS)'s `add_feedback` does
target the exact memories a retrieval returned, via `retrieved_memory_ids`
— but to *correct* their content, which is what `memory_update` does here,
not to score them.

So this appears to be the only system where outcome feedback is a default-on
term in the retrieval score, attributed to the individual memory retrieved,
with negative outcomes carrying weight, composed with similarity under a
bound frozen by experiment — and the only one shipped as an embeddable
primitive rather than a service. Concurrent 2026 research is converging on
the same loop ([RoMeRL](https://arxiv.org/abs/2608.02508),
[Chen & Cheng](https://arxiv.org/abs/2606.12945)).

Formation splits the other way: an August 2026 survey of formation
pipelines found shipping products gate new memories on human approval and
research systems on outcomes — none shipped does the latter — and only two
published LLM-free miners, which is the family the SessionEnd
correction-pair miner here belongs to.

Checked against current sources on 2026-08-15 (retrieval) and 2026-08-17
(formation), and dated because this
landscape moves quickly — Mem0 v2 was a breaking change whose MCP servers
are now archived, and Zep v3 removed its `memory.*` namespace and fact
ratings within the same window.

## Zep, specifically (added 2026-08-27)

Zep earns its own section because it is the most architecturally
articulated system in the survey and because reviewing it shaped one of
our design updates. Its engine is
[Graphiti](https://www.getzep.com/platform/graphiti/), a bi-temporal
knowledge graph: messages ingest as episodes, an LLM extracts entities
and fact triples against a configurable ontology (custom entity/edge
types), and every fact edge carries four timestamps — when it became
true, when it stopped, when the system learned each. A contradicting
fact *expires* the old edge rather than deleting it
([arXiv 2501.13956](https://arxiv.org/abs/2501.13956)).

Read on our axes: Zep's temporality is about fact **validity**, ours is
about fact **usefulness**, and the two miss different failures. Its
contradiction-driven invalidation catches facts that get *denied*
("Alice left TechCorp") and cannot see a condition that quietly stops
*occurring* — the silent-fossil case our live tracks measured
(RESULTS.md, Track 11 C4), which needs fire-rate observation, not
contradiction. Conversely, nothing in Zep scores whether retrieving a
fact ever helped: there is no outcome loop, so it sits with the 19 of
22 systems outside the opening paragraph's count. Its v2-era **fact
ratings** — a write-time relevance score from a configured instruction,
gating retrieval via a minimum-rating filter — were the
importance-prior design our Track 8 disputed and the literature never
causally validated; Zep itself removed the feature in v3, which is
worth recording as the pattern's fate in production.

What we took from the review (2026-08-27, tested before adoption):
the structured-extraction idea — schema fields at formation — replayed
as our Track 16 and adopted as mechanically free (recall held, leakage
fell) with condition mandatory and action optional; and validity-scope
metadata (era/checkout ranges) as declarative fields. What we declined:
permanent write-time rating gates, and any comparison on Zep's headline
benchmark — its LoCoMo numbers are in
[open dispute](https://github.com/getzep/zep-papers/issues/5) (84% vs a
58.44% replication vs a 75.14% rebuttal for the same system), which
says more about the benchmark than about Zep.

