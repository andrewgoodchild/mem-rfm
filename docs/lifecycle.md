# The lifecycle of a memory

Four stages: **formation** (does a memory get written at all), **retrieval**
(what surfaces), **outcome** (what it was worth), **retention** (what stays).
Each is a decision, and the load-bearing question at every stage is the same:
*who* decides, *when*, on *what evidence*. The math behind retrieval and
outcome lives in [theory.md](theory.md); this document is the lifecycle
itself — with formation treated at full depth, because formation is where
the field's default design measurably fails, and everything downstream of it
assumes a populated store.

## 1. Formation — who decides a memory exists

The usual design delegates the write decision to the model mid-task. The
evidence below — one first-hand measurement, one survey of shipped systems
(as of August 2026), and the vendors' own architecture choices — says that
design produces empty stores.

### The store that stayed empty

This repo's own MCP server is the motivating measurement. It ran in live
Claude Code sessions from July 2026 onward: connected over stdio in ~1.4s,
advertised its nine tools every session, never errored. And in all that time
**not one tool call reached the database** — the database directory did not
exist until a deliberate smoke test on 2026-08-15 created it. Nothing was
broken. The server was available, described, and ignored, because every
moment of every session had something more urgent to do than remember.

That is the shape of the problem: formation doesn't fail loudly. It just
never happens.

### Who decides, in shipped systems

| System | Writes decided by | Write trigger | Retrieval |
|---|---|---|---|
| Claude Code auto-memory | model, full discretion | none — model must spontaneously judge utility | passive: first 200 lines / 25KB of `MEMORY.md` injected at session start |
| Claude Code `CLAUDE.md` / Codex `AGENTS.md` | user | user edits (or explicit ask) | injected in full at session start |
| Codex memories (Apr 2026 preview) | **harness only — model forbidden to write** | background job after a thread is idle ≥ 6h (default), ≤ 30 days old, quota permitting | passive: consolidated `memory_summary.md` injected at session start |
| MCP memory servers (reference server, mem0, this repo) | model, full discretion | tool descriptions are the only hint | model must decide to search |
| This repo's `hooks/session_end.py` | harness proposes, human ratifies | session end, deterministic | staged to `pending-memories.md` for review |

Three findings from that table deserve emphasis.

**Claude Code leaves formation entirely to the model.** The official docs
say Claude "decides what's worth remembering based on whether the
information would be useful in a future conversation" — no trigger on
corrections, no trigger on preferences, no harness capture. Retrieval is
push, not pull: the memory index is injected blindly at session start, and
nothing in the loop ever makes the model *want* a memory it doesn't have.

**OpenAI, having presumably watched the same failure, went to the opposite
pole.** Codex's memory feature (shipped as an opt-in preview April 2026) is
100% harness-driven: a background pipeline summarizes threads after they've
been idle six hours, a consolidation pass merges summaries into a durable
`MEMORY.md`, and the result is injected at the next session start. The
in-session model is explicitly instructed — in the injected system prompt —
**"Never update memories. You can only read them."** There is no "model
decides to save" moment anywhere in the native design. Write timing is
wall-clock and quota, not semantic judgment.

**The MCP ecosystem still ships the discretionary design, and routes around
it with scaffolding.** The reference knowledge-graph memory server's own
README ships a system prompt commanding the model to *"Always begin your
chat by saying only 'Remembering...' and retrieve all relevant
information"* — an admission that without forced instructions the tools
simply don't get called. Community hook systems (e.g. OpenViking's
UserPromptSubmit/Stop hooks, May 2026) capture and inject memories
deterministically, "rather than requiring the model to voluntarily invoke
memory tools."

### Why discretion under-fires

Four mechanisms, and they compound.

**1. Saving is never on the critical path.** The model's in-session
objective is finishing the task; a memory write is a cost paid now for a
payoff that lands in a session this instance never experiences. LangChain's
memory docs state the trade plainly: a "hot path" agent "must multitask
between memory creation and its other responsibilities, potentially
affecting the quantity and quality of memories created." Nothing connects
the future benefit back to the present decision.

