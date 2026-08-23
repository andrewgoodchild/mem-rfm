#!/usr/bin/env python3
"""Formation instrument: what was expensive to learn, and did we capture it?

Every experiment in this repository so far has measured RANKING — given a
store, does the prior order it well. This measures FORMATION — is the right
thing in the store at all — using the one asset the live A/B program
produces and nothing else does: a control arm that never had memory and
therefore had to re-derive everything from scratch, paired task-by-task
against an arm that didn't.

Three views:

  counterfactual  Events before the arm's first green test run. Control
                  pays full price for the environment; the memory arm is
                  handed it. The paired gap is a memory's worth measured in
                  work avoided, not in hit@k.

  cost            Re-derivation cost per error class, counted in the
                  CONTROL arm only. Control never has the memory, so this
                  is an unbiased estimate of what the knowledge costs to
                  obtain. (Counting it in the memory arm measures the
                  memory's success instead — once the workaround is known
                  the error stops appearing. That endogeneity is why this
                  view is control-only.)

  coverage        The scorecard: for each expensive class, did formation
                  actually store anything about it? Precision is what
                  earned; recall is whether the costly knowledge got in.

Usage: formation_study.py [--runs pilot2,reval-sphinx,...]
"""
import argparse
import collections
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
AB = os.path.join(REPO, "integrations", "claude-code", "ab")
os.environ.setdefault("RFM_LOG", "0")
os.environ.setdefault("RFM_MEMORY_DB", os.path.join(HERE, "_none.db"))
sys.path.insert(0, os.path.join(REPO, "integrations", "claude-code", "hooks"))
sys.path.insert(0, os.path.join(REPO, "integrations", "claude-code"))
sys.path.insert(0, REPO)
import session_end as se  # noqa: E402

RUNS = ["pilot2", "pilot3", "pilot4", "reval-pytest", "reval-sphinx",
        "reval-xarray", "tax"]
GREEN = re.compile(r"\b\d+ passed\b", re.I)
# Error classes worth pricing: a named cause, not an assertion failure in the
# code under test. Same discipline as the miner's FAILURE vocabulary.
SIGNATURE = re.compile(
    r"\b(?:ModuleNotFoundError|ImportError|ExtensionError"
    r"|VersionRequirementError|DistributionNotFound|AttributeError"
    r"|FileNotFoundError|TypeError)\b"
    r"|pkg_resources|command not found|No such file or directory"
    r"|bad interpreter|unsupported tag", re.I)


def sessions(runs):
    ablog = {}
    for line in open(os.path.join(AB, "ab_log.jsonl")):
        r = json.loads(line)
        lab = str(r.get("label", ""))
        for run in runs:
            if lab.startswith(run + "-"):
                ablog[r["ab_session"]] = (run, lab[len(run) + 1:])
                break
    out = []
    for line in open(os.path.join(AB, "ab_sessions.jsonl")):
        s = json.loads(line)
        meta = ablog.get(s["ab_session"])
        tp = s.get("transcript_path")
        if not meta or not tp or not os.path.exists(tp):
            continue
        run, task, arm = meta[0], meta[1], s["arm"]
        if run == "tax":            # tax encodes the arm in the label suffix
            arm = "idle" if task.endswith("-idle") else "control"
            task = task.rsplit("-", 1)[0]
        out.append((run, task, arm, tp))
    return out


_cache = {}


def events_of(tp):
    if tp not in _cache:
        _cache[tp] = se.load_events(se._parse_transcript(tp))
    return _cache[tp]


def first_green(events):
    for i, e in enumerate(events):
        if e.got and not e.is_err and "pytest" in e.cmd and GREEN.search(e.body or ""):
            return i
    return None


def view_counterfactual(S):
    print("=== counterfactual: Bash events before the first green test run ===")
    print("(lower is better; 'never' = the session never got a passing test)\n")
    by = collections.defaultdict(dict)
    for run, task, arm, tp in S:
        by[(run, task)][arm] = first_green(events_of(tp))
    for run in sorted({r for r, _ in by}):
        rows = [(t, d) for (r, t), d in by.items() if r == run]
        if not rows:
            continue
        mem_arm = "idle" if run == "tax" else "rfm"
        wins = losses = ties = 0
        c_never = m_never = 0
        print(f"-- {run}")
        for task, d in sorted(rows):
            c, m = d.get("control"), d.get(mem_arm)
            c_never += c is None
            m_never += m is None
            if c is not None and m is not None:
                wins += m < c
                losses += m > c
                ties += m == c
            f = lambda x: "never" if x is None else str(x)
            print(f"   {task[:34]:34} control={f(c):>6}  {mem_arm}={f(m):>6}")
        print(f"   -> memory arm faster on {wins}, slower on {losses}, tied on "
              f"{ties}; never-green: control {c_never}, {mem_arm} {m_never}\n")


def view_cost(S):
    print("=== re-derivation cost, priced in the CONTROL arm only ===")
    print("(events = failed commands hitting the class; the memory arm is "
          "excluded by design — see module docstring)\n")
    out = {}
    for run in sorted({r for r, _, _, _ in S}):
        ctl = [(t, events_of(tp)) for r, t, a, tp in S
               if r == run and a == "control"]
        if not ctl:
            continue
        hits = collections.Counter()
        sess = collections.defaultdict(set)
        for task, evs in ctl:
            for e in evs:
                if not e.got:
                    continue
                for m in set(x.group(0).lower() for x in SIGNATURE.finditer(e.body or "")):
                    hits[m] += 1
                    sess[m].add(task)
        if not hits:
            continue
        print(f"-- {run} ({len(ctl)} control sessions)")
        for cls, n in hits.most_common(6):
            print(f"   {cls[:34]:34} {n:3} events   {len(sess[cls])}/{len(ctl)} sessions")
        out[run] = hits
        print()
    return out


def view_coverage(cost):
    print("=== coverage scorecard: was the expensive knowledge captured? ===")
    print("(a class is COVERED if any stored memory's text mentions it)\n")
    for run, hits in cost.items():
        db = os.path.join(HERE, run, "rfm-memory.db")
        if not os.path.exists(db):
            continue
        try:
            mems = sqlite3.connect(db).execute(
                "SELECT content, value_score, outcome_count FROM rfm_memories"
            ).fetchall()
        except sqlite3.Error:
            continue
        earned = sum(1 for _, v, n in mems if v > 0 and n > 0)
        print(f"-- {run}: {len(mems)} memories stored, {earned} earned value")
        for cls, n in hits.most_common(4):
            covering = [(v, o) for c, v, o in mems if cls.lower() in (c or "").lower()]
            if not covering:
                verdict = "NOT CAPTURED"
            elif any(v > 0 and o > 0 for v, o in covering):
                verdict = f"captured, earned ({len(covering)} memor(y/ies))"
            else:
                verdict = f"captured but inert ({len(covering)})"
            print(f"   {cls[:30]:30} cost {n:3} events -> {verdict}")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=",".join(RUNS))
    a = ap.parse_args()
    runs = [r.strip() for r in a.runs.split(",") if r.strip()]
    S = sessions(runs)
    print(f"{len(S)} sessions with surviving transcripts\n")
    view_counterfactual(S)
    view_coverage(view_cost(S))


if __name__ == "__main__":
    main()
