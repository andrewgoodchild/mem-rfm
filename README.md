# mem-rfm

mem-rfm is long-term memory for coding agents that ranks what it
remembers by whether it actually *helped*. The whole thing is one SQLite
file and a pure-Python scoring engine; an MCP server and three hooks
make it drop-in for Claude Code. There is no service and no API key.
Nothing calls a model at ranking time: the prior is one indexed row
read, and session-start injection ranks on it alone. Search multiplies
that prior by similarity from a small local embedding model — the one
neural inference anywhere near retrieval. (Formation and outcome
judging may optionally use a cheap LLM — the sweep — whose judgments
become signals the prior learns from; retrieval itself never calls
one.)

The name is borrowed from marketing's RFM analysis, which segments
customers by the recency, frequency, and monetary value of their
purchases. Memories get the same treatment: recency and frequency come
from ACT-R, the cognitive model of human memory, which prices how likely
a memory is to be needed again. But mem-rfm goes beyond R and F — where
marketing puts monetary value, it puts **measured outcomes**: a signed,
per-memory record of whether acting on the memory helped or hurt, fed
straight back into the ranking. Retrieved-often is cheap to fake — and
our own live program caught helped-when-used being faked too: agents
copy a suggested command, the copy succeeds, the ledger inflates. So a
positive outcome now counts only in sessions where the condition the
memory names actually fired. Helped-when-*needed* is the signal.
**[The full model →](docs/theory.md)**

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
| **Outcome** | `memory_feedback` when a memory surprises | inferred from what the session acted on, at session end — a `+1` lands only if the memory's named condition fired |
| **Retention** | `memory_delete` on "forget that" | idle never-useful memories are pruned; proven ones never are |

There is also an **ungated alternative** to the review step: `sweep.py`
runs continuously (cron or hook) — one cheap LLM extraction per
transcript against a configurable ontology, near-duplicates merged into
a sightings count instead of new rows, a **two-sighting quarantine** in
place of human review (one poisoned transcript is insufficient by
construction), a conditioned LLM outcome judge, and a capped store.
Replayed over the transcripts that once built a fake 17-outcome ledger,
it captured the right facts, consolidated 22 paraphrases into 2 rows,
and awarded that ledger zero credits (RESULTS.md, Tracks 18b–19).

**[The full lifecycle, and who decides at each stage →](docs/lifecycle.md)**

## What it's for, and what it costs

Memory pays for procedural things that repeat **and that the
environment does not already persist** — organizational procedures
and the moments they change, decisions and ownership, user preferences
and working style, cross-repo tribal knowledge. Our own live program
measured that boundary on both sides. The operational knowledge we
originally built this for — build quirks, dependency pins, environment
workarounds — recurs, but a repository persists it and a frontier agent
re-derives or reads it, so there is nothing for memory to save (the
registered table below). Yet in a venue where the source is genuinely
**unreachable** — the agent given no code execution and only a
budget-limited query tool — the same digested memory produced a large,
significant benefit (68 → 82 of 98 correct, p = 0.002; Track 22). So the
rule is exact: **memory helps a frontier agent when, and only when, the
environment does not already hand it the answer** ([findings](docs/findings.md)).

### What it buys

| measured | result | basis |
|---|---|---|
| putting the right memory first, on recurring work | **+0.012 hit@1** [95% CI +0.005, +0.020], rising to +0.020 over the final third as feedback accumulates | 3,000 real support calls; exploratory, **oracle** outcomes |
| retiring facts that a procedure change made wrong | recovers to **0.56 hit@1** where similarity-only is still recommending the dead procedure at **0.20**, 1,500 calls later | same corpus, procedures revised mid-stream; **oracle** outcomes |
| preferring an updated fact over the version it replaced | **0.43 → 0.66**, with no loss of fresh-fact recall | LongMemEval knowledge-update tasks; **oracle** labels |
| scoring a memory by how useful it truly was | **Spearman 0.83** against ground truth within 25 observations | 52,104 Terminal-Bench trials — **real** test-verified rewards |
| a live coding run once the ledger has been earned | memory arm beat control: **−8.6% wall**, 9.7k vs 10.9k output tokens | 10 paired Claude Code sessions; **wild** feedback, exploratory — **overtaken**: the registered causal tracks below re-tested this ledger and found no effect; the row stays for the record |

The pattern across those rows: *ranking* pays where work recurs and
feedback is correct, and pays most at the top slot — the position that
matters when you hand an agent one suggestion. These are retrieval-layer
results; whether having the store causally helps an agent is the
question the registered table below answers, and the two layers came
apart.

**The assumption underneath them, stated plainly.** Three of those rows
use oracle outcomes. They establish what ranking does *given* correct
feedback; they do not establish that a system obtains correct feedback
in the wild. That acquisition step is the load-bearing assumption of
this whole design, and it has the least clean measurement on the page —
if the thesis fails, it fails there, not at +0.012 hit@1.

