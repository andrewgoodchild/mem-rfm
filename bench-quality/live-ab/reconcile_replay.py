#!/usr/bin/env python3
"""Offline replay of session_end's reconcile step (EXPLORATORY, not a
registered track): how often did a staged candidate restate a lesson the
store already held, did the store's save path catch it, and would the
reconcile line have flagged it?

Two corpora, both hand-labelled in reconcile-labels.json (one rater, labels
written before any similarity was computed; ids only, no content):

  staged   every row that reached a store through pending-memories.md in
           the hooks-era runs (pilot2/4, reval-*, synth, synth6, track10)
           — 29 candidates, ratified by ratify_staged.py (approve-all).
           Row ids are chronological, so "the store at staging time" is
           every lower id in that run's DB.
  track18  the sweep's 65 LLM-extracted rows from the Track 18 replay
           (Jaccard-era, so nothing was merged): paraphrase pressure on
           prose memories, the other shape a store holds.

Labels: cluster = same lesson (a reviewer would skip or merge); family =
same underlying condition with different advice — excluded from both the
duplicate and the distinct sets, reported as neither.

Runs session_end.reconcile itself (no LLM, read-only on the DBs). Needs
the untracked run DBs, so point --dir at a checkout that has them.
Under the integration venv for embedding mode; plain python3 measures the
degraded token-overlap mode.

Usage: reconcile_replay.py [--dir bench-quality/live-ab]
"""
import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
os.environ["RFM_LOG"] = "0"
sys.path.insert(0, os.path.join(REPO, "integrations", "claude-code", "hooks"))
import session_end as se  # noqa: E402


def rows_of(d, exp):
    db = sqlite3.connect(f"file:{d}/{exp}/rfm-memory.db?mode=ro", uri=True)
    out = {i: c for i, c in db.execute("SELECT id, content FROM rfm_memories")}
    db.close()
    return out


def replay(items, new_ids):
    """items: {id: (content, cluster, family)}. Each id in new_ids is
    reconciled against every lower id, as staging would have seen it.
    Returns rows of (id, is_dup, flagged, flag_correct, flag_related)."""
    out = []
    for i in new_ids:
        prior = [(j, items[j][0], None) for j in sorted(items) if j < i]
        if not prior:
            continue
        cl, fam = items[i][1], items[i][2]
        is_dup = any(items[j][1] == cl for j, _, _ in prior)
        rec = se.reconcile([("new", items[i][0])], prior, [])[0]
        flagged = [int(n["ref"][1:]) for n in rec["nearest"] if n["duplicate"]]
        correct = any(items[j][1] == cl for j in flagged)
        related = any(items[j][1] != cl and fam and items[j][2] == fam
                      for j in flagged)
        out.append((i, is_dup, bool(flagged), correct, related))
    return out


def report(name, res):
    dups = [r for r in res if r[1]]
    rest = [r for r in res if not r[1]]
    caught = sum(r[3] for r in dups)
    ff_any = sum(r[2] for r in rest)
    ff_rel = sum(r[2] and r[4] for r in rest)
    print(f"{name}: {len(res)} items with a non-empty store; "
          f"{len(dups)} restate an existing lesson")
    print(f"  duplicates flagged (against a true duplicate): "
          f"{caught}/{len(dups)}")
    print(f"  non-duplicates flagged: {ff_any}/{len(rest)} "
          f"({ff_rel} of them against a same-family row, "
          f"{ff_any - ff_rel} against an unrelated one)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=HERE,
                    help="live-ab dir holding the untracked run DBs")
    a = ap.parse_args()
    labels = json.load(open(os.path.join(HERE, "reconcile-labels.json")))
    print(f"similarity mode: {se.similarity.mode()}  "
          f"(duplicate at >= {se.DUPLICATE_AT[se.similarity.mode()]})\n")

    res, staged = [], 0
    for exp, lab in labels["staged"].items():
        content = rows_of(a.dir, exp)
        items = {int(i): (content[int(i)], cl, fam)
                 for i, (cl, fam, _st) in lab.items()}
        new = sorted(int(i) for i, v in lab.items() if v[2])
        staged += len(new)
        res += [r for r in replay(items, new)]
    print(f"staged candidates: {staged} (all ratified approve-all; the "
          f"server's exact-content dedupe returned 'already stored' for 0)")
    report("staged", res)

    content = rows_of(a.dir, "track18")
    items = {}
    for key, ids in labels["sweep_track18"].items():
        cl, fam = key.split("|")
        for i in ids:
            items[i] = (content[i], cl, fam)
    print()
    report("track18", replay(items, sorted(items)))


if __name__ == "__main__":
    main()
