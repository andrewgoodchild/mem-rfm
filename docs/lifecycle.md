# The lifecycle of a memory

Four stages — formation, retrieval, outcome, retention — and at every stage
this repo runs two paths at once: **in-session tool calls**, which exist
because they're cheap and sometimes fire, and a **post-hoc, harness-owned
path, which is the one that actually carries the load.** The design rule
behind the whole document: never make the loop depend on the model deciding
mid-task to do memory work. It measurably doesn't.

## What we do

| stage | in-session (scaffolding) | post-hoc, harness-owned (does the real work) |
|---|---|---|
| **Formation** | `memory_save` for durable facts; "remember this" | SessionEnd hook mines the transcript for failed→fixed command pairs, stages them; `/memory-review` ratifies |
| **Retrieval** | `memory_search` before exploring from scratch | SessionStart hook injects the top-3 by `rfm_score`, never a memory whose outcomes sit negative |
| **Outcome** | `memory_feedback(id, helped)` | SessionEnd hook infers outcomes from *use*: acted-on + how it went |
| **Retention** | `memory_delete` on "forget that" | SessionEnd hook deletes what `rfm_prunable(id, days)` marks (`RFM_PRUNE_DAYS`, default 30; each removal logged); positive outcomes are never prunable |

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
is pull; both feed recency and frequency through recorded accesses — search
records the access at retrieval, an injected memory records its access only
when it is acted on (the "use is the access event" rule under Getting the M
below). Retrieval is an *event*, which is what makes the cache analogy live
rather than decorative.

**Outcome.** `rfm_record_outcome` supplies the dimension similarity cannot:
staleness. A memory that stops being useful — because a procedure changed,
not because it grew less similar — is only detectable here. One outcome per
access, enforced, so the log always reproduces the summary state. How
outcomes actually arrive is the decisive question — "Getting the M"
below.

**Retention.** Ranking decides what surfaces; `rfm_prunable` decides what
stays: idle past the window AND never proved useful. The SessionEnd hook
runs the pass after outcomes (`RFM_PRUNE_DAYS`, default 30; `<= 0`
disables), logging every removal with redacted content. The guard is the
substantive part — a memory retrieved rarely but successfully is exactly
what this system exists to keep. Retention is also formation's safety net:
prolific harness capture is only tolerable because evidence-based pruning
sits downstream.

**The ungated alternative: the sweep.** The review step above is a
choice, not a law, and the shipped alternative removes it
(`integrations/claude-code/sweep.py`, DESIGN_NOTES "the open-throttle
design"): a cron- or hook-driven pass over new transcripts, one
configurable LLM extraction per session against an ontology
(`sweep-config.json`), and the gate's jobs reassigned to structure —
near-duplicates merge into an existing row's `sightings` count instead
of flooding (recurrence captured as frequency, which review used to
throw away); a **two-sighting quarantine** replaces human judgment as
a poisoning defense (sweep-created rows are not injectable until a second
independent origin produces the same lesson: a session that observed the
condition itself, or another repository. One poisoned transcript is
insufficient by construction, and so is one source read in every session of
a repository; poison naming a condition that really fired is not stopped
here); composed actions are
dropped unless the transcript actually ran them; and a hard cap with
grace-period eviction bounds the store. Outcomes in sweep deployments
can additionally come from a conditioned LLM judge — asked whether the
session exhibited the memory's condition AND whether acting changed the
outcome, never "was it used". Validated end to end: mechanically
(test_sweep.py), on replay over the transcripts that built the fossil
ledger (Track 18b: 22 paraphrases → 2 rows, zero of 17 false credits
re-awarded), and live (Track 19: formed, consolidated to 26 sightings,
quarantine-promoted, delivered 19/20 — with the honest ledger reading
value 0.00 because nothing ever proved it helped).

**Verification (added 2026-11-08).** The ledger scores a memory by what
happened when the agent acted on it through a command. A memory that states
a rule is rarely acted on that way, so the ledger never sees it: in Track 31
a stale decision sat in front of the agent on 15 runs and earned nothing,
and nothing demoted it. Anthropic's agent-memory write-up names the missing
step: an offline pass ("dreaming") that re-reads the transcript a note came
from and corrects it, the transcript being the one ground truth a note has.
`decide` now keeps each memory's verbatim quote and the transcript it was
formed from, and `mem_rfm_cli.py verify` re-reads that transcript, finds the
quote's window, and asks whether the conversation still supports the memory
as stated: `confirmed`, `contradicted` (the model must quote the overriding
turn, and the code checks the quote is really there), `unsupported`, or
`source_gone` when Claude Code has deleted the transcript. Only
`contradicted` changes delivery, through the same gate as the negative-value
floor (`store.not_contradicted`, `RFM_VERIFY_GATE=0` to lift it). Nothing is
deleted or rewritten: an LLM retiring memories by comparing them with each
other was wrong 13 of 21 times (Track 28), and a proposed correction is
printed for the operator, never applied. A content update clears the
verdict, so a stamp never outlives the wording it checked. Track 35 measured
it on 100 mechanically falsified memories: precise (1 false contradiction in
133 true memories) and blind to nearly half of what is wrong (57 of 100
caught). So a `contradicted` verdict can be acted on and a `confirmed` one
cannot be read as "true"; the pass retires a wrong rule about half the time
the ledger never would. It is operator-invoked and prints every verdict.

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
   and failed → `−1` (which also catches the session's own failed→fixed
   pair overturning a memory's advice). Acted on and succeeded → `+1`,
   **but only if the memory's condition fired this session**: each memory
   carries the condition class its own text names, the hook observes which
   classes appeared in command output, and a successful copy in a session
   where the condition never occurred records nothing (logged as a skip).
   Without that gate, the loop credits imitation — the top memory in the
   corpus earned 79% of its ledger condition-silent before this rule
   existed (RESULTS.md, Track 11 Correction C4; theory.md "the condition
   side of the production"). In play but never used → **no outcome**:
   absence of use is what `rfm_prunable` measures, not negative evidence.

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
observation. That measurement is dated: July 2026, one model generation
(the audited runs are in `bench-quality/live-ab/model-audit.jsonl`).
Anthropic's November 2026 write-up on agent memory reports salience
judgment improving sharply across model generations, with the newest
models writing few, tested notes where an older one wrote hundreds, and a
"record only failures" rule costing the strongest models the most. So the
rule below holds for the models it was measured on; a retest on a current
model is registered in `research/next-work.md`.

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
   (measured: 15 of 16 wrong, July 2026, one model generation; see above
   for why this is dated rather than settled).
2. Capture and record outcomes at deterministic moments the harness owns.
3. Stage into review; never auto-write to a long-lived store.
4. Make formation cheap and retention ruthless — which requires the
   outcome axis, because similarity cannot prune.
5. Expect cold start (Codex ships six empty hours by design); first-session
   value belongs in checked-in files like `CLAUDE.md`/`AGENTS.md`.
6. Check a formed memory against its own source, because the ledger cannot
   see a rule (below). Keep verification a separate axis from outcome: a
   verdict says the source still supports the wording it checked, no more.

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
