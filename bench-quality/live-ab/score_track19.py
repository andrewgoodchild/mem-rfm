#!/usr/bin/env python3
"""Score Track 19 (the rebuilt testbed) against its registered bars.
Metric of record: the C3-corrected counterfactual. Handles a suspended
run by scoring complete pairs and disclosing the shortfall.

Usage: score_track19.py
"""
import collections
import json
import math
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formation_study as F  # noqa: E402

DIR = os.path.join(HERE, "track19")
ERA = re.compile(r"VersionRequirementError|ExtensionError", re.I)
FAMILY = re.compile(r"sphinxcontrib|alabaster|stubs?.{0,40}pythonpath|"
                    r"pythonpath.{0,40}stubs?", re.I | re.S)


def sign_p(wins, decided):
    """One-sided binomial P(X >= wins | n=decided, p=0.5)."""
    return sum(math.comb(decided, k) for k in range(wins, decided + 1)) \
        / 2 ** decided


def main():
    res = [json.loads(l) for l in open(os.path.join(DIR, "results.jsonl"))]
    by = collections.defaultdict(dict)
    for r in res:
        by[r["instance_id"]][r["arm"]] = r
    pairs = {k: v for k, v in by.items() if len(v) == 2}
    missing = [k for k, v in by.items() if len(v) < 2]
    print(f"sessions {len(res)}   complete pairs {len(pairs)}   "
          f"incomplete/missing: {missing or 'none'}")

    ev, era_ctl = {}, {}
    for _run, label_task, _ab, tp in F.sessions(["track19"]):
        iid, arm = label_task.rsplit("-", 1)
        if arm not in ("control", "sweep"):
            continue
        evs = F.events_of(tp)
        ev[(iid, arm)] = F.first_green_corrected(evs)
        if arm == "control":
            era_ctl[iid] = sum(1 for e in evs
                               if e.got and ERA.search(e.body or ""))

    fmt = lambda x: "never" if x is None else str(x)
    print(f"\n{'task':<12}{'era(ctl)':>9}{'ctl ev':>8}{'swp ev':>8}"
          f"{'ctl wall':>9}{'swp wall':>9}{'verdict':>9}")
    wins = losses = ties = 0
    w_faster = w_slower = 0
    for iid in sorted(pairs):
        c, s = ev.get((iid, "control")), ev.get((iid, "sweep"))
        cw = pairs[iid]["control"]["wall_s"]
        sw = pairs[iid]["sweep"]["wall_s"]
        w_faster += sw < cw
        w_slower += sw > cw
        if c is None and s is None:
            v, ties = "tie", ties + 1
        elif c is None:
            v, wins = "sweep", wins + 1
        elif s is None:
            v, losses = "control", losses + 1
        elif s < c:
            v, wins = "sweep", wins + 1
        elif s > c:
            v, losses = "control", losses + 1
        else:
            v, ties = "tie", ties + 1
        print(f"{iid[-10:]:<12}{era_ctl.get(iid, '-'):>9}{fmt(c):>8}"
              f"{fmt(s):>8}{cw:>9}{sw:>9}{v:>9}")

    era_fired = sum(1 for v in era_ctl.values() if v > 0)
    cw_t = sum(v["control"]["wall_s"] for v in pairs.values())
    sw_t = sum(v["sweep"]["wall_s"] for v in pairs.values())

    db = sqlite3.connect(os.path.join(DIR, "rfm-memory.db"))
    rows = db.execute("SELECT id, content, sightings, access_count, "
                      "value_score, outcome_count, condition_class "
                      "FROM rfm_memories").fetchall()
    fam = [r for r in rows if FAMILY.search(r[1])]
    print(f"\nstore: {len(rows)} memories; era family {len(fam)}:")
    for r in rows:
        print(f"  [{r[0]}] sight={r[2]} acc={r[3]} v={r[4]:.2f} n={r[5]} "
              f"cond={r[6][:30]!r}: {r[1][:90]}")

    log = os.path.join(DIR, "rfm-log.jsonl")
    inj = []
    if os.path.exists(log):
        for l in open(log):
            rec = json.loads(l)
            if rec.get("op") == "injection" and rec.get("injected"):
                inj.append(rec)
    n_sweep = sum(1 for r in res if r["arm"] == "sweep")
    eligible = max(n_sweep - 2, 1)
    print(f"\ninjections with content: {len(inj)} across {n_sweep} "
          f"sweep sessions ({eligible} past the quarantine window)")

    decided = wins + losses
    p = sign_p(wins, decided) if decided else 1.0

    print("\n" + "=" * 62)
    print(f"REGISTERED PREDICTIONS — Track 19 "
          f"(scored at {len(pairs)}/21 pairs; shortfall disclosed)")
    v = []

    def sc(tag, ok, detail):
        v.append(ok)
        print(f"  {tag}: {'PASS' if ok else 'FAIL'} — {detail}")

    sc("T19-P1 condition fires in >= 60% of control sessions",
       era_fired >= 0.6 * len(era_ctl),
       f"{era_fired}/{len(era_ctl)} sessions, "
       f"{100 * era_fired / max(len(era_ctl), 1):.0f}%")
    fam_promoted = any((r[2] or 0) >= 2 for r in fam)
    sc("T19-P2 era memory formed and promoted (sightings >= 2)",
       fam_promoted,
       f"{len(fam)} family rows, max sightings "
       f"{max(((r[2] or 0) for r in fam), default=0)}")
    sc("T19-P3 necessity: wins > losses, one-sided sign p <= 0.05",
       wins > losses and p <= 0.05,
       f"sweep {wins} / control {losses} / tied {ties}; p = {p:.4f}")
    sc("T19-P4 no harm: sweep wall within +15% of control",
       sw_t <= 1.15 * max(cw_t, 1),
       f"control {cw_t}s, sweep {sw_t}s "
       f"({100 * (sw_t - cw_t) / max(cw_t, 1):+.1f}%); sweep faster on "
       f"{w_faster}, slower on {w_slower}")
    sc("T19-P5 delivery: injection in >= 50% of eligible sweep sessions",
       len(inj) >= 0.5 * eligible, f"{len(inj)}/{eligible}")
    print(f"\n  {sum(v)}/{len(v)} PASS")


if __name__ == "__main__":
    main()
