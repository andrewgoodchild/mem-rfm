# Memory types: the taxonomy, what ChatGPT users actually meet, and what an agent needs

This file expands the "Memory types" section of [theory.md](theory.md)
for a question that doc doesn't address: the memory an average person
*experiences* in a chat assistant, how it maps onto the standard
taxonomy, and why the memory that makes ChatGPT feel personal is almost
disjoint from the memory a working agent needs. The scoring implications
stay in theory.md; the measurements cited here live in
[bench-quality/RESULTS.md](../bench-quality/RESULTS.md).

## The taxonomy

The usual agentic-AI taxonomy has five entries: **short-term/working**
memory, and **long-term** memory split into **semantic** (facts),
**episodic** (events tied to a time), and **procedural** (skills). That
is Tulving's and Squire's psychology, and it is a reasonable map of the
territory — reasonable enough that 2026's agent-memory surveys all
standard-issue some version of it.

## Where a ChatGPT user meets each type

The interesting thing about consumer chat memory is that each taxonomy
entry corresponds to a concrete product surface a user can point at:

**Working memory is the conversation itself.** The model follows the
thread because the thread is in its context window. It resets when the
chat ends. Users rarely call this "memory" — it only becomes visible
when it fails (the model forgetting the top of a very long chat).

**Saved memories are semantic — and they are semantic *about you*.**
The "Memory updated" chip, the list in Settings → Personalization:
stable facts and preferences. "Is vegetarian." "Runs a bakery." "Prefers
concise answers." This is the bulk of what "it really knows me" refers
to, and structurally it is a small, curated, user-auditable fact store
about a single entity — the user.

**Chat-history reference is episodic in shape.** The assistant retrieves
from past conversations ("the trip we planned in March"), which is
memory of shared events tied to a time. This is the surface the
long-term-memory benchmarks (LoCoMo, LongMemEval — arXiv 2402.17753,
2410.10813) actually test: given a long multi-session history, can the
system find what was said.

**Custom instructions are procedural — about how to treat you.** "Answer
tersely, no lists, cite sources": skills of interaction, not facts. The
coding-agent equivalent is the hand-curated CLAUDE.md / AGENTS.md file,
which is the one memory mechanism practitioners consistently swear by.

**What no consumer surface offers: procedural skill acquisition and an
outcome ledger.** ChatGPT does not get better at *tasks* from your
usage — there is no skill library, and nothing records whether a
remembered item ever helped. Writes happen on salience ("this looks
worth keeping"), not on measured usefulness.

## Why the felt value is real

"It really knows me" is not an illusion, and the taxonomy shows why. The
consumer surfaces are dominated by semantic-about-you and
procedural-about-you content, and that content has a property the rest
of the taxonomy lacks: **no substrate**. If the assistant doesn't store
your preferences, they are simply gone — the re-derivation cost falls on
the human, in re-typing and re-explaining, every session. Memory there
saves real, unavoidable human effort even if it never makes the model
objectively better at anything. And the value is *felt through the
response surface*: you can see yourself being remembered.

The long-term-memory benchmarks measure exactly this channel — recall
of stated facts — which is why product experience and benchmark scores
agree with each other.

## What an agent needs, and why it is different

A coding agent works inside an environment that is itself a memory: the
repository, its tests, its error messages persist everything and can be
re-read on demand. That inverts the economics. What we measured
(RESULTS.md):

- **Episodic per-task lessons transfer at ~6%.** The bug you fixed
  yesterday is tied to its event; tomorrow is a different bug in a
  different file. Fifteen of sixteen outcomes on such memories were
  negative.
- **Procedural/environment knowledge is what transfers** — build
  quirks, dependency pins, conventions. This is the one robust
  type-shaped finding, and it shapes what to *capture*, not how to
  rank (theory.md: type belongs in the capture policy, not the scoring
  function).
- **Even good procedural memories have shown no causal task benefit in
  our live A/Bs.** Tracks 10 and 11: true, human-ratified memories,
  delivered reliably, on their home tasks — no measurable effect
  against a no-memory control, and the strongest ledger in the corpus
  turned out to have been earned by being *copied*, not by being
  *needed* (Track 11, Correction C4).

The reconciliation is the substrate line: **memory pays where the
environment doesn't persist the knowledge.** Personal context has no
substrate, so chat personalization is felt and real. A repo is all
substrate, serviced by an agent strong enough to read it, so
operational memory competes with cheap re-derivation — and, so far in
our measurements, loses or ties.

## The map in one table

| type | ChatGPT surface | agent-world analog | what the evidence says |
|---|---|---|---|
| working | the current chat | the context window | not a store; the harness's job |
| semantic (about you) | saved memories | user preferences, CLAUDE.md facts | no substrate → saves real human effort; the "knows me" feeling |
| episodic | chat-history reference | per-task/per-bug lessons | recall works (benchmarks); transfers at ~6% for tasks |
| procedural (about you) | custom instructions | CLAUDE.md working style | the memory practitioners actually keep |
| procedural (about the world) | — (none offered) | build quirks, pins, env workarounds | what transfers; causal benefit still unproven in our A/Bs |
| outcome ledger | — (none offered) | mem-rfm's M axis | measures engagement unless conditioned on need (C4) |

The last two rows are the project's territory, and the table is the
disconnect explained: consumer memory lives in the rows where felt
value is real and cheap to deliver; agent memory lives in the rows
where value must be proven against a substrate that already remembers
everything.
