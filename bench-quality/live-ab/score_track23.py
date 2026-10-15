#!/usr/bin/env python3
"""Score Track 23 (show-on-error, live) against its registered bars.

Reads track23/results.jsonl and the transcripts the runner copied into
track23/transcripts/ (never ~/.claude/projects, which Claude Code prunes).

Metric of record: Bash events before the first pytest run that names one
of the task's required test files and shows a clean summary ("first
verified"); a session that never gets one ranks below any that does.
"Clean" is read from the output, not the exit code: agents pipe pytest
through tail, which makes every run exit 0 and can cut the error text.

Usage: score_track23.py [--dir track23-smoke]
"""
import collections
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formation_study as F  # noqa: E402
import run_track23 as T      # noqa: E402

ERA = re.compile(r"VersionRequirementError|ExtensionError", re.I)
NOTE = "[rfm-memory]"
SUMMARY = re.compile(r"\b\d+ (?:passed|failed|errors?)\b")


def sign_p(wins, decided):
    """One-sided binomial P(X >= wins | n=decided, p=0.5)."""
    if decided == 0:
        return 1.0
    return sum(math.comb(decided, k) for k in range(wins, decided + 1)) \
        / 2 ** decided


def notes_in(tp):
    """Mod deliveries: hook_additional_context attachments carrying the
    [rfm-memory] note, with the memory ids they showed."""
    shown = []
    for line in open(tp):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        a = d.get("attachment") or {}
        if d.get("type") == "attachment" and \
                a.get("type") == "hook_additional_context":
            for c in a.get("content") or []:
                if str(c).startswith(NOTE):
                    shown.append([int(i) for i in
                                  re.findall(r'<memory id="(\d+)">', c)])
    return shown


def required_runs(events, files):
    return [(i, e) for i, e in enumerate(events)
            if e.got and "pytest" in e.cmd and any(f in e.cmd for f in files)]


def clean(e):
    """A visible pytest summary with passes and no failures or errors,
    and no non-zero exit."""
    lines = [l for l in (e.body or "").splitlines() if SUMMARY.search(l)]
    if e.is_err or not lines:
        return False
    last = lines[-1]
    return "passed" in last and not re.search(r"failed|error", last)


def first_verified(events, files):
    return next((i for i, e in required_runs(events, files) if clean(e)),
                None)


def bound(events, files):
    """The friction bound: the session's first required-file run was not
    clean (the era break is in place until the agent works around it)."""
    runs = required_runs(events, files)
    return bool(runs) and not clean(runs[0][1])


def rank(x):
    return math.inf if x is None else x


def main():
    out = os.path.join(HERE, sys.argv[sys.argv.index("--dir") + 1]) \
        if "--dir" in sys.argv else os.path.join(HERE, "track23")
    res = [json.loads(l) for l in open(os.path.join(out, "results.jsonl"))]
    by_id = {t["instance_id"]: t for t in json.load(
        open(os.path.join(HERE, "tasks_v2.json")))}
    by = collections.defaultdict(dict)
    for r in res:
        by[r["instance_id"]][r["arm"]] = r
    pairs = {k: v for k, v in by.items() if len(v) == 2}
    print(f"sessions {len(res)}   complete pairs {len(pairs)}   "
          f"incomplete: {[k for k, v in by.items() if len(v) < 2] or 'none'}")

    S = {}
    for iid, arms in pairs.items():
        files = T.test_files(by_id[iid])
        for arm, r in arms.items():
            tp = r.get("transcript") and os.path.join(HERE, r["transcript"])
            if not tp or not os.path.exists(tp):
                S[(iid, arm)] = None
                continue
            evs = F.events_of(tp)
            S[(iid, arm)] = {
                "bound": bound(evs, files),
                "fired": sum(1 for e in evs
                             if e.got and ERA.search(e.body or "")),
                "notes": notes_in(tp),
                "verified": first_verified(evs, files),
                "green": F.first_green_corrected(evs),
            }

    fmt = lambda x: "never" if x is None else str(x)
    print(f"\n{'task':<8}{'fired c/s':>10}{'shown':>6}{'ctl ver':>8}"
          f"{'show ver':>9}{'ctl wall':>9}{'show wall':>10}{'verdict':>9}")
    wins = losses = ties = 0
    slower = faster = 0
    ctl_bound = ctl_fired = show_fired = shown_when_fired = 0
    contaminated = []
    for iid in sorted(pairs):
        c, s = S.get((iid, "control")), S.get((iid, "show"))
        cw, sw = pairs[iid]["control"]["wall_s"], pairs[iid]["show"]["wall_s"]
        if c is None or s is None:
            print(f"{iid[-6:]:<8} transcript missing")
            continue
        ctl_bound += c["bound"]
        ctl_fired += c["fired"] > 0
        show_fired += s["fired"] > 0
        shown_when_fired += s["fired"] > 0 and bool(s["notes"])
        if c["notes"]:
            contaminated.append(iid)
        cv, sv = rank(c["verified"]), rank(s["verified"])
        verdict = "show" if sv < cv else "control" if cv < sv else "tie"
        wins += verdict == "show"
        losses += verdict == "control"
        ties += verdict == "tie"
        slower += sw > cw
        faster += sw < cw
        print(f"{iid[-6:]:<8}{c['fired']:>5}/{s['fired']:<4}"
              f"{len(s['notes']):>6}{fmt(c['verified']):>8}"
              f"{fmt(s['verified']):>9}{cw:>9}{sw:>10}{verdict:>9}")

    n = len(pairs)
    tc = sum(p["control"]["wall_s"] for p in pairs.values())
    ts = sum(p["show"]["wall_s"] for p in pairs.values())
    rc = sum(bool(p["control"]["resolved"]) for p in pairs.values())
    rsv = sum(bool(p["show"]["resolved"]) for p in pairs.values())
    print(f"\nP1 liveness: first required-file run not clean in "
          f"{ctl_bound}/{n} control sessions ({100 * ctl_bound / max(n, 1):.0f}%;"
          f" bar 60%); era text visible in {ctl_fired}/{n}")
    print(f"P2 delivery: memory shown in {shown_when_fired}/{show_fired} "
          f"show sessions where the class fired (bar 80%); control "
          f"sessions with a note: {len(contaminated)} (must be 0)")
    print(f"P3 benefit: show {wins} / control {losses} / tied {ties}; "
          f"one-sided sign p = {sign_p(wins, wins + losses):.3f} (bar 0.05)")
    print(f"P4 no harm: show wall {ts}s vs control {tc}s "
          f"({100 * (ts - tc) / max(tc, 1):+.1f}%; bar +15%); slower on "
          f"{slower}, faster on {faster}; sign p (slower) = "
          f"{sign_p(slower, slower + faster):.3f}")
    print(f"resolved: control {rc}/{n}, show {rsv}/{n}")
    last = res[-1].get("ledger") if res else None
    print(f"P5 ledger (id, outcomes, value) at end: {last}")


if __name__ == "__main__":
    main()
