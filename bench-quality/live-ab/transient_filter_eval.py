#!/usr/bin/env python3
"""Would a transient-content filter on memory_save drop bad memories or good
ones? Measured on the two labelled sets this directory has:

  1. harvest-labelled.jsonl — 86 harvested fix-summary blocks with an
     external label (label_harvest.py): `env-bearing` (carries durable
     environment knowledge: good) vs `pure-per-bug` (only this task's bug:
     bad).
  2. The pilot stores (*.db, gitignored — pass --live-ab pointing at the
     checkout that holds them). Every row was an approve-all ratified miner
     candidate; the outcome loop then labelled it: value_score > 0 good,
     < 0 bad, no outcomes unlabelled. Pooled by unique content.

The filter is integrations/claude-code/transient.py. Read-only on the DBs.

Usage: transient_filter_eval.py [--live-ab DIR]
"""
import argparse
import collections
import glob
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "integrations", "claude-code"))
import transient  # noqa: E402


# The markers the "what to save" guidance names outright, versus the full
# detector (which adds scratch paths, dates and session-state words).
NAMED = {"commit_sha", "pr_or_issue", "ci_status"}


def table(title, groups):
    print(f"\n{title}")
    print(f"  {'label':<14}{'n':>5}{'all':>9}{'rate':>7}{'named':>7}{'rate':>7}   markers")
    for label, texts in groups.items():
        hits = [transient.markers(t) for t in texts]
        dropped = sum(1 for h in hits if h)
        kinds = collections.Counter(k for h in hits for k in h)
        rate = f"{dropped / len(texts):.0%}" if texts else "-"
        named = sum(1 for h in hits if NAMED & set(h))
        nrate = f"{named / len(texts):.0%}" if texts else "-"
        print(f"  {label:<14}{len(texts):>5}{dropped:>9}{rate:>7}"
              f"{named:>7}{nrate:>7}   {dict(kinds.most_common())}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-ab", default=HERE)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(os.path.join(HERE, "harvest-labelled.jsonl"))]
    groups = collections.defaultdict(list)
    for r in rows:
        groups[{"env-bearing": "good(env)", "pure-per-bug": "bad(per-bug)"}
               .get(r["truth"], r["truth"])].append(r["block"])
    table(f"harvest blocks (n={len(rows)})", dict(groups))

    pooled = {}
    for path in sorted(glob.glob(os.path.join(args.live_ab, "**", "*.db"), recursive=True)):
        if "/clones/" in path:
            continue
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            got = con.execute("SELECT content, value_score, outcome_count "
                              "FROM rfm_memories").fetchall()
            con.close()
        except sqlite3.Error:
            continue
        for content, value, n in got:
            prev = pooled.get(content)
            # A content saved in several pilot stores: keep its most-evidenced row.
            if prev is None or (n or 0) > (prev[1] or 0):
                pooled[content] = (value, n)
    groups = {"good(v>0)": [], "bad(v<0)": [], "no-outcome": []}
    for content, (value, n) in pooled.items():
        key = ("no-outcome" if not n else "good(v>0)" if value > 0
               else "bad(v<0)" if value < 0 else "no-outcome")
        groups[key].append(content)
    table(f"pilot-store memories, unique content (n={len(pooled)})", groups)


if __name__ == "__main__":
    main()
