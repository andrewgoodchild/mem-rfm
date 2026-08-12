# mem-rfm

**Agent memory that learns which memories are actually worth keeping.**

A SQLite extension (plus an MCP server for Claude Code) that ranks stored
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

**The name** comes from **RFM**, the customer-scoring model from direct
marketing: **R**ecency, **F**requency, **M**onetary value. Marketers learned
that recency and frequency are free from transaction logs but only measure
*engagement* — without the monetary axis you can't tell a valuable customer
from a busy one. Retrieval logs have the same shape and the same blind spot,
so mem-rfm keeps the structure and swaps the third axis for its analog: did
this memory actually help?

Recency and frequency aren't tracked separately. They come from **ACT-R
base-level activation** — a cognitive-science model of human memory, fitted
to human recall data, in which each past use contributes a term that decays
with age. Many old uses can equal a few recent ones. A 2006 approximation
makes it O(1), so scoring never walks the access log.
[How the model works →](docs/theory.md)

## Should you use this?

**Probably yes if** your agent's work *recurs* — the same problems,
procedures or environments coming back. Operational knowledge is the sweet
spot: build quirks, dependency pins, project conventions, user preferences.
And especially if **several agents share one store**, which is where the
largest measured effects are.

**Probably not if** each task is unrelated to the last, or your workload is
"answer one question about a big pile of documents." We measured both and
memory didn't help; on scattered bug-fixing it was mildly *negative*.

**Definitely not if** you want turnkey team memory. This is a scoring
primitive plus evidence: no access control, no tenancy, no cross-machine
sync. [What team mode actually requires →](docs/team-memory.md)

## Install

Needs a SQLite that can load extensions (≥ 3.35). Apple's bundled CLI has
loading compiled out — use Homebrew's.

```sh
cargo build --release
sqlite3
.load ./target/release/librfm
SELECT rfm_init();
```

For Claude Code, an MCP server with local embeddings and one SQLite file:

```sh
cd integrations/claude-code && uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python mcp sqlite-vec sentence-transformers numpy
claude mcp add -s user rfm-memory -- "$(pwd)/.venv/bin/python" "$(pwd)/server.py"
```

[Full API and configuration →](docs/api.md)

## What we found

The short version. Everything is measured, pre-registered, and the failures
are reported at the same length as the successes.

**Memory pays where work recurs.** Outcome feedback adds 0.02–0.08 NDCG on
questions revisiting earlier ground, across three embedding models. In 70
live coding sessions, exactly one memory earned sustained value: an
environment gotcha about dependency pins. Not a code lesson — a build quirk.

**It doesn't pay where work is episodic.** On scattered real-bug fixing the
system measured its own lesson-transfer rate at **~6%** (15 of 16 outcomes
negative), and across 27 paired tasks the memory arm solved 23 against the
control's 25. Consistent with noise, but not a win.

**The value axis's reliable jobs are safety and maintenance**, not ranking
quality. Rank by usage alone and retrieval collapses to NDCG ≈ 0.01
(rich-get-richer); negative feedback is what breaks that loop. It also
retires stale content that similarity keeps recommending forever.

**Sharing a store across a team is the largest effect** — +26.1, +37.5, +4.0
and +14.5 points hit@5 over per-agent stores on four datasets, three of them
pre-registered replications. Accumulated experience even out-ranks each
dataset's human-written manual, though the manual wins the cold start
decisively.

[All findings, including what argues against using this →](docs/findings.md) ·
[Team memory →](docs/team-memory.md)

## What a bad team member can do

A shared store's ranking is worth attacking. Four attacks, ten defence
configurations, six pre-registered amendments — as far as we know the only
quantified attack/defence evidence for memory ranking anywhere.

| attack | result |
|---|---|
| Write convincing junk | self-correcting — served 6 times instead of similarity's 29 |
| Self-promote your own memories | **worse than no ranking at all** — until `exclude_self`, which fully fixes it |
| Censor a rival | **fails outright** — the bound that limits the ranking's influence also makes it unusable as a weapon |
| Collude with others | **−5.0 points, unfixed.** Six defences failed |

Collusion doesn't yield to ranking, and the six failures share one
explanation: every defence aggregates votes, and a ring manufactures votes.
The most interesting attempt made endorsement a **liability** — vouch for a
memory and its later failures debit you — which puts a ring in a genuine
prisoner's dilemma: cooperate and your standing collapses, defect and the
attack degenerates into the solo case that's already defended. It collapses
ring reputation reliably on both datasets. It still doesn't repair retrieval.

What does work is **detection**: a ring praises only its own members, and
that concentration identified all four colluders on both datasets from the
access log alone. Run [`integrations/audit.sql`](integrations/audit.sql).

[The full attack/defence writeup →](docs/adversarial.md)

## How this compares

An August 2026 survey of 22 memory systems found the access → outcome →
ranking loop shipping in exactly one other open-source system —
[Cognee](https://docs.cognee.ai/guides/feedback-system), where it is off by
default and rates answers rather than task outcomes. Two others implement
pieces: [ReMe](https://github.com/agentscope-ai/ReMe) uses outcome utility
only to prune, and a [MemOS plugin](https://github.com/MemTensor/MemOS)
credits an episode's new traces rather than the memories retrieved.

So this appears to be the only system where outcome feedback is a default-on
term in the retrieval score, attributed to the memory actually retrieved,
with negative outcomes carrying weight — and the only one shipped as an
embeddable primitive rather than a service. Concurrent 2026 research is
converging on the same loop ([RoMeRL](https://arxiv.org/abs/2608.02508),
[Chen & Cheng](https://arxiv.org/abs/2606.12945)); a July 2026 review
([arXiv:2607.23942](https://arxiv.org/abs/2607.23942)) still lists cognitive
activation combined with utility as not yet migrated from cognitive
architectures into language agents.

## Documentation

| | |
|---|---|
| [findings.md](docs/findings.md) | when memory helps and when it doesn't, in full |
| [team-memory.md](docs/team-memory.md) | pooling results, and what team mode actually requires |
| [adversarial.md](docs/adversarial.md) | attacks, defences, and the six that failed |
| [theory.md](docs/theory.md) | RFM, ACT-R, and the composition experiment |
| [api.md](docs/api.md) | functions, config, schema, MCP server |
| [methodology.md](docs/methodology.md) | pre-registration, the correction, known limits |

Also: `PROTOCOL.md` (pre-registrations and amendments 1–10),
`bench-quality/RESULTS.md` (the complete ledger, including everything that
died), `DESIGN_NOTES.md` (design decisions and trade-offs).

## Repository

```
src/                      the extension (lib, functions, math, sql shim, config, clock)
rfm_schema.sql            standalone schema
tests/                    unit + CLI integration tests (cargo test)
bench/                    O(1) throughput benchmark
bench-quality/            retrieval benchmarks + RESULTS.md
experiments/swe-ab/       the live paired A/B on real bugs
integrations/claude-code/ MCP server, hooks, capture snippet, A/B kit
integrations/audit.sql    shared-store forensics + governance recipes
docs/                     the writeups linked above
```

## License

[Apache-2.0](LICENSE). Datasets are downloaded, never redistributed —
provenance and terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
(note LoCoMo is CC BY-NC).
