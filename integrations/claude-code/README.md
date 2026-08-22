# mem-rfm memory for Claude Code

Persistent, outcome-ranked memory as an MCP server. Searching a memory records
an access (recency + frequency); telling it whether the memory helped records
an outcome (value). Ranking = clamped similarity × `rfm_prior(id)` (the frozen bounded composition), all
local — no API keys, one SQLite file.

## Setup

```sh
cd integrations/claude-code
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python mcp sqlite-vec fastembed numpy

# check it actually works before wiring it in
.venv/bin/python smoke_test.py

# register with Claude Code (user scope; use -s project for one project):
claude mcp add -s user rfm-memory -- \
  "$(pwd)/.venv/bin/python" "$(pwd)/server.py"
```

`smoke_test.py` launches the server as a subprocess and speaks MCP over
stdio, the way Claude Code does, then exercises every tool against a
temporary database. That is deliberately not an in-process test: the tool
bodies can be perfectly correct while the server fails to start or ships no
output schemas. It runs green on both recent mcp 1.x (tested on 1.28; the
structured-output surface the server relies on needs ≥ 1.10) and 2.x —
worth knowing, because 2.0 removed the module the server used to import and
moved tool handlers onto a worker thread, and only a real launch showed
either.

Tools exposed: `memory_save`, `memory_search`, `memory_feedback`,
`memory_update`, `memory_get`, `memory_status`, `memory_list`,
`memory_delete`, `memory_export`. The tool
descriptions steer the model; durable capture is harness-owned — install
the hooks below instead of pasting capture instructions (`capture.md`
predates them and remains only as A/B-kit documentation: the live pilots
measured agent-volunteered saves at 11 of 13 never earning an outcome). `memory_list`/`memory_export`
give full inspectability of what is remembered; `memory_delete` honors
"forget that".

## The formation loop (hooks)

`install_hooks.py` registers both hooks in `~/.claude/settings.json`
(idempotent; backs the file up first), maintains the fenced memory-usage
block in `~/.claude/CLAUDE.md`, and installs the `/memory-review` skill.
`--remove` undoes all of it.

- `hooks/session_start.py` injects the top-3 memories by pure `rfm_score`
  (no query exists yet — the RFM prior standalone) and never a memory whose
  outcomes sit negative. K=3 and prior-ranking were chosen by replaying a
  live pilot against outcome ground truth
  (`bench-quality/live-ab/eval_selection.py`); query-similarity ranking was
  evaluated there and rejected — it anti-selects the memories that
  transfer.
- `hooks/session_end.py` mines the transcript for failed→fixed command
  pairs and stages them to `pending-memories.md` (ratified by
  `/memory-review`, never auto-saved), and infers outcomes for memories the
  session acted on — so routine feedback costs no model turns; explicit
  `memory_feedback` is reserved for what inference cannot see.

## Configuration

| env | default | |
|---|---|---|
| `RFM_MEMORY_DB` | `~/.sqlite-rfm/claude-code.db` | one DB = one memory scope |
| `RFM_EMBEDDER` | `sentence-transformers/all-MiniLM-L6-v2` | any fastembed-supported id (a sentence-transformers id outside that registry needs `pip install sentence-transformers`, which the install above does not include) |

Remove with `claude mcp remove rfm-memory`. The database is plain SQLite —
inspect it with any sqlite3 client; scoring columns are plain REALs. Session-start
injection is capped at 1,500 characters (token bloat is a leading
abandonment cause for memory tools); `memory_save` rejects content over
4,000 characters, and `memory_export` truncates at 80,000.

## A/B testing vs Claude Code built-in memory

`ab/` is a self-experiment kit measuring the *incremental* value of mem-rfm
on top of Claude Code's built-in memory (which stays on in both arms):

```sh
# instead of `claude`, launch sessions with:
integrations/claude-code/ab/ab-claude --label "fix auth bug"
# arm assigned randomly (forced --arm sessions are excluded from stats by
# default). The rfm MCP config is generated from this checkout at launch.

# after accumulating sessions in both arms:
integrations/claude-code/ab/ab_stats.py
```

Both arms run `--strict-mcp-config`, so the tool environment is identical
except the memory server; the SessionStart hook self-gates on `RFM_AB_ARM`.
Stats join the assignment log with Claude Code's own session transcripts
(user turns, output tokens, edits, duration) and the rfm DB (memory usage
per session), reporting per-arm means with bootstrap CIs and printed
caveats. Aim for ≥20 non-trivial sessions per arm with comparable
`--label`s before drawing conclusions.
