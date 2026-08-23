#!/usr/bin/env python3
"""Unit + contract tests for rfm.py, ported from the retired Rust extension's
math.rs #[cfg(test)] suite and tests/integration.rs (preserved at the
`rust-extension` tag). Same structure: math properties first, then the full
SQL surface driven through a connection with a frozen clock.

Run: python3 tests/test_rfm.py  (stdlib only; prints PASS/FAIL per group)
"""
import math
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import rfm  # noqa: E402

D = 0.5
FAILED = []


def check(name, cond, detail=""):
    if not cond:
        FAILED.append(name)
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


def close(name, a, b, tol=1e-12):
    check(name, abs(a - b) <= tol, f"{a!r} vs {b!r}")


def state(times, created, now):
    lags = sorted(now - t for t in times)
    return (lags, lags[0] if lags else None,
            lags[1] if len(lags) > 1 else None, now - created)


# ---------------------------------------------------------------- math.rs port

def test_math():
    now = 1_000_000.0
    for times in ([999_000.0], [990_000.0, 999_500.0]):
        lags, t1, t2, l = state(times, 900_000.0, now)
        close("n<=2 exact", rfm.bla_hybrid_k2(len(times), t1, t2, l, D),
              rfm.bla_exact(lags, D))

    b = rfm.bla_hybrid_k2(0, None, None, 86_400.0, D)
    close("never-accessed uses creation age", b, -D * math.log(86_400.0))
    check("older never-accessed decays lower",
          rfm.bla_hybrid_k2(0, None, None, 10 * 86_400.0, D) < b)

    def hybrid_err(times, created, now):
        lags, t1, t2, l = state(times, created, now)
        exact = rfm.bla_exact(lags, D)
        return (abs(rfm.bla_hybrid_k2(len(times), t1, t2, l, D) - exact),
                abs(rfm.bla_optimized(len(times), l, D) - exact))

    err, _ = hybrid_err([10_000.0 + i * 17_000.0 for i in range(50)], 0.0, 864_000.0)
    check("uniform-history error small", err < 0.05, f"{err}")

    times = [1_000.0 + i * 2_000.0 for i in range(20)] + [863_000.0, 863_500.0, 863_900.0]
    err_k2, err_k0 = hybrid_err(times, 0.0, 864_000.0)
    check("recent-burst hybrid beats k=0", err_k2 < err_k0)
    check("burst error bounded", err_k2 < 0.35, f"{err_k2}")

    times = [5_000.0 + i * 300.0 for i in range(30)]
    err_k2, err_k0 = hybrid_err(times, 0.0, 864_000.0)
    check("quiescent bounded", err_k2 <= err_k0 + 1e-9 and err_k2 < 0.35)

    lags, t1, t2, l = state([999_000.0] * 10, 999_000.0, 1_000_000.0)
    close("same-instant degenerate tail", rfm.bla_hybrid_k2(10, t1, t2, l, D),
          rfm.bla_exact(lags, D), tol=1e-9)

    v1 = rfm.ewma_update(0.0, 0, 1.0, 0.3)
    check("first outcome initializes directly", v1 == 1.0)
    close("ewma stays", rfm.ewma_update(v1, 1, 1.0, 0.3), 1.0)
    close("ewma moves", rfm.ewma_update(1.0, 2, -1.0, 0.3), 0.4)

    check("no outcomes -> no value", rfm.shrink(1.0, 0, 3.0) == 0.0)
    close("half confidence at n=k", rfm.shrink(1.0, 3, 3.0), 0.5)
    check("confidence approaches 1", rfm.shrink(1.0, 100, 3.0) > 0.97)
    check("k=0 disables shrinking", rfm.shrink(0.8, 5, 0.0) == 0.8)

    check("logistic(-inf)=0", rfm.logistic_p(float("-inf"), 0.0, 1.0) == 0.0)
    close("logistic(0)=0.5", rfm.logistic_p(0.0, 0.0, 1.0), 0.5)
    check("value01 clamps", rfm.value01(-1.5) == 0.0 and rfm.value01(1.5) == 1.0)
    close("score blend", rfm.score_p(0.0, 0.0, 0.7, 0.3, 0.0, 1.0),
          0.7 * 0.5 + 0.3 * 0.5)


# ------------------------------------------------- integration.rs port (SQL)