**2. There is no forcing moment.** The facts worth keeping — a build quirk,
a dependency pin, a correction — do not arrive labeled. Each one,
individually, looks skippable, and skipping is always locally correct.

**3. When discretion does fire, it fires badly.** We measured this
directly: across 70 live sessions the agent saved 17 sincerely-chosen
lessons, and **15 of 16 later outcomes were negative**. Judging durability
*while working* means predicting the future, and the agent can't.
Discretionary formation is not just rare — it is anti-selected.

**4. Passive retrieval kills demand.** In every shipped system above,
retrieval is injection at session start. The model never issues a memory
query, so it never experiences a query that *fails* — the one signal that
would teach it writing has value. Push-only retrieval starves the write
side of its reason to exist.

### The convergent answer: post-hoc, harness-owned

Every system that ships memory at scale arrived at the same place from
different directions: **take the decision away from the in-session model
and move it after the fact**, when what mattered is visible.

- Codex: background extraction + consolidation, model read-only.
- Hermes: post-session background review.
- LangMem/LangChain: "background" memory formation as the named
  alternative to hot-path tool calls.
- Community Codex/Claude hooks: deterministic capture at prompt-submit and
  session-stop.
- This repo: `hooks/session_end.py` extracts the one signal objectively
  present in a transcript — **a command that failed followed by a variant
  that worked** — a gotcha the session demonstrably paid for, in the
  category (operational knowledge) our A/B says transfers.

Post-hoc formation also fixes the anti-selection problem: after the
session, "what did we have to learn?" is an observation, not a prediction.
And the signal has to be *correction*, not repetition: a frequency-based
miner over the same transcripts surfaced only `pytest -q` and `git stash` —
generic behaviour the model already knows. **Repetition finds what agents
do; correction finds what they had to learn.**

### Over-formation is the ranking problem — which is the point

Deterministic capture over-produces; that is its failure mode, and it is
well documented. Every vendor that auto-captured into a shared or
long-lived store retreated, and the ETH Zurich context-file study
(arXiv:2602.11988) found LLM-generated context files *reduced* task
success. Unreviewed accumulation makes things worse.

There are two defenses, and they compose:

**Stage, don't write.** `session_end.py` proposes candidates to
`pending-memories.md` for human review (the `/memory-review` skill is the
tooling for that step). Staging is what the surviving products do.

**Let retention prune, on evidence.** This is where formation meets the
rest of the repo. Human memory solves formation the same way: encoding is
cheap and largely indiscriminate, and the *environment's* statistics of
recurrence do the selection afterwards — that is precisely the Anderson &
Schooler (1991) result the activation math is built on. The filter belongs
downstream of formation, where evidence exists. But downstream filtering
under load is exactly where similarity-only ranking collapses
(rich-get-richer, NDCG ≈ 0.01 — see [findings.md](findings.md)); the
outcome axis is what makes prolific formation *safe*. Formation and
retention are not separate features. Cheap indiscriminate writes plus
outcome-ranked retention beats careful discretionary writes plus
similarity ranking — because the first pair puts each decision where its
evidence is.

### Formation design rules

1. **Never ask an agent mid-task whether something is worth remembering.**
   Measured: 15 of 16 such judgments were wrong.
2. **Capture at deterministic moments the harness owns** — session end,
   failure→success pairs — not at moments the model must notice.
3. **Stage into review, never auto-write** into a shared or long-lived
   store.
4. **Make formation cheap and prolific; make retention ruthless.** That
   requires an outcome axis, because similarity cannot prune.
5. **Force the outcome loop the same way you force the write loop.**
   Discretionary feedback is discretionary formation's twin and fails the
   same way (see stage 3 below).
6. **Trigger-specific tool descriptions are scaffolding, not a solution.**
   They raise the fire rate of discretionary calls; they do not make them
   reliable.
