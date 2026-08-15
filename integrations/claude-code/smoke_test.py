#!/usr/bin/env python3
"""End-to-end smoke test for the MCP server, over a real stdio launch.

This talks to the server the way Claude Code does — spawning it as a
subprocess and speaking MCP over stdin/stdout — rather than calling the tool
functions in-process. That distinction is the whole point: the tool bodies
can be perfectly correct while the server fails to start, ships no output
schemas, or breaks on an SDK upgrade, and only a real launch shows it. This
test was written after `pip install mcp` began resolving to 2.0, which
removed the module the server imported; in-process tests could not have
caught it.

Runs against a temporary database and log, so it never touches a real store.

Usage:  .venv/bin/python smoke_test.py [-v]
Exit:   0 all checks passed, 1 otherwise.
"""
import argparse
import asyncio
import os
import shutil
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))

# mcp 2.0 renamed the wire-model fields from camelCase to snake_case. The
# server is unaffected; the test has to read both.
def g(obj, *names):
    for n in names:
        v = getattr(obj, n, None)
        if v is not None:
            return v
    return None


def structured(res):
    return g(res, "structuredContent", "structured_content")


def is_error(res):
    return bool(g(res, "isError", "is_error"))


class Checks:
    def __init__(self, verbose):
        self.passed = self.failed = 0
        self.verbose = verbose

    def __call__(self, name, ok, detail=""):
        if ok:
            self.passed += 1
            if self.verbose:
                print(f"  ok    {name}")
        else:
            self.failed += 1
            print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        return ok


