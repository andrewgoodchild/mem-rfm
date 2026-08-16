#!/usr/bin/env python3
"""Parity check: rfm.py (pure Python) vs the Rust extension.

Drives BOTH implementations through the same operation sequence — schema
init, inserts, frozen-clock accesses, outcomes, config changes — then
compares (a) the full persisted table state and (b) every read function,
over a corpus covering each branch of the hybrid activation and the states
only reachable at the boundaries: never accessed, summary-without-times
from a bulk import, sub-EPS lags, t1 == t2, the degenerate tail window,
zero outcomes with a non-zero value.

This is the retirement gate for the extension: rfm.py replaces it only if
this script reports max diff at float round-off and identical rankings.
Exit 0 = parity; exit 1 with a report otherwise.
"""
import math
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import rfm  # noqa: E402

T0 = 1_700_000_000.0          # corpus epoch; all times scripted from here
DAY = 86_400.0
TOL = 1e-12                    # |a-b| for values; state must match tighter


def open_ext(path):
    db = sqlite3.connect(path)
    db.enable_load_extension(True)
    for p in (os.path.join(HERE, "..", "target", "release", "librfm.dylib"),
              os.path.join(HERE, "..", "target", "x86_64-apple-darwin",
                           "release", "librfm.dylib")):
        if os.path.exists(p):
            db.load_extension(p)
            db.enable_load_extension(False)
            return db
    sys.exit("librfm.dylib not found — parity needs the extension present")


def open_py(path):
    db = sqlite3.connect(path)
    rfm.register(db)
    return db


def run_ops(db):
    """The scripted history, identical for both implementations."""
    def at(t):
        db.execute("SELECT rfm_config('now', ?)", (t,))

    def access(mid, t):
        at(t)
        db.execute("SELECT rfm_record_access(?)", (mid,))

    def outcome(mid, o, t):
        at(t)
        db.execute("SELECT rfm_record_outcome(?, ?)", (mid, o))

    db.execute("SELECT rfm_init()")
    at(T0)
    ins = "INSERT INTO rfm_memories(id, content, created_at) VALUES(?, ?, ?)"
    for mid, created in [(1, T0 - 30 * DAY), (2, T0 - 10 * DAY),
                         (3, T0 - 20 * DAY), (4, T0 - 25 * DAY),
                         (5, T0 - 25 * DAY), (6, T0 - 5 * DAY),
                         (7, T0 - 1 * DAY), (10, T0 - 15 * DAY),
                         (11, T0 - 400 * DAY), (12, T0 - 400 * DAY)]:
        db.execute(ins, (mid, f"mem {mid}", created))
    # Host-written boundary rows (bulk import / another client):
    db.execute("INSERT INTO rfm_memories(id, content, created_at, access_count)"
               " VALUES(8, 'imported, no times', ?, 7)", (T0 - 40 * DAY,))
    db.execute("INSERT INTO rfm_memories(id, content, created_at, value_score)"
               " VALUES(9, 'value without outcomes', ?, 0.6)", (T0 - 3 * DAY,))

    access(2, T0 - 3_600)                            # n = 1
    access(3, T0 - 10 * DAY); access(3, T0 - 300)    # n = 2
    for i in range(10):                              # n = 10 spread
        access(4, T0 - 20 * DAY + i * 2 * DAY)
    for i in range(8):                               # burst then quiet
        access(5, T0 - 24 * DAY + i * 3_600)
    for _ in range(5):                               # t1 == t2, degenerate tail
        access(6, T0 - 2 * DAY)
    access(7, T0 - 1e-6)                             # sub-EPS lag
    for i, o in enumerate([1.0, -1.0, 1.0, 1.0, -1.0]):   # EWMA sequence
        t = T0 - 12 * DAY + i * DAY
        access(10, t); outcome(10, o, t + 60)
    access(11, T0 - 300 * DAY); outcome(11, -1.0, T0 - 300 * DAY + 60)
    access(12, T0 - 300 * DAY); outcome(12, 1.0, T0 - 300 * DAY + 60)
    db.commit()


