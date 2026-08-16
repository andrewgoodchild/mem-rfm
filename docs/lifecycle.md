# The lifecycle of a memory

Four stages — formation, retrieval, outcome, retention — and at every stage
this repo runs two paths at once: **in-session tool calls**, which exist
because they're cheap and sometimes fire, and a **post-hoc, harness-owned
path, which is the one that actually carries the load.** The design rule
behind the whole document: never make the loop depend on the model deciding
mid-task to do memory work. It measurably doesn't.

## What we do

| stage | in-session (scaffolding) | post-hoc, harness-owned (load-bearing) |
|---|---|---|
| **Formation** | `memory_save` for durable facts; "remember this" | SessionEnd hook mines the transcript for failed→fixed command pairs, stages them; `/memory-review` ratifies |
| **Retrieval** | `memory_search` before exploring from scratch | SessionStart hook injects the top-5 by `rfm_score` |
| **Outcome** | `memory_feedback(id, helped)` | SessionEnd hook infers outcomes from *use*: acted-on + how it went |
| **Retention** | `memory_delete` on "forget that" | `rfm_prunable(id, days)`; positive outcomes are never prunable |

**Formation.** `hooks/session_end.py` extracts the one signal objectively
present in a transcript — a command that failed followed by a variant that
worked. That is a gotcha the session paid for, in the category
(operational knowledge) our A/B says transfers. Candidates are staged to
`pending-memories.md`, never auto-saved; the `/memory-review` skill is the
ratification step. The in-session `memory_save` path stays available and a
CLAUDE.md block (maintained by `install_hooks.py`) prompts it, but nothing
depends on it firing.

**Retrieval.** `hooks/session_start.py` injects the top memories by pure
`rfm_score` — no query exists at session start, so this is the prior doing
exactly its job — capped at 1,500 characters. Injection is push; `memory_search`
is pull; both feed recency and frequency through recorded accesses (search
does today; see the usage gap below). Retrieval is an *event*, which is what
makes the cache analogy live rather than decorative.

**Outcome.** `rfm_record_outcome` supplies the dimension similarity cannot:
staleness. A memory that stops being useful — because a procedure changed,
not because it grew less similar — is only detectable here. One outcome per
access, enforced, so the log always reproduces the summary state. How
outcomes actually arrive is the load-bearing question — "Getting the M"
below.

**Retention.** Ranking decides what surfaces; `rfm_prunable` decides what
stays: idle past the window AND never proved useful. The guard is the
substantive part — a memory retrieved rarely but successfully is exactly
what this system exists to keep. Retention is also formation's safety net:
prolific harness capture is only tolerable because evidence-based pruning
sits downstream.

## Getting the M

Without outcomes, `rfm_prior` degenerates to recency + frequency — and we
measured what that is worth: ranked by R and F alone, a store collapses
under sequential load (NDCG ≈ 0.01, [findings.md](findings.md)), and the
ablation found the value axis the *only* component whose removal hurts. No
feedback loop, no reason for RFM to exist.

But `memory_feedback` is a discretionary second tool call, competing with
the task for the model's attention, payoff deferred to a future session —
the exact structure that makes discretionary *formation* under-fire. A
CLAUDE.md instruction raises the fire rate; it cannot make it reliable.

The answer is the same answer as formation: **move it post-hoc**. The
SessionEnd hook infers outcomes from the transcript, which contains
everything an outcome needs, in three deterministic steps:

1. **Which memories were in play** — the SessionStart injection block
   carries the `[rfm-memory:…]` marker and memory ids, and `memory_search`
   results with ids sit in the transcript verbatim.
