#!/usr/bin/env python3
"""Acceptance audit for condition-conditioned outcomes (DESIGN_NOTES
gate: "the condition_value audit re-run as acceptance on the new
fields"). Self-contained; exit 0 = pass.

The decisive case is C4's: a memory whose condition never fired this
session, acted on successfully, must earn NOTHING. Negatives are never
gated — advice that broke something is evidence against it regardless.

Usage: hooks/test_conditions.py
"""
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="rfm-condtest-")
os.environ["RFM_MEMORY_DB"] = os.path.join(TMP, "test.db")
os.environ["RFM_LOG"] = "0"
os.environ.pop("RFM_CONDITIONED_OUTCOMES", None)
sys.path.insert(0, HERE)
import session_end as se  # noqa: E402  (reads env at import)
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))
import rfm  # noqa: E402

FLAGSHIP = ("sphinx-rfm clone: app-based tests fail at startup "
            "(ExtensionError/VersionRequirementError) because the venv's "
            "sphinxcontrib packages are too new. Workaround: prepend a "
            "stubs dir to PYTHONPATH.")
E = se.transcripts.Event  # (cmd, is_err, body, got)

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail
                                                   else ""))
    if not ok:
        failures.append(name)


def fresh_db():
    path = os.environ["RFM_MEMORY_DB"]
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    root = os.path.join(HERE, "..", "..", "..")
    db.executescript(open(os.path.join(root, "rfm_schema.sql")).read())
    db.execute("INSERT INTO rfm_memories (id, content, created_at) "
               "VALUES (1, ?, 1000000000)", (FLAGSHIP,))
    db.commit()
    db.close()
    return path


def outcomes_recorded():
    db = sqlite3.connect(os.environ["RFM_MEMORY_DB"])
    n = db.execute("SELECT count(*) FROM rfm_accesses "
                   "WHERE outcome IS NOT NULL").fetchone()[0]
    db.close()
    return n


# 1. Derivation names the flagship's classes and nothing for plain prose.
d = se.derive_condition(FLAGSHIP)
check("derive: flagship names its classes",
      "extensionerror" in d and "versionrequirementerror" in d, d)
check("derive: unconditioned prose stamps ''",
      se.derive_condition("prefer rebasing over merging") == "")

# 2. fired_classes reads got-event output only.
evs = [E("python -m pytest", True,
         "VersionRequirementError: needs sphinx>=5", True),
       E("grep pkg_resources setup.py", False, "pkg_resources", False)]
f = se.fired_classes(evs)
check("fired: sees the error class in arrived output",
      "versionrequirementerror" in f, sorted(f))
check("fired: ignores never-arrived results", "pkg_resources" not in f)

# 3. The C4 case: acted-on success, condition silent -> nothing recorded.
fresh_db()
n = se.record_outcomes([{"id": 1, "outcome": 1.0, "cmd": "PYTHONPATH=stubs "
                         "python -m pytest"}], None, fired=frozenset())
check("gate: silent-condition +1 is skipped", n == 0 and
      outcomes_recorded() == 0, f"recorded={n}")

# 4. Condition fired -> the outcome lands.
fresh_db()
n = se.record_outcomes([{"id": 1, "outcome": 1.0, "cmd": "x"}], None,
                       fired=frozenset({"versionrequirementerror"}))
check("gate: fired-condition +1 records", n == 1 and
      outcomes_recorded() == 1, f"recorded={n}")

# 5. Negatives are never gated.
fresh_db()
n = se.record_outcomes([{"id": 1, "outcome": -1.0, "cmd": "x"}], None,
                       fired=frozenset())
check("gate: silent-condition -1 still records", n == 1, f"recorded={n}")

# 6. Stamping is lazy and never overwrites an explicit stamp.
path = fresh_db()
db = sqlite3.connect(path)
rfm.register(db)
se.ensure_conditions(db)
row = db.execute("SELECT condition_class FROM rfm_memories "
                 "WHERE id = 1").fetchone()[0]
