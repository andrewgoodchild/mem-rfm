#!/usr/bin/env python3
"""The verdict on an acted-on command, and credit through quoted commands
(Track 25, T25-P2). A pipe hides the exit code, so a piped command is
judged from its output. Stdlib only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_end as SE  # noqa: E402

MEM = ("Sphinx venv pins raise VersionRequirementError; "
       "`PYTHONPATH=/path/to/shim python -m pytest tests/`")
RUN = "PYTHONPATH=/tmp/s python -m pytest -q tests/a.py"
TAIL = RUN + " 2>&1 | tail -5"
ERA = "sphinx.errors.VersionRequirementError: needs at least Sphinx v5.0"

VERDICTS = [
    # Not piped: today's rule.
    (RUN, False, "3 passed in 1s", 1.0),
    (RUN, False, "built ok", 1.0),
    (RUN, True, "1 failed", -1.0),
    (RUN, False, "ModuleNotFoundError: x", None),
    # Piped: the exit code is the last stage's.
    (TAIL, False, "3 passed, 1 warning in 1s", 1.0),
    (TAIL, False, "21 failed, 190 passed in 9s", None),
    (TAIL, False, "2 warnings, 2 errors in 0.4s", None),
    (TAIL, False, "no summary here", None),
    (TAIL, False, ERA + "\n1 error in 1s", -1.0),
    (TAIL, False, "ModuleNotFoundError: x\n3 passed", None),
    (TAIL, True, "1 failed", -1.0),
    # The last summary decides.
    (TAIL, False, "1 failed\n3 passed", 1.0),
    # Pipefail makes the exit code real again.
    ("set -o pipefail; " + TAIL, False, "built ok", 1.0),
    # A quoted bar and || are not pipes.
    ('python -m pytest -k "a|b" tests/', False, "built ok", 1.0),
    (RUN + " || true", False, "built ok", 1.0),
]

SPANNED = "Use `pip install 'alabaster<0.7.12'` for this venv."
PROSE = "In zsh, status is a read-only variable for git commands."


def test_verdicts():
    for cmd, is_err, output, want in VERDICTS:
        got = SE.verdict(MEM, cmd, is_err, output)
        assert got == want, (cmd, is_err, output, got, want)


def test_spanned_memory_needs_its_span():
    sig = SE._signature(SPANNED)
    assert SE.acted_on(sig, "pip install 'alabaster<0.7.12'")
    assert not SE.acted_on(sig, "pip install 'alabaster<0.7.13'")


def test_prose_keeps_token_share():
    assert SE.acted_on(SE._signature(PROSE), "git status")


def test_fired_reads_past_the_cut():
    long = "x" * 900 + "\nsphinx.errors.VersionRequirementError"
    e = SE.transcripts.Event("c", False, long[:800], True, long)
    assert "versionrequirementerror" in SE.fired_classes([e])


if __name__ == "__main__":
    test_verdicts()
    test_spanned_memory_needs_its_span()
    test_prose_keeps_token_share()
    test_fired_reads_past_the_cut()
    print("ok")