7. **Expect cold start.** Codex ships a six-hour idle gate — by design,
   nothing exists on day one. First-session value must come from somewhere
   else (e.g. checked-in `AGENTS.md`/`CLAUDE.md`, which every vendor
   positions as the home for rules too important to leave to generated
   memory).

## 2. Retrieval — what surfaces

Similarity picks candidates; the bounded prior reorders among plausible ones
(the math is in [theory.md](theory.md)). Retrieval is itself an event: it
feeds recency and frequency, which is what makes the cache analogy live
rather than decorative.

Retrieval design also feeds back into formation. Injection at session start
(this repo's `hooks/session_start.py`, Claude Code's memory index, Codex's
summary) is push, not pull — reliable, but as noted above, a model that
never queries never learns what a missing memory costs. The two modes
compose: inject the prior-ranked top-K deterministically, keep search
available for the model, and let neither be the only path.

## 3. Outcome — what it was worth

`rfm_record_outcome` supplies the dimension Belady lacks. Exactly one
outcome is accepted per access, enforced, so the access log always
reproduces the summary state and any score can be recomputed from first
principles.

This stage is also what makes forgetting possible. A memory that stops
being useful — because a procedure changed, not because it grew less
similar — can only be detected here. Similarity cannot see staleness: a
stale memory stays semantically perfect forever.

**Outcome recording has formation's problem one level down.** Even when a
memory is retrieved, recording whether it *helped* is a second
discretionary tool call (`memory_feedback`), competing with the task for
the model's attention, with the payoff again deferred. It under-fires for
the same four reasons formation does — and if it does, the prior stays
flat and the value axis never engages. Whatever harness mechanism forces
formation must also infer or force outcomes: correction-pair detection,
task-result inspection at session end, standing instructions
(`install_hooks.py` maintains a CLAUDE.md block for exactly this), or
explicit review — not model discretion mid-task.

## 4. Retention — what stays

Ranking decides what surfaces, not what stays, and stores grew forever.
`rfm_prunable(id, max_unused_days)` borrows Codex's policy, where citation
refreshes a memory and uncited rows age out — usage driving *retention*,
not just rank:

```sql
SELECT id FROM rfm_memories WHERE rfm_prunable(id, 30);
```

A read-only predicate, not a delete: the tables are host-owned. The guard
is the substantive part — **anything with a positive outcome record is
never prunable**, however idle. A memory retrieved rarely but successfully
is exactly what this system exists to keep, and exactly what a pure cache
policy would evict. That guard is the Belady framing's limit showing
through: optimal caching drops the rarely-used item, and here that would be
the wrong call.

Retention is also formation's safety net, per stage 1: a prolific,
harness-owned capture pipeline is only tolerable because pruning and
outcome-ranking sit downstream of it.

## Sources

Formation survey conducted 2026-08-15. Official docs, verified live: Claude
Code memory (code.claude.com/docs/en/memory.md), Claude Code MCP
quickstart, Codex memories (developers.openai.com/codex/memories) and
changelog, AGENTS.md guide (developers.openai.com/codex/guides/agents-md),
LangChain memory concepts (docs.langchain.com/oss/python/concepts/memory).
Primary discussion: openai/codex Discussion #12567 (memory design
questions, Feb 2026), Issue #19195 ("Never update memories" prompt,
Apr 2026), Discussion #23364 (hook-based capture, May 2026), Issues
#21932/#3981 (no AGENTS.md auto-update path). Ecosystem: reference
knowledge-graph MCP memory server README; mem0's Codex analyses. Pipeline
internals for Codex (extraction model, ~5k-token summary budget, exact
config ranges) are community-sourced (codex.danielvaughan.com deep-dives)
and consistent with, but not confirmed by, official docs. First-hand
measurements (idle server, 70-session formation A/B, correction-pair
mining) are this repo's; see [methodology.md](methodology.md).
