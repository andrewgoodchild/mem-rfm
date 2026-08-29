# Why you can trust the negative results

A memory system that only publishes its wins can't tell you when to use it.
This project's main claim to being worth reading is that its failures are
reported at the same length as its successes, and that neither could have
been decided after the fact.

## Pre-registration

`PROTOCOL.md` holds the original protocol plus Amendments 1–16c (the
frozen retrieval evals and the successor-venue evals), and
`bench-quality/live-ab/REVALIDATION.md` registers the held-out live
program — Tracks 1–20, each committed before its sessions ran. Each
states, **before the runs it governs**:

- the candidate mechanisms, and that no others will be reported as primary
- the development set, and which data is held back as test
- the selection rule, applied in a fixed order
- the endpoints and their success bars
- **what would falsify the hypothesis**, written out explicitly

Each amendment was committed to git before its experiments ran, so the commit
order is checkable by anyone with a clone. Where a smoke run happened before
registration — usually to verify a data loader — the registration says so and
describes what was seen.

Two examples of the discipline doing real work:

- **Amendment 3** was written because a pre-run inspection showed the
  registered grid could never fire on the target benchmark: the success bar
  was unreachable by construction. Corrected before any number existed.
- **Amendment 5's** defence endpoint was found to be confounded before the
  full run — it conflated the defence with a generic gain — and was replaced
  with a difference-in-differences form, again before any full-stream number
  existed.

Neither would have been visible after the fact. Both are in the protocol.

## Committed outputs

Per-question and per-call results live under `bench-quality/results-*/`, and
run logs alongside them. Any table cell in this repository can be recomputed
from committed data rather than taken on faith.

The exception, stated plainly: live-session transcripts and memory databases
from the coding A/B stay local, because they can contain machine-specific
detail. A redacted audit of what those memory stores actually contained is
committed at `bench-quality/live-ab/memory-audit.md`, so the numbers derived from
them remain checkable.

## The corrections

The audit trail is the point, so the corrections are reported as
prominently as the results — appended, never edited over, so the error
stays legible next to its fix.

- **The 42-point manual gap was wrong.** An early manual-versus-experience
  experiment rested on a title-mapping bug that silently dropped 22 of 55
  manual entries, leaving 52.7% of calls with no manual coverage — which
  made the manual look far weaker than it was. Pre-publication review
  caught it from the committed logs; re-run with full coverage the gap is
  12 points, the number reported everywhere now.
- **A registered ground truth was wrong, and the model being evaluated
  caught it** (Track 8, Correction C2). The registration declared 100% of
  harvested prose was per-bug knowledge — an artifact of a labeller that
  recognised environment trouble only when named as an error class. A
  three-block pilot of the arm marked two "per-bug" blocks as
  environment; reading them showed the arm was right and the ground truth
  wrong. Disclosed as a peek, because scoring against a ground truth
  already known broken would have been worse.
- **A harm claim was the author's, not the data's** (Track 10, C3). A
  scored entry said a true memory made the agent slower; asked for the
  mechanism, it did not hold — a metric artifact (a green-test detector
  blind to tail-piped output) plus a wall-time sum dominated by one
  outlier task. Rescored, Track 10 detects no effect in either direction.
  The wrong entry stands above the correction.
- **The strongest ledger was manufactured** (Track 11, C4). The corpus's
  top memory (17 outcomes, value 0.998) earned 79% of its ledger in
  sessions where its condition never fired — copied commands, credited
  successes. This correction changed the engine's outcome rule (the
  condition gate) rather than just a number.

A project claiming auditability should show what its own audit caught,
and twice here the audit was performed by the thing under test.

## What died

The complete ledger is `bench-quality/RESULTS.md`. In summary:

- **BM25 hybrid fusion** — won on two development repositories, reversed on
  six held-out ones. The repository split is what caught the overfit.
- **Confident-negative pruning** — cannot be simultaneously retrieval-safe and
  potent at forgetting; both grid corners fail one bar or the other.
- **Three content-based value signals** — semantic richness, diversity, and
  demand-recurrence, all weak or benchmark-dependent as priors.
- **The rank-1 replication bar** — required two of three datasets, achieved
  one.
- **A registered prediction that experience would lose to the manual on a
  low-recurrence dataset** — it won instead. Falsified in our favour, which
  still counts as falsified and is disclosed as such.
- **Six collusion defences**, including two that made things actively worse.
- **Most of our own components**, in the sense that matters: ablation found
  only the outcome axis measurably earns its place on BEAM. Activation, the
  confidence shrink and the decay rate all sit within noise.
- **Hebbian co-retrieval association**, tested by adding it: −3.2 NDCG points.
- **Interleaved consolidation**, tested by adding it: no detectable effect.

## Guarding against silently dead experiments

The failure mode that quietly destroys an evaluation record is not a wrong
result, it is a **measurement of nothing**: a channel that has gone dead, so
every arm returns the same number and the difference you report is noise
dressed as a finding. A comparable project lost months of A/B results to
exactly this — a migration left one scoring channel at zero, and its
best-ever benchmark score turned out to have been achieved with that channel
entirely disabled.

We have hit this class of bug three times, all caught, all disclosed where
the affected result is reported:

- **Amendment 11**: three different decay half-lives and a count-only model
  returned *byte-identical* NDCG. Cause: never-accessed memories were given a
  sentinel activation instead of the creation-age fallback, so on a corpus
  where most memories are never retrieved, every kernel was measuring the
  same constant.
