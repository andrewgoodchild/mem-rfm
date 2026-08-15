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

Provenance: task/issue text in `tasks*.json` is verbatim upstream SWE-bench
content from public pytest/sphinx issue trackers (third-party usernames and
paths that appear there are already public). `validation*.jsonl` records
three environment-pin iterations (v1 → v2 → final); the run gates on the
final file — see RESULTS.md "Corrections" for why all three are kept.
Session transcripts (`sessions/`) and memory DBs stay untracked; a redacted
store audit is committed as `memory-audit.md`.
