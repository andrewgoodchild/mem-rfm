# mem-rfm

**Agent memory that learns which memories are actually worth keeping.**

A pure-Python SQLite scoring engine (plus an MCP server for Claude Code)
that ranks stored
memories by whether they *helped* — not just whether they look relevant.
Shipped with ~30 pre-registered experiments on when agent memory pays off,
when it doesn't, and what happens when someone abuses it.

## The problem

Agent memory systems retrieve by similarity: you ask, they return the
memories whose embeddings sit closest. Nothing in that loop ever notices the
outcome. A memory that was retrieved ten times and wasted the agent's time on
all ten looks exactly as relevant on the eleventh.

So bad memories never leave, and stale ones don't either — when a procedure
changes, the old version stays semantically perfect for the query that
matches it.

## What this does

It closes the loop. After a memory is retrieved you record whether it helped,
and that verdict becomes part of the ranking.

```sql
-- rank by similarity, adjusted by how well each memory has performed
SELECT id, content,
       max(1.0 - vec_distance_cosine(embedding, :query), 0) * rfm_prior(id) AS score
FROM rfm_memories ORDER BY score DESC LIMIT 5;

SELECT rfm_record_access(42);        -- we retrieved memory 42
SELECT rfm_record_outcome(42, 1.0);  -- ...and it helped (-1.0 if it didn't)
```

That's the whole interface. Scoring is one indexed row read — no API keys, no
network, no LLM anywhere in the ranking path.

Underneath, the problem is cache replacement: too many memories to put in
front of the model, so you must predict which are worth having. Recency and
frequency come from ACT-R, a cognitive model of human memory. The outcome
axis is the part a cache policy doesn't have — because a cache hit is always
valuable and a retrieved memory isn't.
**[How the model works →](docs/theory.md)**

## Should you use this?

**Probably yes if** your agent's work *recurs* — the same problems,
procedures or environments coming back. Operational knowledge is the sweet
spot: build quirks, dependency pins, project conventions, user preferences.

**Probably not if** each task is unrelated to the last, or your workload is
"answer one question about a big pile of documents." We measured both and
memory didn't help; on scattered bug-fixing it was mildly *negative*.

**Definitely not if** you want a memory service. This is a scoring primitive
plus evidence — one file, one process, no server.

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
database. `log_stats.py` turns that into the numbers that decide whether it
is working for you: whether feedback is actually coming back, and how often
the ranking differed from plain similarity.

**[Full API and configuration →](docs/api.md)**

## What we found

Memory pays where work **recurs** and doesn't where it's episodic — on
scattered real-bug fixing, the system measured its own lesson-transfer rate
at ~6% and was a mild net tax. Outcome feedback is the component carrying its
weight: an ablation of every part of the scoring function found it the only
one whose removal measurably hurts, and against the one corpus with real
test-verified rewards (52,104 Terminal-Bench trials) the value axis recovers
true utility ordering at Spearman 0.83 within 25 observations.

A four-run live pilot series on real bug-fixing (paired Claude Code
sessions, gold-test scoring, full traces committed) turned that into a
mechanism story. With naive settings, memory was a net tax even though the
ranking was right about which memories mattered (pilot 2). Cutting
agent-volunteered saves — 11 of 13 earned nothing — and letting the harness
infer routine outcomes from the transcript removed the entire overhead
(pilot 3). With an earned ledger and selection that trusts it, the memory
arm beat control on wall clock and tokens for the first time (pilot 4), the
wins landing exactly on the tasks where operational knowledge recurs. The
selection finding is the one to remember: ranking injections by query
similarity was measured and **rejected** — it anti-selects the memories
that transfer, because per-bug content surface-matches new bug reports
while the operational gotchas that actually help match nothing in
particular. Relevance is not value. A registered held-out revalidation of
the frozen stack lives in `bench-quality/live-ab/REVALIDATION.md`.

The honest headline is a modest one, because a large gain was never the
claim. This is a small, deliberately bounded adjustment to similarity search,
and most of what it buys is safety and maintenance — keeping a usage prior
from eating itself, and retiring content that similarity would recommend
forever.

**[All findings, including the ones that argue against using this →](docs/findings.md)**

We also explored pooling memory across a team, measured what a bad team
member can do to a shared store, and then stopped: the mechanism works, but
the market has run that experiment repeatedly and it hasn't landed. None of
it ships here. **[The full write-up →](docs/team-memory.md)**

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
integrations/claude-code/ MCP server, hooks, capture snippet, A/B kit
docs/                     the writeups linked above
```

## License

[Apache-2.0](LICENSE). Datasets are downloaded, never redistributed —
provenance and terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
(note LoCoMo is CC BY-NC).