def read_all(db, theta_s=None, decay=None, beta=None):
    """Every read surface at frozen now = T0, under optional config."""
    db.execute("SELECT rfm_config('now', ?)", (T0,))
    for key, v in (("theta", theta_s and theta_s[0]), ("s", theta_s and theta_s[1]),
                   ("decay", decay), ("beta", beta)):
        if v is not None:
            db.execute("SELECT rfm_config(?, ?)", (key, v))
    out = {}
    ids = [r[0] for r in db.execute("SELECT id FROM rfm_memories ORDER BY id")]
    for i in ids:
        for fn, sql in [
            ("activation", f"SELECT rfm_activation({i})"),
            ("recency", f"SELECT rfm_recency({i})"),
            ("frequency", f"SELECT rfm_frequency({i})"),
            ("value", f"SELECT rfm_value({i})"),
            ("score", f"SELECT rfm_score({i})"),
            ("prior", f"SELECT rfm_prior({i})"),
            ("prunable30", f"SELECT rfm_prunable({i}, 30)"),
            ("prunable500", f"SELECT rfm_prunable({i}, 500)"),
            ("score_w3", f"SELECT rfm_score_w({i}, 0.5, 0.5)"),
            ("score_w4", f"SELECT rfm_score_w({i}, 0.5, 0.5, 0.7)"),
            ("prior_of", "SELECT rfm_prior_of(access_count, created_at, "
                         f"last_access, bla_cache, value_score, outcome_count)"
                         f" FROM rfm_memories WHERE id = {i}"),
        ]:
            out[(i, fn)] = db.execute(sql).fetchone()[0]
    # restore defaults for the next sweep
    for key, v in (("theta", 0.0), ("s", 1.0), ("decay", 0.5), ("beta", 0.3)):
        db.execute("SELECT rfm_config(?, ?)", (key, v))
    return out


def dump_state(db):
    return (db.execute("SELECT * FROM rfm_memories ORDER BY id").fetchall(),
            db.execute("SELECT * FROM rfm_accesses ORDER BY rowid").fetchall())


def expect_error(db, sql, label, failures):
    try:
        db.execute(sql)
        failures.append(f"{label}: expected an error, got success")
    except sqlite3.Error:
        pass


def main():
    ext_path, py_path = "/tmp/rfm_parity_ext.db", "/tmp/rfm_parity_py.db"
    for p in (ext_path, py_path):
        if os.path.exists(p):
            os.remove(p)
    ext, py = open_ext(ext_path), open_py(py_path)

    run_ops(ext)
    run_ops(py)

    failures, max_diff = [], 0.0

    s_ext, s_py = dump_state(ext), dump_state(py)
    if s_ext != s_py:
        for name, a, b in (("rfm_memories", s_ext[0], s_py[0]),
                           ("rfm_accesses", s_ext[1], s_py[1])):
            for ra, rb in zip(a, b):
                if ra != rb:
                    diffs = [abs(x - y) for x, y in zip(ra, rb)
                             if isinstance(x, float) and isinstance(y, float)]
                    if not diffs or max(diffs) > 1e-9:
                        failures.append(f"{name} state drift: {ra} vs {rb}")
                    else:
                        max_diff = max(max_diff, max(diffs))

    sweeps = [dict(), dict(decay=0.3), dict(beta=1.0),
              dict(theta_s=(-2.0, 0.5)), dict(decay=0.7, beta=0.0)]
    for cfgkw in sweeps:
        a, b = read_all(ext, **cfgkw), read_all(py, **cfgkw)
        for key in a:
            d = abs(a[key] - b[key])
            max_diff = max(max_diff, d)
            if d > TOL or math.isnan(d):
                failures.append(f"{cfgkw or 'defaults'} {key}: "
                                f"ext={a[key]!r} py={b[key]!r}")
        rank_a = sorted(range(1, 13), key=lambda i: -a[(i, "prior")])
        rank_b = sorted(range(1, 13), key=lambda i: -b[(i, "prior")])
        if rank_a != rank_b:
            failures.append(f"{cfgkw or 'defaults'}: ranking differs "
                            f"{rank_a} vs {rank_b}")

    # Error-path parity: both must refuse, whatever the message channel.
    for db in (ext, py):
        expect_error(db, "SELECT rfm_record_outcome(10, 0.5)",
                     "second outcome without access", failures)
        expect_error(db, "SELECT rfm_record_access(999)", "bad id", failures)
        expect_error(db, "SELECT rfm_record_outcome(1, 0.5)",
                     "outcome before any access", failures)
        expect_error(db, "SELECT rfm_record_outcome(10, 1.5)",
                     "outcome out of range", failures)
        expect_error(db, "SELECT rfm_config('decay', 1.5)",
                     "decay out of range", failures)
        expect_error(db, "SELECT rfm_record_access(1.9)",
                     "non-integer id", failures)

    print(f"max |ext - py| across state + {len(sweeps)} config sweeps: "
          f"{max_diff:.3e}")
    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for f in failures[:20]:
            print(" -", f)
        sys.exit(1)
    print("parity: rankings identical, all error paths refuse on both")


if __name__ == "__main__":
    main()
