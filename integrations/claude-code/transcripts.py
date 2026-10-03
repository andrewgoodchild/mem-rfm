"""The normalized session: what every downstream consumer of a finished
session reads, whichever harness produced it.

Outcome inference, the correction miner and the sweep need four things from
a session, and none of them is harness-specific:

  events     every shell command, in order, with the harness's own verdict
             (is_err), its output (body) and whether a result arrived (got)
  exposures  the memories the session was SHOWN — injected at session start
             or returned by memory_search — with the index of the first
             command that ran after the session saw each one
  prose      the assistant's own text, with our injected blocks stripped
  start      epoch seconds of the session's first timestamp, or None

Hindsight's multi-harness package (vectorize-io/hindsight, MIT) keeps one
reader per harness emitting a shared turn format, but its format drops tool
results. Ours cannot: outcome inference IS the pairing of a command with
its result. So the shared shape here is events, not turns.

A reader turns one harness's transcript into a Session. Only
claude-code exists today; adding a harness means adding a reader to
READERS and a row to harnesses.py, and nothing downstream changes.
Readers fail open: an unreadable or foreign transcript is an empty Session
with readable=False, never an exception.
"""
import collections
import datetime
import json
import re
import time

# One shell command, in order. `is_err` is the harness's own verdict, kept
# separate from output pattern-matching (a successful `grep -rn
# ModuleNotFoundError` must not read as a failure because its matches
# contain failure words). `got` distinguishes a clean exit from a command
# whose result never arrived (session ended mid-flight) — an unknown result
# is not a success.
Event = collections.namedtuple("Event", "cmd is_err body got")

Session = collections.namedtuple(
    "Session", "events exposures seen prose start readable")
"""exposures: {memory_id: (content, first_event_idx)} -- memories injected
by a hook or returned by memory_search, the ones outcome inference credits.
seen: {memory_id: content} -- every memory the session was shown by any
route, including memory_list/get/export; what makes a later restatement of
it not independent evidence (quarantine)."""

EMPTY = Session([], {}, {}, [], None, False)

# ---------------------------------------------------------------- injection
#
# The injection line is written by the hooks and parsed back from the
# transcript here, so both halves of that contract live in this module.


def day(ts):
    """A memory's save date as shown to the agent: YYYY-MM-DD, or '?' for a
    timestamp the platform cannot represent (a row written by another client
    in milliseconds, or garbage) — never an exception that would take the
    whole injection down with it."""
    try:
        return time.strftime("%Y-%m-%d", time.localtime(ts))
    except (OverflowError, ValueError, OSError, TypeError):
        return "?"


def flatten(content, close_tag="</memories>"):
    """Stored content is untrusted data headed into a model's context:
    control chars and newlines become spaces (one memory cannot fabricate
    extra list items), the enclosing block's close tag is defused (it cannot
    break out of its data block), and our own marker is defused (it cannot
    pass for an injection block — or spoof A/B attribution). The same
    function sanitizes content at write time (server, sweep)."""
    flat = "".join(ch if ch.isprintable() else " " for ch in str(content))
    flat = flat.replace("[rfm-memory:", "[rfm-memory ")
    flat = flat.replace(close_tag, "(/" + close_tag[2:-1] + ")")
    return " ".join(flat.split())


def line_head(mid, created_at):
    """'- [12, saved 2026-03-02] ' -- the date rides inside the id bracket
    so INJECTED captures the content alone."""
    return f"- [{mid}, saved {day(created_at)}] "


# "- [12] content" (older transcripts) or "- [12, saved 2026-03-02] content";
# only the id and the content are captured.
INJECTED = re.compile(r"^- \[(\d+)(?:, [^\]]*)?\] (.+)$", re.M)

# Structural, not content-guessing: our own injection blocks removed from
# prose before anything is mined from it, so the sweep cannot extract a
# memory from the session's echo of it (test_feedback_loop.py). Only the
# shape the hooks write counts — the tag alone on its line — so prose that
# merely mentions a <memory> tag keeps its text.
_OURS = re.compile(
    r"^<(memories|memory)>$[\s\S]*?^</\1>$"
    r"|^\[rfm-memory[^\]\n]*\][^\n]*$", re.M)


def strip_injected(text):
    return _OURS.sub("", text or "")


# ---------------------------------------------------------------- claude-code

def parse_jsonl(path):
    """Every JSON object in a JSONL transcript. Unreadable lines, and lines
    that parse to something other than an object ([1,2], "x", null), are
    skipped, and an unreadable file is an empty list: a reader never
    raises."""
    try:
        lines = open(path, errors="replace").read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _result_text(body):
    """A tool_result's content as one string (it may be a list of blocks)."""
    if isinstance(body, list):
        return " ".join(x.get("text", "") for x in body if isinstance(x, dict))
    return body


def is_bash_call(block):
    """A tool_use block that launches a real (non-empty) Bash command.
    Shared by claude_events and claude_exposures so their two views of which
    Bash calls happened cannot diverge — exposure indices must line up with
    the events list."""
    return (block.get("type") == "tool_use" and block.get("name") == "Bash"
            and bool((block.get("input") or {}).get("command", "")))


