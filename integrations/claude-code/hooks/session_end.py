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
pollutes. Every inferred outcome — and every failure to record one — is
logged to rfm-log.jsonl, and every run ends with a summary line (events,
in-play memories, staged, outcomes), so an empty run is distinguishable
from the hook never firing and the inference is auditable after the fact.

Install (settings.json):

    {"hooks": {"SessionEnd": [{"hooks": [{"type": "command",
      "command": "python3 /path/to/hooks/session_end.py"}]}]}}

Reads the hook payload on stdin; writes candidates to
$RFM_MEMORY_DB's directory as `pending-memories.md` and outcomes to the DB.
"""
import collections
import datetime
import json
import os
import re
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))  # repo root: rfm.py
sys.path.insert(0, os.path.join(HERE, ".."))               # server.py's dir
import rfm  # noqa: E402  (repo-root module; scoring engine)
import log_env  # noqa: E402  (server.py's sibling; shared RFM_LOG contract)

DB_PATH = os.path.expanduser(
    os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))
OUT = os.path.join(os.path.dirname(DB_PATH), "pending-memories.md")
# log_env mirrors server.py's RFM_LOG/RFM_LOG_CONTENT semantics exactly (one
# owner for both processes), so the hook's audit lines land in the same file
# the server writes, RFM_LOG=0 silences the hook too, and content redaction
# follows the same rule as server.py's _redact.
LOG_ENABLED, LOG = log_env.resolve_log(
    os.environ.get("RFM_LOG", "1"), os.path.dirname(DB_PATH))
LOG_CONTENT = log_env.content_enabled(os.environ.get("RFM_LOG_CONTENT", "1"))
MAX_CANDIDATES = 10
# Retention window (days). rfm_prunable's guard makes automatic deletion
# safe: only memories idle past the window AND never proved useful qualify —
# a positive outcome record is never prunable however long idle
# (docs/lifecycle.md calls pruning formation's safety net; this is where it
# is wired). <= 0 disables; the value is never passed through at <= 0
# because rfm_prunable(id, 0) would mean "prune anything idle".
PRUNE_DAYS = float(os.environ.get("RFM_PRUNE_DAYS", "30"))

# A failure worth learning from names a cause. Exit-code noise ("1") and
# ordinary test failures are not gotchas — the agent expects those.
FAILURE = re.compile(
    r"command not found|no such file or directory|permission denied|"
    r"unrecognized option|invalid option|is not recognized|"
    r"modulenotfounderror|importerror|cannot find module|"
    r"unable to load|not a loadable|undefined symbol|"
    r"no matches found|bad interpreter|"
    # Environment/startup exception class (validated on the pilot-2 replay:
    # recovered the run's top-value gotcha — the era-pin stub workaround —
    # with zero noise, where a generic \w+Error class staged ordinary test
    # failures). Names an env cause, not code-under-test behavior.
    r"extensionerror|versionrequirementerror|distributionnotfound|"
    r"pkg_resources", re.I)

# One Bash-call event, in order. `is_err` is the harness's own verdict, kept
# separate from the FAILURE regex (which runs over OUTPUT text, so a
# successful `grep -rn ModuleNotFoundError` must not read as a failure just
# because its matches contain failure words). `got` distinguishes a clean
# exit from a command whose result never arrived (session ended mid-flight)
# — an unknown result is not a success. Named fields everywhere a field is
# read, instead of a positional tuple threaded by index across four
# functions.
Event = collections.namedtuple("Event", "cmd is_err body got")


def tokens(cmd):
    return set(re.findall(r"[A-Za-z0-9_.\-/]+", cmd.split("<<")[0][:300]))


def program(cmd):
    """The command actually being run, skipping env-var prefixes."""
    for tok in cmd.split("<<")[0].split():
        if "=" in tok and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            continue
        return os.path.basename(tok.strip("\"'`(){};|&"))
    return ""


def _is_bash_call(block):
    """A tool_use block that launches a real (non-empty) Bash command.
    Shared by load_events and in_play_memories so their two views of "which
    Bash calls happened" cannot silently diverge — in_play_memories' n_bash
    offset must line up with load_events' events list."""
    return (block.get("type") == "tool_use" and block.get("name") == "Bash"
            and bool((block.get("input") or {}).get("command", "")))


def _log(fields):
    """Append one line to rfm-log.jsonl. Never raises — a log write must
    not be the reason the hook fails."""
    if not LOG_ENABLED:
        return
    try:
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"t": round(time.time(), 3), **fields}) + "\n")
    except OSError:
        pass


