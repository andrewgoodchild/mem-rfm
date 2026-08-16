#!/usr/bin/env python3
"""SessionEnd hook: propose memories from what the session had to learn,
and record outcomes for the memories the session actually used.

Both jobs are post-hoc for the same measured reason: asking an agent
mid-task to do memory work under-fires, and when it does fire it
anti-selects (70 live sessions: 17 sincerely-chosen lessons, 15 of 16 later
outcomes negative). After the session, what mattered is visible in the
transcript. Post-hoc is the pattern Hermes (background_review) and Codex
(consolidation) both use; this is the cheap deterministic slice — no LLM,
only signals objectively present in the log.

FORMATION — **a command that failed, followed by a variant that worked** is
a gotcha the session paid for, in exactly the category our A/B says
transfers (operational knowledge). Candidates are *staged, never saved*
(`pending-memories.md`, ratified by /memory-review): every vendor that
auto-captured content into a long-lived store found unreviewed accumulation
made things worse (arXiv:2602.11988).

OUTCOMES — the M in RFM, and the loop the tool-call path never closes
reliably. Three deterministic steps:
  1. which memories were in play: ids and content from the SessionStart
     injection block ("- [id] content" under the [rfm-memory:] marker) and
     from memory_search tool results, both verbatim in the transcript;
  2. which were acted on: a backtick-quoted span from the memory appearing
     in a later command, or the command's tokens drawn from the memory
     (program match + overlap threshold — the correction-miner's own
     discipline);
  3. how that went: the harness recorded the command's result. Acted on and
     succeeded -> +1; acted on and failed -> -1 (this also catches the
     session's failed->fixed pair overturning a memory's advice). In play
     but never used -> NO outcome: absence of use is what rfm_prunable
     measures, not negative evidence.

Unlike formation, outcomes ARE written directly, and the asymmetry is
principled: formation admits new unbounded *claims* into the store (needs a
human), an outcome adjusts the weight on an existing claim inside a frozen
bounded blend (EWMA lambda=0.3, confidence shrink, beta-capped composition
— the math is the review step, and a wrong outcome decays). Thresholds are
tuned for precision over recall: a missed outcome costs little, a wrong one
pollutes. Every inferred outcome is logged to rfm-log.jsonl with the
matched command, so the inference is auditable after the fact.

Install (settings.json):

    {"hooks": {"SessionEnd": [{"hooks": [{"type": "command",
      "command": "python3 /path/to/hooks/session_end.py"}]}]}}

Reads the hook payload on stdin; writes candidates to
$RFM_MEMORY_DB's directory as `pending-memories.md` and outcomes to the DB.
"""
import json
import os
import re
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))
import rfm  # noqa: E402  (repo-root module; scoring engine)

DB_PATH = os.path.expanduser(
    os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))
OUT = os.path.join(os.path.dirname(DB_PATH), "pending-memories.md")
LOG = os.path.join(os.path.dirname(DB_PATH), "rfm-log.jsonl")
MAX_CANDIDATES = 10

# A failure worth learning from names a cause. Exit-code noise ("1") and
# ordinary test failures are not gotchas — the agent expects those.
FAILURE = re.compile(
    r"command not found|no such file or directory|permission denied|"
    r"unrecognized option|invalid option|is not recognized|"
    r"modulenotfounderror|importerror|cannot find module|"
    r"unable to load|not a loadable|undefined symbol|"
    r"no matches found|bad interpreter", re.I)


def tokens(cmd):
    return set(re.findall(r"[A-Za-z0-9_.\-/]+", cmd.split("<<")[0][:300]))


def program(cmd):
    """The command actually being run, skipping env-var prefixes."""
    for tok in cmd.split("<<")[0].split():
        if "=" in tok and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            continue
        return os.path.basename(tok.strip("\"'`(){};|&"))
    return ""


def load_events(path):
    """(command, errored, text) per Bash call, in order."""
    pending, events = {}, []
    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError:
        return events
    for line in lines:
        try:
            d = json.loads(line)
        except Exception:
            continue
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("name") == "Bash":
                cmd = (b.get("input") or {}).get("command", "")
                if cmd:
                    pending[b.get("id")] = len(events)
                    events.append([cmd, False, ""])
            elif b.get("type") == "tool_result":
                idx = pending.pop(b.get("tool_use_id"), None)
                if idx is None:
                    continue
                body = b.get("content")
                if isinstance(body, list):
                    body = " ".join(x.get("text", "") for x in body
                                    if isinstance(x, dict))
                body = (body or "")[:800]
                events[idx][2] = body
                events[idx][1] = bool(b.get("is_error")) or bool(FAILURE.search(body))
    return events


