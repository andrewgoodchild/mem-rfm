#!/usr/bin/env python3
"""Toy agent-memory loop demonstrating rfm_score ranking dynamics.

Seeds 50 memories, simulates 200 retrievals with mixed outcome feedback over
30 simulated days, and prints the top-5 ranking before and after: memories
that keep getting used *and keep helping* rise; stale or unhelpful ones decay.

Python stdlib only — rfm.py registers the scoring functions on any sqlite3
connection, so there is nothing to build or .load.
"""
import os
import random
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import rfm  # noqa: E402

T0 = 1_800_000_000.0
DAY = 86_400.0

def build_script() -> str:
    """One SQL script for the whole simulation (deterministic)."""
    rng = random.Random(7)
    lines = [
        "SELECT rfm_init();",
        f"SELECT rfm_config('now', {T0});",
    ]
    # 50 memories created over the preceding week. A handful are genuinely
    # useful (their retrieval tends to help), most are neutral or noise.
    useful = {3, 7, 12, 19, 41}      # frequently retrieved AND helpful
    stale = {1, 2, 4, 5, 6}          # popular early, then never again
    for mid in range(1, 51):
        created = T0 - 7 * DAY + rng.random() * 6 * DAY
        lines.append(
            "INSERT INTO rfm_memories(id, content, created_at) "
            f"VALUES ({mid}, 'memory #{mid}', {created});"
        )
    # Warm-up: the stale set gets early buzz.
    t = T0
    for _ in range(40):
        t += rng.random() * 0.2 * DAY
        mid = rng.choice(sorted(stale))
        lines.append(f"SELECT rfm_config('now', {t});")
        lines.append(f"SELECT rfm_record_access({mid});")
        lines.append(f"SELECT rfm_record_outcome({mid}, {rng.choice([1.0, -1.0])});")

    lines.append("SELECT '--- top-5 after early buzz (day ~8) ---';")
    lines.append(
        "SELECT printf('%2d  %-12s score=%.4f', id, content, rfm_score(id)) "
        "FROM rfm_memories ORDER BY rfm_score(id) DESC LIMIT 5;"
    )

    # Main loop: 200 retrievals over ~30 days. Useful memories are retrieved
    # often and mostly help (+1); everything else is occasional and mixed.
    for _ in range(200):
        t += rng.random() * 0.15 * DAY
        if rng.random() < 0.55:
            mid = rng.choice(sorted(useful))
            outcome = 1.0 if rng.random() < 0.85 else -1.0
        else:
            mid = rng.randint(1, 50)
            outcome = rng.choice([1.0, -1.0])
        lines.append(f"SELECT rfm_config('now', {t});")
        lines.append(f"SELECT rfm_record_access({mid});")
        if rng.random() < 0.7:  # not every retrieval gets feedback
            lines.append(f"SELECT rfm_record_outcome({mid}, {outcome});")

    lines.append(f"SELECT rfm_config('now', {t});")
    lines.append("SELECT '--- top-5 after 200 retrievals with feedback (day ~38) ---';")
    lines.append(
        "SELECT printf('%2d  %-12s score=%.4f  R=%.3f F=%.2f V=%+.2f', id, content, "
        "rfm_score(id), rfm_recency(id), rfm_frequency(id), rfm_value(id)) "
        "FROM rfm_memories ORDER BY rfm_score(id) DESC LIMIT 5;"
    )
    lines.append("SELECT '--- where the early-buzz memories ended up ---';")
    lines.append(
        "SELECT printf('%2d  %-12s score=%.4f (rank %d)', id, content, rfm_score(id), "
        "(SELECT count(*) FROM rfm_memories m2 WHERE rfm_score(m2.id) > rfm_score(rfm_memories.id)) + 1) "
        "FROM rfm_memories WHERE id IN (1,2,4,5,6);"
    )
    return "\n".join(lines)

# Only section headers and score rows make it to the terminal.
KEEP = ("---", "score=")

def main() -> None:
    db = sqlite3.connect(":memory:")
    rfm.register(db)
    for stmt in build_script().split(";\n"):
        if not stmt.strip():
            continue
        for row in db.execute(stmt):
            line = str(row[0])
            if any(k in line for k in KEEP):
                print(line)

if __name__ == "__main__":
    main()
