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

## Track 9 — extraction framing (registered 2026-08-24, before any v2 call)

Track 8's arm B produced the first memories this project would want to
keep, and failed its recall prediction: 39% against blocks that name an
actual environment condition (48% of the corpus under the tightened truth
below; 31% against the looser 71% truth — both reported, neither picked
for flattery).

**Truth, tightened, and why this is not tuning to fit.** Track 8's
`has_env` counted any environment prose. Inspecting the misses, they are
dominated by *procedural* language — "pre-existing" (27), "stashed" (18),
"fails identically" (7), "unrelated to this change" (7) — which narrates a
verification step rather than stating a fact. "This failure is
pre-existing" carries nothing durable; "this venv's packages are too new
for this 2020-era checkout" does. The tightened rule requires the text to
name an environment CONDITION (venv, PYTHONPATH, site-packages, too
new/old, era, pinned, setuptools, pkg_resources, editable install, not
installed) rather than assert a status. It is a linguistic distinction
decided independently of what either arm did, and moving to it changes
recall by only 8 points (31% -> 39%), so it does not rescue the arm.

**Diagnosis.** v1 asked for a verdict on the whole block — "store it ONLY
if it IS durable knowledge". Every block is ~90% fix summary, so that
framing invites a whole-block judgement and answers no. v2 asks for
extraction, states that most of the text should be ignored, says a single
sentence at the end still counts, and requires the memory to stand alone
without naming the bug, function, or file — which also targets v1's 26%
identifier leakage.

Only the prompt changes. Same 86 blocks, same models, same gold-patch
ground truth, neither arm seeing it.

Registered predictions:
  T9-P1 (recall): haiku recall vs tight truth >= 65%, up from 39%. This is
        the whole point of the change; below that the framing was not the
        binding constraint and the problem is elsewhere.
  T9-P2 (leakage): haiku stored text leaking gold-patch identifiers < 26%
        (its v1 rate). The stand-alone instruction should help.
  T9-P3 (specificity): >= 80% vs tight truth. Guards the obvious failure —
        buying recall by storing everything.
  T9-P4 (yield): >= 25 clean memories, up from 14.
  T9-P5 (size): haiku still >= sonnet on leakage. v1 found the cheap model
        strictly better; if v2 reverses that, the earlier result was an
        artifact of the prompt rather than a property of the models.

## Track 10 — live A/B on a harvest-built store (registered 2026-08-24)

The first formation experiment in this project worth spending sessions on,
because for the first time the store holds memories a human would keep.

**The store.** Track 9's haiku-v2 arm extracted 11 xarray memories; the
consolidation step merged them to 5 distinct facts (three "linters not
installed" became one, two "dask not installed" became one, two
DeprecationWarning facts became one richer one) and dropped a per-bug leak
about `_maybe_null_out`. Saved through the real MCP path, scope xarray.

**Held out.** All 13 test tasks contributed nothing to the store. The
memories came from 9 other xarray tasks.

**Frozen.** No ratify() call, so staged candidates are never saved and the
store stays at exactly 5 for every session. This is an A/B on the
harvest's output, not on the miner.

**Preflight finding, recorded because it weakens the test.** The store's
most valuable memory says `import xarray` fails without a pkg_resources
shim. `run_stream.prepare()` already mitigates exactly this for xarray
tasks created before 2022 via UV_BUILD_CONSTRAINT — 8 of the 13 held-out
tasks. So the single strongest memory is partly neutralised by a harness
fix that postdates the session it was harvested from. The other four
(linters absent, dask absent and ~97 skips, the DeprecationWarning /
-W interaction, suite runs in ~5s) are untouched and remain live. A null
result therefore has two readings, and this note exists so the weaker one
cannot be quietly ignored afterwards.

**Metric of record is NOT resolved-rate.** With 13 tasks that is
underpowered, and this project has already drawn a false lesson from a
noisy resolved-rate once. The metric is events-before-first-green-test —
formation_study.py's counterfactual view — which is the instrument that
discriminated on reval-sphinx (control 6 events, memory arm 1).

