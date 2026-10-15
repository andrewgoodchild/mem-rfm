#!/usr/bin/env python3
"""Subagents never write the store, and their turns never feed mining or
outcome inference. Stdlib only.

Shapes are from Claude Code 2.1.300: hook input carries `agent_id` only
inside a subagent (`agent_type` alone marks a main thread run with
--agent); subagent transcript records carry isSidechain=true and agentId.

Usage: python3 test_subagent.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "hooks"), HERE]
TMP = tempfile.mkdtemp(prefix="rfm-subagent-test-")
os.environ["RFM_MEMORY_DB"] = os.path.join(TMP, "m.db")
os.environ["RFM_LOG"] = os.path.join(TMP, "log.jsonl")
os.environ.pop("RFM_HOOKS_OFF", None)
os.environ.pop("RFM_AB_ARM", None)

import harnesses  # noqa: E402
import transcripts  # noqa: E402
import pre_tool_use  # noqa: E402
import transient  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def hook(script, payload):
    r = subprocess.run([sys.executable, os.path.join(HERE, "hooks", script)],
                       input=json.dumps(payload), capture_output=True, text=True,
                       env=os.environ)
    return r.returncode, r.stdout.strip()


print("pre_tool_use guard")
cc = harnesses.HARNESSES["claude-code"]
for tool in pre_tool_use.WRITE_TOOLS:
    rc, out = hook("pre_tool_use.py", {"tool_name": f"mcp__rfm-memory__{tool}",
                                       "agent_id": "a1b2", "agent_type": "Explore",
                                       "session_id": "s"})
    d = json.loads(out) if out else {}
    check(f"subagent {tool}: denied",
          rc == 0 and d.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out)
rc, out = hook("pre_tool_use.py", {"tool_name": "mcp__rfm-memory__memory_save",
                                   "session_id": "s"})
check("main-thread memory_save: no opinion", rc == 0 and out == "", out)
rc, out = hook("pre_tool_use.py", {"tool_name": "mcp__rfm-memory__memory_save",
                                   "agent_type": "reviewer", "session_id": "s"})
check("--agent main thread (agent_type, no agent_id): allowed", out == "", out)
rc, out = hook("pre_tool_use.py", {"tool_name": "mcp__rfm-memory__memory_search",
                                   "agent_id": "a1b2"})
check("subagent memory_search: allowed (reads are the point)", out == "", out)
rc, out = hook("pre_tool_use.py", {"tool_name": "Bash", "agent_id": "a1b2"})
check("unrelated tool: no opinion", out == "", out)
rc, out = subprocess.run([sys.executable, os.path.join(HERE, "hooks", "pre_tool_use.py")],
                         input="not json", capture_output=True, text=True).returncode, ""
check("garbage stdin: exits 0 (fail open)", rc == 0)
check("registry declares the guard with a server-scoped matcher",
      cc.hooks["pre_tool"].event == "PreToolUse"
      and cc.hooks["pre_tool"].matcher == "mcp__rfm-memory__.*")

print("transcript reader drops sidechain records")


def bash(i, cmd, ok, side):
    use = {"type": "assistant", "isSidechain": side,
           "message": {"content": [{"type": "tool_use", "id": f"b{i}", "name": "Bash",
                                    "input": {"command": cmd}}]}}
    res = {"type": "user", "isSidechain": side,
           "message": {"content": [{"type": "tool_result", "tool_use_id": f"b{i}",
                                    "content": "ok" if ok else "error: no such option",
                                    "is_error": not ok}]}}
    if side:
        use["agentId"] = res["agentId"] = "a1b2"
    return [use, res]


p = os.path.join(TMP, "mixed.jsonl")
recs = (bash(1, "pytest -x", True, False) + bash(2, "make --frobnicate", False, True)
        + bash(3, "make build", True, True))
with open(p, "w") as f:
    for r in recs:
        f.write(json.dumps(r) + "\n")
s = transcripts.read(p)
check("only the main thread's Bash calls are events",
      [e.cmd for e in s.events] == ["pytest -x"], str(s.events))

print("session_end gate")
rc, _ = hook("session_end.py", {"transcript_path": p, "session_id": "x", "agent_id": "a1b2"})
log = [json.loads(l) for l in open(os.environ["RFM_LOG"])] if os.path.exists(os.environ["RFM_LOG"]) else []
check("session_end inside a subagent: skipped and logged",
      rc == 0 and log and log[-1].get("skipped") == "subagent", str(log[-1:] if log else log))

print("transient markers")
for text, want in (
        ("fixed in commit 3f9a2c1, CI is green now", {"commit_sha", "ci_status"}),
        ("see PR #482 for the discussion", {"pr_or_issue"}),
        ("uv pip install needs --python .venv/bin/python here", set()),
        ("tox -e py312 fails on macOS without OpenSSL headers", set())):
    got = set(transient.markers(text))
    check(f"markers({text[:40]!r}) = {sorted(want)}", got == want, str(sorted(got)))

print(f"\n{len(failures)} failure(s)" if failures else "\nall passed")
sys.exit(1 if failures else 0)
