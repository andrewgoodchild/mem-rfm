#!/usr/bin/env python3
"""Optional Claude Code SessionStart hook: inject the top memories by pure
rfm_score into session context. No query exists at session start, so this is
the RFM prior doing exactly its job — surfacing what has been recently,
frequently, and successfully used, before you ask anything.

Register in ~/.claude/settings.json:
  "hooks": {"SessionStart": [{"hooks": [{"type": "command",
    "command": "<venv-python> <path-to>/session_start.py"}]}]}
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.expanduser(os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))
TOP_K = 5
# Hard injection budget: token bloat is a leading abandonment cause for
# memory tools; stay far under Claude Code's own 25KB MEMORY.md discipline.
CHAR_BUDGET = 1500


def resolve_dylib():
    if os.environ.get("RFM_DYLIB"):
        return os.environ["RFM_DYLIB"]
    for p in (
        os.path.join(HERE, "..", "..", "..", "target", "release", "librfm.dylib"),
        os.path.join(HERE, "..", "..", "..", "target", "x86_64-apple-darwin", "release", "librfm.dylib"),
    ):
        if os.path.exists(p):
            return p
    return None


def main():
    # A/B gating: when an experiment is running (ab/ab-claude sets
    # RFM_AB_ARM), inject only in the rfm arm so the control stays clean.
    if os.environ.get("RFM_AB_ARM", "rfm") != "rfm":
        sys.exit(0)
    dylib = resolve_dylib()
    if dylib is None or not os.path.exists(DB_PATH):
        sys.exit(0)  # nothing to inject; stay silent
    db = sqlite3.connect(DB_PATH)
    db.enable_load_extension(True)
    db.load_extension(dylib)
    db.enable_load_extension(False)
    rows = db.execute(
        "SELECT id, content, rfm_score(id) AS s FROM rfm_memories "
        "ORDER BY s DESC LIMIT ?", (TOP_K,)).fetchall()
    if not rows:
        sys.exit(0)
    lines, used = [], 0
    for mid, content, _s in rows:
        line = f"- [{mid}] {content[:300]}"
        if used + len(line) > CHAR_BUDGET:
            break
        lines.append(line)
        used += len(line) + 1
    if not lines:
        sys.exit(0)
    # The marker lets ab_stats attribute transcripts by identity (and detect
    # injected sessions) instead of trusting time windows alone.
    marker = f"[rfm-memory:{os.environ.get('RFM_AB_SESSION', 'standalone')}]"
    context = (
        f"{marker} Long-term memories most likely to matter (ranked by "
        "recency, frequency, and past usefulness):\n" + "\n".join(lines) +
        "\n\nMemory usage: memory_search before exploring from scratch; "
        "memory_feedback(id, helped) after a memory proves useful or wrong; "
        "memory_save for durable facts only (preferences, decisions, "
        "lessons); memory_delete honors 'forget that'.")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))


if __name__ == "__main__":
    main()
