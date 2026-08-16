---
name: memory-review
description: Review staged memory candidates from past sessions and save the keepers to the rfm-memory store. Use when the user runs /memory-review, asks to review pending or staged memories, or asks what the SessionEnd hook has collected.
---

# Review staged memory candidates

Staged candidates live in `pending-memories.md` next to the memory database
(default `~/.sqlite-rfm/pending-memories.md`; the directory of `$RFM_MEMORY_DB`
if that is set). They were proposed by the SessionEnd hook — extracted
failed-command→working-variant pairs — and are deliberately NOT saved:
unreviewed accumulation is the documented failure mode of every
auto-capturing memory system. You are the review step.

## Procedure

1. Read the pending file. If it is missing or has no candidate lines, say so
   and stop — do not invent candidates.
2. For each candidate, judge it before showing it:
   - **Worth keeping**: names a project-specific gotcha someone would hit
     again (a flag that doesn't exist, a required env var, a path quirk).
   - **Drop silently**: generic knowledge any model already has, one-off
     typos, secrets or tokens, or pairs where the "fix" is unrelated to the
     failure.
3. Present the survivors to the user with your keep/drop recommendation and
   let them decide (AskUserQuestion with multiSelect works well). The user
   may edit wording — the stored fact should state the lesson, not the
   transcript.
4. For each keeper, call `memory_save` with:
   - content: one self-contained sentence, imperative where possible
     ("In <project>, `X` fails (reason); use `Y`.").
   - scope: the repo/project name the lesson belongs to; unscoped only if it
     genuinely applies everywhere.
5. After saving, rewrite the pending file to remove everything that was
   reviewed (kept or dropped), preserving any sections the user deferred.
   Tell the user what was saved (with ids) and what was dropped.

## Also offer, when relevant

- If the store has memories whose facts the user says are outdated, use
  `memory_update` (not delete+save — update preserves the memory's earned
  usage record).
- If a reviewed memory came up during this session, record
  `memory_feedback(id, helped)` — the ranking depends on outcomes.
