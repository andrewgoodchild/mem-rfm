# sqlite-rfm memory for Claude Code

Persistent, outcome-ranked memory as an MCP server. Searching a memory records
an access (recency + frequency); telling it whether the memory helped records
an outcome (value). Ranking = embedding similarity × `rfm_score(id)`, all
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
`memory_status`. The tool descriptions steer the model: search before starting
work, save durable facts, report feedback after using a memory.

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
inspect it with any sqlite3 that can `.load` the extension.
