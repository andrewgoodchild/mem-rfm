#!/usr/bin/env python3
"""The verify pass: check each formed memory against the source it came from.

The outcome ledger learns whether acting on a memory worked. A memory that
states a rule is rarely acted on through a command, so the ledger never
sees it: in Track 31 a stale decision sat in front of the agent on 15 runs
and earned nothing, and nothing demoted it. The source can do what the
ledger cannot. `decide` keeps each memory's verbatim quote and the
transcript it was formed from; this reads that transcript again, finds the
window the quote sits in, and asks whether the conversation, read whole,
still supports the memory as stated.

Verdicts, written to `verified` with `verified_at`:
  confirmed     the window supports the memory as a decision the developer
                reached or accepted;
  contradicted  the conversation overrides or rejects it, and the model has
                quoted the overriding turn verbatim, a quote this code
                checks is really there (a contradiction without a grounded
                quote is recorded as unsupported, never as contradicted);
  unsupported   the quote is in the window but the window does not decide
                the thing, or the quote itself is gone;
  source_gone   the transcript no longer exists (Claude Code deletes old
                ones), so nothing can be checked.

Only `contradicted` changes anything downstream: every delivery path skips
such rows (store.not_contradicted). Nothing is deleted or rewritten here. An
LLM retiring memories by comparing them with each other was wrong 13 of 21
times (Track 28); checking a memory against its own source is a different
question, and the model may propose a correction, which is printed for the
operator and never applied. Track 35 measures these verdicts before they
should be trusted unseen; RFM_VERIFY_GATE=0 turns the delivery gate off.

Runs when an operator points it at the store, never on its own, and prints
every verdict with its id.

Usage: verify.py [--all] [--ids ID ...] [--model NAME] [--dry-run]
  default: rows never verified; --all: every row with a quote.
"""
import argparse
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "hooks"))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import decisions  # noqa: E402
import store      # noqa: E402

PROMPT = """You check a coding agent's long-term memory against the
conversation it was formed from. Below is part of a past conversation
between a developer and an agent, and one memory another model wrote from
it for an agent that will work in the same repository later. The memory
quotes the conversation; the quote is marked.

--- BEGIN CONVERSATION PART ---
{window}
--- END CONVERSATION PART ---

Memory: {memory}
Its quote: {quote}

Decide one verdict:
  confirmed     the conversation supports the memory as stated, as something
                the developer decided or accepted;
  contradicted  a turn in this part rejects, reverses or replaces what the
                memory states, so an agent following the memory would do the
                wrong thing; a proposal the developer turned down counts;
  unsupported   the quote is here but this part does not decide the thing:
                it was only proposed, guessed, or stated by the agent and
                never accepted.

For contradicted, `evidence` must be a verbatim excerpt of at most 200
characters from the turn that overrides the memory. If the memory is wrong
only in a detail and the conversation states the right one, give the
corrected memory in `correction`; otherwise leave it empty.

Reply with JSON only:
{{"verdict": "confirmed|contradicted|unsupported", "evidence": "...",
  "correction": ""}}"""

ORIGIN = "transcript:"


def transcript_of(origins):
    """The transcript path recorded at save time, or None."""
    try:
        for o in json.loads(origins or "[]"):
            if isinstance(o, str) and o.startswith(ORIGIN):
                return o[len(ORIGIN):]
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def window_for(chat, quote):
    """The window of the conversation the quote sits in, or None if the
    quote is nowhere in it (the same normalization as decisions.grounded)."""
    for part in decisions.windows(chat):
        if decisions.grounded({"quote": quote}, part):
            return part
    return None


def judge(window, memory, quote, llm, parse):
    """One verdict from the model, made safe: an unknown verdict is
    unsupported, and a contradiction stands only on grounded evidence."""
    raw = parse(llm(PROMPT.format(window=window, memory=memory, quote=quote)))
    v = raw if isinstance(raw, dict) else {}
    verdict = v.get("verdict")
    evidence = v.get("evidence") if isinstance(v.get("evidence"), str) else ""
    correction = v.get("correction") \
        if isinstance(v.get("correction"), str) else ""
    if verdict == "contradicted":
        if not decisions.grounded({"quote": evidence}, window):
            verdict, evidence = "unsupported", ""
    elif verdict != "confirmed":
        verdict = "unsupported"
    return {"verdict": verdict, "evidence": evidence,
            "correction": correction.strip()}


def check(row, llm, parse, chats=None):
    """(verdict dict) for one (id, content, quote, origins) row. `chats`
    caches a transcript's conversation across the rows formed from it."""
    mid, content, quote, origins = row
    path = transcript_of(origins)
    if not path or not os.path.exists(path):
        return {"id": mid, "verdict": "source_gone", "evidence": "",
                "correction": ""}
    chats = {} if chats is None else chats
    if path not in chats:
        chats[path] = decisions.chat_of(path)
    window = window_for(chats[path], quote or "")
    if window is None:
        return {"id": mid, "verdict": "unsupported", "evidence": "",
                "correction": "", "why": "quote not in source"}
    return {"id": mid, **judge(window, content, quote, llm, parse)}


def run(db, rows, llm, parse, write=True, log=None):
    """Verify each row, write the verdicts, return them."""
    out, chats = [], {}
    for row in rows:
        v = check(row, llm, parse, chats)
        out.append(v)
        if write:
            db.execute("UPDATE rfm_memories SET verified = ?, verified_at = ?"
                       " WHERE id = ?", (v["verdict"], time.time(), v["id"]))
        if log:
            log({"op": "verify", "id": v["id"], "verdict": v["verdict"],
                 "corrected": bool(v.get("correction"))})
    if write:
        db.commit()
    return out


def select(db, ids=None, everything=False):
    """Rows to check: those with a quote, never verified unless --all."""
    where = "quote IS NOT NULL"
    args = []
    if ids:
        where += f" AND id IN ({','.join('?' * len(ids))})"
        args = list(ids)
    elif not everything:
        where += " AND verified IS NULL"
    return db.execute("SELECT id, content, quote, origins FROM rfm_memories "
                      f"WHERE {where} ORDER BY id", args).fetchall()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--all", action="store_true",
                    help="re-check rows already verified")
    ap.add_argument("--ids", nargs="*", type=int, default=None)
    ap.add_argument("--model", default=None,
                    help="judge model (default: sweep-config.json's)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print verdicts, write nothing")
    args = ap.parse_args(argv)
    import rfm
    import sweep
    if args.model:
        sweep.CONFIG["model"] = args.model
    db = sqlite3.connect(sweep.DB_PATH, timeout=10.0)
    rfm.register(db)
    store.ensure(db)
    rows = select(db, args.ids, args.all)
    if not rows:
        print("nothing to verify: no formed memories with a quote"
              + ("" if args.all else " await a first check"))
        return 0
    verdicts = run(db, rows, sweep.llm, sweep.parse_json,
                   write=not args.dry_run, log=sweep._log)
    content = {r[0]: r[1] for r in rows}
    counts = {}
    for v in verdicts:
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
        line = f"[{v['id']}] {v['verdict']}: {content[v['id']][:120]}"
        if v.get("evidence"):
            line += f"\n      evidence: {v['evidence'][:200]!r}"
        if v.get("correction"):
            line += f"\n      proposed: {v['correction'][:200]}"
        print(line)
    db.close()
    print(json.dumps({"checked": len(verdicts), **counts,
                      "written": not args.dry_run}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
