#!/usr/bin/env python3
"""acted_on on template commands (Track 24, T24-P3): a memory's command with
a placeholder credits the real command that fills it in, and nothing
broader. Templates are real spans from the live-A/B stores. Stdlib only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_end as SE  # noqa: E402

SHIM = "`PYTHONPATH=/path/to/shim python -m pytest tests/`"
STUBS = "`PYTHONPATH=<stubs> python -m pytest <tests>`"
PYTEST = "`python -m pytest <tests>`"
SHOW = "`git show <fix> -- <source files>`"
ANCESTOR = "`git merge-base --is-ancestor <fix> HEAD`"
GREP = "`git log --all --oneline --grep=<keyword>`"
MKDIR = "`mkdir -p <stubs>/<package>`"
STASH = "`git stash -q && python -m pytest <target> && git stash pop -q`"
DOTS = "`PYTHONPATH=<stubs> python -m pytest ...`"

CREDIT = [
    (SHIM, "PYTHONPATH=/tmp/sphinx_shim python -m pytest -q tests/test_x.py 2>&1 | tail -8"),
    (SHIM, "cd /repo && PYTHONPATH=/tmp/s python -m pytest tests/"),
    (STUBS, "PYTHONPATH=/tmp/stubs python -m pytest tests/test_y.py"),
    (DOTS, "PYTHONPATH=/tmp/stubs python -m pytest -x tests"),
    (ANCESTOR, "git merge-base --is-ancestor abc123 HEAD"),
    (GREP, "git log --all --oneline --grep=flaky"),
    (STASH, "git stash -q && python -m pytest tests/a.py && git stash pop -q"),
]

REFUSE = [
    (SHIM, "python -m pytest -q tests/test_x.py"),      # no override
    (SHIM, "PYTHONPATH=. python -m pytest tests/"),     # no real fill
    (SHIM, "PYTHONPATH=/tmp/shim python setup.py test"),
    (SHIM, "PYTHONPATH=/tmp/shim python -m pip list"),
    (SHIM, "python -m pytest tests/ PYTHONPATH=/tmp/s"),  # out of order
    (STUBS, "python -m pytest tests/test_y.py"),
    (PYTEST, "python -m pytest tests/test_y.py"),       # every test run
    (SHOW, "git show abc123 -- sphinx/util.py"),        # generic
    (MKDIR, "mkdir -p /tmp/stubs/six"),                 # all wildcard
    (GREP, "git log --all --oneline"),
    (STASH, "python -m pytest tests/a.py"),
]

# A span with no placeholder stays verbatim.
PLAIN = "`pip install 'alabaster<0.7.12'`"


def test_credits():
    for mem, cmd in CREDIT:
        assert SE.acted_on(SE._signature(mem), cmd), (mem, cmd)


def test_refuses():
    for mem, cmd in REFUSE:
        assert not SE.acted_on(SE._signature(mem), cmd), (mem, cmd)


def test_plain_span_stays_verbatim():
    assert SE.acted_on(SE._signature(PLAIN), "pip install 'alabaster<0.7.12'")
    assert not SE.acted_on(SE._signature(PLAIN), "pip install 'alabaster<0.7.13'")


if __name__ == "__main__":
    test_credits()
    test_refuses()
    test_plain_span_stays_verbatim()
    print("ok")
