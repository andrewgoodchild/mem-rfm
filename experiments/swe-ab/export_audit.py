#!/usr/bin/env python3
"""Regenerate memory-audit.md from the two experiment memory DBs (which stay
untracked — *.db is gitignored). Redaction = replace the home directory with
'~' and flatten whitespace; everything else is the agent's own saved lessons.

Usage: python3 export_audit.py > memory-audit.md
"""
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
STORES = [("pytest", "rfm-memory.db"), ("sphinx", "rfm-memory-sphinx.db")]

print("# Memory-store audit — live coding A/B (pytest + sphinx)")
print()
print("Redacted export of the two experiment memory stores (content is the")
print("agent's own saved lessons; access/outcome counts back the README's")
print("15-of-16-negative / ~6% transfer / +0.58 claims). Generated from the")
print("local DBs, which stay untracked; regenerate with export_audit.py.")

for name, filename in STORES:
    db = sqlite3.connect(os.path.join(HERE, filename))
    rows = db.execute(
        "SELECT id, content, access_count, outcome_count, value_score "
        "FROM rfm_memories ORDER BY id").fetchall()
    accesses, outcomes = db.execute(
        "SELECT count(*), count(outcome) FROM rfm_accesses").fetchone()
    negative = db.execute(
        "SELECT count(*) FROM rfm_accesses WHERE outcome < 0").fetchone()[0]
    print()
    print(f"## {name} store: {len(rows)} memories, {accesses} accesses, "
          f"{outcomes} outcomes ({negative} negative)")
    print()
    for mid, content, uses, n_out, value in rows:
        flat = " ".join(str(content).replace(HOME, "~").split())
        print(f"- [{mid}] uses={uses} outcomes={n_out} value={value:+.2f} — {flat}")
    db.close()
