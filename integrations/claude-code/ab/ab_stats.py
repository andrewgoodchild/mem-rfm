#!/usr/bin/env python3
"""A/B stats: mem-rfm arm vs control arm from real Claude Code sessions.

Joins three local sources:
  1. ab_log.jsonl        — arm assignments with start/end epochs (ab-claude)
  2. Claude Code session transcripts (~/.claude/projects/<munged-cwd>/*.jsonl)
     matched to assignments by first-timestamp-in-window
  3. the rfm memory DB   — searches/outcomes in each rfm session's window

Per-session metrics: user turns (interaction effort), assistant output
tokens, wall duration, Edit/Write tool calls, rfm tool usage. Reports per-arm
means/medians and a bootstrap CI on the arm difference. Honest caveats
printed with every report: self-experiment, task heterogeneity, small n —
treat as directional until n >= ~20 per arm on comparable task labels.

Usage: ab_stats.py [--log ab/ab_log.jsonl] [--min-turns 2]
"""
import argparse
import glob
import json
import os
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.expanduser(os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))


def munge(cwd: str) -> str:
    return cwd.replace("/", "-").replace(".", "-").replace("_", "-")


def parse_iso(ts: str) -> float:
    import datetime as dt
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def transcript_metrics(path):
    """Best-effort parse of one Claude Code session JSONL."""
    user_turns = out_tokens = edits = rfm_calls = 0
    first_ts = last_ts = None
    with open(path) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("timestamp")
            if ts:
                t = parse_iso(ts)
                first_ts = t if first_ts is None else min(first_ts, t)
                last_ts = t if last_ts is None else max(last_ts, t)
            msg = rec.get("message") or {}
            if rec.get("type") == "user" and isinstance(msg.get("content"), str):
                user_turns += 1
            if rec.get("type") == "assistant":
                usage = msg.get("usage") or {}
                out_tokens += usage.get("output_tokens", 0) or 0
                for block in msg.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "")
                        if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                            edits += 1
                        if "memory_" in name:
                            rfm_calls += 1
    return {"user_turns": user_turns, "out_tokens": out_tokens, "edits": edits,
            "rfm_calls": rfm_calls, "first_ts": first_ts, "last_ts": last_ts}


def rfm_db_window(start, end):
    if not os.path.exists(DB_PATH):
        return {}
    db = sqlite3.connect(DB_PATH)
    try:
        acc, outc = db.execute(
            "SELECT count(*), count(outcome) FROM rfm_accesses "
            "WHERE accessed_at BETWEEN ? AND ?", (start, end)).fetchone()
        return {"rfm_accesses": acc, "rfm_outcomes": outc}
    finally:
        db.close()


def bootstrap_ci(a, b, n=10_000, seed=7):
    """CI on mean(a) - mean(b)."""
    rng = np.random.default_rng(seed)
    a, b = np.asarray(a, float), np.asarray(b, float)
    diffs = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(n)]
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.path.join(HERE, "ab_log.jsonl"))
    ap.add_argument("--min-turns", type=int, default=2,
                    help="ignore trivial sessions with fewer user turns")
    args = ap.parse_args()
    if not os.path.exists(args.log):
        raise SystemExit(f"no assignment log at {args.log} — run some ab-claude sessions first")

    assignments = [json.loads(l) for l in open(args.log) if l.strip()]
    sessions = []
    claimed = set()  # each transcript belongs to at most one assignment
    for asg in assignments:
        proj_dir = os.path.expanduser(f"~/.claude/projects/{munge(asg['cwd'])}")
        best, best_path = None, None
        for path in glob.glob(os.path.join(proj_dir, "*.jsonl")):
            if path in claimed:
                continue
            m = transcript_metrics(path)
            if m["first_ts"] is None:
                continue
            # transcript belongs to this assignment if it started in-window;
            # among candidates prefer the one starting closest to launch time
            if asg["start"] - 60 <= m["first_ts"] <= asg["end"] + 60:
                if best is None or (abs(m["first_ts"] - asg["start"])
                                    < abs(best["first_ts"] - asg["start"])):
                    best, best_path = m, path
        if best is None or best["user_turns"] < args.min_turns:
            continue
        claimed.add(best_path)
        row = {"arm": asg["arm"], "label": asg.get("label", ""),
               "duration_s": asg["end"] - asg["start"], **best}
        if asg["arm"] == "rfm":
            row.update(rfm_db_window(asg["start"], asg["end"]))
        sessions.append(row)

    arms = {"rfm": [s for s in sessions if s["arm"] == "rfm"],
            "control": [s for s in sessions if s["arm"] == "control"]}
    print(f"matched sessions: rfm={len(arms['rfm'])}, control={len(arms['control'])} "
          f"(from {len(assignments)} assignments)")
    if not arms["rfm"] or not arms["control"]:
        raise SystemExit("need sessions in BOTH arms before stats mean anything")

    print(f"\n| metric | rfm mean (median) | control mean (median) | diff [95% CI] |")
    print("|---|---|---|---|")
    for metric in ("user_turns", "out_tokens", "edits", "duration_s"):
        a = [s[metric] for s in arms["rfm"]]
        b = [s[metric] for s in arms["control"]]
        lo, hi = bootstrap_ci(a, b)
        print(f"| {metric} | {np.mean(a):.1f} ({np.median(a):.0f}) "
              f"| {np.mean(b):.1f} ({np.median(b):.0f}) "
              f"| {np.mean(a)-np.mean(b):+.1f} [{lo:+.1f}, {hi:+.1f}] |")
    used = [s for s in arms["rfm"] if s.get("rfm_calls", 0) > 0]
    print(f"\nrfm-arm sessions actually using memory tools: {len(used)}/{len(arms['rfm'])}")
    if used:
        print(f"  mean memory calls when used: "
              f"{np.mean([s['rfm_calls'] for s in used]):.1f}; "
              f"db accesses in-window: "
              f"{np.mean([s.get('rfm_accesses', 0) for s in used]):.1f}")
    n = min(len(arms["rfm"]), len(arms["control"]))
    print(f"\nCAVEATS: self-experiment; tasks differ between sessions; n={n} per arm "
          f"{'(directional only — aim for >=20)' if n < 20 else ''}. "
          "Lower user_turns/duration on comparable labels = memory helped. "
          "Compare within matching labels when possible.")


if __name__ == "__main__":
    main()
