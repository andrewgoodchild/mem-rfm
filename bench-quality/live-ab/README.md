# Live paired A/B: does memory help an agent fix real bugs?

`run_pilot.py` (8 pytest tasks) and `run_stream.py` (27 validated
pytest+sphinx tasks) run headless Claude Code sessions in paired arms
(control vs mem-rfm MCP server) against SWE-Bench-CL tasks, scored by the
SWE-bench protocol (gold test patches). Results: `results.jsonl`
(committed); analysis in `bench-quality/RESULTS.md` and the root README.

> **⚠️ These scripts run an LLM agent with UNATTENDED Bash access**
> (`--allowedTools "Bash,Edit,Write,..."`) against upstream bug-report text,
> in local clones on your machine. Run them in a container or sandbox if
> you don't accept that. Each full run also spends real LLM quota
> (~54 sessions).

`run_pilot2.py` (exploratory, NOT pre-registered) re-runs the paired design
against the hooks-era stack: SessionStart injection, SessionEnd correction
mining + inferred outcomes, and `ratify_staged.py` standing in for
/memory-review between tasks (approve-all). 10 era-coherent sphinx tasks,
chronological, fresh store under `pilot2/`. It is an integration test of the
harness-owned formation/outcome pipeline plus a first read on the recurrence
hypothesis (operational gotchas repay across same-repo tasks); resolution is
recorded but secondary — analyze wall/turns/tokens via `ab/ab_stats.py` and
the memory trace via `log_stats.py pilot2/rfm-log.jsonl`. Requires the hooks
registered (`install_hooks.py`); temporarily strips the managed rfm block
from `~/.claude/CLAUDE.md` while running (restored on exit, even on Ctrl-C).

## Reproducing the environment

`clones/` is gitignored (upstream repos are never redistributed). To
rebuild it:

```sh
cd clones
for arm in control rfm; do
  git clone https://github.com/sphinx-doc/sphinx sphinx-$arm
  git clone https://github.com/pytest-dev/pytest pytest-$arm
  uv venv --python 3.9 sphinx-$arm-venv
  uv venv --python 3.9 pytest-$arm-venv
done
```

Per-task checkouts, editable installs, and era pins (old sphinx needs
`pytest<7.2 setuptools<60 jinja2<3.1 markupsafe<2.1`, pre-2022 also
`docutils<0.18`; pytest needs `hypothesis`) are applied by the runners'
`prepare()` per session — nothing else is manual. Then gate the task
list: `python3 run_stream.py --validate` (no LLM; committed
`validation.jsonl` records the run this repo's results used). Runners
require the hooks registered (`../../integrations/claude-code/
install_hooks.py`) and temporarily strip the managed rfm block from
`~/.claude/CLAUDE.md` while running (restored on exit).

Provenance: task/issue text in `tasks*.json` is verbatim upstream SWE-bench
content from public pytest/sphinx issue trackers (third-party usernames and
paths that appear there are already public). `validation*.jsonl` records
three environment-pin iterations (v1 → v2 → final); the run gates on the
final file — see RESULTS.md "Corrections" for why all three are kept.
Session transcripts (`sessions/`) and memory DBs stay untracked; a redacted
store audit is committed as `memory-audit.md`.
