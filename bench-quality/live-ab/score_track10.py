#!/usr/bin/env python3
"""Score Track 10 against its registered predictions.

Metric of record is the counterfactual — Bash events before the first
green test run — not resolved-rate, which was registered as predicted-null
precisely so a lucky reading of 13 tasks could not be turned into a claim
afterwards.

Usage: score_track10.py
"""
import collections
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formation_study as F  # noqa: E402  (sessions, events_of, first_green)

DIR = os.path.join(HERE, "track10")


def main():
    res = [json.loads(l) for l in open(os.path.join(DIR, "results.jsonl"))]
    by = collections.defaultdict(dict)
    for r in res:
        by[r["instance_id"]][r["arm"]] = r
    paired = {k: v for k, v in by.items() if len(v) == 2}
    print(f"sessions {len(res)}   complete pairs {len(paired)}"
          f"   incomplete {len(by)-len(paired)}\n")

    # --- transcripts, for the counterfactual ---
    S = [(run, task, arm, tp) for run, task, arm, tp
         in F.sessions(["track10"])]
    tp_of = {(task, arm): tp for _, task, arm, tp in S}

    print(f"{'task':<26}{'ctl res':>8}{'rfm res':>8}"
          f"{'ctl ev':>8}{'rfm ev':>8}{'verdict':>10}")
    wins = losses = ties = 0
    c_never = m_never = 0
    for iid in sorted(paired):
        c, m = paired[iid]["control"], paired[iid]["rfm"]
        ce = F.first_green(F.events_of(tp_of[(iid, "control")])) \
            if (iid, "control") in tp_of else None
        me = F.first_green(F.events_of(tp_of[(iid, "rfm")])) \
            if (iid, "rfm") in tp_of else None
        if ce is None:
            c_never += 1
        if me is None:
            m_never += 1
        if ce is None and me is not None:
            v, wins = "rfm", wins + 1
        elif me is None and ce is not None:
            v, losses = "control", losses + 1
        elif ce is None and me is None:
            v, ties = "both never", ties + 1
        elif me < ce:
            v, wins = "rfm", wins + 1
        elif me > ce:
            v, losses = "control", losses + 1
        else:
            v, ties = "tie", ties + 1
        print(f"{iid:<26}{str(c['resolved']):>8}{str(m['resolved']):>8}"
              f"{('never' if ce is None else ce):>8}"
              f"{('never' if me is None else me):>8}{v:>10}")

    cr = sum(1 for v in paired.values() if v["control"]["resolved"])
    mr = sum(1 for v in paired.values() if v["rfm"]["resolved"])
    cw = sum(v["control"]["wall_s"] for v in paired.values())
    mw = sum(v["rfm"]["wall_s"] for v in paired.values())

    # --- utilisation: did the store actually get consulted? ---
    inj = acc = 0
    log = os.path.join(DIR, "rfm-log.jsonl")
    ops = collections.Counter()
    if os.path.exists(log):
        for l in open(log):
            ops[json.loads(l)["op"]] += 1
        inj = ops.get("injection", 0)
        acc = ops.get("access", 0) + ops.get("outcome", 0)
    db = os.path.join(DIR, "rfm-memory.db")
    outcomes = 0
    if os.path.exists(db):
        try:
            outcomes = sqlite3.connect(db).execute(
                "SELECT COALESCE(SUM(outcome_count),0) FROM rfm_memories"
            ).fetchone()[0]
        except sqlite3.Error:
            pass

    print(f"\ncounterfactual (events to first green): rfm better on {wins}, "
          f"control better on {losses}, tied {ties}")
    print(f"  never reached green: control {c_never}, rfm {m_never}")
    print(f"resolved: control {cr}/{len(paired)}, rfm {mr}/{len(paired)}")
    print(f"wall: control {cw}s, rfm {mw}s "
          f"({100*(mw-cw)/max(cw,1):+.1f}%)")
    print(f"store log ops: {dict(ops)}")
    print(f"total outcomes recorded on the 5 memories: {outcomes}")

    print("\n" + "=" * 62)
    print("REGISTERED PREDICTIONS — Track 10")
    v = []

    def sc(tag, ok, detail):
        v.append(ok)
        print(f"  {tag}: {'PASS' if ok else 'FAIL'} — {detail}")

    sc("T10-P1 counterfactual: rfm wins > losses", wins > losses,
       f"{wins} wins vs {losses} losses ({ties} tied)")
    sc("T10-P2 resolved-rate: no meaningful difference", abs(cr - mr) <= 2,
       f"control {cr}, rfm {mr} (registered as predicted-null)")
    sc("T10-P3 utilisation >=50% of rfm sessions",
       inj >= 0.5 * len(paired),
       f"{inj} injections across {len(paired)} rfm sessions, "
       f"{outcomes} outcomes on the store")
    sc("T10-P4 no harm: rfm wall within +15%",
       mw <= 1.15 * max(cw, 1), f"{100*(mw-cw)/max(cw,1):+.1f}%")
    print(f"\n  {sum(v)}/{len(v)} PASS")

    if wins <= losses and inj >= 0.5 * len(paired):
        print("\n  READ THIS BEFORE CLAIMING ANYTHING: injection landed and "
              "the counterfactual did not move. Per the registration, that "
              "is the strongest negative this project can produce — "
              "memories a human would keep did not change what the agent "
              "did, and formation was never the binding constraint.")


if __name__ == "__main__":
    main()
