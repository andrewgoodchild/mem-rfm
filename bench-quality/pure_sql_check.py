#!/usr/bin/env python3
"""Is rfm_prior reproducible in plain SQL, exactly?

If it is, the extension becomes an optimization rather than a dependency:
the scoring runs on hosted SQLite, on a Python build without
enable_load_extension, and anywhere else loadable extensions are banned. That
is a bigger claim than a speedup, so it is checked the way everything else
here is -- against the shipped code, over the states that actually occur,
including the ones that only occur at the boundaries.

The expression below is a transcription of math.rs (bla_hybrid_k2, logistic_p,
shrink, value01, score_p) and functions.rs (activation_of, score_of_cfg).

Usage: pure_sql_check.py [--rows 2000]
"""
import argparse
import math
import os
import random
import sqlite3
import sys

import common

# Defaults from src/config.rs. The SQL is generated against explicit
# constants so a config change cannot silently desynchronise the two.
D, W_A, W_V, SHRINK_K, BETA, THETA, S, EPS = 0.5, 0.7, 0.3, 3.0, 0.3, 0.0, 1.0, 1e-3


def prior_sql(now, d=D, w_a=W_A, w_v=W_V, k=SHRINK_K, beta=BETA,
              theta=THETA, s=S):
    """Pure-SQL rfm_prior(id). Layered subqueries rather than one expression,
    because the hybrid activation branches five ways and a single flattened
    CASE would be unreviewable."""
    return f"""
SELECT id, ({1.0 - beta} + {beta} * ({w_a} / (1.0 + exp(-(B - {theta}) / {s}))
       + {w_v} * max(0.0, min(1.0, (v_eff + 1.0) / 2.0)))) AS prior FROM (
  SELECT id, v_eff, CASE
    WHEN n <= 0            THEN {-d} * ln(L)
    WHEN t1 IS NULL        THEN ln(n / {1.0 - d}) - {d} * ln(L)
    WHEN n =  1            THEN {-d} * ln(t1)
    WHEN t2 IS NULL        THEN ln(n / {1.0 - d}) - {d} * ln(L)
    WHEN n =  2            THEN ln(pow(t1, {-d}) + pow(t2, {-d}))
    WHEN L2 - t2 < {EPS}   THEN ln(pow(t1, {-d}) + pow(t2, {-d})
                                   + (n - 2) * pow(t2, {-d}))
    ELSE ln(pow(t1, {-d}) + pow(t2, {-d}) + (n - 2)
            * (pow(L2, {1.0 - d}) - pow(t2, {1.0 - d}))
            / ({1.0 - d} * (L2 - t2)))
  END AS B FROM (
    SELECT id, n, L, t1, t2, max(L, t2) AS L2,
           CASE WHEN n_out + {k} <= 0 THEN 0.0
                ELSE v * n_out / (n_out + {k}) END AS v_eff FROM (
      SELECT id, access_count AS n, value_score AS v,
             max(outcome_count, 0) AS n_out,
             max({now} - created_at, {EPS}) AS L,
             CASE WHEN last_access IS NULL THEN NULL
                  ELSE max({now} - last_access, {EPS}) END AS t1,
             CASE WHEN bla_cache IS NULL OR last_access IS NULL THEN NULL
                  ELSE max({now} - bla_cache,
                           max({now} - last_access, {EPS})) END AS t2
      FROM rfm_memories)))
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=2000)
    args = ap.parse_args()

    db = sqlite3.connect(":memory:")
    db.enable_load_extension(True)
    db.load_extension(common.resolve_dylib())
    db.enable_load_extension(False)
    db.execute("SELECT rfm_init()")

    now = 1_800_000_000.0
    rnd = random.Random(11)
    rows = []
    # Hand-picked boundary states first: every branch of the hybrid, plus the
    # states a bulk import or a host-modified row can leave behind.
    edge = [
        (0, None, None, 0.0, 0),          # never accessed
        (1, 5.0, None, 0.0, 0),           # exactly one access
        (2, 5.0, 50.0, 0.0, 0),           # exactly two: head only, no tail
        (5, 5.0, 50.0, 0.0, 0),           # tail integral
        (5, None, None, 0.0, 0),          # summary state, no times (import)
        (5, 5.0, None, 0.0, 0),           # t1 but no t2
        (7, 1e-4, 2e-4, 0.0, 0),          # sub-EPS lags, both clamped
        (4, 100.0, 100.0, 0.0, 0),        # t1 == t2
        (9, 10.0, 10.0 + 1e-6, 0.0, 0),   # degenerate tail window L2-t2 < EPS
        (3, 5.0, 50.0, 1.0, 1),           # value at +1
        (3, 5.0, 50.0, -1.0, 12),         # value at -1, many outcomes
        (3, 5.0, 50.0, 0.5, 0),           # value set but zero outcomes
    ]
    for n, a1, a2, v, no in edge:
        rows.append((n, None if a1 is None else now - a1,
                     None if a2 is None else now - a2, v, no))
    for _ in range(args.rows - len(rows)):
        n = rnd.choice([0, 1, 2, 3, rnd.randint(4, 400)])
        a1 = rnd.choice([None, rnd.uniform(1e-4, 3e7)])
        a2 = None if a1 is None else rnd.choice([None, a1 + rnd.uniform(0, 3e7)])
        rows.append((n, None if a1 is None else now - a1,
                     None if a2 is None else now - a2,
                     rnd.uniform(-1, 1), rnd.choice([0, 1, 2, 5, 40])))

    for i, (n, la, bc, v, no) in enumerate(rows, start=1):
        db.execute(
            "INSERT INTO rfm_memories(id, content, created_at, access_count,"
            " last_access, bla_cache, value_score, outcome_count)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (i, f"m{i}", now - 4e7, n, la, bc, v, no))
    db.commit()
    db.execute("SELECT rfm_config('now', ?)", (now,))

    ext = dict(db.execute("SELECT id, rfm_prior(id) FROM rfm_memories"))
    pure = dict(db.execute(prior_sql(now)))

    worst, worst_id, mismatches = 0.0, None, 0
    for i in ext:
        a, b = ext[i], pure[i]
        if a is None or b is None or math.isnan(a) or math.isnan(b):
            mismatches += 1
            continue
        d = abs(a - b)
        if d > worst:
            worst, worst_id = d, i
        if d > 1e-12:
            mismatches += 1

    print(f"rows compared          : {len(ext)}")
    print(f"rows differing > 1e-12 : {mismatches}")
    print(f"max abs difference     : {worst:.3e}  (id {worst_id})")

    # Ranking is what actually ships, so check the decision, not just the number.
    o_ext = [i for i, _ in sorted(ext.items(), key=lambda kv: (-kv[1], kv[0]))]
    o_pure = [i for i, _ in sorted(pure.items(), key=lambda kv: (-kv[1], kv[0]))]
    print(f"full ranking identical : {o_ext == o_pure}")
    print("VERDICT:", "EXACT" if mismatches == 0 and o_ext == o_pure
          else "DIVERGES")
    return 0 if mismatches == 0 and o_ext == o_pure else 1


if __name__ == "__main__":
    sys.exit(main())