def claude_events(records):
    """[Event, ...] per Bash call, in order."""
    pending, raw = {}, []
    for d in records:
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if is_bash_call(b):
                cmd = (b.get("input") or {}).get("command", "")
                pending[b.get("id")] = len(raw)
                raw.append([cmd, False, "", False])
            elif b.get("type") == "tool_result":
                idx = pending.pop(b.get("tool_use_id"), None)
                if idx is None:
                    continue
                body = (_result_text(b.get("content")) or "")[:800]
                raw[idx][2] = body
                raw[idx][1] = bool(b.get("is_error"))
                raw[idx][3] = True
    return [Event(*r) for r in raw]


# MCP tools whose results put stored memories in front of the session.
_READ_TOOL = re.compile(r"memory_(search|list|get|export)$")
# memory_export's markdown lines: "- [12] (2026-03-02, 3 uses, ...) content".
_EXPORT_LINE = re.compile(r"^- \[(\d+)\] \([^)]*\) (.+)$", re.M)


def _rows_in(value):
    """(id, content) for every stored memory in a read tool's result:
    objects carrying an int id and a content string (search hits, list
    items, a single get), or export's markdown lines."""
    if isinstance(value, dict):
        if isinstance(value.get("id"), int) and isinstance(value.get("content"), str):
            yield value["id"], value["content"]
        for v in value.values():
            yield from _rows_in(v)
    elif isinstance(value, list):
        for v in value:
            yield from _rows_in(v)
    elif isinstance(value, str):
        for mid, content in _EXPORT_LINE.findall(value):
            yield int(mid), content


def claude_exposures(records):
    """(exposures, seen) — see Session.

    Only two sources are trusted, because both are written by us: a hook's
    additionalContext (attachment.type == "hook_additional_context" -- where
    Claude Code records it in headless AND interactive sessions: checked on
    interactive transcripts from 2.1.220 and 2.1.246) and the results
    of our own MCP read tools. Text the session merely read or wrote — a
    user message, a pasted CI log, assistant prose, a tool_result from
    `cat` — can contain "[rfm-memory:" and "- [N] ..." lines, and was once
    enough to write an outcome against any memory id N."""
    mems, seen, read_calls = {}, {}, {}
    n_bash = 0

    def note(mid, content, exposure):
        seen.setdefault(int(mid), content)
        if exposure:
            mems.setdefault(int(mid), (content, n_bash))

    for d in records:
        att = d.get("attachment")
        if isinstance(att, dict) and att.get("type") == "hook_additional_context":
            body = att.get("content")
            for part in (body if isinstance(body, list) else [body]):
                if isinstance(part, str) and "[rfm-memory:" in part:
                    for mid, content in INJECTED.findall(part):
                        note(mid, content, True)
            continue
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if is_bash_call(b):
                n_bash += 1
            elif b.get("type") == "tool_use":
                m = _READ_TOOL.search(str(b.get("name", "")))
                if m:
                    read_calls[b.get("id")] = m.group(1)
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in read_calls:
                body = _result_text(b.get("content")) or ""
                try:
                    parsed = json.loads(body)
                except (json.JSONDecodeError, TypeError):
                    parsed = body
                exposure = read_calls[b.get("tool_use_id")] == "search"
                for mid, text in _rows_in(parsed):
                    note(mid, text, exposure)
    return mems, seen


def claude_prose(records):
    """The assistant's text blocks, in order, injected blocks stripped."""
    out = []
    for r in records:
        if r.get("type") != "assistant":
            continue
        c = (r.get("message") or {}).get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    out.append(strip_injected(b.get("text") or "").strip())
    return out


def claude_start(records):
    """Epoch seconds of the earliest transcript timestamp, or None."""
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


def claude_readable(records):
    """Does this look like a Claude Code transcript at all? A foreign or
    empty file parses to records carrying none of its message/attachment
    shapes; saying so lets the caller log 'unreadable' instead of an
    indistinguishable 'nothing happened'."""
    return any(isinstance(d.get("message"), dict) or "attachment" in d
               for d in records)


def read_claude_code(path, prose=True):
    records = parse_jsonl(path)
    exposures, seen = claude_exposures(records)
    return Session(
        events=claude_events(records),
        exposures=exposures,
        seen=seen,
        prose=claude_prose(records) if prose else [],
        start=claude_start(records),
        readable=claude_readable(records),
    )


READERS = {"claude-code": read_claude_code}


def read(path, harness="claude-code", prose=True):
    """The Session for one transcript. An unknown harness reads as an empty,
    unreadable Session rather than raising — the hooks fail open. prose=False
    skips the assistant-text pass for callers that never read it."""
    reader = READERS.get(harness)
    if reader is None:
        return EMPTY
    try:
        return reader(path, prose)
    except Exception:
        # Valid JSON in an unexpected shape ("text": null, "message": "hi",
        # a dict where a list belongs) must not take a SessionEnd hook or a
        # whole sweep down with it: unreadable, not fatal.
        return EMPTY