def _parse_transcript(path):
    """Every JSONL record in the transcript, parsed once. load_events and
    in_play_memories both scan it (for different signals); a shared parse
    avoids reading and JSON-decoding a potentially multi-MB transcript
    twice per hook run."""
    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def load_events(records):
    """[Event, ...] per Bash call, in order."""
    pending, raw = {}, []
    for d in records:
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if _is_bash_call(b):
                cmd = (b.get("input") or {}).get("command", "")
                pending[b.get("id")] = len(raw)
                raw.append([cmd, False, "", False])
            elif b.get("type") == "tool_result":
                idx = pending.pop(b.get("tool_use_id"), None)
                if idx is None:
                    continue
                body = b.get("content")
                if isinstance(body, list):
                    body = " ".join(x.get("text", "") for x in body
                                    if isinstance(x, dict))
                body = (body or "")[:800]
                raw[idx][2] = body
                raw[idx][1] = bool(b.get("is_error"))
                raw[idx][3] = True
    return [Event(*r) for r in raw]


def corrections(events):
    """Failed command → the later command that fixed it.

    Requires substantial token overlap so we pair a command with its own
    retry rather than with whatever happened to run next, and requires the
    fix to have succeeded. A candidate must name a cause (FAILURE match):
    ordinary exit-1 noise — a failing test the agent is working on — is not
    a gotcha, per the module docstring. Failures are mined from the harness
    verdict OR an error-shaped output (a `.load`-style tool can fail while
    exiting 0), but the fix must be clean on both signals."""
    out, used = [], set()
    for i, e in enumerate(events):
        reason = FAILURE.search(e.body) if e.got else None
        if not e.got or not (e.is_err or reason):
            continue        # not a known failure
        if reason is None:
            continue        # failed, but names no cause: expected noise
        base = tokens(e.cmd)
        if not base:
            continue
        for j in range(i + 1, min(i + 6, len(events))):
            if j in used:
                continue
            fix = events[j]
            # Identity is checked on the FULL text: two heredoc calls can share
            # a first line while differing entirely in body.
            if (not fix.got or fix.is_err or FAILURE.search(fix.body)
                    or fix.cmd.strip() == e.cmd.strip()):
                continue
            # The fix must be a retry of the SAME program, not merely the next
            # thing that ran — without this, an unrelated success gets paired
            # with the failure that happened to precede it.
            prog = program(e.cmd)
            if not prog or prog not in tokens(fix.cmd):
                continue
            overlap = len(base & tokens(fix.cmd)) / max(1, len(base))
            if overlap >= 0.5:
                head_a = e.cmd.split("\n")[0][:200]
                head_b = fix.cmd.split("\n")[0][:200]
                # Two heredoc calls can differ only in their body; the rendered
                # advice would then read "X fails; use X instead". Useless.
                if head_a == head_b:
                    continue
                out.append({
                    "failed": head_a,
                    "fixed": head_b,
                    "error": reason.group(0).lower(),
                })
                used.add(j)
                break
    return out


INJECTED = re.compile(r"^- \[(\d+)\] (.+)$", re.M)


def in_play_memories(records):
    """{memory_id: (content, first_event_idx)} for memories the session could
    have acted on: the SessionStart injection block and memory_search tool
    results, both of which sit verbatim in the transcript.

    first_event_idx is how many Bash events precede the memory's first
    appearance (0 for injected ones), counted with load_events' own
    _is_bash_call predicate. A memory cannot have influenced a command that
    ran before the session ever saw it, so outcome inference starts matching
    there."""
    mems, search_calls = {}, set()
    n_bash = 0

    def note(mid, content):
        mems.setdefault(int(mid), (content, n_bash))

    def scan_text(text):
        if "[rfm-memory:" in text:
            for mid, content in INJECTED.findall(text):
                note(mid, content)

    for d in records:
        # Headless (sdk-cli) transcripts carry the SessionStart injection in
        # an attachment record (attachment.type == "hook_additional_context"),
        # never inside message.content — scanning only messages misses the
        # PRIMARY way memories enter a session (pilot 2: inference recovered
        # 1 of 15 outcomes until this branch existed). Interactive transcripts
        # embed it in a message, so both paths stay.
        att = d.get("attachment")
        if isinstance(att, dict) and att.get("type") == "hook_additional_context":
            body = att.get("content")
            for part in (body if isinstance(body, list) else [body]):
                if isinstance(part, str):
                    scan_text(part)
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
            elif _is_bash_call(b):
                n_bash += 1
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
                        note(r["id"], str(r.get("content", "")))
                except Exception:
                    continue
    return mems


