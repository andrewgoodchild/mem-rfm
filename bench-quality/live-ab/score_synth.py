#!/usr/bin/env python3
"""Score a synthesis track (REVALIDATION.md Tracks 5, 6, ...).

The one thing this tool exists to get right: **memories have two origins,
and conflating them silently inverts the score.** The correction miner
ratifies candidates at session end whether or not a nudge fired, and those
saves land in the same store and the same log as anything the agent
volunteers. Scoring Track 5 by hand, an early version counted ratified
miner candidates as volunteered saves and reported the capture prediction
as PASS when the synthesis channel had produced nothing at all, and the
no-op prediction as FAIL when nothing had leaked. Origin is therefore
classified first, from the miner's own template, and every prediction is
scored against the right population.

Usage: score_synth.py [--dir synth6] [--baseline-wall 2988]
"""
import argparse
import collections
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The miner's rendered template (session_end.main). Anything matching this
# came from the correction miner; anything else the agent wrote.
MINED_RE = re.compile(r"^In this project, `.+` fails \(", re.S)
# Classes formation_study.py marked NOT CAPTURED on the pytest corpus.
MISSED = ("modulenotfounderror", "pkg_resources", "importerror")
GENERIC = {"cd", "ls", "cat", "echo", "head", "tail", "pwd", "which",
           "true", "false", "sleep", "mkdir", "rm", "cp", "mv", "touch"}


def origin(content):
    return "mined" if MINED_RE.match(content or "") else "synthesized"


def sessions_from(log):
    """Per-session nudges and saves. Saves carry no session field, so they
    attribute to the preceding injection marker — the log is append-ordered
    within a run."""
    out, cur = [], None
    for line in open(log):
        r = json.loads(line)
        if r["op"] == "injection":
            cur = {"id": r["session"], "nudges": [], "saves": []}
            out.append(cur)
        elif cur is None:
            continue
        elif r["op"] == "synthesis_nudge":
            cur["nudges"].append(r)
        elif r["op"] == "save":
            cur["saves"].append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="synth6")
    ap.add_argument("--baseline-wall", type=float, default=2988.0,
                    help="Track 5 total wall seconds; the +15% bound")
    a = ap.parse_args()
    d = os.path.join(HERE, a.dir)
    log = os.path.join(d, "rfm-log.jsonl")
    if not os.path.exists(log):
        sys.exit(f"no log at {log}")

    sess = sessions_from(log)
    ops = collections.Counter(json.loads(l)["op"] for l in open(log))
    print(f"{a.dir}: {len(sess)} sessions   ops: {dict(ops)}\n")

    mems = []
    db = os.path.join(d, "rfm-memory.db")
    if os.path.exists(db):
        try:
            mems = sqlite3.connect(db).execute(
                "SELECT id, content FROM rfm_memories").fetchall()
        except sqlite3.Error:
            pass
    synth = [(i, c) for i, c in mems if origin(c) == "synthesized"]
    mined = [(i, c) for i, c in mems if origin(c) == "mined"]
    print(f"store: {len(mems)} memories — {len(mined)} mined, "
          f"{len(synth)} synthesized")

    print(f"\n{'session':10} {'nudges':>7} {'class':<24} {'program':<10} {'saves':>6}")
    for s in sess:
        n = s["nudges"][0] if s["nudges"] else None
        print(f"{s['id']:10} {len(s['nudges']):>7} "
              f"{(n['class'] if n else '-'):<24} "
              f"{(n.get('program','?') if n else '-'):<10} {len(s['saves']):>6}")

    fired = [s for s in sess if s["nudges"]]
    nudges = [n for s in sess for n in s["nudges"]]

    # P1 capture — synthesized memories only, naming a triggered class
    if not nudges:
        print("\nP1 capture: NOT TRIGGERED — no nudge fired in any session. "
              "The finding is the trigger rate, not the nudge.")
    else:
        hits = [(i, c) for i, c in synth
                if any(k in (c or "").lower() for k in MISSED)]
        print(f"\nP1 capture: {len(synth)} synthesized memories, {len(hits)} "
              f"naming a NOT CAPTURED class -> {'PASS' if hits else 'FAIL'}")
        for i, c in hits:
            print(f"    [{i}] {c[:200]}")

    # P2 trigger precision — no nudge may fire on a generic program
    if nudges:
        bad = [n for n in nudges if n.get("program") in GENERIC]
        print(f"P2 trigger precision: {len(nudges)} nudges, {len(bad)} on a "
              f"generic program -> {'PASS' if not bad else 'FAIL'}")
        for n in bad:
            print(f"    spurious: {n['class']} via {n['program']}")
    else:
        print("P2 trigger precision: NOT TRIGGERED")

    # P3 no-op discipline — SYNTHESIZED saves only; mined ones are not leaks
    quiet = [s for s in sess if not s["nudges"]]
    synth_ids = {i for i, _ in synth}
    leaked = [s for s in quiet
              if any(sv.get("id") in synth_ids for sv in s["saves"])]
    print(f"P3 no-op discipline: {len(quiet)} sessions without a nudge, "
          f"{len(leaked)} produced a synthesized memory anyway "
          f"-> {'PASS' if not leaked else 'FAIL'}")

    # P4 cost
    res = os.path.join(d, "results.jsonl")
    if os.path.exists(res):
        wall = sum(json.loads(l)["wall_s"] for l in open(res))
        delta = 100 * (wall - a.baseline_wall) / a.baseline_wall
        print(f"P4 cost: {wall}s vs baseline {a.baseline_wall:.0f}s "
              f"({delta:+.1f}%, bound +15%) -> "
              f"{'PASS' if delta <= 15 else 'FAIL'}")

    if fired and not synth:
        print("\nDiagnostic: the nudge fired and produced no synthesized "
              "memory. Check the transcripts for whether the model wrote the "
              "explanation into its response text instead — that was Track "
              "5's finding, and it is a different failure from the nudge not "
              "landing.")


if __name__ == "__main__":
    main()