Registered predictions:
  T10-P1 (counterfactual): the rfm arm reaches its first green test in
        fewer Bash events than control on more tasks than it loses on.
        This is the claim. Ties are common and count as neither.
  T10-P2 (resolved-rate): NO significant difference, and none is claimed.
        Registered so a favourable resolved-rate cannot be retro-fitted
        into evidence — if rfm wins there, it is noise unless P1 also
        holds.
  T10-P3 (utilisation): >= 50% of rfm sessions show the store being
        consulted — an injection recorded and at least one memory access
        logged by the outcome loop. If injection never lands, P1 is
        untestable rather than false.
  T10-P4 (no harm): rfm total wall within +15% of control.

If P1 fails while P3 holds, the honest conclusion is that memories a human
would keep still do not change what the agent does — which would be the
strongest negative result this project has produced, and would mean the
formation half was never the binding constraint.

## Track 11 — same fact, four forms: a token-matched content ablation (registered 2026-08-27, before any session)

Two threads converge on one experiment. Our corpus's sharpest split —
memories with a verbatim backtick command average 3.2 outcomes, memories
without one 0.5 — is confounded: `acted_on()` matches by reproducing a
backtick span, so a quotable memory is mechanically easier to score than a
useful one. And a literature sweep (2026-08-27) shows the field now runs
no-memory controls routinely (AWM 2409.07429, ReasoningBank 2509.25140,
Memp 2508.06433 — all author-reported gains) while the independent tests
keep finding nulls once token budgets are matched (2606.15017, already
cited at Track 5 as the reason benefit claims were deferred; AMA-Bench
2602.22769: memory systems frequently underperform plain long-context).
This track is that deferred token-matched benefit test, and it
de-confounds the form split in the same run: the outcome measure is the
harness's, not `acted_on()`'s, so quotability cannot reach it.

**One fact, four forms, two controls.** The unit under test is the
corpus's highest-value memory — pilot 4 store id 2, the sphinx era-pin
stubs workaround (value 0.998, 17 outcomes there, 22 across sibling
stores). Every injected arm carries a single memory whose ledger
(value_score, outcome_count, access statistics) is cloned from that row,
so R, F, M, injection rank, and the floor are identical across arms —
only the content string differs. Texts are committed in
store-track11.json; lengths are registered inside a ±10% band around the
verbatim reference (1,214 chars) and all inject as one unbroken line:

  none      no MCP server (Track 4 resolved the attachment tax as
            context-cost-only at this scale; disclosed, not re-measured)
  placebo   true-but-inapplicable content: Track 10's kept xarray
            memories (ids 1, 2, 4, 5 joined with " | " — dask/linters/
            warnings/suite-speed, deliberately NOT the pkg_resources one,
            whose PYTHONPATH-shim technique is the flagship's own
            family). 1,098 chars, −9.6%.
  prose     the same condition and workaround described with no runnable
            command, no path, no literal invocation. 1,299 chars, +7.0%.
  verbatim  the stored memory, byte-identical (preflight asserts this
            against the pilot 4 store). 1,214 chars.
  abstract  the Memp-style generalization: placeholder commands
            (`PYTHONPATH=<stubs>`), condition stated as a class, "applies
            to any era-pinned repo". 1,150 chars, −5.3%.

**Tasks, and why they are knowingly in-sample.** The validated in-era
sphinx pool is exhausted: every validated 2020–2021 task IS the pilot dev
set, and the era-band alternates (7440, 7748, 7985, 8035–8721, 9229–9711
others) all failed validation. So this runs on 8 of the 10 dev tasks —
excluding sphinx-7454, whose session minted the memory, and sphinx-9658,
whose checkout (232dbe41c) is named in the memory text because that
session amended it. This is registered as a CEILING experiment and the
asymmetry is the design: these are the tasks the flagship's ledger was
earned on, so a positive here is a best-case ceiling and claims no
transfer, while a null here generalizes — if the corpus's best memory
cannot beat no-memory on its home turf, it cannot beat it anywhere.

