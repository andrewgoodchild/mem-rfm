# mem-rfm

**A study of when agent memory actually pays — with the SQLite primitive
we built to measure it.**

RFM here is recency, frequency, and — where retail analytics puts
"monetary" — *measured outcomes*: the two ACT-R activation axes plus a
signed record of whether each memory, once retrieved, actually helped.
The primitive is a pure-Python SQLite scoring engine (plus an MCP server
and hooks for Claude Code). The study is ~30 pre-registered experiments
and a live paired-session program on when memory pays off, when it
doesn't, and what happens when someone abuses it — failures scored in
public alongside the wins.

## The findings

**Relevance is not value.** The study's most transportable result, and it
is about retrieval in general, not this implementation: ranking injected
memories by query similarity was measured and **rejected**, because
similarity *anti-selects* the memories that transfer. Per-bug content
surface-matches new bug reports and per-bug lessons don't transfer
(~6% measured); the operational gotchas that help session after session —
env workarounds, invocation patterns — are similar to nothing in
particular. An outcome-ranked prior kept 18 of 19 hits at 43% less
injected context; similarity ranking dropped a third of the hits.

**Recurrence gates value.** Memory pays where work recurs and doesn't
where it's episodic. On scattered real-bug fixing it was a mild net tax;
on a maximal-recurrence support workload the same frozen scoring beat
similarity at rank-1 with CI > 0; a live paired series found the wins
landing exactly on the tasks where operational knowledge recurs.

**Outcome feedback is the term that earns its keep.** An ablation of
every component of the scoring function found it the only one whose
removal measurably hurts across corpora — and against the one corpus
with real test-verified rewards (52,104 Terminal-Bench trials), the
value axis recovers true utility ordering at Spearman 0.83 within 25
observations, despite having been designed entirely on oracle labels.

**Memory's cost has three parts, and only one was widely known.** A
four-pilot live series plus a registered held-out revalidation priced
them: *machinery turns* (reading injections, saving, feedback — measured,
and removable: suppressing agent-volunteered saves, 11 of 13 of which
earned nothing, and inferring routine outcomes from the transcript took
the memory arm from +45s/session to at-or-below control); *cold-start
burden* (an empty store costs before it can pay — sometimes near zero,
and once badly not: a never-seen repo broke its registered cost bound at
+32% wall, the series' **first registered FAIL**, with a resolution gap
that no memory-side mechanism explains — three of its four failures ran
with empty injections); and the ***attachment tax*** — the constant
context cost of a memory server's tool schemas riding in every session,
paid before the first memory is saved. That last one is the leading
suspect for the FAIL, it quietly sits under every MCP-based memory
product ever benchmarked, and it is unmeasured — the registered next
experiment isolates it.

The registered revalidation otherwise held: 5 PASS, 2 NOT TRIGGERED
across a cold-start track and a staleness track, where an era-specific
memory took honest negatives, slid down the ranking, and had its claim
scoped by the agent — demotion and content correction working together
on held-out data (`bench-quality/live-ab/REVALIDATION.md`).

What this cost to learn: the live program behind these numbers is 196
headless Claude Code sessions and ~10 hours of agent wall clock, on the
order of a few million tokens end to end. Phase sizes of n=10–11 are a
budget bound, not a choice — treat the live results as mechanism
evidence, not effect-size estimates.

**[All findings, including the ones that argue against using this →](docs/findings.md)**

We also explored pooling memory across a team, measured what a bad team
member can do to a shared store, and then stopped: the mechanism works,
but the market has run that experiment repeatedly and it hasn't landed.
None of it ships here. **[The full write-up →](docs/team-memory.md)**

## The instrument

Agent memory systems retrieve by similarity: you ask, they return the
memories whose embeddings sit closest. Nothing in that loop ever notices
the outcome. A memory that was retrieved ten times and wasted the
agent's time on all ten looks exactly as relevant on the eleventh. Bad
memories never leave, and stale ones don't either — when a procedure
changes, the old version stays semantically perfect for the query that
matches it.

The primitive closes the loop. After a memory is retrieved you record
whether it helped, and that verdict becomes part of the ranking:

```sql
-- rank by similarity, adjusted by how well each memory has performed
SELECT id, content,
       max(1.0 - vec_distance_cosine(embedding, :query), 0) * rfm_prior(id) AS score
FROM rfm_memories ORDER BY score DESC LIMIT 5;

SELECT rfm_record_access(42);        -- we retrieved memory 42
SELECT rfm_record_outcome(42, 1.0);  -- ...and it helped (-1.0 if it didn't)
```

