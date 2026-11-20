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

## Anthropic's five layers (added 2026-11-08)

Anthropic's research write-up on the components of agent memory
(anthropic.com/research/components-of-agent-memory) names five layers,
and its vocabulary is likely to become the field's, so here is mem-rfm in
it. **Transcripts**: the normalized session `transcripts.py` reads is the
same event log; mem-rfm offers no search over it, and Track 30 measured
that baseline (raw turns 0.88 corrections per task against formed memories
0.47 and no memory 1.22). **Memory notes**: the rows. **Representations**:
none; grouping memories by conversation added nothing live (Track 30) and
LLM supersession was wrong 13 of 21 times (Track 28), which matches their
finding that wikis pay only on multi-document judgment. **Injected
context**: SessionStart's top-3, 1,500 characters, and this is the one
place the two designs differ in kind. Their top layer is curated by an
offline pass with no stated rule; mem-rfm's promotion rule is mechanical
and earned: rank by recency, frequency and signed outcomes, never a row
the ledger has voted down, never one its own source contradicts.
**Dreaming**: the sweep, the outcome inference and the prune are an
offline consolidation pass of that kind, minus the step they put first,
correcting a note against the transcript it came from. `verify.py` adds
that step (Track 35 measures it). Where the write-up and this program
disagree is in-session salience: they report it improving sharply across
model generations and advise telling a model what memory is for rather
than how to use it; this program measured discretionary saving
anti-selecting on one model generation in July 2026 and built around that.
The claim is now dated in `lifecycle.md`, and a retest is registered.

Two smaller sources read the same week. Ayan Pahwa's from-scratch research
agent (github.com/iayanpahwa/research-agent-from-scratch, write-up at
humanbound.ai) records, at n=1 per arm, a note saved from a wrong first run
being read first and repeated with confidence by the second, "a bad note
outlives the run that made it": the failure the verify pass exists for,
illustrated independently. David Lee's doctrine (github.com/davidlee/doctrine,
its memory layer in RFC 009) keeps verification as an axis separate from
status, suppresses low-trust high-severity memories from retrieval, and
records a measured bug (EVD-001) where an attestation survived a rewrite of
the text it attested; `store.CLEAR_VERIFIED` is the rule that prevents it
here. Its memory layer is otherwise unmeasured design.

## Memorilla (added 2026-11-17)

Memorilla (Stanford SNAP, arXiv 2610.21375, Apache-2.0) is a trained memory
module: it compresses a whole document collection into 16 query-dependent
memory tokens placed in a frozen Qwen3-8B's input embedding space, and on
FactKG beats giving the model every document (84.33% against 80.43%). A
second recipe trains the module from game reward alone with GRPO on
TextWorld, 18.6% to 24.2% solve rate. It belongs beside RoMeRL and Chen &
Cheng as the convergent direction, memory shaped by outcome, with the
distinction stated: they train a module from reward, mem-rfm scores rows
from outcomes, and nothing in their code path runs against an API model.
Three things were taken (Amendment 19b, methodology.md "Standing
measures", Track 37): full context as a standard arm, the hard-subset
measure, and PersonalizationV4 as the applicability venue.
Its Table 11 (Qwen3-8B decoder, test split) puts PV4 at closed book 58.30,
RAG top-5 64.98, full context 59.12, Mem0 65.07, MemoRAG 67.88, Memorilla
66.65: every memory method within three points of plain retrieval, and
full context below it. Track 37 ran mem-rfm's arms on the same split with a
Claude answerer and landed in the same place (RESULTS.md).

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

