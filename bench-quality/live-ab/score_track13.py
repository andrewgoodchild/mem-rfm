#!/usr/bin/env python3
"""Score Track 13 against its registered predictions.

Metric of record is the C3-corrected counterfactual (first pytest run
that exits 0), registered as primary per Correction C3; the legacy
text-match detector is reported alongside, not scored.

Usage: score_track13.py
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formation_study as F      # noqa: E402
import score_track11 as s11      # noqa: E402  (corrected_first_green, compare)

DIR = os.path.join(HERE, "track13")
ARM_NAMES = ["none", "verbatim"]
ERA = re.compile(r"VersionRequirementError|ExtensionError", re.I)


def main():
    res = [json.loads(l) for l in open(os.path.join(DIR, "results.jsonl"))]
    by = collections.defaultdict(dict)
    for r in res:
        by[r["instance_id"]][r["arm"]] = r
    tasks = sorted(by)
    complete = {k: v for k, v in by.items() if len(v) == len(ARM_NAMES)}
    print(f"sessions {len(res)}   complete pairs {len(complete)}"
          f"   incomplete {len(by) - len(complete)}\n")

    cev, lev, era_ctl = {}, {}, {}
    for _run, label_task, _ab, tp in F.sessions(["track13"]):
        iid, arm = label_task.rsplit("-", 1)
        if arm not in ARM_NAMES:
            continue
        evs = F.events_of(tp)
        cev[(iid, arm)] = s11.corrected_first_green(evs)
        lev[(iid, arm)] = F.first_green(evs)
        if arm == "none":
            era_ctl[iid] = sum(1 for e in evs
                               if e.got and ERA.search(e.body or ""))

    fmt = lambda x: ("absent" if x == "absent"
                     else "never" if x is None else str(x))
    print(f"{'task':<26}{'era(ctl)':>9}{'none':>8}{'verbatim':>10}"
          f"{'legacy n/v':>13}{'wall n':>8}{'wall v':>8}")
    for iid in tasks:
        wn = by[iid].get("none", {}).get("wall_s", "-")
        wv = by[iid].get("verbatim", {}).get("wall_s", "-")
        leg = (f"{fmt(lev.get((iid, 'none'), 'absent'))}/"
               f"{fmt(lev.get((iid, 'verbatim'), 'absent'))}")
        print(f"{iid:<26}{era_ctl.get(iid, '-'):>9}"
              f"{fmt(cev.get((iid, 'none'), 'absent')):>8}"
              f"{fmt(cev.get((iid, 'verbatim'), 'absent')):>10}"
              f"{leg:>13}{wn:>8}{wv:>8}")

    fired = sum(1 for v in era_ctl.values() if v > 0)
    w, l, t = s11.compare(cev, "verbatim", "none", tasks)
    landed = 0
    log = os.path.join(DIR, "rfm-log.jsonl")
    if os.path.exists(log):
        for line in open(log):
            rec = json.loads(line)
            if rec.get("op") == "injection" and rec.get("injected") == [1]:
                landed += 1
    n_verb = sum(1 for r in res if r["arm"] == "verbatim")
    wn = sum(v["none"]["wall_s"] for v in complete.values())
    wv = sum(v["verbatim"]["wall_s"] for v in complete.values())
    faster = sum(1 for v in complete.values()
                 if v["verbatim"]["wall_s"] < v["none"]["wall_s"])

    print("\n" + "=" * 62)
    print("REGISTERED PREDICTIONS — Track 13")
    v = []

    def sc(tag, ok, detail):
        v.append(ok)
        print(f"  {tag}: {'PASS' if ok else 'FAIL'} — {detail}")

    sc("T13-P1 condition liveness (era class in >= 3/8 control)",
       fired >= 3, f"fired in {fired}/{len(era_ctl)} control sessions")
    sc("T13-P2 necessity (verbatim beats none, corrected)",
       w > l, f"verbatim {w} / none {l} / tied {t}")
    sc("T13-P3 utilisation (injection landed >= 90%)",
       n_verb > 0 and landed >= 0.9 * n_verb, f"{landed}/{n_verb}")
    sc("T13-P4 no harm (verbatim wall within +15% of none)",
       wv <= 1.15 * max(wn, 1),
       f"none {wn}s, verbatim {wv}s ({100 * (wv - wn) / max(wn, 1):+.1f}%); "
       f"verbatim faster on {faster}/{len(complete)} tasks")
    print(f"\n  {sum(v)}/{len(v)} PASS")

    if fired < 3:
        print("\n  Registered reading for P1 FAIL: the condition is dead at "
              "both capability tiers — the memory is a fossil of one August "
              "session, and no workload in this project's task pool can "
              "make it pay.")
    elif w <= l:
        print("\n  Registered reading for P1 PASS + P2 FAIL: the condition "
              "fires, the cure is in context, and it buys nothing — "
              "necessity failing where the disease is demonstrably present.")


if __name__ == "__main__":
    main()