def test_sql_surface():
    db = sqlite3.connect(":memory:")
    rfm.register(db)
    q = lambda sql, *p: db.execute(sql, p).fetchone()[0]

    check("init", q("SELECT rfm_init()") == "ok")
    check("init idempotent", q("SELECT rfm_init()") == "ok")
    db.execute("SELECT rfm_config('now', 1000000.0)")
    db.execute("INSERT INTO rfm_memories(id, content, created_at) "
               "VALUES (1, 'a', 900000.0), (2, 'b', 900000.0)")

    close("first access activation", q("SELECT rfm_record_access(1)"),
          rfm.bla_hybrid_k2(1, 0.0, None, 100_000.0, 0.5))
    close("outcome returns value", q("SELECT rfm_record_outcome(1, 1.0)"), 1.0)

    db.execute("SELECT rfm_config('now', 1005000.0)")
    db.execute("SELECT rfm_record_access(1)")
    close("recency", q("SELECT rfm_recency(1)"), math.exp(0.0 / 86_400.0))
    close("frequency n=2", q("SELECT rfm_frequency(1)"), math.log(3.0))
    close("frequency n=0", q("SELECT rfm_frequency(2)"), 0.0)

    act1 = rfm.bla_hybrid_k2(2, 0.0, 5_000.0, 105_000.0, 0.5)
    close("activation", q("SELECT rfm_activation(1)"), act1)
    close("value", q("SELECT rfm_value(1)"), 1.0)
    v_eff = rfm.shrink(1.0, 1, 3.0)
    score1 = rfm.score_p(act1, v_eff, 0.7, 0.3, 0.0, 1.0)
    close("score", q("SELECT rfm_score(1)"), score1)
    close("score_w3", q("SELECT rfm_score_w(1, 1.0, 0.0)"),
          rfm.score_p(act1, v_eff, 1.0, 0.0, 0.0, 1.0))
    act1_d03 = rfm.bla_hybrid_k2(2, 0.0, 5_000.0, 105_000.0, 0.3)
    close("score_w4 decay", q("SELECT rfm_score_w(1, 0.5, 0.5, 0.3)"),
          rfm.score_p(act1_d03, v_eff, 0.5, 0.5, 0.0, 1.0))
    check("version", q("SELECT rfm_version()") == rfm.VERSION)
    close("prior", q("SELECT rfm_prior(1)"), 0.7 + 0.3 * score1)
    close("prior_of matches prior",
          q("SELECT rfm_prior_of(access_count, created_at, last_access, "
            "bla_cache, value_score, outcome_count) FROM rfm_memories WHERE id=1"),
          q("SELECT rfm_prior(1)"), tol=0.0)

    close("config set", q("SELECT rfm_config('tau', 3600.0)"), 3600.0)
    close("config get", q("SELECT rfm_config('tau')"), 3600.0)
    check("unfreeze clears", q("SELECT rfm_config('now', NULL)") is None)

    row = db.execute("SELECT access_count, last_access, bla_cache, value_score,"
                     " outcome_count FROM rfm_memories WHERE id = 1").fetchone()
    check("summary state", row == (2, 1005000.0, 1000000.0, 1.0, 1), f"{row}")
    db.execute("SELECT rfm_config('now', 1005000.0)")

    # Guards. The second access above re-arms the outcome slot, so take it
    # legitimately first; the repeat must then be refused.
    close("re-armed outcome accepted", q("SELECT rfm_record_outcome(1, 1.0)"), 1.0)

    def refuses(name, sql):
        try:
            db.execute(sql)
            check(name, False, "no error raised")
        except sqlite3.Error:
            pass
    refuses("second outcome refused", "SELECT rfm_record_outcome(1, 0.5)")
    refuses("outcome before access", "SELECT rfm_record_outcome(2, 0.5)")
    refuses("outcome out of range", "SELECT rfm_record_outcome(1, 1.5)")
    refuses("bad id", "SELECT rfm_record_access(99)")
    refuses("non-integer id", "SELECT rfm_record_access(1.9)")
    refuses("bad config key", "SELECT rfm_config('nope')")
    refuses("decay out of range", "SELECT rfm_config('decay', 1.0)")

    # Prunable: positive outcome record is never prunable, however idle.
    db.execute("SELECT rfm_config('now', 1005000.0)")
    check("idle+negative prunable",
          q("SELECT rfm_prunable(2, 0)") == 1)  # id 2: never accessed, old
    check("proved-useful never prunable",
          q("SELECT rfm_prunable(1, 0)") == 0)