def corrections(events):
    """Failed command → the later command that fixed it.

    Requires substantial token overlap so we pair a command with its own
    retry rather than with whatever happened to run next, and requires the
    fix to have succeeded."""
    out, used = [], set()
    for i, (cmd, failed, err) in enumerate(events):
        if not failed:
            continue
        base = tokens(cmd)
        if not base:
            continue
        for j in range(i + 1, min(i + 6, len(events))):
            if j in used:
                continue
            fix, fix_failed, _ = events[j]
            # Identity is checked on the FULL text: two heredoc calls can share
            # a first line while differing entirely in body.
            if fix_failed or fix.strip() == cmd.strip():
                continue
            # The fix must be a retry of the SAME program, not merely the next
            # thing that ran — without this, an unrelated success gets paired
            # with the failure that happened to precede it.
            prog = program(cmd)
            if not prog or prog not in tokens(fix):
                continue
            overlap = len(base & tokens(fix)) / max(1, len(base))
            if overlap >= 0.5:
                head_a = cmd.split("\n")[0][:200]
                head_b = fix.split("\n")[0][:200]
                # Two heredoc calls can differ only in their body; the rendered
                # advice would then read "X fails; use X instead". Useless.
                if head_a == head_b:
                    continue
                reason = FAILURE.search(err)
                out.append({
                    "failed": head_a,
                    "fixed": head_b,
                    "error": (reason.group(0) if reason else "failed").lower(),
                })
                used.add(j)
                break
    return out


INJECTED = re.compile(r"^- \[(\d+)\] (.+)$", re.M)


def in_play_memories(path):
    """{memory_id: content} for memories the session could have acted on:
    the SessionStart injection block and memory_search tool results, both of
    which sit verbatim in the transcript."""
    mems, search_calls = {}, set()

    def scan_text(text):
        if "[rfm-memory:" in text:
            for mid, content in INJECTED.findall(text):
                mems.setdefault(int(mid), content)

    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError:
        return mems
    for line in lines:
        try:
            d = json.loads(line)
        except Exception:
            continue
        content = (d.get("message") or {}).get("content")
        if isinstance(content, str):
            scan_text(content)
            continue
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                scan_text(b.get("text", ""))
            elif (b.get("type") == "tool_use"
                  and str(b.get("name", "")).endswith("memory_search")):
                search_calls.add(b.get("id"))
            elif (b.get("type") == "tool_result"
                  and b.get("tool_use_id") in search_calls):
                body = b.get("content")
                if isinstance(body, list):
                    body = " ".join(x.get("text", "") for x in body
                                    if isinstance(x, dict))
                try:
                    for r in json.loads(body or "{}").get("result", []):
                        mems.setdefault(int(r["id"]), str(r.get("content", "")))
                except Exception:
                    continue
    return mems


def acted_on(mem_content, cmd):
    """Did this command come from this memory? Precision over recall: a
    backtick-quoted span reproduced verbatim, or the command's tokens drawn
    from the memory with its program named there."""
    for span in re.findall(r"`([^`]{8,})`", mem_content):
        if span in cmd:
            return True
    prog = program(cmd)
    mt = tokens(mem_content)
    if not prog or prog not in mt:
        return False
    ct = tokens(cmd)
    return bool(ct) and len(ct & mt) / len(ct) >= 0.6


def infer_outcomes(mems, events):
    """First acted-on command per memory decides the outcome. In play but
    never acted on -> no outcome (idleness is rfm_prunable's signal)."""
    out = []
    for mid, content in mems.items():
        for cmd, failed, _err in events:
            if acted_on(content, cmd):
                out.append({"id": mid, "outcome": -1.0 if failed else 1.0,
                            "cmd": cmd.split("\n")[0][:200]})
                break
    return out


def record_outcomes(inferred):
    """Write outcomes, deferring to any loop the model already closed:
    an outstanding access gets the outcome attached; a never-accessed
    (injected-only) memory gets its use recorded as the access; a latest
    access that already carries an explicit outcome is left alone."""
    if not inferred or not os.path.exists(DB_PATH):
        return 0
    db = sqlite3.connect(DB_PATH, timeout=10.0)
    rfm.register(db)
    done = 0
    for o in inferred:
        try:
            row = db.execute(
                "SELECT outcome FROM rfm_accesses WHERE memory_id = ? "
                "ORDER BY accessed_at DESC, rowid DESC LIMIT 1",
                (o["id"],)).fetchone()
            if row is not None and row[0] is not None:
                continue      # model gave explicit feedback; it wins
            if row is None:
                db.execute("SELECT rfm_record_access(?)", (o["id"],))
            db.execute("SELECT rfm_record_outcome(?, ?)",
                       (o["id"], o["outcome"]))
            done += 1
            with open(LOG, "a") as fh:
                fh.write(json.dumps({"t": round(time.time(), 3),
                                     "op": "outcome_inferred", **o}) + "\n")
        except (sqlite3.Error, OSError):
            continue          # unknown id or log trouble — never break the hook
    db.commit()
    db.close()
    return done


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    transcript = payload.get("transcript_path")
    if not transcript or not os.path.exists(transcript):
        return
    events = load_events(transcript)
    notes = []

    found = corrections(events)
    if found:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "a") as f:
            f.write(f"\n## Candidates from session {payload.get('session_id', '?')[:8]}\n")
            f.write("<!-- Proposed, not saved. Review, then keep the useful ones\n"
                    "     with memory_save. -->\n\n")
            for c in found[:MAX_CANDIDATES]:
                f.write(f"- In this project, `{c['failed']}` fails ({c['error']}); "
                        f"use `{c['fixed']}` instead.\n")
        notes.append(f"staged {min(len(found), MAX_CANDIDATES)} memory "
                     f"candidate(s) in {OUT}")

    recorded = record_outcomes(infer_outcomes(in_play_memories(transcript), events))
    if recorded:
        notes.append(f"recorded {recorded} inferred outcome(s)")
    if notes:
        print("rfm: " + "; ".join(notes), file=sys.stderr)


if __name__ == "__main__":
    main()
