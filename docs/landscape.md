# How mem-rfm compares

An August 2026 survey of 22 memory systems found the access → outcome →
ranking loop shipping in only two others.
[Cognee](https://docs.cognee.ai/guides/feedback-system) has one, off by
default, rating answers rather than task outcomes.
[Codex](https://github.com/openai/codex) has a real one — citing a memory
bumps a usage counter that drives both consolidation ordering and retention —
but at whole-session granularity, with no negative signal.
[ReMe](https://github.com/agentscope-ai/ReMe) used outcome utility only to
prune, and no longer has those operations. [MemOS](https://github.com/MemTensor/MemOS)'s `add_feedback` does
target the exact memories a retrieval returned, via `retrieved_memory_ids`
— but to *correct* their content, which is what `memory_update` does here,
not to score them.

That survey missed one, and an earlier version of this page wrongly called
mem-rfm the only system with this design.
[Reflect](https://docs.starlight-search.com/guides/memories.md) has shipped a
default-on outcome term since April 2026, by its docs: it blends similarity
with a per-memory value updated from reviewed runs, with a failed run scoring
zero. Its server is closed, and it credits every memory retrieved in a run
equally, with no check that a memory's condition occurred. Single-file peers
also exist ([sqlite-memory](https://github.com/sqliteai/sqlite-memory),
[TAIPANBOX Engram](https://github.com/TAIPANBOX/Engram)), so mem-rfm is not
the only embeddable primitive either.

As of November 2026 we have not found another open-source system that scores
retrieved memories with signed, automatically inferred outcomes in its
default ranking, and credits a success only when the memory's named condition
fired. That is a claim about what we looked at, not about every project.
GitHub Copilot's memory now votes automatically on whether a memory is still
valid, and upvoted memories are more likely to be sent: products score
whether a memory is still valid, mem-rfm scores whether acting on it worked,
and it publishes its failures. Concurrent 2026 research is converging on the
same loop ([RoMeRL](https://arxiv.org/abs/2608.02508),
[Chen & Cheng](https://arxiv.org/abs/2606.12945)).

Formation splits the other way: an August 2026 survey of formation
pipelines found shipping products gate new memories on human approval and
research systems on outcomes — none shipped does the latter — and only two
published LLM-free miners, which is the family the SessionEnd
correction-pair miner here belongs to.

Checked against current sources on 2026-08-15 (retrieval), 2026-08-17
(formation) and 2026-11-01 (the outcome claims above; counts stay August's),
and dated because this landscape moves quickly — Mem0 v2 was a breaking change whose MCP servers
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