def test_regressions():
    """Ports of integration.rs regression tests that had no equivalent here,
    plus pins for validation gaps found after the port."""
    # epoch_zero_timestamps_keep_t2_and_stay_consistent: bla_cache's old 0.0
    # sentinel dropped a legitimate second access at wall time <= 0, and
    # rfm_record_access's return diverged from what rfm_activation read back.
    db = sqlite3.connect(":memory:")
    rfm.register(db)
    q = lambda sql, *p: db.execute(sql, p).fetchone()[0]
    q("SELECT rfm_init()")
    db.execute("SELECT rfm_config('now', 0.0)")
    db.execute("INSERT INTO rfm_memories(id, content, created_at) "
               "VALUES (1, 'x', -100.0)")
    db.execute("SELECT rfm_record_access(1)")
    db.execute("SELECT rfm_config('now', 100.0)")
    returned = q("SELECT rfm_record_access(1)")
    expected = rfm.bla_hybrid_k2(2, 0.0, 100.0, 200.0, D)
    close("epoch-0 returned activation", returned, expected)
    close("epoch-0 reread activation", q("SELECT rfm_activation(1)"), expected)
    check("epoch-0 access survives as t2",
          q("SELECT bla_cache FROM rfm_memories WHERE id = 1") == 0.0)

    # prunable_respects_idle_window_and_proven_value (wide-window branch and
    # the negative-days error path were unported).
    db = sqlite3.connect(":memory:")
    rfm.register(db)
    q = lambda sql, *p: db.execute(sql, p).fetchone()[0]
    q("SELECT rfm_init()")
    db.execute("SELECT rfm_config('now', 0.0)")
    db.execute("INSERT INTO rfm_memories(id, content, created_at) VALUES "
               "(1, 'idle useless', 0.0), (2, 'idle useful', 0.0), "
               "(3, 'fresh', 0.0)")
    db.execute("SELECT rfm_record_access(1)")
    db.execute("SELECT rfm_record_outcome(1, -1.0)")
    db.execute("SELECT rfm_record_access(2)")
    db.execute("SELECT rfm_record_outcome(2, 1.0)")
    db.execute("SELECT rfm_config('now', 3456000.0)")  # 40 days later
    db.execute("SELECT rfm_record_access(3)")
    check("idle and never useful -> prunable", q("SELECT rfm_prunable(1, 30)") == 1)
    check("proven useful never prunable", q("SELECT rfm_prunable(2, 30)") == 0)
    check("recent access keeps it alive", q("SELECT rfm_prunable(3, 30)") == 0)
    check("still inside a wider window", q("SELECT rfm_prunable(1, 90)") == 0)

    def refuses(name, sql):
        try:
            db.execute(sql)
            check(name, False, "no error raised")
        except sqlite3.Error:
            pass
    refuses("negative window refused", "SELECT rfm_prunable(1, -1)")
    refuses("non-finite window refused", "SELECT rfm_prunable(1, 1e400)")
    refuses("NULL window refused", "SELECT rfm_prunable(1, NULL)")
    refuses("explicit NULL decay refused", "SELECT rfm_score_w(1, 0.5, 0.5, NULL)")


