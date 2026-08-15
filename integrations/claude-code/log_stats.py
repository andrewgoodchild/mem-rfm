#!/usr/bin/env python3
"""Summarise a dogfooding log written by server.py.

Three things can be true of a memory system in daily use, and only the third
is worth having:

  1. it runs            — searches return rows
  2. the prior is alive — rfm_prior varies across rows rather than sitting
                          at a constant, so something is being ranked
  3. it changes what you see — the returned set differs from what plain
                          similarity would have returned

and one more that decides whether ANY published finding here applies to your
usage: whether the loop is closed. Every result in this repository assumes
outcomes come back. If the client never calls memory_feedback, the value axis
is inert and you are running cosine similarity with extra steps.

This applies the same rules the benchmark harness does (PROTOCOL.md
Amendments 11-12): a channel that never varies is reported as DEAD rather
than quietly averaged, and an exact zero is treated as a bug report.

Usage: log_stats.py [path-to-rfm-log.jsonl] [--days N]
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

DEFAULT = os.path.expanduser(os.environ.get(
    "RFM_LOG", "~/.sqlite-rfm/rfm-log.jsonl"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=DEFAULT)
    ap.add_argument("--days", type=float, default=None,
                    help="only consider the last N days")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        sys.exit(f"no log at {args.path}\n"
                 "(the server writes one on first use; RFM_LOG=0 disables it)")

    cutoff = time.time() - args.days * 86400 if args.days else 0
    recs = []
    for line in open(args.path):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue                      # tolerate a torn final write
        if r.get("t", 0) >= cutoff:
            recs.append(r)

    if not recs:
        sys.exit("no records in window")

    ops = Counter(r["op"] for r in recs)
    searches = [r for r in recs if r["op"] == "search"]
    feedback = [r for r in recs if r["op"] == "feedback" and "error" not in r]

    span = (recs[-1]["t"] - recs[0]["t"]) / 86400
    print(f"=== {args.path} ===")
    print(f"{len(recs)} records over {span:.1f} days "
          f"({time.strftime('%Y-%m-%d', time.localtime(recs[0]['t']))} to "
          f"{time.strftime('%Y-%m-%d', time.localtime(recs[-1]['t']))})")
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(ops.items())))

    # ---- 1. loop closure -------------------------------------------------
    returned = sum(len(s["results"]) for s in searches)
    print("\n--- loop closure ---")
    if not returned:
        print("  no memories returned yet")
    else:
        rate = len(feedback) / returned
        print(f"  memories returned by search : {returned}")
        print(f"  outcomes recorded           : {len(feedback)}"
              f"  ({rate:.1%} of returned)")
        pos = sum(1 for f in feedback if f.get("helped"))
        if feedback:
            print(f"  positive / negative         : {pos} / "
                  f"{len(feedback) - pos}")
        if rate == 0:
            print("  OPEN LOOP — no feedback has ever been recorded. The value")
            print("  axis is inert; this is similarity search with a decay")
            print("  term. Every outcome-based finding in docs/findings.md")
            print("  is inapplicable to this store until feedback arrives.")
        elif rate < 0.05:
            print("  SPARSE — under 5% of retrievals get an outcome. The value")
            print("  axis is mostly running on the neutral prior.")
        if feedback and pos == len(feedback):
            print("  NOTE: every outcome is positive. A signal with no negative")
            print("  cases cannot demote anything, which is most of the point.")

    # ---- 1b. usage accounting -------------------------------------------
    rec = sum(s.get("accesses_recorded", 0) for s in searches)
    sup = sum(s.get("accesses_suppressed", 0) for s in searches)
    if rec or sup:
        print("\n--- usage accounting ---")
        print(f"  accesses recorded            : {rec}")
        print(f"  suppressed as repeat-in-window: {sup}"
              f"  ({sup / max(rec + sup, 1):.1%})")
        if sup > rec:
            print("  Most retrievals are repeats inside the window. That is")
            print("  either a retry-heavy client or genuinely repetitive work;")
            print("  worth knowing which before reading the frequency axis.")

    # ---- 2. prior liveness ----------------------------------------------
    print("\n--- prior liveness ---")
    if searches:
        spreads = [s.get("prior_spread", 0.0) for s in searches]
        dead = sum(1 for x in spreads if x < 1e-9)
        print(f"  mean prior spread within a result set : "
              f"{sum(spreads)/len(spreads):.4f}")
        print(f"  searches where the prior was flat     : {dead}"
              f"/{len(searches)}")
        if dead == len(searches):
            print("  DEAD SIGNAL — the prior never varied across candidates.")
            print("  Expected while memories are new and unused; if it")
            print("  persists after real usage, something is wrong.")

    # ---- 3. does it change what you see ---------------------------------
    print("\n--- effect on results ---")
    if searches:
        changed = sum(1 for s in searches if s.get("set_changed"))
        reordered = sum(1 for s in searches if s.get("order_changed"))
        print(f"  searches where RFM changed the RETURNED SET : "
              f"{changed}/{len(searches)} ({changed/len(searches):.1%})")
        print(f"  searches where RFM changed the ORDER        : "
              f"{reordered}/{len(searches)} ({reordered/len(searches):.1%})")
        if reordered == 0:
            print("  RFM is not affecting retrieval at all — identical to")
            print("  plain cosine ranking over this window.")

    # ---- per-memory ------------------------------------------------------
    hits = Counter()
    fb = defaultdict(lambda: [0, 0])
    for s in searches:
        for r in s["results"]:
            hits[r["id"]] += 1
    for f in feedback:
        fb[f["id"]][0 if f.get("helped") else 1] += 1
    if hits:
        print("\n--- most retrieved ---")
        print("  id   retrieved  +ve  -ve")
        for mid, n in hits.most_common(10):
            p, m = fb[mid]
            print(f"  {mid:<5}{n:>9}{p:>5}{m:>5}")

    never = [mid for mid, (p, m) in fb.items() if p + m == 0]
    if never:
        print(f"\n  {len(never)} memories retrieved but never rated")


if __name__ == "__main__":
    main()