def rehydrate(mems):
    """Replace transcript-derived memory content with the store's full text.
    Injected lines are cut to the injection char budget, so a signature
    built from the transcript can lack exactly the backtick spans that
    identify acted-on commands (pilot 2: the top memory's stubs path sat
    past the cut in every session, and inference recovered 1 of 15
    outcomes). The transcript text stays as fallback for deleted ids."""
    if not mems or not os.path.exists(DB_PATH):
        return mems
    try:
        db = sqlite3.connect(DB_PATH, timeout=10.0)
        for mid, (content, idx) in list(mems.items()):
            row = db.execute("SELECT content FROM rfm_memories WHERE id = ?",
                             (mid,)).fetchone()
            if row is not None:
                mems[mid] = (row[0], idx)
        db.close()
    except sqlite3.Error:
        pass
    return mems


def session_start_time(records):
    """Epoch seconds of the earliest transcript timestamp — the session
    boundary record_outcomes needs: explicit feedback given THIS session
    wins over an inferred outcome, but an outcome closed in a previous
    session must not block this session's use from being recorded (injection
    writes no access row, so the previous outcome is still the latest).
    None when nothing parses; the caller then abstains from overriding any
    existing outcome — the conservative reading."""
    best = None
    for d in records:
        ts = d.get("timestamp")
        if not isinstance(ts, str):
            continue
        try:
            t = datetime.datetime.fromisoformat(
                ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        best = t if best is None else min(best, t)
    return best


def _signature(mem_content):
    """(backtick spans, program-tokens) for a memory's content, computed
    once and reused against every candidate command — acted_on's inputs
    that don't vary per command, hoisted out of infer_outcomes' inner
    loop."""
    return re.findall(r"`([^`]{8,})`", mem_content), tokens(mem_content)


def acted_on(sig, cmd):
    """Did this command come from the memory this signature was built for?
    Precision over recall: a backtick-quoted span reproduced verbatim, or
    the command's tokens drawn from the memory with its program named
    there."""
    spans, mt = sig
    for span in spans:
        if span in cmd:
            return True
    prog = program(cmd)
    if not prog or prog not in mt:
        return False
    ct = tokens(cmd)
    return bool(ct) and len(ct & mt) / len(ct) >= 0.6


def infer_outcomes(mems, events):
    """First acted-on command per memory decides the outcome. In play but
    never acted on -> no outcome (idleness is rfm_prunable's signal).

    Precision over recall, so abstain wherever the verdict is not the
    harness's own: matching starts at the memory's first appearance (an
    earlier command cannot have come from it), a command whose result never
    arrived decides nothing, and a zero-exit command whose output still
    looks error-shaped is ambiguous — no outcome beats a wrong one."""
    out = []
    for mid, (content, first_idx) in mems.items():
        sig = _signature(content)
        for e in events[first_idx:]:
            if not acted_on(sig, e.cmd):
                continue
            if not e.got:
                break                 # result never arrived: verdict unknown
            if not e.is_err and FAILURE.search(e.body):
                break                 # zero-exit but error-shaped: ambiguous
            out.append({"id": mid, "outcome": -1.0 if e.is_err else 1.0,
                        "cmd": e.cmd.split("\n")[0][:200]})
            break
    return out


def record_outcomes(inferred, session_start):
    """Write outcomes, deferring to any loop the model already closed THIS
    session: an outstanding access gets the outcome attached; a memory with
    no access — or whose latest access carries an outcome from a PREVIOUS
    session, which is a closed retrieval, not this one — gets its use
    recorded as a fresh access; a latest access whose outcome was recorded
    this session is left alone (explicit feedback wins). With no
    session_start (no parseable transcript timestamp), any existing outcome
    defers — abstaining beats double-counting."""
    if not inferred or not os.path.exists(DB_PATH):
        return 0
    try:
        db = sqlite3.connect(DB_PATH, timeout=10.0)
    except sqlite3.Error as e:
        _log({"op": "outcome_inferred_failed", "error": f"connect: {e}"})
        return 0
    done = 0
    try:
        rfm.register(db)
        for o in inferred:
            try:
                row = db.execute(
                    "SELECT accessed_at, outcome FROM rfm_accesses "
                    "WHERE memory_id = ? "
                    "ORDER BY accessed_at DESC, rowid DESC LIMIT 1",
                    (o["id"],)).fetchone()
                if row is not None and row[1] is not None and (
                        session_start is None or row[0] >= session_start):
                    continue      # explicit feedback this session; it wins
                if row is None or row[1] is not None:
                    db.execute("SELECT rfm_record_access(?)", (o["id"],))
                db.execute("SELECT rfm_record_outcome(?, ?)",
                           (o["id"], o["outcome"]))
                done += 1
                rec = dict(o)
                rec["cmd"] = log_env.redact(o["cmd"], LOG_CONTENT)
                _log({"op": "outcome_inferred", **rec})
            except sqlite3.Error as e:
                # Unknown id or other DB trouble on this one item — logged
                # so a systematic failure is distinguishable from "nothing
                # was acted on this session", never fatal to the hook.
                _log({"op": "outcome_inferred_failed", "id": o["id"],
                      "error": str(e)})
                continue
        db.commit()
    except sqlite3.Error as e:
        _log({"op": "outcome_inferred_failed", "error": f"commit: {e}"})
        done = 0          # e.g. locked past the timeout at commit: best-effort
    finally:
        db.close()
    return done


def prune(window_days):
    """Retention pass: delete memories that rfm_prunable marks — idle past
    the window AND never useful. Mirrors server _delete (both tables), and
    logs each removal with redacted content so an audit can see what left
    and why. Best-effort like everything else in this hook."""
    if window_days <= 0 or not os.path.exists(DB_PATH):
        return 0
    try:
        db = sqlite3.connect(DB_PATH, timeout=10.0)
    except sqlite3.Error:
        return 0
    pruned = 0
    try:
        rfm.register(db)
        rows = db.execute(
            "SELECT id, content FROM rfm_memories "
            "WHERE rfm_prunable(id, ?) = 1", (float(window_days),)).fetchall()
        for mid, content in rows:
            db.execute("DELETE FROM rfm_memories WHERE id = ?", (mid,))
            db.execute("DELETE FROM rfm_accesses WHERE memory_id = ?", (mid,))
            _log({"op": "prune", "id": mid, "window_days": window_days,
                  "content": log_env.redact(str(content), LOG_CONTENT)})
            pruned += 1
        db.commit()
    except sqlite3.Error as e:
        _log({"op": "prune_failed", "error": str(e)})
        pruned = 0
    finally:
        db.close()
    return pruned


def main():
    # A/B gating: when an experiment is running (ab/ab-claude sets
    # RFM_AB_ARM), a control-arm session must neither stage candidates nor
    # record outcomes — the arms run the same task back-to-back, so a
    # control lesson ratified into the shared store would leak the current
    # task into the rfm arm. Mirrors session_start.py's gate.
    if os.environ.get("RFM_AB_ARM", "rfm") != "rfm":
        return
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    transcript = payload.get("transcript_path")
    if not transcript or not os.path.exists(transcript):
        return
    records = _parse_transcript(transcript)
    events = load_events(records)
    session = (payload.get("session_id") or "?")[:8]
    notes = []

    found = corrections(events)
    staged = min(len(found), MAX_CANDIDATES)
    if found:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "a") as f:
            f.write(f"\n## Candidates from session {session}\n")
            f.write("<!-- Proposed, not saved. Review, then keep the useful ones\n"
                    "     with memory_save. -->\n\n")
            for c in found[:MAX_CANDIDATES]:
                f.write(f"- In this project, `{c['failed']}` fails ({c['error']}); "
                        f"use `{c['fixed']}` instead.\n")
        notes.append(f"staged {staged} memory candidate(s) in {OUT}")

    mems = rehydrate(in_play_memories(records))
    recorded = record_outcomes(infer_outcomes(mems, events),
                               session_start_time(records))
    if recorded:
        notes.append(f"recorded {recorded} inferred outcome(s)")
    pruned = prune(PRUNE_DAYS)
    if pruned:
        notes.append(f"pruned {pruned} idle never-useful memor"
                     + ("y" if pruned == 1 else "ies"))
    # Run marker, written even when every count is zero: without it, a run
    # that found nothing is indistinguishable in the log from the hook never
    # firing, and the formation loop cannot be audited.
    _log({"op": "session_end", "session": session, "events": len(events),
          "in_play": len(mems), "staged": staged, "outcomes": recorded,
          "pruned": pruned})
    if notes:
        print("rfm: " + "; ".join(notes), file=sys.stderr)


if __name__ == "__main__":
    main()
