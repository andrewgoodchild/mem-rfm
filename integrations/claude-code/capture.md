# Agent-decided capture (paste into your project CLAUDE.md or ~/.claude/CLAUDE.md)

Copy the block below. This is the capture model the 2026 tool retreat
converged on: the agent decides what's durable (no extraction pipeline, no
capture-everything hooks, no surprise token bills).

```markdown
## Memory (rfm-memory MCP)

- At the start of a task, call memory_search with the task topic before
  exploring from scratch.
- When a retrieved memory materially helped (or was wrong/misleading), call
  memory_feedback with its id — this trains the ranking.
- Save with memory_save only durable facts: user preferences, project
  decisions and their reasons, hard-won debugging lessons, environment
  quirks. One self-contained fact per call.
- Never save: current task state, anything derivable from the repo, secrets.
- When the user says "remember X" → memory_save. "Forget X" → memory_list to
  find it, then memory_delete.
```