check("stamp: derivation fills NULL", "extensionerror" in (row or ""))
db.execute("UPDATE rfm_memories SET condition_class = 'pkg_resources' "
           "WHERE id = 1")
se.ensure_conditions(db)
row = db.execute("SELECT condition_class FROM rfm_memories "
                 "WHERE id = 1").fetchone()[0]
check("stamp: explicit stamp survives re-run", row == "pkg_resources")
db.close()

# Show-on-error signature: the trigger is the condition class, the keys
# only choose among memories that share it.
sig = se.error_signature(
    "Traceback (most recent call last):\n  ...\n"
    "ModuleNotFoundError: No module named 'sphinxcontrib.applehelp'")
check("signature: class extracted",
      sig is not None and sig["classes"] == ("modulenotfounderror",))
check("signature: module and its top package are keys",
      sig and {"sphinxcontrib.applehelp", "sphinxcontrib"} <= sig["keys"],
      str(sig and sorted(sig["keys"])))
check("signature: no condition class -> no signature",
      se.error_signature("AssertionError: 3 != 4\n1 failed") is None)
path_sig = se.error_signature(
    "ls: /tmp/sphinx_type_hint_links/stubs: No such file or directory")
check("signature: missing path and basename are keys",
      path_sig and {"/tmp/sphinx_type_hint_links/stubs", "stubs"}
      <= path_sig["keys"], str(path_sig and sorted(path_sig["keys"])))
check("signature: every class in the output, not just the first error",
      set(se.error_signature("zsh: no matches found: *.whl\n"
                             "pkg_resources is not importable")["classes"])
      == {"pkg_resources"})
vre = se.error_signature("VersionRequirementError: sphinxcontrib.applehelp "
                         "needs Sphinx>=5")
check("match: specific class surfaces a memory without a shared key",
      se.signature_match(vre, FLAGSHIP) is not None)
check("match: memory naming no class never matches",
      se.signature_match(vre, "Run tox -e py39 for tests.") is None)
check("match: stamped condition_class wins over derivation",
      se.signature_match(vre, FLAGSHIP, "pkg_resources") is None)
generic = se.error_signature(
    "cat: /tmp/foo/report.txt: No such file or directory")
check("match: generic class without a shared key is refused",
      se.signature_match(generic, "The build dir is missing (no such file "
                         "or directory); run make docs first.") is None)
check("match: generic class with a shared key surfaces",
      (se.signature_match(generic, "report.txt is written by `make report`"
                          " -- no such file or directory until it runs.")
       or 0) >= 1)

tail = se.error_signature("collecting ...\n" + "." * 20000
                          + "\nModuleNotFoundError: No module named 'dask'")
check("signature: error at the end of long output is found",
      tail and "dask" in tail["keys"], str(tail))
perm = se.error_signature("bash: ./run.sh: Permission denied")
check("signature: permission denied names the path as a key",
      perm and "run.sh" in perm["keys"], str(perm and sorted(perm["keys"])))
check("match: permission-denied memory sharing the path surfaces",
      se.signature_match(perm, "run.sh loses its exec bit on checkout "
                         "(permission denied): chmod +x run.sh") is not None)
eng = se.error_signature("This package requires Python>=3.10\n"
                         "ModuleNotFoundError: No module named 'foo'")
check("signature: English before 'requires' is not a key",
      eng and "package" not in eng["keys"] and "this" not in eng["keys"],
      str(eng and sorted(eng["keys"])))
six = se.error_signature("ModuleNotFoundError: No module named 'six'")
check("match: keys match whole tokens only ('six' not in 'sixty')",
      se.signature_match(six, "ModuleNotFoundError after sixty retries: "
                         "pin the mirror") is None)
check("match: stamps compare case- and space-insensitively",
      se.signature_match(six, "pip install six fixes it",
                         "ModuleNotFoundError, pkg_resources") is not None)

print(f"\n{'PASS' if not failures else 'FAIL: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
