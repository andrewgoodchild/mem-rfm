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
   and stop — do not invent candidates. Candidates are the lines starting
   `- `. Most are followed by an indented reconcile line:

   `<!-- rfm-reconcile: ref=ab12cd34.2 nearest[embedding]=#12 0.91 likely-duplicate condition=pkg_resources scope=xarray; ab12cd34.1 0.87 likely-duplicate from=bash#14->#16 of /path/to/transcript.jsonl -->`

   - `ref` names this candidate; `#N` is a stored memory id; a bare ref
     (`ab12cd34.1`) is another candidate in this file.
   - the number is similarity (`embedding` cosine, or `tokens` overlap when
     the embedder was unavailable — the scales differ; trust the
     `likely-duplicate` mark over the raw number). `nearest[...]=none`
     means nothing in the store was close.
   - `from=` is provenance: which Bash calls in which transcript the pair
     came from. Open it only if the candidate is unclear.
   The reconcile line is metadata — never save it as memory content.
2. Reconcile before judging. The store's save path only rejects EXACT
   duplicates, so a restated lesson is saved again unless you catch it here.
   For every `likely-duplicate` neighbour, read it (`memory_get(N)` for
   `#N`, the file for a candidate ref) and decide:
   - **Skip as duplicate**: the neighbour already says it. Drop the
     candidate.
   - **Merge**: the candidate adds a real detail (a flag, a path, the
     actual remedy). Fold it into the existing memory with
     `memory_update(N, merged text)` — update keeps the memory's earned
     usage record; a second row would split it and compete for an
     injection slot.
   - **Supersede**: the candidate corrects the neighbour (the old advice
     is wrong or outdated). Replace with `memory_update(N, new text)`.
   - **Distinct**: same words, different lesson — treat as a new
     candidate. The mark is a hint, not a verdict.
   Several candidates pointing at each other (`ab12cd34.1`, `ab12cd34.2`,
   ...) are usually ONE lesson seen in several sessions: keep at most one,
   stated generally.
3. For each remaining candidate, judge it before showing it:
   - **Worth keeping**: names a project-specific gotcha someone would hit
     again (a flag that doesn't exist, a required env var, a path quirk).
   - **Drop silently**: generic knowledge any model already has, one-off
     typos, secrets or tokens, or pairs where the "fix" is unrelated to the
     failure.
4. Present the survivors to the user with your keep/drop/skip/merge
   recommendation — naming the memory id for any skip, merge or supersede —
   and let them decide (AskUserQuestion with multiSelect works well). The user
   may edit wording — the stored fact should state the lesson, not the
   transcript.
5. For each keeper, call `memory_save` with:
   - content: one self-contained sentence, imperative where possible
     ("In <project>, `X` fails (reason); use `Y`.").
   - scope: the repo/project name the lesson belongs to; unscoped only if it
     genuinely applies everywhere.
6. After saving, rewrite the pending file to remove everything that was
   reviewed (kept, merged, skipped or dropped) together with its reconcile
   line, preserving any sections the user deferred. Tell the user what was
   saved (with ids), what was merged into which id, and what was dropped.

## Also offer, when relevant

- If the store has memories whose facts the user says are outdated, use
  `memory_update` (not delete+save — update preserves the memory's earned
  usage record).
- If a reviewed memory came up during this session, record
  `memory_feedback(id, helped)` — the ranking depends on outcomes.
