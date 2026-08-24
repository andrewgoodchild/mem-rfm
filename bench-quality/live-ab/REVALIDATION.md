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

## Track 6 — synthesis, retargeted (registered 2026-08-23, before any session)

Track 5's capture prediction FAILED, and its diagnostic named two defects,
both ours. This is the same experiment with both fixed, on the same ten
pytest tasks, so Track 6 vs Track 5 is a clean A/B on trigger and nudge
design rather than on workload.

**Defect 1 — no generic-program guard.** One of Track 5's two firings was
spurious: `command not found` with `program=cd`. The correction miner
already refuses uninformative programs (`informative_head`); the trigger
did not. Fixed with an explicit GENERIC set applied to both sides.

**Defect 2 — the nudge asked the wrong question.** It fired on an
*environment* error class and then asked for "the root cause" in the
abstract. Both times the model produced a fluent root-cause explanation of
**the bug it was fixing** — per-bug code knowledge this project measures at
~6% transfer and does not want stored — and correctly declined to save it.
The retargeted nudge names the environment class, asks why *this checkout
or virtualenv* produces it and what made it stop, and states explicitly
that per-bug lessons are not wanted.

**What Track 5 established that this run inherits:** the trigger reaches
the model, costs nothing measurable (−6.4% wall), and the no-op line holds
— zero invented memories across ten sessions under an explicit invitation
to save. Track 6 changes only what the trigger fires on and what it asks
for.

Registered predictions:
  T6-P1 (capture): >= 1 memory whose text is NOT the miner's
        `In this project, X fails...` template and which names the
        environment class that triggered its nudge. This is the
        prediction Track 5 failed; it is re-registered unchanged.
  T6-P2 (trigger precision): every nudge fires on a non-generic program.
        Falsifies the guard.
  T6-P3 (no-op discipline): sessions with no nudge produce zero
        non-template memories (Track 5: PASS, re-registered).
  T6-P4 (cost): total wall within +15% of Track 5's 2,988s.

Scored PASS/FAIL/NOT TRIGGERED as usual. If no nudge fires at all, T6-P1
and T6-P2 are NOT TRIGGERED and the finding is that the guard made an
already-rare trigger rarer — which would itself argue the threshold, not
the nudge, is the binding constraint.

## Track 8 — prose harvest: deterministic vs LLM (registered 2026-08-24)

The fourth formation strategy. Attempts 1-3 died: precision filtering (an
oracle filter buys ~0), cost-scored admission (Spearman +0.146), and
struggle-triggered synthesis (fires in 3 of 102 sessions). This one asks
whether the causal prose the agent already writes unprompted — which the
Bash-event miner has never read — is better raw material.

**Ground truth was built first, and it is external to both arms.** Each
SWE-bench task ships a `gold_patch`: the real diff naming the files and
functions that held the bug. So "is this explanation about the task's own
code?" is a lookup, not a judgement. Neither arm sees the gold patch; both
classify from the prose alone. This avoids the trap that would otherwise
sink the comparison — an LLM graded by an LLM scores free points a regex
cannot.

**The ground-truth result is already in, and it is a hard negative.**
Across all 88 causal blocks in the corpus (not merely the longest per
session — that confound was checked and ruled out), **zero** fail to name
the task's own gold-patch code. 100% of what this channel harvests is
per-bug knowledge, the class measured at ~6% transfer. The agent narrates
the deliverable it was asked for, not the environment it fought through.
Availability was never the problem: 52% of sessions have the prose, and
all of it is the wrong kind.

That kills the harvest as a *source*. It leaves a sharper and still-useful
question, which is what the two arms now test: **given a pool ground truth
says is entirely per-bug, which classifier correctly refuses to store it?**
A formation strategy that writes nothing is strictly better than one that
poisons the store, and the arms are scored on rejection, not capture.

Arm A — deterministic: the shipped `classify()` in harvest_replay.py.
Arm B — LLM: `claude -p` per block, prose only, no gold patch, asked to
        store only durable environment/tooling knowledge that would help
        on a DIFFERENT task. Run at two sizes (haiku, sonnet) because
        "does formation need a big model?" is a live deployment question:
        this would run at every SessionEnd.

