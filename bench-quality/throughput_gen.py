#!/usr/bin/env python3
"""Generate a synthetic rfm database for the scoring benchmark.

Usage: gen.py OUT.db N_MEMORIES ACCESSES_PER_MEMORY

Writes rfm_memories + rfm_accesses with summary columns exactly as
rfm_record_access/rfm_record_outcome would have maintained them, so
rfm_score(id) sees realistic state without replaying millions of calls.
Deterministic (fixed seed).
"""
import random
import sqlite3
import sys

NOW = 1_800_000_000.0  # frozen "now" used by bench.sh via rfm_config('now', ...)
SPAN = 90 * 86_400.0   # accesses spread over the last 90 days
LAMBDA = 0.3

def main() -> None:
    out, n_mem, n_acc = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    rng = random.Random(42)
    db = sqlite3.connect(out)
    db.executescript(open(f"{sys.path[0]}/../rfm_schema.sql").read())
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=OFF")

    mem_rows, acc_rows = [], []
    for mid in range(1, n_mem + 1):
        created = NOW - SPAN - rng.random() * 30 * 86_400.0
        times = sorted(created + rng.random() * (NOW - created) for _ in range(n_acc))
        value, n_out = 0.0, 0
        for t in times:
            outcome = None
            if rng.random() < 0.5:  # half the accesses get outcome feedback
                # Mirrors math.rs ewma_update (first outcome initializes) and
                # the default lambda; kept in the log so an offline replay of
                # rfm_accesses reproduces value_score/outcome_count exactly.
                outcome = rng.choice([1.0, 1.0, -1.0])
                value = outcome if n_out == 0 else LAMBDA * outcome + (1 - LAMBDA) * value
                n_out += 1
            acc_rows.append((mid, t, outcome))
        mem_rows.append((mid, f"memory {mid}", created, len(times),
                         times[-1], times[-2] if len(times) > 1 else None, value, n_out))
        if len(acc_rows) >= 500_000:
            db.executemany(
                "INSERT INTO rfm_accesses(memory_id, accessed_at, outcome) VALUES(?,?,?)", acc_rows)
            acc_rows.clear()
    db.executemany(
        "INSERT INTO rfm_memories(id, content, created_at, access_count, last_access,"
        " bla_cache, value_score, outcome_count) VALUES(?,?,?,?,?,?,?,?)", mem_rows)
    if acc_rows:
        db.executemany(
            "INSERT INTO rfm_accesses(memory_id, accessed_at, outcome) VALUES(?,?,?)", acc_rows)
    db.commit()
    db.close()
    print(f"{out}: {n_mem} memories x {n_acc} accesses")

if __name__ == "__main__":
    main()
