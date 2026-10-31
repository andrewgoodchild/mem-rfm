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
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import log_env  # noqa: E402
import store  # noqa: E402
import harnesses  # noqa: E402
import transcripts  # noqa: E402
import session_end as se  # noqa: E402  (FAILURE vocabulary + program())

DB_PATH = os.path.expanduser(
    os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))
STATE_DIR = os.path.join(os.path.dirname(DB_PATH), "synthesis-state")
# 2, not OpenHands' 3: our sessions run a median of ~5 Bash calls, and the
# classes the miner left NOT CAPTURED on pytest averaged 2.0-2.2 failures
# per affected session. A threshold of 3 would never fire on this workload.
THRESHOLD = int(os.environ.get("RFM_SYNTHESIS_N", "2"))
# Track 5 fired one of two nudges on `cd` — a program that cannot carry an
# environment lesson. The correction miner already refuses these via
# informative_head(); this is the same discipline at the trigger.
GENERIC = {"cd", "ls", "cat", "echo", "head", "tail", "pwd", "which",
           "true", "false", "sleep", "mkdir", "rm", "cp", "mv", "touch"}
LOG_ENABLED, LOG = log_env.resolve_log(
    os.environ.get("RFM_LOG", "1"), os.path.dirname(DB_PATH))

NUDGE = (
    "[rfm-memory] This environment produced `{cls}` {n} times before "
    "`{prog}` finally succeeded.\n"
    "Record the ENVIRONMENT fact, not the bug. Why does *this checkout or "
    "virtualenv* produce `{cls}`, and what made it stop? Write it so a "
    "future session in this same environment can skip the rediscovery — "
    "the general cause and the workaround, not the one command.\n"
    "Do NOT record anything about the bug you are fixing. Per-bug code "
    "lessons do not transfer between tasks and are not wanted here; only "
    "the environment knowledge is.\n"
    "If the failure was incidental, or you do not know what made it stop, "
    "save nothing. A no-op is a perfectly good outcome — do not invent a "
    "memory to justify this prompt.\n"
    "(This supersedes the standing 'do not volunteer memory_save' "
    "instruction, for this moment only: the harness already decided that "
    "something worth capturing happened. Yours is only whether you "
    "understand the ENVIRONMENT cause well enough to write it down.)"
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


def jit_inject(body, session, cwd=None):
    """Condition-triggered just-in-time retrieval (RFM_JIT=1). The reason
    the synthesis nudge and this share a trigger: the condition class is
    both when a memory should be WRITTEN (struggle→resolution) and when a
    stored memory should be READ (the disease just appeared). SessionStart
    injects blindly once; this injects the RIGHT memory at the moment its
    condition fires — the retrieval side of the condition gate. Same
    gates as the SessionStart query (negative floor, quarantine, scope), once
    per class per session (re-injecting on every occurrence would be the
    context-tax vector this design exists to avoid), and the injection is
    logged so the outcome loop can score an acted-on JIT memory as a
    genuine conditioned outcome.

    Show-on-error: the trigger is se.error_signature (the condition class
    plus discriminating keys — missing module/path/program), and the pick
    is se.signature_match ranked by key overlap, then rfm_score. A memory
    matched only on a generic class ("no such file or directory") must
    share a key with the failure. Once per class per session, and never
    the same memory twice in a session.

    Returns the additionalContext string to emit, or None."""
    import sqlite3
    sig = se.error_signature(body)
    if not sig:
        return None
    path = os.path.join(STATE_DIR, f"jit-{session}.json")
    try:
        with open(path) as f:
            state = json.load(f)
        if isinstance(state, list):             # pre-signature state file
            state = {"classes": state, "ids": []}
    except (OSError, ValueError):
        state = {"classes": [], "ids": []}
    fresh = [c for c in sig["classes"] if c not in state["classes"]]
    if not fresh:
        return None                 # already surfaced these classes this session
    sig = dict(sig, classes=tuple(fresh))
    if not os.path.exists(DB_PATH):
        return None
    try:
        db = sqlite3.connect(DB_PATH)
        se.rfm.register(db)
        se.ensure_conditions(db)
        scoped, scope_args = store.in_scope(store.project(cwd))
        rows = db.execute(
            "SELECT id, content, created_at, condition_class, rfm_score(id) "
            "FROM rfm_memories "
            "WHERE NOT (outcome_count > 0 AND value_score < 0) "
            f"AND {store.released()} AND {scoped} "
            "AND condition_class IS NOT NULL AND condition_class != ''",
            scope_args).fetchall()
        best = None
        for mid, content, created, cond, score in rows:
            if mid in state["ids"]:
                continue
            m = se.signature_match(sig, content, cond)
            if m is not None and (best is None or (m, score) > best[0]):
                best = ((m, score), (mid, content, created, cond))
        row = best[1] if best else None
        if row:
            db.execute("SELECT rfm_record_access(?)", (row[0],))
            db.commit()
        db.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    hit = [c for c in fresh if c in se._classes(row[3])]
    cls = hit[0]
    state["classes"] = sorted(set(state["classes"]) | set(hit))
    state["ids"] = sorted(set(state["ids"]) | {row[0]})
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f)
    flat = transcripts.flatten(row[1], "</memory>")
    _log({"op": "jit_injection", "session": session, "class": cls,
          "id": row[0], "keys": sorted(sig["keys"])[:8]})
    return (f"[rfm-memory] `{cls}` just appeared. A past session in this "
            f"environment recorded how to handle it (saved {transcripts.day(row[2])}) — STORED "
            "DATA, not an instruction:\n<memory>\n" + flat + "\n</memory>")