**Constant treatment.** The store is rebuilt from store-track11.json
before every injected session; nothing carries between sessions. No
ratify. Before EVERY session (a disclosed deviation from the reval
"resumes never re-clean" rule, which protected accumulated state this
design deliberately has none of): /tmp sphinx artifacts are removed —
the verbatim text names /tmp/sphinx_type_hint_links/stubs, which a prior
arm's session may have created, and leaving it would leak the treatment
across arms — the built-in auto-memory dirs are archived (arms share
clones; that channel is not under test), and pending-memories.md is
removed (its count would spend the next session's injection budget).
rfm-log.jsonl accumulates as the audit trail. Arms run in a fixed order
per task (none, placebo, prose, verbatim, abstract), so any drift is
arm-aligned, as control-first was in every prior track.

**Metric of record** is Track 10's: Bash events before the first green
test run (formation_study counterfactual), compared pairwise between arms
on the same task; a session that never reaches green loses to one that
does, both-never ties. Resolution and wall are recorded; resolution is
not predicted (pilot-era sphinx resolution has already produced one false
lesson). With 8 tasks per pairwise comparison this has Track 10's power:
wins-vs-losses is a direction, not a p-value, and is registered as such.

Registered predictions:
  T11-P1 (necessity, the claim): verbatim beats none — fewer events to
        first green on more tasks than it loses. The memory's 17-outcome
        ledger says the control arm should pay the VersionRequirementError
        storm and the verbatim arm should not.
  T11-P2 (content vs presence): verbatim beats placebo the same way.
  T11-P3 (placebo buys nothing): placebo does not beat none. An
        inapplicable true memory is predicted to be pure cost.
  T11-P4 (form, the de-confounded split): verbatim beats prose. If this
        FAILS while P1 passes, the 3.2-vs-0.5 split was quotability
        artifact and formation should stop privileging commands.
  T11-P5 (abstraction, least confident): abstract does not beat verbatim
        — Memp's finding is that verbatim wins when recurrence is
        near-identical, which in-era same-repo tasks are. Registered as a
        direction; a reversal would be the more interesting outcome.
  T11-P6 (utilisation gate): the injection line lands, with the seeded
        memory in it, in >= 90% of injected-arm sessions. If it does not,
        P1/P2/P4/P5 are untestable, not false.
  T11-P7 (no harm): verbatim total wall within +15% of none. Other arms'
        walls are reported, not predicted.

**Registered interpretation, fixed now so it cannot be softened later.**
If P1 fails while P6 holds, the finding is not only "the store did not
help": it is that the outcome ledger itself — M, 17 outcomes of it, the
strongest signal the instrument has ever produced — was counting
engagement, not causal value. That reading implicates every M-ranked
result in this project, and the M-axis follow-up (Track 12, future, not
registered here: rank-rule comparison — earned-outcome M vs write-time
importance vs uniform vs per-token M — against a causal panel) is
conditional on P1 passing, because a value rule cannot be validated
against a quantity that measurement says is zero.

## Track 13 — the weak-agent arm (registered 2026-08-27, before any session)

Track 11 and its Correction C4 leave exactly one mechanism standing
under which the flagship memory could ever show causal value: the era
class bit hard once (the mint session) and never again for a frontier
agent — fable-5 sidesteps app-based tests unprompted, in every arm, in
every run audited (C4 points 1 and 4). The last live hypothesis from the
2026-08-27 literature sweep is Memp's: memory built by a strong model
retains value for a weaker one, i.e. memory's headroom lives where the
agent struggles. A weaker agent may actually meet the condition, and the
memory may save it.

Design: run_track13.py. The 8 Track 11 tasks, two arms only — none and
verbatim — with the model pinned to claude-haiku-4-5-20251001 in BOTH
arms (the pin is the treatment; everything else is Track 11's protocol
verbatim: fresh single-memory store per session from store-track11.json
under the cloned 17-outcome ledger, per-session /tmp and auto-memory
hygiene, clause-free prompt, no ratify, fixed arm order). 16 sessions.

Metric of record: the C3-CORRECTED counterfactual — Bash events before
the first pytest run that exits 0 — registered as primary this time, as
C3 requires of future registrations. The legacy text-match detector is
reported alongside, not scored.

Also recorded here, so the decision is legible: the other candidate
live test — Track 14, un-mitigated xarray pkg_resources — was probed
dead before registration. On the prepared pre-2022 checkout
(xarray-3095), `import xarray` succeeds with pkg_resources blocked
outright (sys.modules['pkg_resources'] = None), so the track10 memory's
runtime condition cannot fire under the frozen harness at any
setuptools version: the pkg_resources need was build-time only, already
absorbed by UV_BUILD_CONSTRAINT. Track 14 is NOT RUN, and the probe is
the finding.

Registered predictions:
  T13-P1 (condition liveness, the gate): the era class
        (VersionRequirementError/ExtensionError) appears in command
        output in >= 3 of 8 CONTROL sessions. This claims a weak agent
        actually meets the condition a strong one sidesteps.
  T13-P2 (necessity, the claim): verbatim beats none on the corrected
        counterfactual — fewer events to first green on more tasks than
        it loses, ties counting for neither. Scored regardless of P1,
        but if P1 fails the registered reading is that the condition is
        dead at both capability tiers: the memory is a fossil of one
        August session, and no workload in this project's task pool can
        make it pay.
  T13-P3 (utilisation): the injection line, with the seeded memory in
        it, lands in >= 90% of verbatim sessions.
  T13-P4 (no harm): verbatim total wall within +15% of none, with the
        per-task distribution reported before any total is quoted (the
        C3 lesson).

If P1 passes and P2 still fails, that is the strongest negative this
line can produce: the condition fires, the cure is in context, and it
buys nothing — necessity failing where the disease is demonstrably
present. If P1 and P2 both pass, it is this project's first positive
causal result, scoped to weak agents, and Track 12 unblocks against
that panel.

## Track 15 — the yardstick run (registered 2026-08-27, before any session)

(Track 14 — un-mitigated xarray — was probed dead before registration;
recorded under Track 13.)

Every wins-vs-losses number this project has produced sits on n=1
session per (task, arm) cell with no measurement of within-condition
variance. That is the Mem0-vs-Zep criticism our own mapping conceded
applies to us squarely, and it is the flaw C3 hit twice (one outlier
task carried 134% of a wall gap; "variance in approach, not memory").
This is an ESTIMATION run in Track 4's shape: no hypothesis, deliverables
and one decision rule.

Design: run_track15.py. One task — sphinx-7757, chosen because it
showed the widest spread across Track 11's five arms (2–22 corrected
events to green, 133–344s wall; mid difficulty) — CONTROL arm only (no
MCP server, no memory machinery: pure session-to-session variance), 10
sessions on claude-fable-5 and 10 on claude-haiku-4-5-20251001, model
pinned and stamped per record along with the CLI version
(run_stream.cli_version, added with this registration). Track 11/13
per-session hygiene. Disclosed limit: a single task lower-bounds
task-general variance; what this prices is within-task session noise,
the component paired designs difference away least.

