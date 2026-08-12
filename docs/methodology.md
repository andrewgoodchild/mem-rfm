# Why you can trust the negative results

A memory system that only publishes its wins can't tell you when to use it.
This project's main claim to being worth reading is that its failures are
reported at the same length as its successes, and that neither could have
been decided after the fact.

## Pre-registration

`PROTOCOL.md` holds the original protocol plus Amendments 1–10. Each states,
**before the runs it governs**:

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
committed at `experiments/swe-ab/memory-audit.md`, so the numbers derived from
them remain checkable.

## The correction

One published number was wrong.

An early version of the manual-versus-experience experiment claimed a
42-point gap. It rested on a title-mapping bug that silently dropped 22 of 55
manual entries, leaving 52.7% of calls with no manual coverage at all — which
made the manual baseline look far weaker than it was.

Pre-publication review caught it from the committed logs. The experiment was
re-run with full coverage; the corrected gap is 12 points, and that is the
number reported everywhere in this repo. The full disclosure is under
"Corrections" in `bench-quality/RESULTS.md`.

It is included here because a project claiming auditability should show what
its own audit caught.

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
  feedback would be. The one place outcomes were scored directly is the live
  coding A/B, where gold tests decided them — and that is also the experiment
  where memory did *not* help.
- **The live A/B is n=27 with a single executor model.**
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
cargo build --release
cargo test --release          # 21 tests: unit + CLI integration
cd bench-quality
# dataset download commands are in bench-quality/README.md
python locomo_eval.py         # and the other *_eval.py runners
```

Every eval prints its own tables and confidence intervals, and writes
per-question rows next to the committed ones so you can diff against ours.
