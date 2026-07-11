#!/usr/bin/env python3
"""Toy agent-memory loop demonstrating rfm_score ranking dynamics.

Seeds 50 memories, simulates 200 retrievals with mixed outcome feedback over
30 simulated days, and prints the top-5 ranking before and after: memories
that keep getting used *and keep helping* rise; stale or unhelpful ones decay.

Python stdlib only. If this Python's sqlite3 module supports loadable
extensions it is used directly; otherwise (e.g. macOS system Python) the
script drives a .load-capable sqlite3 CLI via subprocess. Set SQLITE3_BIN to
point at one (default: /usr/local/opt/sqlite/bin/sqlite3).
"""
import os
import random
import shutil
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "..", "target")

# Candidate artifacts/binaries, probed at startup: builds and Homebrew
# prefixes differ per machine (native arm64 vs Rosetta/Intel), so resolution
# is by trying, not by assuming this machine's layout. Env vars override.
def _dylib_candidates():
    if os.environ.get("RFM_DYLIB"):
        return [os.environ["RFM_DYLIB"]]
    return [p for p in (
        os.path.join(TARGET, "release", "librfm.dylib"),
        os.path.join(TARGET, "x86_64-apple-darwin", "release", "librfm.dylib"),
    ) if os.path.exists(p)]

def _sqlite3_candidates():
    if os.environ.get("SQLITE3_BIN"):
        return [os.environ["SQLITE3_BIN"]]
    found = [p for p in (
        "/opt/homebrew/opt/sqlite/bin/sqlite3",
        "/usr/local/opt/sqlite/bin/sqlite3",
        shutil.which("sqlite3"),
    ) if p and os.path.exists(p)]
    return found

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

# Both output paths keep the same lines: section headers and score rows.
KEEP = ("---", "score=")

def run_stdlib(script: str, dylib: str) -> str:
    db = sqlite3.connect(":memory:")
    db.enable_load_extension(True)
    db.load_extension(dylib)
    db.enable_load_extension(False)
    out = []
    for stmt in script.split(";\n"):
        if not stmt.strip():
            continue
        for row in db.execute(stmt):
            line = str(row[0])
            if any(k in line for k in KEEP):
                out.append(line)
    return "\n".join(out)

def run_cli(script: str, sqlite3_bin: str, dylib: str) -> str:
    proc = subprocess.run(
        [sqlite3_bin, "-batch", "-noheader", ":memory:", "-cmd", f".load {dylib}"],
        input=script, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{sqlite3_bin} failed:\n{proc.stderr}")
    return "\n".join(l for l in proc.stdout.splitlines() if any(k in l for k in KEEP))

def main() -> None:
    script = build_script()
    dylibs = _dylib_candidates()
    if not dylibs:
        sys.exit("no librfm.dylib found — run `cargo build --release` (or set RFM_DYLIB)")
    errors = []
    if hasattr(sqlite3.Connection, "enable_load_extension"):
        for dylib in dylibs:
            try:
                print(run_stdlib(script, dylib))
                return
            except sqlite3.OperationalError as e:
                errors.append(f"stdlib + {dylib}: {e}")
    for sqlite3_bin in _sqlite3_candidates():
        for dylib in dylibs:
            try:
                print(run_cli(script, sqlite3_bin, dylib))
                return
            except RuntimeError as e:
                errors.append(str(e))
    sys.exit("could not run the demo with any sqlite3/dylib combination:\n" + "\n".join(errors))

if __name__ == "__main__":
    main()