Deliverables, per model: min / median / max / SD of corrected
events-to-first-green and wall; resolved-rate spread; sessions that
never reach green.

  T15-D1 (decision rule): from the fable spread, the minimal paired
        difference plausibly detectable by wins-vs-losses over 8 and 13
        pairs is computed and appended as a stated limitation note to
        the Track 10, 11, and 13 entries in RESULTS.md. If the
        within-condition spread of events-to-green covers the largest
        between-arm difference Track 11 observed on this task (13
        events), those entries' null readings gain an explicit
        "underpowered for small effects" qualifier. Either outcome is
        recorded; the note can only weaken past claims, never
        strengthen them.

## Track 16 — structured extraction (registered 2026-08-27, before any call)

The formation half of the DESIGN_NOTES proposal ("config-driven
extraction and value, and the three clocks"), tested by replay before
any live adoption: the Track 9 extractor re-run on the same 86 harvested
blocks against the same gold-patch ground truth neither arm sees, with
the output changed from freeform memory text to the schema
{condition_class, scope, era, action, evidence}. Haiku only — Track 9's
P5 settled the size question (haiku beat sonnet on leakage, and
formation runs at every SessionEnd, so it must be affordable).

What the structure is FOR (Track 11 + Correction C4): condition_class
makes condition-conditioned M mechanical instead of regex-crafted;
action gives acted_on() a declared match target in place of the
convicted backtick heuristic; era/scope houses validity metadata. This
track tests only whether the extractor can EMIT that structure without
losing what v2's extraction framing bought, and whether requiring a
nameable condition suppresses per-bug stores structurally.

Runner: run_track16.py (v3 prompt committed in it), jobs capped at 4 —
Track 15's sessions are running concurrently and share the API budget,
disclosed. Output track16/arm-haiku-v3.jsonl, resumable, sandbox cwd,
hooks off, block truncation and JSON parsing identical to Tracks 8/9.

Bars anchored to Track 9's ACHIEVED haiku-v2 numbers (recall 88%,
leakage 19%, specificity 62%, stored 53):
  T16-P1 (recall preserved): recall vs tight truth >= 80%. The known
        risk of a schema is refusal-by-formality; below 80% the
        structure costs more than it pays and the freeform v2 stands.
  T16-P2 (leakage): gold-identifier leakage across each stored row's
        condition_class+action+evidence text < 19% (v2's achieved).
  T16-P3 (condition validity): among stored rows whose source block
        names at least one error class (20 of 86 do), the emitted
        condition_class matches a named class >= 70% of the time
        (normalized substring match; mechanical).
  T16-P4 (completeness): condition_class AND action both non-empty in
        >= 80% of stored rows — fields the downstream mechanisms
        consume cannot be optional in practice.
  T16-P5 (structure as filter, the interesting one): specificity vs
        tight truth >= 70%, up from v2's 62% — the claim is that a
        store which must NAME a condition refuses per-bug blocks more
        reliably than one asked to write prose. If specificity does not
        rise, schema does not substitute for judgment, and the
        design proposal's extraction half loses its cheapest argument.

## Track 17 — formation-tier matching (registered 2026-08-27, before any session)

Track 13's residue, promoted: every memory ever tested on a weak agent
was formed from a STRONG agent's struggles, and it taxed the weak agent
(0 wins, +27.6% wall). The last unforeclosed causal design in reach:
memories mined from haiku's OWN failure classes, tested on haiku, on a
repo no haiku session has touched. Thresholds are set from Track 15's
yardstick, not guessed.

**Phase A (struggle collection): 11 sessions.** xarray chronological
first half (2905, 3095, 3151, 3305, 3677, 3993, 4075, 4094, 4356, 4629,
4687 — Track 3's phase-A list, all validated), haiku pinned, CONTROL
arm, no memory machinery. Per-session hygiene as Track 11 (xarray tmp
globs, auto-memory archive per session).

**Formation (committed before any Phase B session).** From Phase A
transcripts only: (1) the deterministic correction miner
(session_end.corrections) plus per-class fired counts; (2) the Track 16
v3 structured extractor (haiku) over session prose, under the Track 16
amendments — condition_class MANDATORY, action optional, provenance
recorded (quoted-from-session vs composed; a composed action is kept
only if a Phase A transcript ran it); (3) consolidation to at most 6
distinct facts, human-reviewed, committed as store-track17.json with
cold ledgers (no cloned outcome history — this store must earn its own,
under the now-live conditioned-outcome gate). Phase B tasks are the
disjoint second half, so mined-from/tested-on leakage is structurally
excluded.

**Phase B (paired test): 22 sessions.** xarray second half (4695, 4966,
6461, 6599, 6721, 6744, 6938, 6992, 7229, 7233, 7393), haiku pinned,
arms none and mined, store rebuilt per session (constant treatment),
no ratify. Metric of record: the corrected counterfactual
(formation_study.first_green_corrected). Model and CLI stamped per
record.

Registered predictions:
  T17-P1 (friction exists, the gate): >= 1 named condition class fires
        in >= 4 of 11 Phase A control sessions. If not, formation has
        nothing tier-specific to mine and the track reports NOT
        TRIGGERED for P3 rather than a false null.
  T17-P2 (formation yield): the pipeline produces >= 3 distinct
        condition-stamped facts from Phase A. Falsifies: haiku's
        struggles do not condense into nameable conditions.
  T17-P3 (necessity, the claim): mined beats none on the corrected
        counterfactual with one-sided sign p <= 0.05 over the decided
        pairs (at 11 decided that is >= 9 wins; ties shrink the
        denominator and the bar adjusts per the binomial). Track 15:
        haiku's within-condition SD is 3.5 events, so no single pair is
        evidence and only sign consistency counts.
  T17-P4 (utilisation): injection lands in >= 90% of mined-arm
        sessions.
  T17-P5 (no harm): mined total wall within +15% of none, per-task
        distribution reported before the total (C3 lesson; single-pair
        wall gaps under ~45s are noise at haiku's SD 22.6s).

If P1 passes and P3 fails, tier-matched formation joins the negative
ledger and the within-pool program is closed at four nulls. If P3
passes, it is the project's first positive causal result and the
conditioned-outcome instrument scores its first honest ledger.
