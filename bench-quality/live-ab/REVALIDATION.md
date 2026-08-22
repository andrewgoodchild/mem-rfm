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
