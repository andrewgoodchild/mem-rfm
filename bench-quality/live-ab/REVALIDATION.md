# Revalidation protocol (registered BEFORE any session runs)

Pilots 2–4 tuned the stack (miner class, inference fixes, injection
policy, trailer) against the same 10 sphinx tasks — that set is now a
development set, and pilot 4's positive result is in-sample. This
protocol freezes the stack as committed at the registration commit and
revalidates on held-out tasks. Sessions run only after this file is
committed; any stack change after registration voids the run.

Frozen stack: hooks/miner/selection as of the registration commit
(prior top-3 + negative-value floor, feedback-on-surprise trailer,
environment-class miner, ratify_staged approve-all, no volunteered
saves; pilot 3's prompt). Runner: run_reval.py. Clean-room protocol as
pilot 4 (built-in auto-memory archived per clone before phase 1 only,
pilot /tmp artifacts removed; resumes never re-clean).

## Track 1 — pytest two-phase (held-out repo family, cold start earned in-protocol)

Tasks (validated, never used in any pilot), chronological:
  Phase A (accumulate): pytest-5631, 5787, 5809, 5840, 6197
  Phase B (measure):    pytest-6202, 8399, 10051, 10081, 10356
Paired arms both phases. The rfm store starts EMPTY and carries from A
into B; nothing is seeded. pytest-10356 was a July discordant hard task
(favored control); it stays in, disclosed.

Registered predictions:
  T1-P1 (machinery cost): Phase A rfm total wall within +10% of control
        total wall, and rfm mean output tokens within +15% of control.
        (Falsifies: the pilot-3/4 overhead removal does not transfer.)
  T1-P2 (formation, conditional): IF any rfm session's transcript
        contains a named-cause failure per the committed FAILURE class,
        the miner stages >=1 candidate across the run. An unconditional
        zero with named-cause failures present falsifies the miner.
  T1-P3 (steady state, conditional): IF >=1 memory earns value > 0 in
        Phase A, then in Phase B its injections earn positive outcomes
        in >=50% of the sessions where it is injected. No wall-clock
        advantage is predicted for pytest (July: bug-fix lessons do not
        transfer there; env friction is mild).
  T1-P4 (selection discipline): zero injected memories with negative
        value at injection time (floor holds); explicit negative
        feedback on an injected memory in session N excludes it from
        injection in sessions > N once its value is negative.

## Track 2 — sphinx hold-out era (inapplicable-knowledge / staleness test)

Tasks (validated, never used, 2022–2023 era — different pins, the
2020-era stubs workaround is expected NOT to apply): sphinx-10323,
10449, 10466, 10673, 11445, 11510. 7590 excluded (validation provenance,
RESULTS.md Corrections #4). Paired arms. The rfm store is seeded with
pilot 4's END store (all five memories, earned ledger intact) — the
worst case a strong stale ledger presents.

Registered predictions:
  T2-P1 (does not hurt): rfm total wall within +10% of control total.
  T2-P2 (staleness mechanism): any injected memory that receives
        explicit negative feedback is excluded from injection in later
        sessions once its value goes negative.
  T2-P3 (no fabricated wins): if the stubs workaround is genuinely not
        needed on 2022+ checkouts, memory 2/4 outcome rate drops vs
        pilot 4 (no prediction of benefit — this track tests absence of
        harm, and the ledger adjusting downward IS the pass condition).

## Metrics and decision rules

Primary: per-pair wall deltas and totals, per-arm output tokens and
assistant messages (dedup by message id), injected/hits/distractors from
the committed log, formation counts, store end state. Resolution is
recorded, not predicted (ceilinged at this difficulty). Each prediction
is scored PASS/FAIL in RESULTS.md with the numbers; conditional
predictions whose condition never fires are reported as NOT TRIGGERED,
never as passes.

Track 3 (future, not registered here): a never-seen repo — xarray (22
SWE-bench-CL tasks, pure Python, era pins tractable) — same two-phase
design, once clone/venv/validation are built.

## Track 3 — xarray two-phase (never-seen repo; registered 2026-08-22, before any session)

The first track on a repository no pilot or revalidation has touched.
22 SWE-Bench-CL tasks, all 22 validated under the committed era pins
(tasks_xarray.json, validation-xarray.jsonl; three environment
iterations to get there — pkg_resources via UV_BUILD_CONSTRAINT
setuptools<81, arm64 wheel floors numpy>=1.21/pandas>=1.3 — all
committed with this registration). Stack: as of the registration commit,
which now includes the empty-store policy trailer and the SessionEnd
retention pass (RFM_PRUNE_DAYS=30) — both post-dating Tracks 1–2 and
disclosed as such.

Design: chronological halves, paired arms, empty store, ledger earned
in-protocol. Phase A (accumulate): xarray-2905..4687 (2019-04..2020-12).
Phase B (measure): xarray-4695..7393 (2020-12..2022-12). The era shift
inside Phase B (13 months idle between 4966 and 6461, pins change) is
disclosed: memories earned on 2019–2020 checkouts may stop applying
mid-phase, which produces staleness observations in passing (recorded,
not predicted).

Registered predictions (same shapes as Track 1):
  T3-P1 (machinery cost): Phase A rfm total wall within +10% of control;
        rfm mean output tokens within +15% of control.
  T3-P2 (formation, conditional): IF any rfm transcript contains a
        named-cause failure per the committed FAILURE class, the miner
        stages >=1 candidate across the run.
  T3-P3 (steady state, conditional): IF >=1 memory earns value > 0 in
        Phase A, its Phase-B injections earn positive outcomes in >=50%
        of the sessions where it is injected.
  T3-P4 (selection discipline): no memory whose value sits negative at
        injection time is ever injected; explicit negative feedback in
        session N excludes the memory from injection in sessions > N
        once its value is negative.
No wall-clock advantage is predicted: xarray's recurrence profile is
unknown, and the honest prior after Tracks 1–2 is that scientific-stack
env friction (numpy/pandas era pins) may recur like sphinx's or may not,
like pytest's. That question is what the track exists to answer.

## Track 4 — the attachment tax (registered 2026-08-23, before any session)

Track 3's FAIL left two suspects standing: the constant cost of the
memory server's mere presence (tool schemas in every session's context),
and n=11 variance. External review flagged the same unknown from the
other side: it sits unmeasured under pilot 4's win too. This track
isolates it.

Design: run_tax.py, two arms over the 10 pilot sphinx tasks (a
development set — acceptable here because no memory content exists to
overfit with): control (no MCP server) vs idle (rfm-memory server
attached, store empty and verified to stay empty, hooks inert via
RFM_HOOKS_OFF with the observability sidecar retained). Clause-free
prompt both arms. The only systematic differences in the idle arm are
the server's tool schemas in context and its process startup.

This is an ESTIMATION experiment with one prediction and one registered
decision rule:
  T4-P1 (the tax is visible in context): idle-arm mean input tokens per
        session exceeds control's — the schema overhead is real and its
        size is reported per session.
  T4-D1 (decision rule, two-sided by design): if idle total wall is
        within ±10% of control AND the resolution gap is <= 1 task, the
        attachment tax is a context-cost-only effect at this scale and
        Track 3's Phase-A gap is attributed to variance-or-unknown, NOT
        to the tax. If idle exceeds +10% wall or drops >= 2 tasks, the
        tax has behavioral cost and Track 3's reading strengthens.
        Either outcome is informative; neither is a pass or a fail of
        the memory system.


## Corrections to this protocol

Registered text above is never edited after its runs — corrections are
appended here, in the same discipline RESULTS.md uses.

**C1 (2026-08-23) — the steady-state prediction was ambiguous as
written.** T1-P3 and T3-P3 both say "IF >=1 memory earns value > 0 in
Phase A, its Phase-B injections earn positive outcomes in >=50% of the
sessions where it is injected." *Its* never says whether the subject is
one such memory or all of them, and on Track 3 the two readings
disagree: the best memory earned in 8 of 8 injected sessions
(existential PASS) while two others earned in 1 of 7 each (universal
FAIL). Scored as AMBIGUOUS in RESULTS.md and reported under both
readings; neither was claimed.

The defect is ours and prospective, so the fix is prospective. Future
registrations use this wording, which names a single determinate memory
chosen by a rule fixed in advance:

> **Steady state (conditional).** IF at least one memory ends Phase A
> with `value_score > 0`, THEN the single memory with the highest
> end-of-Phase-A `value_score` — ties broken by `outcome_count`, then
> by lowest `id` — earns a positive outcome in at least 50% of the
> Phase-B sessions in which it is injected. Per-memory rates for every
> Phase-A-proven memory are reported alongside as descriptive context,
> but the prediction is scored on the designated memory alone.

Both readings of the original remain reported for Track 3. This
correction does not change that score.

## Track 5 — struggle-triggered synthesis (registered 2026-08-23, before any session)

**What this tests, and what it does not.** This is a CAPTURE test, not a
benefit test. It asks whether a synthesis channel writes down the expensive
knowledge the failed→fixed miner provably misses. It makes no performance
claim: a benefit claim requires the token-matched control design
(arXiv 2606.15017 showed a vanilla baseline given the same token budget
matches or beats AWM/ASI/ReasoningBank), and that is deferred to a
follow-up. Nothing here should be read as "memory helped".

**Why capture and not precision.** An independent oracle experiment
(research/formation-survey-2-2026-08-23.md) deleted every never-contributing
memory — a perfect filter removing up to 49.5% of a store — and moved
accuracy by ~0, every CI covering zero; our own stores agree (pilot 2 spent
59% of injection slots on never-earners and displaced nothing). Precision
has no headroom. Separately, our own calibration curve found re-derivation
cost does NOT predict realized usefulness (Spearman +0.146, n=19, and the
two most expensive pairs in the corpus are junk artifacts), which kills the
cost-prior alternative. Recall is what is left.

**The gap being targeted, measured.** formation_study.py's coverage
scorecard on reval-pytest: the two costliest knowledge classes —
`modulenotfounderror` (11 control-arm events across 5 of 10 sessions) and
`pkg_resources` (8 events, 4 sessions) — are both **NOT CAPTURED**, while
the three memories formation did store earned nothing. Zero recall on the
expensive knowledge.

**Mechanism.** hooks/post_tool_use.py counts failures per named error class
and fires exactly one nudge per session, at the moment a class that failed
>= RFM_SYNTHESIS_N (=2) times is finally resolved by a success of the same
program — struggle-then-resolution, when the knowledge exists and the
reasoning is still in context. The harness supplies the detection; the agent
supplies only the explanation (agents diagnose their own failures badly:
0 of 121 reflections named the correct object in arXiv 2605.29463, and
programmatic signal extraction moved that to 86%). The nudge carries memU's
no-op line verbatim and explicitly supersedes the standing
do-not-volunteer instruction for that one moment.

**Design.** run_synth.py, the 10 pytest tasks of Track 1, rfm arm only,
fresh store, clause-free prompt, RFM_SYNTHESIS=1. The comparison baseline is
**reval-pytest's own rfm arm** — same tasks, same stack, same prompt, miner
only — so the delta isolates the synthesis channel.

Registered predictions:
  T5-P1 (capture): the synthesis channel produces >= 1 memory whose text
        names one of the classes the scorecard marked NOT CAPTURED on this
        repo (modulenotfounderror / pkg_resources / importerror).
        Falsifies: the channel fires and still misses the costly knowledge.
  T5-P2 (no-op discipline): sessions in which the nudge did NOT fire
        produce zero saved memories. Falsifies: the channel leaks into an
        open invitation to volunteer.
  T5-P3 (over-extraction bound): at most one saved memory per session.
  T5-P4 (cost): total wall clock within +15% of reval-pytest's rfm arm.
        Falsifies: synthesis is not affordable at this trigger rate.

Scored PASS/FAIL/NOT TRIGGERED in RESULTS.md as usual; a conditional whose
condition never fires (no session struggles) is NOT TRIGGERED, and would
itself be the finding.
