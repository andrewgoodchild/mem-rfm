#!/usr/bin/env python3
"""Score Track 11 against its registered predictions.

Metric of record is the counterfactual — Bash events before the first
green test run — compared pairwise between arms on the same task. A
session that never reaches green loses to one that does; both-never is a
tie, as in Track 10's scorer.

Usage: score_track11.py
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formation_study as F  # noqa: E402  (sessions, events_of, first_green)

DIR = os.path.join(HERE, "track11")
ARM_NAMES = ["none", "placebo", "prose", "verbatim", "abstract"]


def compare(events, a, b, tasks):
    """(a wins, b wins, ties) on events-to-first-green, a vs b."""
    wins = losses = ties = 0
    for iid in tasks:
        ea, eb = events.get((iid, a), "absent"), events.get((iid, b), "absent")
        if ea == "absent" or eb == "absent":
            continue
        if ea is None and eb is None:
            ties += 1
        elif ea is None:
            losses += 1
        elif eb is None:
            wins += 1
        elif ea < eb:
            wins += 1
        elif ea > eb:
            losses += 1
        else:
            ties += 1
    return wins, losses, ties


def corrected_first_green(events):
    """RESULTS.md Correction C3: the registered detector requires the
    literal 'N passed' text, which tail-piped pytest output can lose. The
    corrected rule — first pytest run that exited 0 — is C3's, and both
    readings are reported because the registration pointed at the shipped
    (known-defective) detector."""
    for i, e in enumerate(events):
        if e.got and not e.is_err and "pytest" in e.cmd:
            return i
    return None


def main():
    res = [json.loads(l) for l in open(os.path.join(DIR, "results.jsonl"))]
    by = collections.defaultdict(dict)
    for r in res:
        by[r["instance_id"]][r["arm"]] = r
    complete = {k: v for k, v in by.items() if len(v) == len(ARM_NAMES)}
    print(f"sessions {len(res)}   complete tasks {len(complete)}"
          f"   incomplete {len(by) - len(complete)}\n")
    tasks = sorted(by)

    # --- transcripts, for the counterfactual ---
    events = {}
    for _run, label_task, _ab_arm, tp in F.sessions(["track11"]):
        iid, arm_name = label_task.rsplit("-", 1)
        if arm_name in ARM_NAMES:
            events[(iid, arm_name)] = F.first_green(F.events_of(tp))

    fmt = lambda x: ("absent" if x == "absent"
                     else "never" if x is None else str(x))
    hdr = f"{'task':<26}" + "".join(f"{a:>10}" for a in ARM_NAMES)
    print(hdr + "   (events to first green; resolved marked *)")
    for iid in tasks:
        row = f"{iid:<26}"
        for a in ARM_NAMES:
            cell = fmt(events.get((iid, a), "absent"))
            if by[iid].get(a, {}).get("resolved"):
                cell += "*"
            row += f"{cell:>10}"
        print(row)

    wall = {a: sum(v[a]["wall_s"] for v in complete.values())
            for a in ARM_NAMES} if complete else {}
    resolved = {a: sum(1 for v in complete.values() if v[a]["resolved"])
                for a in ARM_NAMES} if complete else {}
    print("\nper-arm totals over complete tasks:")
    for a in ARM_NAMES:
        print(f"  {a:>9}: resolved {resolved.get(a, 0)}/{len(complete)}, "
              f"wall {wall.get(a, 0)}s")

    # --- C3-corrected counterfactual, reported alongside the registered ---
    cev = {}
    for _run, label_task, _ab_arm, tp in F.sessions(["track11"]):
        iid, arm_name = label_task.rsplit("-", 1)
        if arm_name in ARM_NAMES:
            cev[(iid, arm_name)] = corrected_first_green(F.events_of(tp))
    print("\nC3-corrected (first pytest exit 0):")
    for iid in tasks:
        print(f"{iid:<26}" + "".join(
            f"{fmt(cev.get((iid, a), 'absent')):>10}" for a in ARM_NAMES))
    for tag, a, b in [("P1", "verbatim", "none"), ("P2", "verbatim", "placebo"),
                      ("P3", "placebo", "none"), ("P4", "verbatim", "prose"),
                      ("P5", "abstract", "verbatim")]:
        w, l, t = compare(cev, a, b, tasks)
        print(f"  {tag} {a} vs {b}: {w}/{l}/{t}")

    # --- utilisation: injections that actually landed ---
    injected_sessions = sum(1 for r in res if r["ab_arm"] == "rfm")
    landed = 0
    log = os.path.join(DIR, "rfm-log.jsonl")
    if os.path.exists(log):
        for l in open(log):
            rec = json.loads(l)
            if rec.get("op") == "injection" and rec.get("injected") == [1]:
                landed += 1
    print(f"\ninjections landed: {landed} across {injected_sessions} "
          f"injected-arm sessions")

    print("\n" + "=" * 62)
    print("REGISTERED PREDICTIONS — Track 11")
    v = []

    def sc(tag, ok, detail):
        v.append(ok)
        print(f"  {tag}: {'PASS' if ok else 'FAIL'} — {detail}")

    def duel(a, b):
        w, l, t = compare(events, a, b, tasks)
        return w, l, f"{a} {w} / {b} {l} / tied {t}"

    w, l, d = duel("verbatim", "none")
    sc("T11-P1 necessity (verbatim beats none)", w > l, d)
    p1 = w > l
    w, l, d = duel("verbatim", "placebo")
    sc("T11-P2 content vs presence (verbatim beats placebo)", w > l, d)
    w, l, d = duel("placebo", "none")
    sc("T11-P3 placebo buys nothing (placebo does not beat none)", w <= l, d)
    w, l, d = duel("verbatim", "prose")
    sc("T11-P4 form (verbatim beats prose)", w > l, d)
    w, l, d = duel("abstract", "verbatim")
    sc("T11-P5 abstraction (abstract does not beat verbatim)", w <= l, d)
    p6 = injected_sessions > 0 and landed >= 0.9 * injected_sessions
    sc("T11-P6 utilisation (injection landed >= 90%)", p6,
       f"{landed}/{injected_sessions}")
    nw, vw = wall.get("none", 0), wall.get("verbatim", 0)
    sc("T11-P7 no harm (verbatim wall within +15% of none)",
       vw <= 1.15 * max(nw, 1),
       f"none {nw}s, verbatim {vw}s ({100 * (vw - nw) / max(nw, 1):+.1f}%)")
    print(f"\n  {sum(v)}/{len(v)} PASS")

    if not p1 and p6:
        print("\n  READ THIS BEFORE CLAIMING ANYTHING: injection landed and "
              "the corpus's highest-value memory did not beat no-memory on "
              "its home turf. Per the registration, that implicates the "
              "instrument, not just the store: the outcome ledger (M) was "
              "counting engagement, and nothing this project has measured "
              "with it establishes causal value.")


if __name__ == "__main__":
    main()