That's the whole interface. Scoring is one indexed row read — no API
keys, no network, no LLM anywhere in the ranking path.

Underneath, the problem is cache replacement: too many memories to put
in front of the model, so you must predict which are worth having.
Recency and frequency come from ACT-R, a cognitive model of human
memory. The outcome axis is the part a cache policy doesn't have —
because a cache hit is always valuable and a retrieved memory isn't.
Everything above was measured through this instrument, with every
retrieval, injection, and outcome logged to an auditable JSONL trace.
**[How the model works →](docs/theory.md)**

## Should you use the primitive?

**Probably yes if** your agent's work *recurs* — the same problems,
procedures or environments coming back. Operational knowledge is the
sweet spot: build quirks, dependency pins, project conventions, user
preferences.

**Probably not if** each task is unrelated to the last, or your workload
is "answer one question about a big pile of documents." We measured both
and memory didn't help; on scattered bug-fixing it was mildly
*negative*. Budget either way for the cost no memory system reports:
attaching one adds its tool schemas to every session's context before
the first memory is saved, and our one registered FAIL is currently best
explained by exactly that tax.

**Probably not if someone else owns your harness and it ships its own
memory.** Claude Code, Cursor, Devin and Windsurf all do, natively — no
attachment tax, better transcript access, the default slot. We say this
while our only shipped integration *is* Claude Code, and that is not an
accident: the integration is this study's instrument, and the study is
what found the overlap — in our own pilots, the harness's built-in
memory silently captured the same operational lesson as our store, in
both arms. Running mem-rfm alongside a native memory adds cost without a
measured marginal benefit. What survives the overlap is what native
memory doesn't do — an outcome ledger with signed negatives, auditable
staleness demotion, a store that travels across harnesses. Want those,
use it for those; otherwise the harness has this covered.

**Definitely not if** you want a memory service. This is a scoring
primitive plus evidence — one file, one process, no server.

## Install

Needs Python 3.10+ with its bundled sqlite3 (≥ 3.35) — nothing to compile:

```python
import sqlite3, rfm            # rfm.py, repo root, stdlib-only
db = sqlite3.connect("memories.db")
rfm.register(db)
db.execute("SELECT rfm_init()")
```

Non-Python hosts rank with the verified plain-SQL expression instead —
`bench-quality/pure_sql_check.py` generates it and pins it to the engine;
see [api.md](docs/api.md).

For Claude Code, an MCP server with local embeddings and one SQLite file:

```sh
cd integrations/claude-code && uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python mcp sqlite-vec fastembed numpy
.venv/bin/python smoke_test.py     # 39 checks over a real stdio launch
claude mcp add -s user rfm-memory -- "$(pwd)/.venv/bin/python" "$(pwd)/server.py"
.venv/bin/python install_hooks.py  # formation loop: injection, transcript
                                   # mining, inferred outcomes, /memory-review
```

It logs every save, search and outcome to `rfm-log.jsonl` beside the
database. `log_stats.py` turns that into the numbers that decide whether
it is working for you: whether feedback is actually coming back, and how
often the ranking differed from plain similarity.

**[Full API and configuration →](docs/api.md)**

## How this compares

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

## Documentation

| | |
|---|---|
| [findings.md](docs/findings.md) | when memory helps and when it doesn't, in full |
| [theory.md](docs/theory.md) | the model: Belady, ACT-R, memory types |
| [lifecycle.md](docs/lifecycle.md) | formation to retention: who decides at each stage, and why |
| [api.md](docs/api.md) | functions, config, schema, MCP server |
| [methodology.md](docs/methodology.md) | pre-registration, corrections, known limits |
| [team-memory.md](docs/team-memory.md) | the team exploration, and why we stopped |

Also: `PROTOCOL.md` (pre-registrations, amendments 1–14) and
`bench-quality/live-ab/REVALIDATION.md` (the registered held-out revalidation),
`bench-quality/RESULTS.md` (the complete ledger, including everything that
died), `DESIGN_NOTES.md` (design decisions and trade-offs).

## Repository

```
rfm.py                    the scoring engine (registers the rfm_* SQL functions)
rfm_schema.sql            standalone schema
tests/                    engine unit + SQL-surface tests (python3 tests/test_rfm.py)
bench-quality/            all evidence: retrieval evals, live A/B, throughput, RESULTS.md
integrations/claude-code/ MCP server, hooks, A/B kit — the study's live instrument
docs/                     the writeups linked above
```

## License

[Apache-2.0](LICENSE). Datasets are downloaded, never redistributed —
provenance and terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
(note LoCoMo is CC BY-NC).
