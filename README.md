# mem-rfm

mem-rfm is long-term memory for coding agents that ranks what it
remembers by whether it actually *helped*. The whole thing is one SQLite
file and a pure-Python scoring engine; an MCP server and three hooks
make it drop-in for Claude Code. There is no service and no API key.
Nothing calls a model at ranking time: the prior is one indexed row
read, and session-start injection ranks on it alone. Search multiplies
that prior by similarity from a small local embedding model, the one
neural inference anywhere near retrieval. (Formation and outcome
judging may optionally use a cheap LLM, the sweep, whose judgments
become signals the prior learns from; retrieval itself never calls
one.)

The name is borrowed from marketing's RFM analysis, which segments
customers by the recency, frequency, and monetary value of their
purchases. Memories get the same treatment: recency and frequency come
from ACT-R, the cognitive model of human memory, which prices how likely
a memory is to be needed again. But mem-rfm goes beyond R and F: where
marketing puts monetary value, it puts **measured outcomes**, a signed
per-memory record of whether acting on the memory helped or hurt, fed
straight back into the ranking. Retrieved-often is cheap to fake, and
our own live program caught helped-when-used being faked too: agents
copy a suggested command, the copy succeeds, the ledger inflates. So a
positive outcome now counts only in sessions where the condition the
memory names actually fired. Helped-when-*needed* is the signal.
**[The full model →](docs/theory.md)**

## How it works

Retrieval multiplies similarity by each memory's earned prior; every
retrieval records an access, and the outcome (did it help?) scores it:

```sql
SELECT id, content,
       max(1.0 - vec_distance_cosine(embedding, :query), 0) * rfm_prior(id) AS score
FROM rfm_memories ORDER BY score DESC LIMIT 5;

SELECT rfm_record_access(42);        -- we retrieved memory 42
SELECT rfm_record_outcome(42, 1.0);  -- ...and it helped (-1.0 if it didn't)
```

In Claude Code the loop runs itself: every stage has a cheap in-session
path and a harness-owned path that does the real work:

| stage | you, in-session | the harness, post-hoc |
|---|---|---|
| **Formation** | `memory_save` on "remember this" | SessionEnd mines failed→fixed command pairs from the transcript; `/memory-review` ratifies |
| **Retrieval** | `memory_search` | SessionStart injects the top-3 by `rfm_score` |
| **Outcome** | `memory_feedback` when a memory surprises | inferred from what the session acted on, at session end; a `+1` lands only if the memory's named condition fired |
| **Retention** | `memory_delete` on "forget that" | idle never-useful memories are pruned; proven ones never are |

There is also an **ungated alternative** to the review step: `sweep.py`
runs continuously (cron or hook), doing one cheap LLM extraction per
transcript against a configurable ontology, near-duplicates merged into
a sightings count instead of new rows, a **two-sighting quarantine** in
place of human review (one poisoned transcript is insufficient by
construction), a conditioned LLM outcome judge, and a capped store.
Replayed over the transcripts that once built a fake 17-outcome ledger,
it captured the right facts, consolidated 22 paraphrases into 2 rows,
and awarded that ledger zero credits (RESULTS.md, Tracks 18b–19).

**[The full lifecycle, and who decides at each stage →](docs/lifecycle.md)**

## What it's for, and what it costs

When someone says ChatGPT "really knows me," that is memory doing its
easiest job. It is holding facts that live nowhere else: that you are
vegetarian, that you want short answers, what you are building. Nothing
in your environment remembers those for you, so writing them down is
pure gain, and you feel it in every reply.

Coding agents are the opposite case. The facts a coding memory would
hold, such as build quirks, dependency pins and environment
workarounds, are already written down in the repository the agent can
open and read. A stored note is competing with a source the agent can
simply consult. That difference is what decides whether memory pays
here, and it is the finding this project spent its live program
measuring ([memory-types.md](docs/memory-types.md) maps the full
taxonomy). Two questions follow.

**Does the ranking surface the right memory?** Yes, where the work
repeats. The clearest case is a fact that goes stale: when a procedure
changes, the outcome scores pull the old version down and retrieval
recovers to 0.56 hit@1, while plain similarity search is still
recommending the dead procedure at 0.20. That result depends on getting
honest feedback about what helped, which is harder than it sounds. Our
own scoring was fooled for weeks: an agent that copies a suggested
command and succeeds looks like proof the memory helped, even when the
problem the memory warns about never came up. A memory now earns credit
only in sessions where the situation it describes actually occurred.

**Does having the store make the agent better at its job?** Only when
the agent could not have found the answer by itself. In about twenty
pre-registered experiments on real bug-fixing, memory did not help at
all: a capable agent simply reads the repository, so a stored note about
a build quirk saves nothing, and carrying it costs roughly 25% in extra
wall-clock. Change one thing, though, and the picture inverts. Put the
information somewhere the agent cannot read (behind a rate-limited
search tool rather than files on disk) and the same memories produce a
large improvement: 95 correct answers against 80, p = 0.001. So the
question to ask before adopting this is not "is my agent smart enough"
but "can my agent already reach this information?" Skip it, too, if your
harness ships its own memory, since Claude Code, Cursor and Devin
capture the same operational lessons.

Every number, every pre-registered prediction, the buys table, the
acquisition measurement, and the full 13-row registered results table
are in **[findings.md](docs/findings.md)**; the complete per-track ledger
is `bench-quality/RESULTS.md`.

**[All findings, and everything that died along the way →](docs/findings.md)**

## Installation

Python 3.10+ with its bundled sqlite3 (≥ 3.35), nothing to compile:

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
# optional, ungated formation instead of /memory-review:
#   .venv/bin/python sweep.py      # cron/hook; see docs/lifecycle.md
```

Every save, search, and outcome is logged to `rfm-log.jsonl` beside the
database; `log_stats.py` turns the log into the numbers that decide
whether it is working for you. **[Full API and configuration →](docs/api.md)**

## Documentation

| | |
|---|---|
| [theory.md](docs/theory.md) | the model: Belady, ACT-R, and the outcome axis |
| [memory-types.md](docs/memory-types.md) | the taxonomy, what ChatGPT users actually meet, and what an agent needs |
| [lifecycle.md](docs/lifecycle.md) | formation to retention: who decides at each stage, and why |
| [findings.md](docs/findings.md) | when memory helps and when it doesn't, in full |
| [landscape.md](docs/landscape.md) | how this compares to the other memory systems, dated |
| [api.md](docs/api.md) | functions, config, schema, MCP server, repo layout |
| [methodology.md](docs/methodology.md) | pre-registration, corrections, known limits |
| [team-memory.md](docs/team-memory.md) | the team exploration, and why we stopped |

Also: `PROTOCOL.md` (pre-registrations, amendments 1–16c),
`bench-quality/live-ab/REVALIDATION.md` (the registered live tracks), and
`bench-quality/RESULTS.md` (the complete ledger).

## License

[Apache-2.0](LICENSE). Datasets are downloaded, never redistributed;
provenance and terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
(note LoCoMo is CC BY-NC).
