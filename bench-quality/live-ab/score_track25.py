#!/usr/bin/env python3
"""Score Track 25 (outcome honesty, then a live run) against its registered
bars. P1-P4 are offline on track23/ transcripts; P5 and P6 read track25/,
when it exists.

Usage: score_track25.py
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score_track24 as Z    # noqa: E402

S, F, se = Z.S, Z.F, Z.se
sys.path.insert(0, os.path.join(HERE, "..", "..", "integrations", "claude-code"))
import mod_bridge as B       # noqa: E402

DIR = os.path.join(HERE, "track23")
LIVE = os.path.join(HERE, "track25")


def span_credit(sig, cmd):
    spans = sig[0]
    return any(s in cmd or (se._template(s) and
                            se._fills_template(se._template(s), cmd))
               for s in spans)


def old_acted_on(sig, cmd):
    """As Track 24 left it: token share for any memory with no template."""
    spans, _ = sig
    return span_credit(sig, cmd) or (
        not any(se._holes(s) for s in spans) and Z.old_acted_on(sig, cmd))


def main():
    db = os.path.join(DIR, "rfm-memory.db")
    se.DB_PATH = db
    con = sqlite3.connect(db)
    store = dict(con.execute("SELECT id, content FROM rfm_memories"))
    con.close()
    sig = se._signature(store[1])
    res = [json.loads(l) for l in open(os.path.join(DIR, "results.jsonl"))]
    tp = {(r["instance_id"], r["arm"]): os.path.join(HERE, r["transcript"])
          for r in res}

    ones = bad = decided = 0
    for (iid, arm), path in sorted(tp.items()):
        at = S.note_positions(path).get(1)
        if arm != "show" or at is None:
            continue
        evs = F.events_of(path)
        got = se.infer_outcomes({1: (store[1], at)}, evs)
        i = next((i for i, e in enumerate(evs[at:], at)
                  if se.acted_on(sig, e.cmd)), None)
        if i is None:
            continue
        decided += 1
        is_clean = S.clean(evs[i], evs[i].full)
        for o in got:
            ones += o["outcome"] > 0
            bad += o["outcome"] > 0 and not is_clean
        print(f"  {iid[-4:]} clean={is_clean} outcome="
              f"{got[0]['outcome'] if got else None}")
    print(f"P1: {decided} deciding runs, +1 on {ones}, +1 on unclean {bad} "
          f"(bar: 6 and 0)")

    same_fired = same_mined = 0
    for path in tp.values():
        evs = F.events_of(path)
        mod = set()
        for e in evs:
            if e.got:
                mod.update(B.fired_in(e.full))
        same_fired += mod == se.fired_classes(evs)
        same_mined += se.corrections(evs) == se.corrections(
            [e._replace(full="") for e in evs])
    print(f"P3: fired classes equal the mod's on {same_fired} of {len(tp)}; "
          f"corrections unchanged on {same_mined} of {len(tp)} (bar 38, 38)")

    mems = Z.stored_memories()
    lost = gained = cut = prose = 0
    for path in tp.values():
        cmds = [e.cmd for e in F.events_of(path)]
        for m in mems:
            s = se._signature(m)
            for c in cmds:
                new, old = se.acted_on(s, c), old_acted_on(s, c)
                lost += span_credit(s, c) and not new
                gained += new and not old
                cut += old and not new
                prose += new and not s[0]
    print(f"P4: span credit lost {lost}, pairs gaining credit {gained} "
          f"(bar 0, 0); token credit removed {cut}; prose credit left {prose}")

    results = os.path.join(LIVE, "results.jsonl")
    if not os.path.exists(results):
        print("P5, P6: no live run yet")
        return
    live = [json.loads(l) for l in open(results)]
    ldb = os.path.join(LIVE, "rfm-memory.db")
    se.DB_PATH = ldb
    con = sqlite3.connect(ldb)
    lstore = dict(con.execute("SELECT id, content FROM rfm_memories"))
    rows = con.execute("SELECT memory_id, outcome, accessed_at FROM "
                       "rfm_accesses WHERE outcome IS NOT NULL "
                       "ORDER BY accessed_at").fetchall()
    con.close()
    print(f"live: {len(live)} sessions, mod outcomes in store: {rows}")
    expected = []
    for r in live:
        path = os.path.join(HERE, r["transcript"])
        at = S.note_positions(path)
        evs = F.events_of(path)
        mems_ = {m: (lstore[m], i) for m, i in at.items()}
        got = se.infer_outcomes(mems_, evs)
        expected += [(o["id"], o["outcome"]) for o in got]
        print(f"  {r['instance_id'][-4:]} resolved={r['resolved']} "
              f"wall={r['wall_s']} notes={len(at)} inferred="
              f"{[(o['id'], o['outcome']) for o in got]}")
    recorded = sorted((m, v) for m, v, _ in rows)
    print(f"P5: mod outcomes {len(rows)} over {len(live)} sessions, inferred "
          f"in {sum(1 for _ in expected)} (bar: >= 2 sessions)")
    print(f"P6: mod {recorded} vs session_end {sorted(expected)}: "
          f"{'agree' if recorded == sorted(expected) else 'DISAGREE'}")


if __name__ == "__main__":
    main()