2. **Whether one was acted on** — operational memories are commands, pins,
   paths. A backtick-quoted span from the memory reproduced in a later
   command, or a command whose tokens are drawn from the memory (program
   match plus overlap threshold — the correction-miner's own discipline).
3. **How that went** — the harness recorded the command's result. Acted on
   and succeeded → `+1`. Acted on and failed → `−1` (which also catches the
   session's own failed→fixed pair overturning a memory's advice). In play
   but never used → **no outcome**: absence of use is what `rfm_prunable`
   measures, not negative evidence.

Three rules keep it honest. **Explicit feedback wins** — if the latest
access already carries a model-recorded outcome, inference defers to it.
**Use is the access event** — an injected memory records its access when it
is acted on, not when it is displayed, so injection alone never inflates
recency and frequency. **Precision over recall** — a missed outcome costs
little (the prior shrinks toward neutral), a wrong one pollutes, so the
matching thresholds are tight, and every inferred outcome is logged to
`rfm-log.jsonl` with the command that triggered it, auditable after the
fact.

Unlike formation, outcomes are **written directly, not staged**, and the
asymmetry is principled: formation admits new unbounded *claims* into the
store, which needs a human; an outcome adjusts the weight on an existing
claim inside a frozen bounded blend (EWMA λ=0.3, confidence shrink,
β-capped composition). The math is the review step, and a wrong outcome
decays — a wrong memory doesn't.

So the M arrives through three channels, by reliability: explicit user or
model feedback when it happens (rare, highest signal), the in-session
`memory_feedback` call the CLAUDE.md block prompts for (raises the fire
rate, cannot be relied on), and the post-hoc inference above (deterministic
floor — every session that *acts on* a memory closes that memory's loop).
What we deliberately do not do is Codex-style whole-session credit: a
citation-bump with no valence and no per-memory attribution is the design
this repo exists to improve on.

## Why: what the field taught us

We surveyed who decides formation in shipped systems (2026-08):

| system | writes decided by | trigger | retrieval |
|---|---|---|---|
| Claude Code auto-memory | model, full discretion | none | index injected at session start |
| `CLAUDE.md` / `AGENTS.md` | user | user edits | injected in full |
| Codex memories (Apr 2026) | **harness only — model forbidden** | background job, ≥ 6h idle | summary injected at session start |
| MCP memory servers | model, full discretion | tool descriptions | model must decide to search |
| this repo | harness proposes, human ratifies | session end | staged for review |

The poles are instructive. Claude Code leaves formation entirely to the
model ("decides what's worth remembering") — and our own server ran in live
sessions for six weeks without a single tool call reaching the database.
OpenAI went the other way: Codex's in-session model is told, in its own
system prompt, **"Never update memories. You can only read them."** There
is no "model decides to save" moment anywhere in its design. The MCP
ecosystem still ships discretion and routes around it with scaffolding (the
reference memory server's README forces the model to open every chat with
"Remembering…").

Discretion under-fires for structural reasons: saving is never on the
task's critical path (cost now, payoff in a session this instance never
sees); no moment forces the decision; and push-only retrieval means the
model never experiences the failed memory query that would teach it writing
has value. Worse, when discretion *does* fire it anti-selects — across 70
live sessions our agent saved 17 sincerely-chosen lessons and **15 of 16
later outcomes were negative**. Judging durability mid-task means
predicting the future; post-hoc, "what did we have to learn?" is an
observation.

Post-hoc capture over-produces — that's its known failure mode. Every
vendor that auto-captured into a long-lived store retreated, and the ETH
Zurich study (arXiv:2602.11988) found LLM-generated context files *reduced*
task success. Hence the two defenses that compose: stage for review, and
let outcome-ranked retention prune. Human memory works the same way —
encoding is cheap and indiscriminate, and the environment's recurrence
statistics do the selecting (Anderson & Schooler 1991, the same result the
activation math is built on). Cheap indiscriminate writes plus ruthless
evidence-based retention beats careful discretionary writes plus similarity
ranking, because it puts each decision where its evidence is.

Distilled:

1. Never ask an agent mid-task whether something is worth remembering
   (measured: 15 of 16 wrong).
2. Capture and record outcomes at deterministic moments the harness owns.
3. Stage into review; never auto-write to a long-lived store.
4. Make formation cheap and retention ruthless — which requires the
   outcome axis, because similarity cannot prune.
5. Expect cold start (Codex ships six empty hours by design); first-session
   value belongs in checked-in files like `CLAUDE.md`/`AGENTS.md`.

## Sources

Survey conducted 2026-08-15 against live official docs: Claude Code memory
and MCP docs (code.claude.com), Codex memories and AGENTS.md guides
(developers.openai.com), LangChain memory concepts. Primary discussion:
openai/codex Discussion #12567, Issue #19195 ("Never update memories"),
Discussion #23364 (hook-based capture). Codex pipeline internals beyond the
official docs are community-sourced (codex.danielvaughan.com). First-hand
measurements (the idle server, the 70-session formation A/B,
correction-pair mining) are this repo's; see
[methodology.md](methodology.md).