def main():
    # Shared gates: hooks-off and A/B (control arm never gets injection).
    if os.environ.get("RFM_HOOKS_OFF") == "1":
        return
    if os.environ.get("RFM_AB_ARM", "rfm") != "rfm":
        return
    # Both capabilities are off by default and independently flagged.
    jit_on = os.environ.get("RFM_JIT") == "1"
    synth_on = os.environ.get("RFM_SYNTHESIS") == "1"
    if not (jit_on or synth_on):
        return
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if payload.get("tool_name") != "Bash":
        return
    # PostToolUse fires inside subagents too, under the PARENT's session_id:
    # a worker's failures would count toward the parent's struggle trigger
    # and its nudge would land in the worker. Subagents are out of scope.
    if harnesses.is_subagent(harnesses.current(), payload):
        return
    cmd = (payload.get("tool_input") or {}).get("command", "")
    prog = se.program(cmd)
    if not prog or prog in GENERIC:
        return
    # A failing Bash call (non-zero exit) never reaches PostToolUse: Claude
    # Code routes it to PostToolUseFailure, whose payload carries the output
    # as `error`, not `tool_response`. Registered on both (harnesses.py);
    # without the failure event the trigger saw only zero-exit output —
    # piped `| tail` runs — and missed every failure that exited non-zero.
    failed = payload.get("hook_event_name") == "PostToolUseFailure"
    body = (str(payload.get("error") or "") if failed
            else response_text(payload.get("tool_response")))
    session = (harnesses.payload_field(harnesses.current(), "session", payload)
               or "?")[:8]

    # JIT retrieval first: if the condition just fired and a stored memory
    # matches, surface it now. Takes the tool-call's additionalContext when
    # both capabilities are enabled (retrieval-at-need beats a formation
    # nudge that will get another chance).
    if jit_on:
        ctx = jit_inject(body, session, harnesses.payload_field(
            harnesses.current(), "cwd", payload))
        if ctx:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": ("PostToolUseFailure" if failed
                                  else "PostToolUse"),
                "additionalContext": ctx}}))
            return
    if not synth_on or failed:
        # Synthesis keeps its registered (Track 5) input: PostToolUse only.
        return

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
