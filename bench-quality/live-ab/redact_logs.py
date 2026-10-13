#!/usr/bin/env python3
"""Redact machine-identifying detail from the committed live-A/B logs.

The runs drive real Claude Code sessions, so their logs pick up the local
home directory (and with it the username and the ~/.claude/CLAUDE.md
location), the munged ~/.claude/projects/ directory names, and the session
transcript IDs. None of that is needed to read or re-score a run:

  /Users/<you>/code/mem-rfm      -> <repo>
  /Users/<you>                   -> ~
  -Users-<you>-code-mem-rfm      -> -<repo>   (munged project dir names)
  -Users-<you>                   -> -<home>
  <session uuid>.jsonl           -> session-<sha256[:12]>.jsonl

The session pseudonym is a hash, so it is stable across files and runs and
mapping.json keys still join to transcripts.txt and rfm-log.jsonl "src".
Credential-shaped spans go through the same secret_scan.redact the memory
store uses. The commands the agent ran are the experiment's data and stay.

Usage:
  python3 redact_logs.py            # rewrite tracked files under live-ab/
  python3 redact_logs.py FILE...    # rewrite just these
  python3 redact_logs.py --check [FILE...]   # list offenders, exit 1 if any
The repo's pre-commit hook (.githooks/pre-commit) runs --check on staged
live-ab files; enable it once with `git config core.hooksPath .githooks`.
"""
import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(REPO, "integrations", "claude-code"))
os.environ["RFM_SECRET_SCAN"] = "1"
import secret_scan  # noqa: E402


def _munge(path):
    # Claude Code names ~/.claude/projects/ dirs by replacing / and . with -.
    return re.sub(r"[/.]", "-", path)


RULES = [
    (re.compile(re.escape(REPO) + r"(?![\w.-])"), "<repo>"),
    (re.compile(re.escape(HOME) + r"(?![\w.-])"), "~"),
    (re.compile(re.escape(_munge(REPO)) + r"(?![\w.])"), "-<repo>"),
    (re.compile(re.escape(_munge(HOME)) + r"(?![\w.])"), "-<home>"),
]
SESSION = re.compile(
    r"(?<![\w-])([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"(?=\.jsonl)")


def _session(m):
    return "session-" + hashlib.sha256(m.group(1).encode()).hexdigest()[:12]


def redact(text):
    """(clean_text, kinds found)."""
    kinds = []
    for pat, repl in RULES:
        text, n = pat.subn(repl, text)
        if n:
            kinds.append("path")
    text, n = SESSION.subn(_session, text)
    if n:
        kinds.append("session_id")
    text, secrets = secret_scan.redact(text)
    return text, kinds + secrets


def tracked():
    out = subprocess.run(["git", "ls-files", "-z", "--", HERE], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    return [os.path.join(REPO, p) for p in out.split("\0") if p]


def main(argv):
    check = "--check" in argv
    files = [os.path.abspath(f) for f in argv if f != "--check"] or tracked()
    dirty = 0
    for path in files:
        if os.path.abspath(path) == os.path.abspath(__file__):
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        clean, kinds = redact(text)
        if clean == text:
            continue
        dirty += 1
        rel = os.path.relpath(path, REPO)
        print(f"{rel}: {', '.join(sorted(set(kinds)))}")
        if not check:
            with open(path, "w", encoding="utf-8") as f:
                f.write(clean)
    if check and dirty:
        print(f"\n{dirty} file(s) need redaction: "
              "python3 bench-quality/live-ab/redact_logs.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