- **Amendment 12**: the `no_prior` arm returned **exactly** +0.0000 across
  355 paired questions. Cause: the harness's `rfm_beta*` path recomputes the
  blend in Python with a literal β and never reads `rfm_config('beta', …)`,
  so setting β=0 changed nothing.
- **Amendment 12**: verdict labels were sign-inverted for the additive arms —
  a negative delta there means "adding this hurts", not "this earns its
  place". The first render reported a harmful mechanism as a success.

Three habits came out of it, and they are cheap:

1. **Liveness assertions.** Every ablation arm reports what fraction of
   scored rows had a varying prior. An arm at 0.0000 is flagged
   `DEAD SIGNAL` in the output rather than silently averaged.
2. **Score through the shipped code path.** Ablation arms call the
   engine's own `rfm_prior()`, so every config key they set actually
   applies. A harness-side re-implementation is where the β bug hid.
3. **Treat an exact zero as a bug report.** Across hundreds of paired
   questions, a delta of precisely 0.0000 is almost never a real null — it
   means the two arms ran identical code.

A fourth, from swapping the embedding backend rather than changing the
model. `fastembed` was adopted to cut the install from 769 MB to 163 MB on
the strength of a smoke test showing cosine 1.000000 against
sentence-transformers on four sample strings. Re-running BEAM and diffing
per-question rows showed 482 differing cells and similarity NDCG down 2.4
points. Cause: fastembed ships this model's tokenizer truncating at **128
tokens** where sentence-transformers uses **256**, so every memory longer
than a short paragraph was embedded from half its text. The smoke test could
not have caught it — all four strings were under the cut, where the two
backends agree exactly. With truncation and padding matched, all 1,065 rows
are bit-identical.

The lesson is about what counts as evidence for a drop-in replacement: two
implementations agreeing on the inputs you happened to try is not the same
as agreeing on the inputs you have. The committed per-question rows are what
made the difference visible, which is the argument for committing them.

Related: `model_eval.py --selfcheck` reconciles its in-process activation
against the engine (exact for n ≤ 2; the n = 3 divergence is Petrov's
approximation working as designed), and every engine change is checked for
**retrieval regression** by re-running a committed benchmark and diffing
per-question rows — adding the `kind` column, `rfm_prunable` and the squash
parameters was verified bit-identical across all 1,065 BEAM rows.

## Benchmarks and scoring

[LoCoMo](https://github.com/snap-research/locomo) (CC BY-NC),
[LongMemEval](https://github.com/xiaowu0162/LongMemEval),
[BEAM](https://github.com/mohammadtavakoli78/BEAM),
[SWE-Bench-CL](https://github.com/thomasjoshi/agents-never-forget),
[ABCD](https://github.com/asappresearch/abcd) (MIT),
[STAR](https://github.com/RasaHQ/STAR) (MIT),
[MultiDoc2Dial](https://doc2dial.github.io/multidoc2dial/) (CC BY 3.0),
[FloDial](https://dair-iitd.github.io/FloDial/) (CDLA-Sharing-1.0).

**No LLM judges, no API keys.** Retrieval is scored against each dataset's own
human annotations — the procedure, document or flowchart that actually
applied. Anyone can reproduce the results for the cost of laptop time.

## Known limits

Stated plainly, because they bound every number above:

- **Outcome signals in the benchmark experiments come from dataset
  annotations**, not real task success. They are cleaner than production
  feedback would be. Outcomes were scored directly (gold tests, agent
  behaviour) only in the live coding program — which is also where memory
  did not causally help: on repository work the terminal tracks found no
  benefit and a measured wall-clock cost, because the agents do not pay
  the costs the memories describe (findings.md).
- **The live program is ~230 sessions across Tracks 1–20, mostly on one
  executor model per track** (claude-fable-5; Track 10 ran opus-5, Tracks
  13/17/19 pinned haiku — stamped per record since Track 13, recovered
  from transcripts before that in `model-audit.jsonl`). Per-track n is a
  budget bound of 8–21 pairs; a 20-session yardstick (Track 15) measured
  the within-condition noise these are read against, and claims rest on
  sign consistency, not per-pair effect sizes.
- **Causal benefit was tested only on coding workloads.** The successor
  venues where the environment does not already persist the knowledge
  (preferences — PrefEval; organizational/tribal — MEMTRACK, Track 20)
  are measured at the retrieval layer, not yet with a live causal A/B.
- **Two of the four dialog datasets lack natural agent identities and
  ordering**, so agent assignment and stream order were simulated
  (round-robin and a seeded shuffle). Disclosed in the protocol. STAR has
  both natural, which is why it carries the most weight.
- **SWE-Bench-CL's gold links are heuristic** (file-overlap based) and noisy.
- **The staleness result is one dataset, exploratory, never pre-registered.**
- **Adversarial results assume host-asserted identity.** They defend against a
  principal misbehaving within its rights, not impersonation.
- **Retrieval metrics are proxies for task success** everywhere except the
  live A/B.

## Reproducing

```sh
python3 tests/test_rfm.py     # engine unit + SQL-surface tests
cd bench-quality
python3 pure_sql_check.py     # plain-SQL expression pinned to the engine
# dataset download commands are in bench-quality/README.md
python locomo_eval.py         # and the other *_eval.py runners
```

Every eval prints its own tables and confidence intervals, and writes
per-question rows next to the committed ones so you can diff against ours.
