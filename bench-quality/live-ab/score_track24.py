#!/usr/bin/env python3
"""Score Track 24 (template commands in acted_on) against its registered
bars. Offline: reads track23/ transcripts and the local stores, runs no
session. old_acted_on is the matcher as Track 23 ran it.

Usage: score_track24.py
"""
import glob
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score_track23 as S    # noqa: E402

F, se = S.F, S.se
sys.path.insert(0, os.path.dirname(se.__file__))
import test_acted_on as TA   # noqa: E402

DIR = os.path.join(HERE, "track23")


def old_acted_on(sig, cmd):
    spans, mt = sig
    if any(span in cmd for span in spans):
        return True
    prog = se.program(cmd)
    if not prog or prog not in mt:
        return False
    ct = se.tokens(cmd)
    return bool(ct) and len(ct & mt) / len(ct) >= 0.6


def credited(sig, events, start=0):
    return any(se.acted_on(sig, e.cmd) for e in events[start:])


def stored_memories():
    seen = set()
    for p in glob.glob(os.path.join(HERE, "**", "*.db"), recursive=True):
        try:
            db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            seen.update(c for (c,) in
                        db.execute("SELECT content FROM rfm_memories"))
            db.close()
        except sqlite3.Error:
            continue
    return seen


def main():
    db = sqlite3.connect(os.path.join(DIR, "rfm-memory.db"))
    store = dict(db.execute("SELECT id, content FROM rfm_memories"))
    db.close()
    sig = se._signature(store[1])
    res = [json.loads(l) for l in open(os.path.join(DIR, "results.jsonl"))]
    tp = {(r["instance_id"], r["arm"]): os.path.join(HERE, r["transcript"])
          for r in res}

    ran, hit, built_none, false_show = [], [], [], []
    outcomes, decisive = [], []
    for (iid, arm), path in sorted(tp.items()):
        if arm != "show":
            continue
        at = S.note_positions(path).get(1)
        if at is None:
            continue
        evs = F.events_of(path)
        if any(S.PATH_PYTEST.search(e.cmd) for e in evs):
            ran.append(iid)
            hit += [iid] if credited(sig, evs, at) else []
        if not S.built_shim(path):
            built_none.append(iid)
            false_show += [iid] if credited(sig, evs, at) else []
        got = se.infer_outcomes({1: (store[1], at)}, evs)
        outcomes += got
        full = S.full_bodies(path)
        for i, e in enumerate(evs[at:], at):
            if got and se.acted_on(sig, e.cmd):
                decisive.append(S.clean(e, full[i]))
                break
    print(f"P1 recall: credited in {len(hit)} of {len(ran)} (bar 9 of 10); "
          f"missed {sorted(set(ran) - set(hit))}")

    ctl = [i for (i, a), p in tp.items()
           if a == "control" and credited(sig, F.events_of(p))]
    print(f"P2 specificity: {len(ctl)} of 19 control sessions credited "
          f"{ctl}; {len(false_show)} of {len(built_none)} noted no-shim "
          f"sessions credited {false_show} (bar 0 and 0)")

    plain = [m for m in stored_memories()
             if not any(se._holes(s) for s in se._signature(m)[0])]
    templated = stored_memories() - set(plain)
    pairs = diffs = added = removed = 0
    for path in tp.values():
        cmds = [e.cmd for e in F.events_of(path)]
        for m in plain:
            s = se._signature(m)
            for c in cmds:
                pairs += 1
                diffs += se.acted_on(s, c) != old_acted_on(s, c)
        for m in templated:
            s = se._signature(m)
            for c in cmds:
                new, old = se.acted_on(s, c), old_acted_on(s, c)
                added += new and not old
                removed += old and not new
    print(f"P4 no regression: {diffs} differences over {pairs} pairs "
          f"({len(plain)} memories; bar 0)")
    print(f"T24b-P2 on {len(templated)} template memories: credit added on "
          f"{added} pairs, removed on {removed}")

    bad = [(m, c) for m, c in TA.CREDIT if not se.acted_on(se._signature(m), c)]
    bad += [(m, c) for m, c in TA.REFUSE if se.acted_on(se._signature(m), c)]
    if se.acted_on(se._signature(TA.PLAIN), TA.NEAR):
        bad.append((TA.PLAIN, TA.NEAR))    # the registered refusal
    total = len(TA.CREDIT) + len(TA.REFUSE) + 2
    print(f"P3 fixtures: {total - len(bad)} of {total} pass {bad or ''}")

    ups = sum(o["outcome"] > 0 for o in outcomes)
    print(f"P5 ledger effect: {len(outcomes)} outcomes, +1 on {ups}, -1 on "
          f"{len(outcomes) - ups}; the deciding run was clean in "
          f"{sum(decisive)} of {len(decisive)}")
    for o in outcomes:
        print(f"   {o['outcome']:+.0f} {o['cmd'][:90]}")


if __name__ == "__main__":
    main()
