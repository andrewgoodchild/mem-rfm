#!/usr/bin/env python3
"""The Python side of the Claude Code mod (mods/rfm-live): live,
condition-gated outcome capture.

The SessionEnd hook infers outcomes after the fact, from a transcript. The
mod sees each Bash result as it happens, so it can close the loop the
ledger is about while the session runs: a command's output names a
memory's condition class -> the mod shows that memory beside the error ->
the next command drawn from it (acted_on) succeeds or fails -> the outcome
is recorded. The memory was shown BECAUSE its condition fired, so a
positive outcome here is helped-when-needed by construction.

Every judgement is session_end.py's own (CONDITION_CLASSES, acted_on,
FAILURE, record_outcomes), so the two paths cannot drift; record_outcomes
already defers to an outcome recorded earlier in the same session, so the
SessionEnd hook never double-counts what the mod recorded.

One JSON request on stdin, one JSON answer on stdout:
  {"op": "classes"} -> {"classes": [...]}   (the mod's cheap pre-filter, so
      it spawns Python only for output that can fire a condition)
  {"op": "match", "output": "..."}
      -> {"fired": [classes], "memories": [{"id", "content", "classes"}]}
      (memories chosen by session_end.signature_match, as the
      show-on-error hook chooses them)
  {"op": "outcome", "id": 12, "command": "...", "is_error": false,
   "output": "...", "fired": [classes], "session_start": 1790000000.0}
      -> {"acted": bool, "outcome": 1.0 | -1.0 | null, "recorded": bool}
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "hooks"))
import session_end as SE  # noqa: E402

MATCH_K = int(os.environ.get("RFM_MOD_MATCH_K", 2))


def fired_in(output):
    body = (output or "").lower()
    return sorted(c for c in SE.CONDITION_CLASSES if c in body)


def classes(_req):
    return {"classes": list(SE.CONDITION_CLASSES)}


def match(req):
    fired = fired_in(req.get("output"))
    if not fired or not os.path.exists(SE.DB_PATH):
        return {"fired": fired, "memories": []}
    db = sqlite3.connect(SE.DB_PATH, timeout=10.0)
    try:
        SE.rfm.register(db)
        SE.ensure_conditions(db)
        db.commit()
        # The session_start gates, so the mod never shows what injection
        # would refuse: no memory the loop has voted against, and no
        # sweep-formed memory still in quarantine.
        cols = {r[1] for r in db.execute("PRAGMA table_info(rfm_memories)")}
        quarantine = ("AND (sightings IS NULL OR sightings >= "
                      f"{int(os.environ.get('RFM_QUARANTINE', 2))}) "
                      if "sightings" in cols else "")
        rows = db.execute(
            "SELECT id, content, condition_class, rfm_score(id) AS s "
            "FROM rfm_memories WHERE condition_class != '' "
            "AND NOT (outcome_count > 0 AND value_score < 0) "
            f"{quarantine}ORDER BY s DESC").fetchall()
    finally:
        db.close()
    # The show-on-error hook's rule (post_tool_use.jit_inject): a memory
    # must share a class with the failure, and a generic class (path,
    # command not found, ...) also a key — the missing module, path or
    # program. Best key overlap first, then the prior.
    sig = SE.error_signature(req.get("output"))
    ranked = []
    for mid, content, cond, score in rows:
        m = SE.signature_match(sig, content, cond)
        if m is not None:
            shared = sorted(SE._classes(cond) & set(sig["classes"]))
            ranked.append(((m, score), {"id": mid, "content": content,
                                        "classes": shared}))
    ranked.sort(key=lambda r: r[0], reverse=True)
    return {"fired": fired, "memories": [h for _, h in ranked[:MATCH_K]]}


def outcome(req):
    db = sqlite3.connect(SE.DB_PATH, timeout=10.0)
    try:
        row = db.execute("SELECT content FROM rfm_memories WHERE id = ?",
                         (req["id"],)).fetchone()
    finally:
        db.close()
    if row is None:
        return {"acted": False, "outcome": None, "recorded": False}
    cmd = req.get("command") or ""
    if not SE.acted_on(SE._signature(row[0]), cmd):
        return {"acted": False, "outcome": None, "recorded": False}
    value = SE.verdict(row[0], cmd, bool(req.get("is_error")),
                       req.get("output"),
                       SE.condition_stamps([req["id"]]).get(req["id"]))
    if value is None:
        return {"acted": True, "outcome": None, "recorded": False}
    done = SE.record_outcomes(
        [{"id": req["id"], "outcome": value, "cmd": cmd.split("\n")[0][:200]}],
        req.get("session_start"), frozenset(req.get("fired") or ()))
    return {"acted": True, "outcome": value, "recorded": done == 1}


def main():
    req = json.load(sys.stdin)
    op = {"classes": classes, "match": match, "outcome": outcome}.get(req.get("op"))
    if op is None:
        json.dump({"error": f"unknown op {req.get('op')!r}"}, sys.stdout)
        return 2
    json.dump(op(req), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
