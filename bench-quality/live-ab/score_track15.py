#!/usr/bin/env python3
"""Score Track 15 (the yardstick run) — deliverables and decision rule
T15-D1, per REVALIDATION.md. Estimation only; no pass/fail hypotheses.

Usage: score_track15.py
"""
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formation_study as F  # noqa: E402

DIR = os.path.join(HERE, "track15")


def spread(xs):
    xs = sorted(xs)
    sd = f"{st.stdev(xs):.1f}" if len(xs) > 1 else "n/a"
    return (f"n={len(xs)} min={xs[0]} med={st.median(xs)} max={xs[-1]} "
            f"sd={sd} range={xs[-1] - xs[0]}")


def main():
    res = [json.loads(l) for l in open(os.path.join(DIR, "results.jsonl"))]
    wall = {}
    for r in res:
        wall.setdefault(r["model"], []).append(r["wall_s"])

    ev_c, ev_l, never = {}, {}, {}
    for _run, label_task, _arm, tp in F.sessions(["track15"]):
        alias = label_task.split("-")[0]
        evs = F.events_of(tp)
        c = F.first_green_corrected(evs)
        l = F.first_green(evs)
        if c is None:
            never[alias] = never.get(alias, 0) + 1
        else:
            ev_c.setdefault(alias, []).append(c)
        if l is not None:
            ev_l.setdefault(alias, []).append(l)

    print("Track 15 deliverables — sphinx-7757, control arm, 10 reps/model")
    for alias in ("fable", "haiku"):
        model = [r["model"] for r in res if alias in r["model"]][0] \
            if any(alias in r["model"] for r in res) else alias
        print(f"\n[{alias}] ({model})")
        if alias in ev_c:
            print(f"  events-to-green (corrected): {spread(ev_c[alias])}")
        print(f"  never-green (corrected): {never.get(alias, 0)}")
        if alias in ev_l:
            print(f"  events-to-green (legacy, reported): "
                  f"{spread(ev_l[alias])}")
        w = wall.get(next((m for m in wall if alias in m), ""), [])
        if w:
            print(f"  wall_s: {spread(w)}")
        resolved = sum(1 for r in res if alias in r["model"] and r["resolved"])
        print(f"  resolved: {resolved}/10")

    print("\n" + "=" * 62)
    fs = ev_c.get("fable", [])
    if fs:
        rng = max(fs) - min(fs)
        covered = rng >= 13
        print(f"T15-D1: fable within-condition range of corrected "
              f"events-to-green is {rng} (spread above). Registered "
              f"comparator: 13 events (Track 11's largest between-arm "
              f"difference on this task, legacy detector).")
        print(f"  -> {'COVERS' if covered else 'does NOT cover'} the "
              f"comparator; the limitation note appended to Tracks "
              f"10/11/13 states the measured spread either way.")


if __name__ == "__main__":
    main()