What we can say about acquisition: across six live runs the loop closed
**67 times by transcript inference against 23 explicit model calls**,
and replaying those transcripts with explicit feedback as ground truth,
inference recovered 9 of 15 outcomes with **zero sign errors** — it
misses (the relevance judgments it structurally cannot see) but it does
not invert. Sign accuracy turned out to be the wrong reassurance: the
causal tracks below found the loop's *credit* was wrong — its positives
were largely earned in sessions where the memory's condition never
fired (copied commands, credited successes; 79% of the top ledger).
Outcomes are now condition-gated — a `+1` requires the named condition
to have fired — and the ledger that motivated the fix could not have
been earned under it (theory.md, "the condition side of the
production").

### What it costs, and where it doesn't pay

Unrelated episodic tasks and one-question-over-a-document-pile workloads
showed no benefit, and on repository bug-fixing the terminal tracks
measured carrying memories as a real cost — +25 to +27% wall where
delivery worked and the knowledge went unneeded. If your
harness already ships its own memory — Claude Code, Cursor and Devin all
do — the overlap is real and measured: in our own pilots the native
memory captured the same operational lessons our store did.

Those costs are pre-registered and scored. The live coding program ran
paired Claude Code sessions on real bugs in three open-source Python
repos — memory arm against control, resolution scored by each project's
own tests — and it is the hardest case for memory: episodic work, where
our own measurements put lesson transfer at ~6%. Every prediction below
was written down and committed before the run it governs:

| what we asked | prediction | outcome |
|---|---|---|
| cold start, familiar repo (pytest) | machinery cost stays within +10% wall / +15% tokens | **PASS** — −7.6% / −12.4% |
| cold start, never-seen repo (xarray) | same bound | **FAIL** — +32.0% / +35.5%. The leading suspect was excluded by the last row; still unexplained at n=11 ([forensics](docs/findings.md#the-registered-fail-in-detail)) |
| does the miner catch what sessions pay for? | it stages a candidate whenever a named-cause failure occurs | **PASS** — staged and ratified in-run |
| does a proven memory keep earning? (pytest) | a memory that earned in phase one earns again in phase two | **NOT TRIGGERED** — nothing earned value on that repo, as registered |
| same question, never-seen repo (xarray) | as above | **AMBIGUOUS** — our registered wording was defective; disclosed rather than quietly repaired, and [corrected for future registrations](bench-quality/live-ab/REVALIDATION.md) |
| do stale memories do harm? (sphinx, new era) | an outdated earned ledger stays within +10% wall | **PASS** — +3.0%, and the ledger demoted itself |
| do demoted memories stay demoted? | outcome-demoted memories are never re-injected | **PASS** — verified in-run |
| what does an idle memory server cost? (sphinx) | measurable context overhead from tool schemas alone; two-sided decision rule on wall and resolution | **MEASURED** — +189 tokens/session (~0.9% of context), wall +1.0%, resolution identical: context-cost-only |
| does a human-ratified store help on held-out tasks? (xarray) | fewer events to a first passing test than control | **FAIL** — no effect in either direction, with injection landing 13/13 (Track 10, corrected reading) |
| does the best earned memory beat no-memory at home? (sphinx) | token-matched, four content forms, on the tasks that earned its ledger | **FAIL** — ties under both detectors; forensics showed 79% of its ledger was earned with its condition silent (Track 11 + C4) |
| does it at least help a weaker model? (haiku) | condition-liveness gate, then sign consistency | **FAIL** — 0 wins of 5 decided pairs, +27.6% wall: a measured tax (Track 13) |
| does the full ungated lifecycle help where friction is forced? | a pool engineered so verification dies without the workaround | **FAIL at the gate** — the agent met the condition in 1 of 20 control sessions and verified around it; every lifecycle stage worked, delivery 19/20, and carrying the memory cost +25% wall (Track 19) |
| does memory help when the control CANNOT read the source? | organizational questions, both arms given no code execution and only a budget-limited query tool | **PASS** — control 68, memory **82** of 98 correct, up on 12 instances / down on 1, **sign p = 0.002**, with 13% fewer queries (Track 22) — the one condition under which memory helped |

How to read the table: the first eight rows are **cost or safety
bounds** — the program's first phase set out to establish that memory
does no harm on the workload where it helps least. (The idle-server row
closes the loop on the xarray FAIL above it: registered while that
failure stood unexplained, its context-cost-only verdict is what
attributes the gap to variance rather than machinery.) The next four are
the registered benefit predictions on repository coding, and all failed —
the fourth terminally: on that workload the agents do not pay the costs
the memories describe, because a frontier agent reads or re-derives from
the repo, so there is nothing for memory to save while carrying it costs
real time. **The last row is the one that flips.** Every negative above
shares a hidden feature — the control could reach the source — and Track
22 removes it: with the timeline behind a budget-limited query tool and
no code execution, the digested memory produced a large, significant
benefit. So the table reads as a boundary, not a verdict: **memory helps
a frontier agent when, and only when, the environment does not already
hand it the answer** — engineered budget, LLM-adjudicated, organizational
venue; the repository negatives stand. The search also located a defect
in the instrument along the way (the ledger credited condition-blind
copying — fixed by the condition gate). Related retrieval-layer results:
on PrefEval the composition bound transferred at exactly +0.0000 and the
retrieval problem was measured as *applicability, not similarity*; and on a
MEMTRACK replay (organizational/tribal knowledge) the ungated formation
stack cleared every registered bar (Track 20, 5/5) — forming and
delivering organizational memory with no human in the loop, at a small
fraction of the redundancy tax the benchmark's own authors measured for
memory-as-tools, and without harming correctness. First venue where
mem-rfm is not a net negative; whether it is a net *positive* needs
timelines that exceed the context window, the registered next question.
Per-track record in `bench-quality/RESULTS.md`; synthesis in
[findings.md](docs/findings.md).

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

[Apache-2.0](LICENSE). Datasets are downloaded, never redistributed —
provenance and terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
(note LoCoMo is CC BY-NC).
