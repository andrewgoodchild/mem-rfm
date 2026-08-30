#!/usr/bin/env python3
"""Track 22 events MCP server: the ONLY interface to the timeline when the
agent has no code execution. Exposes one capped query tool. The data lives
in the sqlite DB named by TRACK22_EVENTS_DB; the agent's process, granted
no filesystem tool, cannot reach it except through query_events.
"""
import os
import sqlite3
import sys

try:                                    # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:                     # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

DB = os.environ.get("TRACK22_EVENTS_DB", "")
CAP = int(os.environ.get("TRACK22_CAP", "5"))
# Per-session query BUDGET: below the enumeration threshold, the timeline
# cannot be dumped by exhaustive querying (probe 3: 48 queries reconstructed
# 36 events). One server process per session, so this module-global counter
# is per-session. Applied to BOTH arms equally; the memory arm's edge is
# that it also holds the digested store and can spend fewer queries.
MAX_QUERIES = int(os.environ.get("TRACK22_MAX_QUERIES", "6"))
_used = {"n": 0}
mcp = _Server("track22-events")


@mcp.tool()
def query_events(keywords: str) -> str:
    """Search the team's Slack/Linear/Git timeline. Returns up to five
    events whose text contains ALL of the space-separated keywords
    (case-insensitive). Retrieval is BUDGETED: only a limited number of
    queries are available per session, so choose keywords carefully — the
    full timeline cannot be enumerated."""
    if _used["n"] >= MAX_QUERIES:
        return (f"query budget exhausted ({MAX_QUERIES} queries used); no "
                "more retrievals available this session")
    _used["n"] += 1
    if not DB or not os.path.exists(DB):
        return "events store unavailable"
    kws = [w.lower() for w in (keywords or "").split()]
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT ts, text FROM events ORDER BY ts").fetchall()
    con.close()
    hits = ([t for _ts, t in rows if all(k in t.lower() for k in kws)]
            if kws else [t for _ts, t in rows[-CAP:]])
    if not hits:
        return "no matching events; try different keywords"
    out = "\n".join(f"- {t}" for t in hits[:CAP])
    if len(hits) > CAP:
        out += f"\n...({len(hits) - CAP} more matches; refine keywords)"
    return out


if __name__ == "__main__":
    mcp.run()
