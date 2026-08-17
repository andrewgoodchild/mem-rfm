#!/usr/bin/env python3
"""Approve-all ratifier for staged memory candidates (pilot harness only).

In live use, candidates staged in pending-memories.md by the SessionEnd
hook are ratified by a human running /memory-review. A headless A/B
session has no human in the loop, so this script stands in for the review
step between tasks: every staged candidate is saved verbatim through the
real MCP server over stdio — the same code path /memory-review's
memory_save takes, so embeddings, de-dup, and logging all behave exactly
as they would in a ratified session — then the pending file is archived
to pending-reviewed.md and truncated.

Approve-all is deliberate: the pilot measures the deterministic miner's
precision as-is, not a curated store. A wrong candidate is supposed to be
demoted by the outcome loop, and the pilot exists to watch that happen.

Runs under integrations/claude-code/.venv (it has the `mcp` client):
    .venv/bin/python ratify_staged.py --db <pilot-db> [--scope sphinx]
Exit: 0 on success (including nothing staged), 1 on any save error — the
runner treats nonzero as fatal so a backlog can never silently accumulate
and trigger the SessionStart review nudge mid-experiment.
"""
import argparse
import asyncio
import json
import os
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "..", "integrations", "claude-code", "server.py")


def structured(res):
    # mcp 2.0 renamed the wire-model fields camelCase -> snake_case; the
    # server is unaffected, the client has to read both (smoke_test.py's g()).
    for n in ("structuredContent", "structured_content"):
        v = getattr(res, n, None)
        if v is not None:
            return v
    return None


def is_error(res):
    return bool(getattr(res, "isError", None) or getattr(res, "is_error", None))


def load_candidates(pending):
    """Candidate lines only: session headers and the proposed-not-saved
    comment are scaffolding. Same "- " predicate session_start.py's
    staged_review_note counts by, so the two views of "what is staged"
    cannot diverge."""
    try:
        with open(pending) as f:
            return [line[2:].strip() for line in f if line.startswith("- ")]
    except OSError:
        return []


async def ratify(db, scope):
    pending = os.path.join(os.path.dirname(db), "pending-memories.md")
    candidates = load_candidates(pending)
    if not candidates:
        print("ratify: nothing staged")
        return 0

    params = StdioServerParameters(
        command=sys.executable, args=[SERVER],
        env={**os.environ, "RFM_MEMORY_DB": db})
    saved = deduped = failed = 0
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for content in candidates:
                args = {"content": content}
                if scope:
                    args["scope"] = scope
                res = await s.call_tool("memory_save", args)
                body = structured(res)
                if is_error(res) or not body:
                    failed += 1
                    print(f"ratify: FAILED to save: {content[:80]}")
                elif body.get("status") == "already stored":
                    deduped += 1     # a recurring gotcha staged again — the
                else:                # store already carries it
                    saved += 1

    # Archive then truncate, in that order: a crash between the two leaves
    # the candidates present in BOTH files, which re-ratifies (de-dup makes
    # that harmless) — the reverse order could lose them entirely.
    with open(pending) as f:
        text = f.read()
    archive = os.path.join(os.path.dirname(db), "pending-reviewed.md")
    with open(archive, "a") as f:
        f.write(f"\n<!-- ratified {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"(approve-all, ratify_staged.py) -->\n{text}")
    with open(pending, "w") as f:
        f.write("")

    print(f"ratify: {saved} saved, {deduped} already stored, {failed} failed "
          f"of {len(candidates)} staged")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="pilot memory DB path")
    ap.add_argument("--scope", default=None, help="scope for saved memories")
    args = ap.parse_args()
    sys.exit(asyncio.run(asyncio.wait_for(
        ratify(os.path.abspath(args.db), args.scope), timeout=300)))


if __name__ == "__main__":
    main()
