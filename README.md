# mem-rfm

## What is mem-rfm?

mem-rfm is long-term memory for coding agents that ranks what it
remembers by whether it actually *helped*. The whole thing is one SQLite
file and a pure-Python scoring engine; an MCP server and a pair of hooks
make it drop-in for Claude Code. There is no service, no API key, and no
LLM anywhere in the ranking path — scoring is one indexed row read.

The name is borrowed from marketing's RFM analysis, which segments
customers by the recency, frequency, and monetary value of their
purchases. Memories get the same treatment: recency and frequency come
from ACT-R, the cognitive model of human memory, which prices how likely
a memory is to be needed again. But mem-rfm goes beyond R and F — where
marketing puts monetary value, it puts **measured outcomes**: a signed,
per-memory record of whether acting on the memory helped or hurt, fed
straight back into the ranking. Retrieved-often is cheap to fake;
helped-when-used is the signal. **[The full model →](docs/theory.md)**

## How it works

Retrieval multiplies similarity by each memory's earned prior; every
retrieval records an access, and the outcome — did it help? — scores it:

```sql
SELECT id, content,
       max(1.0 - vec_distance_cosine(embedding, :query), 0) * rfm_prior(id) AS score
FROM rfm_memories ORDER BY score DESC LIMIT 5;

SELECT rfm_record_access(42);        -- we retrieved memory 42
SELECT rfm_record_outcome(42, 1.0);  -- ...and it helped (-1.0 if it didn't)
```

In Claude Code the loop runs itself — every stage has a cheap in-session
path and a harness-owned path that does the real work:

| stage | you, in-session | the harness, post-hoc |
|---|---|---|
| **Formation** | `memory_save` on "remember this" | SessionEnd mines failed→fixed command pairs from the transcript; `/memory-review` ratifies |
| **Retrieval** | `memory_search` | SessionStart injects the top-3 by `rfm_score` |
| **Outcome** | `memory_feedback` when a memory surprises | inferred from what the session acted on, at session end |
| **Retention** | `memory_delete` on "forget that" | idle never-useful memories are pruned; proven ones never are |

**[The full lifecycle, and who decides at each stage →](docs/lifecycle.md)**

## Benefits

Memory pays for procedural things that repeat — build quirks, dependency
pins, environment workarounds, invocation patterns: the operational
knowledge that comes back session after session. That is exactly where
the measured wins landed: in live paired runs, the memory arm's
advantage sat on the tasks where operational knowledge recurred, and the
ranking consistently promoted the memories that kept proving out while
demoting the ones that didn't.

The claims are pre-registered and scored. The live program ran paired
Claude Code sessions on real bugs in three open-source Python repos —
memory arm against control, resolution scored by each project's own
tests. Every prediction below was written down and committed before the
run it governs:

| what we asked | prediction | outcome |
|---|---|---|
| cold start, familiar repo (pytest) | machinery cost stays within +10% wall / +15% tokens | **PASS** — −7.6% / −12.4% |
| cold start, never-seen repo (xarray) | same bound | **FAIL** — +32.0% / +35.5%, cause not established |
| does the miner catch what sessions pay for? | it stages a candidate whenever a named-cause failure occurs | **PASS** — staged and ratified in-run |
| does a proven memory keep earning? (pytest) | a memory that earned in phase one earns again in phase two | **NOT TRIGGERED** — nothing earned value on that repo, as registered |
| same question, never-seen repo (xarray) | as above | **AMBIGUOUS** — our registered wording was defective; disclosed, not repaired after the fact |
| do stale memories do harm? (sphinx, new era) | an outdated earned ledger stays within +10% wall | **PASS** — +3.0%, and the ledger demoted itself |
| do demoted memories stay demoted? | outcome-demoted memories are never re-injected | **PASS** — verified in-run |
| what does an idle memory server cost? (sphinx) | measurable context overhead from tool schemas alone; two-sided decision rule on wall and resolution | **REGISTERED — result pending** |

**[All findings, and everything that died along the way →](docs/findings.md)**

## Installation

Python 3.10+ with its bundled sqlite3 (≥ 3.35) — nothing to compile:

```python
import sqlite3, rfm            # rfm.py, repo root, stdlib-only
db = sqlite3.connect("memories.db")
rfm.register(db)
db.execute("SELECT rfm_init()")
```

For Claude Code, the MCP server with local embeddings, plus the hooks
that run the lifecycle table above:

```sh
cd integrations/claude-code && uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python mcp sqlite-vec fastembed numpy
.venv/bin/python smoke_test.py     # 39 checks over a real stdio launch
claude mcp add -s user rfm-memory -- "$(pwd)/.venv/bin/python" "$(pwd)/server.py"
.venv/bin/python install_hooks.py  # injection, transcript mining,
                                   # inferred outcomes, /memory-review
```

Every save, search, and outcome is logged to `rfm-log.jsonl` beside the
database; `log_stats.py` turns the log into the numbers that decide
whether it is working for you. **[Full API and configuration →](docs/api.md)**

## Documentation

| | |
|---|---|
| [theory.md](docs/theory.md) | the model: Belady, ACT-R, and the outcome axis |
| [lifecycle.md](docs/lifecycle.md) | formation to retention: who decides at each stage, and why |
| [findings.md](docs/findings.md) | when memory helps and when it doesn't, in full |
| [landscape.md](docs/landscape.md) | how this compares to the other memory systems, dated |
| [api.md](docs/api.md) | functions, config, schema, MCP server, repo layout |
| [methodology.md](docs/methodology.md) | pre-registration, corrections, known limits |
| [team-memory.md](docs/team-memory.md) | the team exploration, and why we stopped |

Also: `PROTOCOL.md` (pre-registrations, amendments 1–14),
`bench-quality/live-ab/REVALIDATION.md` (the registered live tracks), and
`bench-quality/RESULTS.md` (the complete ledger).

## License

[Apache-2.0](LICENSE). Datasets are downloaded, never redistributed —
provenance and terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
(note LoCoMo is CC BY-NC).
