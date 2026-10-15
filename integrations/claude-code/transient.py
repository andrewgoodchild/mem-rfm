"""Transient-content detector: does a proposed memory carry state that will
not matter in 30 days?

A memory is re-injected into future sessions for months. Commit SHAs, PR
numbers, CI status, "currently on branch X", scratch paths under /tmp and
today's date are true when written and noise (or actively misleading) a
month later. This module only *names* such markers; callers decide what to
do with them. memory_save does not reject on them — see
bench-quality/live-ab/transient_filter_eval.py for why a hard filter is not
justified by the labelled data — the wording in the tool description and
the CLAUDE.md fence is the lever, and this is the measurement.

Pure stdlib, no state: importable from the server, the hooks and the bench.
"""
import re

# Each pattern is (name, regex). Kept deliberately narrow: a false positive
# here would suppress a durable lesson, which costs more than letting one
# piece of ephemera through to /memory-review.
PATTERNS = (
    # 7-40 hex chars with at least one digit AND one a-f letter, as a whole
    # word: a git SHA. Requiring both excludes plain numbers and words like
    # "deadbeef"-free English; "cafe" alone is too short to match.
    ("commit_sha", re.compile(
        r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b")),
    ("pr_or_issue", re.compile(
        r"(?:\b(?:PR|pull request|issue|MR)\s*#?\d+\b|/pull/\d+|/issues/\d+"
        r"|(?<![\w&])#\d{2,}\b)", re.I)),
    ("ci_status", re.compile(
        r"\b(?:CI|checks?|build|pipeline|workflow|actions?)\s+(?:is\s+|are\s+|was\s+)?"
        r"(?:green|red|passing|failing|passed|failed|broken|pending)\b", re.I)),
    ("session_state", re.compile(
        r"\b(?:currently|right now|at the moment|as of (?:today|now)|for now"
        r"|in progress|WIP|uncommitted|not yet (?:pushed|merged|committed)"
        r"|this session|just now|today|yesterday|tonight)\b", re.I)),
    ("scratch_path", re.compile(r"(?:^|[\s`'\"=:(])/(?:private/)?tmp/|/var/folders/")),
    ("date", re.compile(r"\b20\d\d-[01]\d-[0-3]\d\b")),
)


def markers(text):
    """Names of the transient patterns found in `text` (sorted, unique)."""
    text = text or ""
    return sorted({name for name, rx in PATTERNS if rx.search(text)})


def is_transient(text):
    return bool(markers(text))
