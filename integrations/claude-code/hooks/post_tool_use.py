#!/usr/bin/env python3
"""PostToolUse hook: struggle-triggered synthesis.

The formation miner extracts failed→fixed command pairs. It cannot produce
the one thing that actually earned in our corpus: a synthesized root-cause
explanation plus a constructed workaround (one such memory took 22 positive
outcomes across three runs; no command pair encodes it). That memory existed
only because an agent volunteered it — a channel we then suppressed, because
11 of 13 volunteered saves earned nothing.

This hook reinstates the channel *triggered instead of invited*. Asking an
agent "was that durable?" gets a wrong answer most of the time; asking it
"you just fought X twice and won — what was the root cause?" asks about
something objectively present in the transcript. The trigger is
deterministic and cheap: count failures per named error class, and fire once
when a class that has failed >= RFM_SYNTHESIS_N times is finally followed by
a success of the same program. Struggle-then-resolution is the moment the
knowledge exists and the reasoning is still in context.

Design constraints, each from a measured finding:

  * ONE nudge per session. Over-extraction is the failure mode of every
    system that auto-captures; a nudge that re-fires becomes an invitation.
  * A no-op must be acceptable. memU's job template carries the line this
    borrows verbatim — without it, a capture prompt manufactures a memory
    to justify itself.
  * The agent supplies the *phrasing*, never the *detection*. Agents
    diagnose their own failures badly (0 of 121 reflections named the
    correct object in one study; programmatic signal extraction moved that
    to 86%), so the nudge hands over the facts the harness observed and
    asks only for the explanation.
  * Off by default (RFM_SYNTHESIS=1 to enable), A/B-gated, and inert under
    RFM_HOOKS_OFF — this is a registered experiment, not a default.

Reads the PostToolUse payload on stdin; state lives beside the database.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import log_env  # noqa: E402
import session_end as se  # noqa: E402  (FAILURE vocabulary + program())

DB_PATH = os.path.expanduser(
    os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))
STATE_DIR = os.path.join(os.path.dirname(DB_PATH), "synthesis-state")
# 2, not OpenHands' 3: our sessions run a median of ~5 Bash calls, and the
# classes the miner left NOT CAPTURED on pytest averaged 2.0-2.2 failures
# per affected session. A threshold of 3 would never fire on this workload.
THRESHOLD = int(os.environ.get("RFM_SYNTHESIS_N", "2"))
LOG_ENABLED, LOG = log_env.resolve_log(
    os.environ.get("RFM_LOG", "1"), os.path.dirname(DB_PATH))

NUDGE = (
    "[rfm-memory] You just spent {n} failed attempts on `{cls}` before "
    "`{prog}` succeeded. That is the kind of environment knowledge this "
    "project pays to rediscover every session.\n"
    "If — and only if — you now understand the ROOT CAUSE, record it with "
    "memory_save: what actually breaks, why it breaks here, and the "
    "workaround that worked, in enough detail that a future session could "
    "apply it without re-deriving it. Prefer the general cause over the "
    "single command.\n"
    "A no-op is a perfectly good outcome — do not invent a memory to "
    "justify this prompt. If you do not yet know why it failed, or the fix "
    "was incidental, save nothing and carry on.\n"
    "(This one prompt supersedes the standing 'do not volunteer memory_save' "
    "instruction, for this moment only — the harness detected the struggle, "
    "so the judgement of WHETHER to capture has already been made. Yours is "
    "only whether you understand the cause well enough to write it down.)"
)


def _log(fields):
    if not LOG_ENABLED:
        return
    try:
        import time
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"t": round(time.time(), 3), **fields}) + "\n")
    except OSError:
        pass


def response_text(resp):
    """Bash tool_response, whatever shape the harness hands us."""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        return " ".join(str(resp.get(k, "")) for k in
                        ("stdout", "stderr", "output", "content", "error"))
    if isinstance(resp, list):
        return " ".join(x.get("text", "") if isinstance(x, dict) else str(x)
                        for x in resp)
    return ""


def main():
    # Experiment flag, A/B gate, and hooks-off gate. Silent no-op on all three.
    if os.environ.get("RFM_SYNTHESIS") != "1":
        return
    if os.environ.get("RFM_HOOKS_OFF") == "1":
        return
    if os.environ.get("RFM_AB_ARM", "rfm") != "rfm":
        return
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if payload.get("tool_name") != "Bash":
        return
    cmd = (payload.get("tool_input") or {}).get("command", "")
    prog = se.program(cmd)
    if not prog:
        return
    body = response_text(payload.get("tool_response"))
    session = (payload.get("session_id") or "?")[:8]

    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"{session}.json")
    try:
        with open(path) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {"classes": {}, "fired": False}
    if state.get("fired"):
        return                      # one nudge per session, by design

    hit = se.FAILURE.search(body or "")
    if hit:
        cls = hit.group(0).lower()
        entry = state["classes"].setdefault(cls, {"n": 0, "progs": []})
        entry["n"] += 1
        if prog not in entry["progs"]:
            entry["progs"].append(prog)
        with open(path, "w") as f:
            json.dump(state, f)
        return

    # A success: did it resolve a class this session has been fighting?
    for cls, entry in state["classes"].items():
        if entry["n"] >= THRESHOLD and prog in entry["progs"]:
            state["fired"] = True
            with open(path, "w") as f:
                json.dump(state, f)
            _log({"op": "synthesis_nudge", "session": session, "class": cls,
                  "failures": entry["n"], "program": prog})
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": NUDGE.format(
                    n=entry["n"], cls=cls, prog=prog)}}))
            return
    with open(path, "w") as f:
        json.dump(state, f)


if __name__ == "__main__":
    main()