async def run(check):
    tmp = tempfile.mkdtemp(prefix="rfm-smoke-")
    env = dict(os.environ)
    env.update({
        "RFM_MEMORY_DB": os.path.join(tmp, "smoke.db"),
        "RFM_LOG": os.path.join(tmp, "smoke-log.jsonl"),
        "RFM_ACCESS_WINDOW": "3600",     # long, so repeat retrieval is suppressed
    })
    params = StdioServerParameters(
        command=sys.executable, args=[os.path.join(HERE, "server.py")], env=env)

    try:
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                init = await s.initialize()
                check("server starts over stdio",
                      g(init, "serverInfo", "server_info").name == "sqlite-rfm-memory")

                tools = {t.name: t for t in (await s.list_tools()).tools}
                expected = {"memory_save", "memory_search", "memory_feedback",
                            "memory_update", "memory_get", "memory_status",
                            "memory_list", "memory_delete", "memory_export"}
                check("all tools present", expected <= set(tools),
                      f"missing {expected - set(tools)}")

                # Structured output: a bare dict/list return annotation silently
                # disables it, which is invisible until a client tries to parse.
                no_schema = [n for n, t in tools.items()
                             if not g(t, "outputSchema", "output_schema")]
                check("every tool declares an output schema", not no_schema,
                      f"missing on {no_schema}")

                # Annotations: MCP defaults are the worst case, so silence here
                # means every tool claims to be destructive and open-world.
                # 2.0 stores these snake_case, 1.x camelCase; it accepts either
                # as a constructor kwarg, so the server is fine on both and only
                # the reader has to cope.
                def ann(n, camel, snake):
                    a = tools[n].annotations
                    return g(a, camel, snake) if a else None

                open_world = [n for n in expected
                              if ann(n, "openWorldHint", "open_world_hint") is not False]
                check("nothing claims to be open-world", not open_world, f"{open_world}")
                check("read-only tools marked read-only",
                      all(ann(n, "readOnlyHint", "read_only_hint") is True
                          for n in ("memory_get", "memory_status",
                                    "memory_list", "memory_export")))
                check("destructive tools marked destructive",
                      ann("memory_delete", "destructiveHint", "destructive_hint") is True
                      and ann("memory_update", "destructiveHint",
                              "destructive_hint") is True)
                check("memory_search admits it mutates",
                      ann("memory_search", "readOnlyHint", "read_only_hint") is False)

                # --- save -------------------------------------------------
                res = await s.call_tool("memory_save", {
                    "content": "in this repo, run cargo build --release before "
                               "benchmarking; cargo test does not refresh the dylib"})
                saved = structured(res)
                check("save returns structured content", bool(saved))
                mid = saved["id"]

                dup = structured(await s.call_tool("memory_save", {
                    "content": "in this repo, run cargo build --release before "
                               "benchmarking; cargo test does not refresh the dylib"}))
                check("identical content de-duplicates",
                      dup["id"] == mid and dup["status"] == "already stored")

                # --- search -----------------------------------------------
                res = await s.call_tool("memory_search",
                                        {"query": "how do I benchmark", "limit": 3})
                hits = structured(res)["result"]
                check("search returns structured results", bool(hits))
                check("search finds the saved memory", any(h["id"] == mid for h in hits))

                got = structured(await s.call_tool("memory_get", {"memory_id": mid}))
                check("retrieval recorded an access", got["accesses"] >= 1,
                      f"accesses={got['accesses']}")

                # Repeat retrieval inside the window must not re-count: a
                # retrying client would otherwise manufacture frequency.
                before = got["accesses"]
                for _ in range(3):
                    await s.call_tool("memory_search",
                                      {"query": "how do I benchmark", "limit": 3})
                after = structured(await s.call_tool("memory_get",
                                                    {"memory_id": mid}))["accesses"]
                check("repeat retrieval suppressed inside the window",
                      after == before, f"{before} -> {after}")

                # --- feedback ---------------------------------------------
                fb = structured(await s.call_tool(
                    "memory_feedback", {"memory_id": mid, "helped": True,
                                        "note": "smoke test"}))
                check("feedback moves the value score", fb["value_score"] > 0)

                # One outcome per access, deliberately. A second vote without a
                # new retrieval would let the EWMA absorb two while the access
                # log recorded one, so value_score could no longer be
                # reproduced by replaying rfm_accesses -- and it is the same
                # guard that stops a caller stuffing the ballot.
                check("second outcome without a new access is rejected",
                      is_error(await s.call_tool(
                          "memory_feedback", {"memory_id": mid, "helped": True})))

                # A partial score therefore needs its own retrieval to attach
                # to. First outcome initialises the EWMA directly, so the
                # stored value is exactly what was passed.
                part_id = structured(await s.call_tool("memory_save", {
                    "content": "prefer ripgrep over grep for repo-wide searches"
                }))["id"]
                seen = [h["id"] for h in structured(await s.call_tool(
                    "memory_search", {"query": "ripgrep repo-wide search",
                                      "limit": 10}))["result"]]
                check("the new memory was retrieved", part_id in seen)
                part = structured(await s.call_tool(
                    "memory_feedback", {"memory_id": part_id, "helped": True,
                                        "score": -0.5}))
                check("feedback accepts a partial score",
                      abs(part["value_score"] - (-0.5)) < 1e-9,
                      f"value_score={part['value_score']}")

                # --- update preserves what the memory earned ---------------
                pre = structured(await s.call_tool("memory_get", {"memory_id": mid}))
                upd = structured(await s.call_tool("memory_update", {
                    "memory_id": mid,
                    "content": "in this repo, run cargo build --release before "
                               "benchmarking (cargo test leaves the dylib stale)"}))
                post = structured(await s.call_tool("memory_get", {"memory_id": mid}))
                check("update preserves access history",
                      post["accesses"] == pre["accesses"] == upd["accesses"])
                check("update preserves the outcome record",
                      post["outcomes"] == pre["outcomes"]
                      and abs(post["value"] - pre["value"]) < 1e-9)
                check("update actually changed the content",
                      post["content"] != pre["content"])

                # --- scope ------------------------------------------------
                a_id = structured(await s.call_tool("memory_save", {
                    "content": "the gateway config lives in infra/gw",
                    "scope": "proj-a"}))["id"]
                b_id = structured(await s.call_tool("memory_save", {
                    "content": "the dashboard config lives in infra/dash",
                    "scope": "proj-b"}))["id"]
                glob_id = structured(await s.call_tool("memory_save", {
                    "content": "user prefers short commit messages"}))["id"]
                # limit high enough that exclusion cannot be confused with
                # simply ranking below the cut.
                scoped = [h["id"] for h in structured(await s.call_tool(
                    "memory_search", {"query": "where does config live",
                                      "limit": 50, "scope": "proj-a"}))["result"]]
                check("scoped search includes its own scope", a_id in scoped)
                check("scoped search includes unscoped memories", glob_id in scoped)
                check("scoped search excludes other scopes", b_id not in scoped,
                      f"proj-b memory {b_id} leaked into {scoped}")

                # --- min_score gates accounting, not just display ----------
                cold = structured(await s.call_tool("memory_save", {
                    "content": "unrelated note about deep sea marine biology"}))["id"]
                await s.call_tool("memory_search", {"query": "cargo build flags",
                                                    "limit": 10, "min_score": 0.9})
                cold_row = structured(await s.call_tool("memory_get",
                                                        {"memory_id": cold}))
                check("min_score keeps weak matches from earning usage",
                      cold_row["accesses"] == 0, f"accesses={cold_row['accesses']}")

                # --- list / status / export -------------------------------
                lst = structured(await s.call_tool("memory_list", {"limit": 2}))
                check("list paginates", lst["total"] > 2 and lst["has_more"] is True
                      and len(lst["items"]) == 2)
                st = structured(await s.call_tool("memory_status", {}))
                check("status counts memories and outcomes",
                      st["memories"] > 0 and st["outcomes"] > 0)
                exp = await s.call_tool("memory_export", {})
                check("export returns markdown",
                      "# mem-rfm export" in exp.content[0].text)

                # --- errors are errors, not success envelopes -------------
                for name, args in (("memory_get", {"memory_id": 99999}),
                                   ("memory_save", {"content": "   "}),
                                   ("memory_update", {"memory_id": 99999,
                                                      "content": "x"}),
                                   ("memory_feedback", {"memory_id": 99999,
                                                        "helped": True}),
                                   ("memory_feedback", {"memory_id": 1,
                                                        "helped": True,
                                                        "score": 7.0})):
                    r_ = await s.call_tool(name, args)
                    check(f"{name}{tuple(args.values())} reports isError",
                          is_error(r_))

                # --- delete -----------------------------------------------
                d = structured(await s.call_tool("memory_delete",
                                                 {"memory_id": cold}))
                check("delete reports success", d["deleted"] is True)
                check("deleted memory is gone",
                      is_error(await s.call_tool("memory_get",
                                                 {"memory_id": cold})))

                # The log is what a dogfooding run is judged on; it must exist.
                check("wrote a log", os.path.exists(env["RFM_LOG"])
                      and os.path.getsize(env["RFM_LOG"]) > 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    print("mem-rfm MCP smoke test (real stdio launch)")
    check = Checks(args.verbose)
    try:
        asyncio.run(run(check))
    except BaseException as e:
        # An ExceptionGroup hides the real cause behind a TaskGroup wrapper,
        # which is useless in a smoke test's output.
        print(f"\nABORTED: {type(e).__name__}: {e}")

        def leaves(exc, depth=1):
            subs = getattr(exc, "exceptions", ())
            if not subs:
                print(f"{'  ' * depth}cause: {type(exc).__name__}: {exc}")
                return
            for sub in subs:
                leaves(sub, depth + 1)
        leaves(e)
        return 1
    total = check.passed + check.failed
    print(f"\n{check.passed}/{total} checks passed")
    return 0 if check.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