Registered predictions:
  T8-P1 (arm A precision): the deterministic classifier calls >= 20 blocks
        "environment". Ground truth says 0 are. Predicted precision 0.00,
        i.e. every such call is a false positive. FAIL if precision > 0.10.
  T8-P2 (arm B rejection): the LLM arm refuses to store >= 80% of blocks.
        This is the prediction I am least sure of and the reason to run:
        the prose is fluent, confident and genuinely explanatory, and a
        model asked "is this durable?" may be seduced by its quality
        rather than judging its scope.
  T8-P3 (size): haiku and sonnet agree on >= 70% of blocks. If they agree,
        formation can run on the cheap model; if sonnet is much stricter,
        the classification is harder than it looks.
  T8-P4 (no free lunch): among blocks arm B does elect to store, >= 80%
        are ones ground truth marks `mixed` rather than pure `per-bug` —
        i.e. if it stores anything, it stores the least-wrong ones. If its
        stores are indistinguishable from random per-bug blocks, the arm
        has no discrimination even where it acts.

Scored PASS/FAIL. Note the asymmetry deliberately built in: arm A can only
lose (its own author already measured it wrong), and arm B can win only by
declining to act. Neither outcome rescues the harvest as a source. The
question this track answers is narrower — whether an LLM in formation is
safe, not whether it is valuable.

### Correction C2 to Track 8 (2026-08-24, arms running, before any scoring)

**The ground truth registered above was wrong, and the arm caught it.**

Track 8's registration states that 100% of harvested blocks are per-bug and
calls this "a hard negative". That number was an artifact of the labeller.
`label_harvest.py` recognised environment trouble only when it was named as
an ERROR CLASS (`ModuleNotFoundError`, `VersionRequirementError`). Agents
rarely write that in prose. They write *"this venv's sphinxcontrib packages
are too new for this 2020-era checkout"*. Detecting only the former, the
labeller saw no environment content anywhere and I reported the channel
dead.

**How it was caught, stated plainly because the sequence matters.** A
three-block pilot of the haiku arm marked two ground-truth "per-bug" blocks
as environment. I read those two blocks expecting to find the model
confabulating. It was not: both carried real environment knowledge in a
verification tail, and from one of them haiku extracted the era-pin stub
workaround — the highest-value memory this project has recorded. So this
correction is *caused by* seeing 3 of 172 arm outputs. That is a peek, and
pretending otherwise would be worse than declaring it. The alternative was
to score a run against a ground truth already known to be broken.

Re-measured with prose detection added: **71% of blocks (61/86) carry
durable environment knowledge; 29% (25/86) are pure fix summary.** Every
block still names gold-patch code, so the identity signal separates
nothing — every block is a fix summary — and the real structure is a
nugget buried in a tail.

**This changes what the arms are testing, and it is the more interesting
question.** The unit of extraction is a SPAN, not a block. A block-level
classifier cannot win: storing an env-bearing block stores the whole fix
summary with it. Extracting the nugget and discarding the rest is a
semantic operation, which is the case for an LLM in formation that this
project has been circling for two days.

Predictions T8-P1..P4 above are VOID — P2 in particular predicted the model
would reject >=80% of blocks, which under corrected truth would be the
wrong behaviour. Re-registered, on quantities not yet observed (the pilot
covered 3 blocks; these concern 86 x 2):

  C2-P1 (recall): arm B stores on >= 70% of env-bearing blocks.
  C2-P2 (specificity): arm B refuses >= 60% of pure-per-bug blocks.
  C2-P3 (extraction cleanliness): among blocks arm B stores, < 30% of the
        memory texts contain a gold-patch file or symbol. This is the
        quality measure and it is fully mechanical — the arm never saw the
        gold patch, so leaked identity tokens are its own doing.
  C2-P4 (size): haiku and sonnet agree on store/reject for >= 70% of
        blocks. Decides whether formation can run on the cheap model.
  C2-P5 (arm A floor): the deterministic arm cannot extract at all — it
        classifies whole blocks. If it stores, 100% of its stored text
        contains gold-patch identity tokens, against arm B's < 30%. This
        is near-certain and is registered as the baseline the LLM arm has
        to beat, not as a discovery.
