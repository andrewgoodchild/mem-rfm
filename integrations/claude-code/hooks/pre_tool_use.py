#!/usr/bin/env python3
"""PreToolUse guard: subagents do not write the memory store.

A subagent (Agent/Task tool worker) sees a slice of the task. A "lesson" it
saves is about the slice, and an outcome it reports grades a memory against
a goal it was never given. Both land in the user-global store with the same
weight as the main thread's. Formation and outcomes are the main session's
job: its SessionEnd hook mines the main transcript, and subagent turns live
in separate files (<session>/subagents/agent-*.jsonl) that it never reads.

The MCP server cannot tell who is calling it, so the gate sits here: Claude
Code puts `agent_id` in a hook's input only when the hook fires inside a
subagent. A write tool called from there is denied, with a reason the
subagent can act on (report it to the parent instead). Reads stay allowed:
a subagent searching for a known gotcha is the point of having memory.
The one store change a read makes stays too: memory_search records an
access on each hit, as every retrieval does, so a subagent's searches do
move recency and frequency. Outcomes and content are the gated part; a
fan-out of workers searching at once records one access per memory, since
the server suppresses re-accesses inside ACCESS_WINDOW.

Registered by install_hooks.py with matcher mcp__rfm-memory__.* (see
harnesses.py), so it spawns only for this server's tools. Fails open: an
unparseable payload or a main-thread call produces no output, which Claude
Code treats as "no opinion".
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import harnesses  # noqa: E402

WRITE_TOOLS = ("memory_save", "memory_feedback", "memory_update", "memory_delete")

REASON = ("rfm-memory: subagents do not write the memory store. Put the "
          "lesson or the helped/misled verdict in your final report; the main "
          "session decides what is remembered.")


def decide(payload, harness=None):
    """The hook's stdout object, or None for no opinion."""
    harness = harness or harnesses.current()
    tool = str((payload or {}).get("tool_name", ""))
    if not tool.endswith(WRITE_TOOLS) or "__" not in tool:
        return None
    if not harnesses.is_subagent(harness, payload):
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": REASON}}


def main():
    if os.environ.get("RFM_HOOKS_OFF") == "1":
        return
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    out = decide(payload)
    if out:
        print(json.dumps(out))


if __name__ == "__main__":
    main()
