# mem-rfm memory for Claude Code

Persistent, outcome-ranked memory as an MCP server. Searching a memory records
an access (recency + frequency); telling it whether the memory helped records
an outcome (value). Ranking = clamped similarity × `rfm_prior(id)` (the frozen bounded composition), all
local — no API keys, one SQLite file.

## Setup

```sh
cd integrations/claude-code
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python mcp sqlite-vec sentence-transformers numpy
cargo build --release          # from the repo root, if not already built

# register with Claude Code (user scope; use -s project for one project):
claude mcp add -s user rfm-memory -- \
  "$(pwd)/.venv/bin/python" "$(pwd)/server.py"
```

Tools exposed: `memory_save`, `memory_search`, `memory_feedback`,
`memory_status`, `memory_list`, `memory_delete`, `memory_export`. The tool
descriptions steer the model; for reliable agent-decided capture, paste the
snippet from `capture.md` into your CLAUDE.md. `memory_list`/`memory_export`
give full inspectability of what is remembered; `memory_delete` honors
"forget that".

## Optional: session-start injection

`hooks/session_start.py` injects the top-5 memories by pure `rfm_score` at
session start (no query exists yet — this is the RFM prior standalone).
Register in `~/.claude/settings.json`:

```json
{"hooks": {"SessionStart": [{"hooks": [{"type": "command",
  "command": "/path/to/.venv/bin/python /path/to/hooks/session_start.py"}]}]}}
```

## Configuration

| env | default | |
|---|---|---|
| `RFM_MEMORY_DB` | `~/.sqlite-rfm/claude-code.db` | one DB = one memory scope |
| `RFM_DYLIB` | repo `target/release/librfm.dylib` | extension artifact |
| `RFM_EMBEDDER` | `all-MiniLM-L6-v2` | any sentence-transformers id |

Remove with `claude mcp remove rfm-memory`. The database is plain SQLite —
inspect it with any sqlite3 that can `.load` the extension. Session-start
injection is capped at 1,500 characters (token bloat is a leading
abandonment cause for memory tools); `memory_save` rejects content over
4,000 characters, and `memory_export` truncates at 200,000.

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
