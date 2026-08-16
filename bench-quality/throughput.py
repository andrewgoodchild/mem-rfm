#!/usr/bin/env python3
"""Scoring-throughput benchmark: rfm_score(id) (Petrov k=2 from one summary
row) vs exact ACT-R recompute scanning rfm_accesses. Also reports max
activation approximation error.

Replaces throughput.sh, which drove a .load-capable sqlite3 CLI against the
retired Rust extension (preserved at the `rust-extension` tag). Same
databases (throughput_gen.py), same frozen clock, same measurements, now
through rfm.py — so the published numbers are numbers the shipped engine
produces.

Usage: throughput.py [--sizes 10000,100000] [--accesses 20]
"""
import argparse
import os
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import rfm  # noqa: E402

NOW = 1_800_000_000.0


def bench(n, accesses):
    path = os.path.join(HERE, f"bench_{n}_{accesses}.db")
    if not os.path.exists(path):
        subprocess.run([sys.executable, os.path.join(HERE, "throughput_gen.py"),
                        path, str(n), str(accesses)],
                       check=True, capture_output=True)
    db = sqlite3.connect(path)
    rfm.register(db)
    db.execute("SELECT rfm_config('now', ?)", (NOW,))

    t = time.perf_counter()
    db.execute("SELECT sum(rfm_score(id)) FROM rfm_memories").fetchone()
    t_score = time.perf_counter() - t

    exact = (f"SELECT memory_id, ln(sum(pow(max({NOW} - accessed_at, 0.001),"
             " -0.5))) AS b FROM rfm_accesses GROUP BY memory_id")
    t = time.perf_counter()
    db.execute(f"SELECT sum(b) FROM ({exact})").fetchone()
    t_exact = time.perf_counter() - t

    err = db.execute(
        f"SELECT max(abs(rfm_activation(m.id) - e.b)) FROM rfm_memories m "
        f"JOIN ({exact}) e ON e.memory_id = m.id").fetchone()[0]
    db.close()
    return t_score, t_exact, err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="10000,100000")
    ap.add_argument("--accesses", type=int, default=20)
    args = ap.parse_args()

    print("| rows | accesses/row | rfm_score (s) | exact recompute (s) "
          "| us/row | max abs err |")
    print("|---|---|---|---|---|---|")
    for n in (int(s) for s in args.sizes.split(",")):
        t_score, t_exact, err = bench(n, args.accesses)
        print(f"| {n} | {args.accesses} | {t_score:.3f} | {t_exact:.3f} "
              f"| {t_score / n * 1e6:.2f} | {err:.3g} |")


if __name__ == "__main__":
    main()
