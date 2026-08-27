#!/usr/bin/env python3
"""Score Track 18 (the open-throttle replay) against its registered
bars.

Usage: score_track18.py
"""
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score_track8 as S8  # noqa: E402  (leaks)

DIR = os.path.join(HERE, "track18")
DB = os.path.join(DIR, "rfm-memory.db")
LOG = os.path.join(DIR, "rfm-log.jsonl")
FAMILY = re.compile(r"sphinxcontrib|alabaster|stubs?.{0,40}pythonpath|"
                    r"pythonpath.{0,40}stubs?", re.I | re.S)


def main():
    db = sqlite3.connect(DB)
    rows = db.execute("SELECT id, content, sightings, access_count, "
                      "value_score, outcome_count FROM rfm_memories").fetchall()
    log = [json.loads(l) for l in open(LOG)] if os.path.exists(LOG) else []
    mapping = json.load(open(os.path.join(DIR, "mapping.json")))
    n_tp = len(open(os.path.join(DIR, "transcripts.txt")).read().split())

    fam = [r for r in rows if FAMILY.search(r[1])]
    fam_ids = {r[0] for r in fam}
    fam_sightings = sum((r[2] or 1) for r in fam)
    fam_pos = sum(1 for l in log if l.get("op") == "sweep_judge"
                  and l.get("id") in fam_ids and l.get("outcome") == 1.0)

    admits = [l for l in log if l.get("op") == "sweep_admit"]
    leaks = 0
    for l in admits:
        info = mapping.get(l.get("src", ""), {})
        row = next((r for r in rows if r[0] == l["id"]), None)
        if row and info.get("task") and S8.leaks(row[1], info["task"]):
            leaks += 1
    dedupes = sum(1 for l in log if l.get("op") == "sweep_dedupe_hit")
    judges = sum(1 for l in log if l.get("op", "").startswith("sweep_judge"))
    extracts = len({l.get("src") for l in log
                    if l.get("op") in ("sweep_admit", "sweep_dedupe_hit",
                                       "sweep_provenance_drop")})
    calls_per_tp = (extracts + judges) / max(n_tp, 1)

    print(f"store: {len(rows)} rows from {n_tp} transcripts; "
          f"{len(admits)} admits, {dedupes} dedupe-hits, {judges} judge ops")
    print(f"era-pin family: {len(fam)} row(s), combined sightings "
          f"{fam_sightings}, judged +1s {fam_pos}")
    for r in fam:
        print(f"  [{r[0]}] sightings={r[2]} accesses={r[3]} "
              f"value={r[4]:.2f} n={r[5]}: {r[1][:110]}")

    print("\n" + "=" * 62)
    print("REGISTERED PREDICTIONS — Track 18")
    v = []

    def sc(tag, ok, detail):
        v.append(ok)
        print(f"  {tag}: {'PASS' if ok else 'FAIL'} — {detail}")

    sc("T18-P1 capture (era-pin fact present)", len(fam) >= 1,
       f"{len(fam)} family row(s)")
    sc("T18-P2 dedupe-as-frequency (<=2 rows, sightings >= 5)",
       1 <= len(fam) <= 2 and fam_sightings >= 5,
       f"{len(fam)} rows, {fam_sightings} sightings")
    sc("T18-P3 fossil refusal (judged +1s on family <= 4, was 17)",
       fam_pos <= 4, f"{fam_pos} judged positives")
    lr = leaks / max(len(admits), 1)
    sc("T18-P4 junk bound (source-task leakage <= 40%)", lr <= 0.40,
       f"{leaks}/{len(admits)} = {100 * lr:.0f}%")
    sc("T18-P5 cost (<= 3 LLM calls per transcript)", calls_per_tp <= 3,
       f"{calls_per_tp:.1f}/transcript")
    print(f"\n  {sum(v)}/{len(v)} PASS")


if __name__ == "__main__":
    main()
