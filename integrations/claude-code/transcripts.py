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
    "Session", "events exposures prose start readable")
"""exposures: {memory_id: (content, first_event_idx)}."""

# ---------------------------------------------------------------- injection
#
# The injection line is written by the hooks and parsed back from the
# transcript here, so both halves of that contract live in this module.


def day(ts):
    """A memory's save date as shown to the agent: YYYY-MM-DD."""
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def flatten(content, close_tag="</memories>"):
    """Stored content is untrusted data headed into a model's context:
    control chars and newlines become spaces (one memory cannot fabricate
    extra list items) and the enclosing block's close tag is defused (it
    cannot break out of its data block)."""
    flat = "".join(ch if ch.isprintable() else " " for ch in str(content))
    return " ".join(flat.replace(close_tag, "(" + close_tag[2:-1] + ")").split())


def line_head(mid, created_at):
    """'- [12, saved 2026-03-02] ' -- the date rides inside the id bracket
    so INJECTED captures the content alone."""
    return f"- [{mid}, saved {day(created_at)}] "


# "- [12] content" (older transcripts) or "- [12, saved 2026-03-02] content";
# only the id and the content are captured.
INJECTED = re.compile(r"^- \[(\d+)(?:, [^\]]*)?\] (.+)$", re.M)

# Structural, not content-guessing: our own injection blocks, and the host
# wrappers that carry hook output, removed from prose before anything is
# mined from it. Without this the sweep can extract a memory from the
# session's own echo of it (test_feedback_loop.py).
_OURS = re.compile(
    r"<(memories|memory|system-reminder|task-notification)>[\s\S]*?</\1>"
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


def claude_exposures(records):
    """{memory_id: (content, first_event_idx)} for memories the session could
    have acted on: the SessionStart injection block and memory_search tool
    results, both verbatim in the transcript. first_event_idx is how many
    Bash events precede the memory's first appearance (0 for injected ones):
    a memory cannot have influenced a command that ran before the session
    saw it."""
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
            elif is_bash_call(b):
                n_bash += 1
            elif (b.get("type") == "tool_use"
                  and str(b.get("name", "")).endswith("memory_search")):
                search_calls.add(b.get("id"))
            elif (b.get("type") == "tool_result"
                  and b.get("tool_use_id") in search_calls):
                try:
                    body = _result_text(b.get("content"))
                    for r in json.loads(body or "{}").get("result", []):
                        note(r["id"], str(r.get("content", "")))
                except Exception:
                    continue
    return mems


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
    return Session(
        events=claude_events(records),
        exposures=claude_exposures(records),
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
        return Session([], {}, [], None, False)
    return reader(path, prose)
