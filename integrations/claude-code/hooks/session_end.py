#!/usr/bin/env python3
"""SessionEnd hook: propose memories from what the session had to learn.

The alternative to asking an agent mid-task "is this worth remembering?" —
which we measured going badly. In 70 live sessions the agent saved 17
sincerely-chosen lessons and 15 of 16 later outcomes were negative: judging
durability *while working* means predicting the future.

Post-hoc formation is the pattern Hermes (background_review) and Codex
(consolidation) both use. This is the cheap deterministic slice of it: rather
than an LLM summarising the transcript, it extracts the one signal that is
objectively visible in the log — **a command that failed, followed by a
variant that worked**. That is a gotcha the session paid for, and it is
exactly the category our A/B says transfers: operational knowledge (build
quirks, dependency pins, invocation details), not per-task lessons.

Two deliberate limits:

*Proposes, never writes.* Candidates are staged for review, not saved. Every
vendor that auto-captured into a shared or long-lived store (Cursor, and the
context-file study at arXiv:2602.11988) found unreviewed accumulation made
things worse. Staging is also what the surviving products do.

*Unvalidated.* A probe over this repo's own transcripts found frequency
mining surfaces generic behaviour (`pytest -q`, `git stash`) rather than
project knowledge, and found no correction pairs with a cruder heuristic than
this one. Treat the output as a lead, not a finding.

Install (settings.json):

    {"hooks": {"SessionEnd": [{"hooks": [{"type": "command",
      "command": "python3 /path/to/hooks/session_end.py"}]}]}}

Reads the hook payload on stdin; writes candidates to
$RFM_MEMORY_DB's directory as `pending-memories.md`.
"""
import json
import os
import re
import sys

DB_PATH = os.path.expanduser(
    os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))
OUT = os.path.join(os.path.dirname(DB_PATH), "pending-memories.md")
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


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    transcript = payload.get("transcript_path")
    if not transcript or not os.path.exists(transcript):
        return
    found = corrections(load_events(transcript))
    if not found:
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as f:
        f.write(f"\n## Candidates from session {payload.get('session_id', '?')[:8]}\n")
        f.write("<!-- Proposed, not saved. Review, then keep the useful ones\n"
                "     with memory_save. -->\n\n")
        for c in found[:MAX_CANDIDATES]:
            f.write(f"- In this project, `{c['failed']}` fails ({c['error']}); "
                    f"use `{c['fixed']}` instead.\n")
    print(f"rfm: staged {min(len(found), MAX_CANDIDATES)} memory candidate(s) "
          f"in {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