def test_meta_and_compact():
    """The lambda path-dependence guard and access-log compaction (v0.3.0)."""
    db = sqlite3.connect(":memory:")
    rfm.register(db)
    q = lambda sql, *p: db.execute(sql, p).fetchone()[0]
    q("SELECT rfm_init()")
    db.execute("SELECT rfm_config('now', 1000.0)")
    check("init writes no stamp (DDL-only; a DML write would leave the "
          "implicit transaction open under the invoking SELECT)",
          q("SELECT count(*) FROM rfm_meta") == 0)

    db.execute("INSERT INTO rfm_memories(id, content, created_at) "
               "VALUES (1, 'a', 0.0), (2, 'b', 0.0)")
    db.execute("SELECT rfm_record_access(1)")
    close("outcome under stamped lambda", q("SELECT rfm_record_outcome(1, 1.0)"), 1.0)
    close("first outcome stamps the ledger's lambda",
          q("SELECT value FROM rfm_meta WHERE key = 'lambda'"), 0.3)

    # A mismatched lambda is refused BEFORE any row is touched...
    db.execute("SELECT rfm_record_access(1)")
    db.execute("SELECT rfm_config('lambda', 0.1)")
    try:
        db.execute("SELECT rfm_record_outcome(1, 0.5)")
        check("mismatched lambda refused", False, "no error raised")
    except sqlite3.Error:
        pass
    # ...so restoring the stamped lambda lets the SAME access take its outcome.
    db.execute("SELECT rfm_config('lambda', 0.3)")
    close("restored lambda accepted on the same access",
          q("SELECT rfm_record_outcome(1, 0.5)"),
          rfm.ewma_update(1.0, 1, 0.5, 0.3))

    # Compaction: resolved history goes, the latest row (the outcome slot)
    # and the score stay.
    db.execute("SELECT rfm_config('now', 2000.0)")
    db.execute("SELECT rfm_record_access(1)")
    db.execute("SELECT rfm_record_outcome(1, 1.0)")
    db.execute("SELECT rfm_config('now', 3000.0)")
    db.execute("SELECT rfm_record_access(1)")
    score_before = q("SELECT rfm_score(1)")
    n_before = q("SELECT count(*) FROM rfm_accesses WHERE memory_id = 1")
    deleted = q("SELECT rfm_compact(1e9)")
    check("compact drops resolved non-latest rows", deleted == n_before - 1,
          f"deleted {deleted} of {n_before}")
    close("compaction never changes a score", q("SELECT rfm_score(1)"),
          score_before, tol=0.0)
    v_prev = q("SELECT value_score FROM rfm_memories WHERE id = 1")
    n_prev = q("SELECT outcome_count FROM rfm_memories WHERE id = 1")
    close("the outcome slot survives compaction",
          q("SELECT rfm_record_outcome(1, -1.0)"),
          rfm.ewma_update(v_prev, n_prev, -1.0, 0.3))

    # A lone resolved row IS the latest row: compact must keep it.
    db.execute("SELECT rfm_record_access(2)")
    db.execute("SELECT rfm_record_outcome(2, 1.0)")
    check("latest row survives even when resolved",
          q("SELECT rfm_compact(1e9)") == 0)

    def refuses(name, sql):
        try:
            db.execute(sql)
            check(name, False, "no error raised")
        except sqlite3.Error:
            pass
    refuses("compact NULL refused", "SELECT rfm_compact(NULL)")
    refuses("compact non-finite refused", "SELECT rfm_compact(1e400)")

    # Legacy DB with no rfm_meta at all: outcomes still work, no guard.
    db2 = sqlite3.connect(":memory:")
    rfm.register(db2)
    db2.execute("SELECT rfm_init()")
    db2.execute("DROP TABLE rfm_meta")
    db2.execute("SELECT rfm_config('now', 1000.0)")
    db2.execute("INSERT INTO rfm_memories(id, content, created_at) "
                "VALUES (1, 'x', 0.0)")
    db2.execute("SELECT rfm_record_access(1)")
    close("legacy DB without rfm_meta still records outcomes",
          db2.execute("SELECT rfm_record_outcome(1, 1.0)").fetchone()[0], 1.0)


def test_schema_files_agree():
    """rfm.py's inline schema and the standalone rfm_schema.sql must create
    identical structures — same pinning discipline as pure_sql_check.
    Compared via table_info/index_list, not sqlite_master text, because the
    .sql file carries comments that sqlite_master preserves verbatim."""
    a, b = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
    rfm.register(a)
    a.execute("SELECT rfm_init()")
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    b.executescript(open(os.path.join(root, "rfm_schema.sql")).read())

    def dump(c):
        tables = sorted(t for (t,) in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"))
        out = {t: c.execute(f"PRAGMA table_info({t})").fetchall() for t in tables}
        out["__indexes__"] = sorted(
            (n, c.execute(f"PRAGMA index_info({n})").fetchall())
            for (n,) in c.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND sql IS NOT NULL"))
        return out

    check("inline schema == rfm_schema.sql", dump(a) == dump(b),
          "schemas drifted")


if __name__ == "__main__":
    for fn in (test_math, test_sql_surface, test_regressions,
               test_meta_and_compact, test_schema_files_agree):
        fn()
    if FAILED:
        print(f"\n{len(FAILED)} FAILURE(S)")
        sys.exit(1)
    print("all rfm.py tests passed")
