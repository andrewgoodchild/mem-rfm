#!/usr/bin/env python3
"""Score Track 20 (MEMTRACK replay) against its registered bars.

Usage: score_track20.py
"""
import collections
import glob
import json
import math
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "track20")
STORES = os.path.join(DIR, "stores")


def sign_p(wins, decided):
    return sum(math.comb(decided, k) for k in range(wins, decided + 1)) \
        / 2 ** decided if decided else 1.0


def main():
    by = collections.defaultdict(dict)
    for l in open(os.path.join(DIR, "results.jsonl")):
        r = json.loads(l)
        by[r["id"]][r["arm"]] = r
    pairs = {k: v for k, v in by.items() if len(v) == 2}
    clis = {r["cli"] for v in by.values() for r in v.values()}

    nq = sum(v["control"]["nq"] for v in pairs.values())
    c_corr = sum(v["control"]["exact_correct"] for v in pairs.values())
    r_corr = sum(v["rfm"]["exact_correct"] for v in pairs.values())
    cw = sum(v["control"]["wall_s"] for v in pairs.values())
    rw = sum(v["rfm"]["wall_s"] for v in pairs.values())
    faster = sum(1 for v in pairs.values()
                 if v["rfm"]["wall_s"] < v["control"]["wall_s"])
    slower = sum(1 for v in pairs.values()
                 if v["rfm"]["wall_s"] > v["control"]["wall_s"])

    # P1: promoted memories per store
    promoted_stores = 0
    total_stores = 0
    for db in glob.glob(os.path.join(STORES, "*.db")):
        total_stores += 1
        con = sqlite3.connect(db)
        try:
            n = con.execute("SELECT count(*) FROM rfm_memories WHERE "
                            "COALESCE(sightings,1) >= 2").fetchone()[0]
        except sqlite3.Error:
            n = 0
        con.close()
        promoted_stores += n >= 1

    # P2: injection delivery (per-store session log)
    inj = 0
    slog = os.path.join(STORES, "rfm-log.jsonl")
    if os.path.exists(slog):
        for l in open(slog):
            r = json.loads(l)
            if r.get("op") == "injection" and r.get("injected"):
                inj += 1
    n_rfm = sum(1 for v in pairs.values() if "rfm" in v)

    # P5: store-build calls (from the build log narrator lines is lost;
    # recompute the bound from the committed store call counts if present,
    # else report from run.log build section)
    build_calls = []
    blog = os.path.join(DIR, "build-smoke.log")
    if os.path.exists(blog):
        import re
        for line in open(blog):
            m = re.search(r"(\d+) calls", line)
            if m:
                build_calls.append(int(m.group(1)))

    print(f"complete pairs {len(pairs)}/43   questions {nq}   "
          f"CLI(s) {sorted(clis)}")
    print(f"correctness (exact-match): control {c_corr}, rfm {r_corr}")
    print(f"wall total: control {cw}s, rfm {rw}s "
          f"({100*(rw-cw)/max(cw,1):+.1f}%); rfm faster {faster}, "
          f"slower {slower}")
    print(f"stores with a promoted memory: {promoted_stores}/{total_stores}")
    print(f"injection-with-content sessions: {inj}/{n_rfm}")
    if build_calls:
        print(f"store-build calls: mean {sum(build_calls)/len(build_calls):.1f}"
              f", max {max(build_calls)} per instance")

    print("\n" + "=" * 60)
    print(f"REGISTERED PREDICTIONS — Track 20 "
          f"(at {len(pairs)}/43 pairs)")
    v = []

    def sc(tag, ok, detail):
        v.append(ok)
        print(f"  {tag}: {'PASS' if ok else 'FAIL'} — {detail}")

    sc("T20-P1 formation (>=50% stores with a promoted memory)",
       promoted_stores >= 0.5 * max(total_stores, 1),
       f"{promoted_stores}/{total_stores}")
    sc("T20-P2 delivery (injection >=60% of rfm sessions)",
       inj >= 0.6 * max(n_rfm, 1), f"{inj}/{n_rfm}")
    sc("T20-P3 correctness parity (rfm >= control - 7)",
       r_corr >= c_corr - 7, f"rfm {r_corr} vs control {c_corr}")
    sc("T20-P4 no tax (rfm wall within +10% of control)",
       rw <= 1.10 * max(cw, 1),
       f"{100*(rw-cw)/max(cw,1):+.1f}%; slower on {slower}/{len(pairs)} "
       f"(sign p={sign_p(max(faster,slower), faster+slower):.3f})")
    if build_calls:
        sc("T20-P5 store-build cost (<=6 calls/instance mean)",
           sum(build_calls)/len(build_calls) <= 6,
           f"mean {sum(build_calls)/len(build_calls):.1f}")
    print(f"\n  {sum(v)}/{len(v)} PASS")


if __name__ == "__main__":
    main()
