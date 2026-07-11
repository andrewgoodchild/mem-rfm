#!/usr/bin/env python3
"""A/B stats: mem-rfm arm vs control arm from real Claude Code sessions.

Joins three local sources:
  1. ab_log.jsonl        — arm assignments (ab-claude), incl. forced flag and
                           an ab_session marker
  2. Claude Code session transcripts (~/.claude/projects/<munged-cwd>/*.jsonl)
     matched by the injected [rfm-memory:<ab_session>] marker when present,
     else by first-timestamp-in-window; transcripts carrying an rfm injection
     marker are never attributed to control assignments
  3. the rfm memory DB   — accesses/outcomes in each rfm session's window

Metrics per session: human user turns (isMeta records excluded), assistant
output tokens (deduplicated by message.id — Claude Code repeats usage across
one record per content block), Edit/Write calls, wall duration, rfm tool
usage. Forced-arm sessions are EXCLUDED from the stats by default
(self-selection); include with --include-forced.

Usage: ab_stats.py [--log ab/ab_log.jsonl] [--min-turns 2] [--include-forced]
"""
import argparse
import datetime as dt
import functools
import glob
import json
import os
import re
import sqlite3

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.expanduser(os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))
SIDECAR = os.path.join(HERE, "ab_sessions.jsonl")
# Format contract with hooks/session_start.py's injection marker.
MARKER_RE = re.compile(r"\[rfm-memory:([^\]]+)\]")


def munge(cwd: str) -> str:
    """Claude Code's project-dir munging: every non-alphanumeric becomes '-'.
    (Very long paths additionally get truncated+hashed — unhandled here; if
    your cwd path is >~100 chars, pass transcripts explicitly.)"""
    return re.sub(r"[^a-zA-Z0-9]", "-", cwd)


def parse_iso(ts: str) -> float:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def peek(path, max_lines=20):
    """Cheap look at a transcript's opening records: first timestamp and any
    injection marker, without parsing the whole file."""
    first_ts, marker = None, None
    with open(path) as f:
        for _ in range(max_lines):
            line = f.readline()
            if not line:
                break
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("timestamp")
            if ts and first_ts is None:
                first_ts = parse_iso(ts)
            content = (rec.get("message") or {}).get("content")
            if isinstance(content, str) and marker is None:
                m = MARKER_RE.search(content)
                if m:
                    marker = m.group(1)
    return first_ts, marker


@functools.cache
def transcript_metrics(path):
    """Best-effort parse of one Claude Code session JSONL."""
    user_turns = out_tokens = edits = rfm_calls = 0
    first_ts = last_ts = None
    seen_msg_ids = set()
    marker = None
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
            if rec.get("type") == "user":
                content = msg.get("content")
                if isinstance(content, str):
                    m = MARKER_RE.search(content)
                    if m:
                        marker = m.group(1)
                    # Count only genuine human prompts: hook injections,
                    # command caveats etc. are isMeta and would otherwise
                    # inflate the rfm arm (whose hook injects context).
                    if not rec.get("isMeta"):
                        user_turns += 1
            if rec.get("type") == "assistant":
                usage = msg.get("usage") or {}
                # One API message is written as one record PER CONTENT BLOCK,
                # each repeating the same usage — dedup by message id
                # (measured ~2.9x overcount otherwise).
                mid = msg.get("id")
                if mid is None or mid not in seen_msg_ids:
                    seen_msg_ids.add(mid)
                    out_tokens += usage.get("output_tokens", 0) or 0
                for block in msg.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "")
                        if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                            edits += 1
                        if "memory_" in name:
                            rfm_calls += 1
    return {"user_turns": user_turns, "out_tokens": out_tokens, "edits": edits,
            "rfm_calls": rfm_calls, "first_ts": first_ts, "last_ts": last_ts,
            "marker": marker}


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
    """Vectorized CI on mean(a) - mean(b)."""
    rng = np.random.default_rng(seed)
    a, b = np.asarray(a, float), np.asarray(b, float)
    means_a = rng.choice(a, size=(n, len(a)), replace=True).mean(axis=1)
    means_b = rng.choice(b, size=(n, len(b)), replace=True).mean(axis=1)
    diffs = means_a - means_b
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def load_assignments(log_path):
    out, bad = [], 0
    for i, line in enumerate(open(log_path), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
            print(f"WARNING: skipping malformed log line {i}")
    if bad:
        print(f"WARNING: {bad} malformed assignment line(s) skipped")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.path.join(HERE, "ab_log.jsonl"))
    ap.add_argument("--min-turns", type=int, default=2,
                    help="ignore trivial sessions with fewer human turns")
    ap.add_argument("--include-forced", action="store_true",
                    help="include --arm forced sessions (self-selected!)")
    args = ap.parse_args()
    if not os.path.exists(args.log):
        raise SystemExit(f"no assignment log at {args.log} — run some ab-claude sessions first")

    assignments = load_assignments(args.log)
    forced = [a for a in assignments if a.get("forced")]
    if forced and not args.include_forced:
        print(f"note: excluding {len(forced)} forced-arm session(s) "
              "(self-selected; --include-forced to keep)")
        assignments = [a for a in assignments if not a.get("forced")]

    # Primary join: the sidecar the SessionStart hook writes for both arms
    # (ab_session -> exact transcript path). Marker/window matching remains
    # as fallback for sessions predating the sidecar or missing hook setup.
    sidecar = {}
    if os.path.exists(SIDECAR):
        for line in open(SIDECAR):
            try:
                rec = json.loads(line)
                if rec.get("transcript_path"):
                    sidecar[rec["ab_session"]] = rec["transcript_path"]
            except json.JSONDecodeError:
                continue

    sessions = []
    claimed = set()
    for asg in assignments:
        best_path = sidecar.get(asg.get("ab_session"))
        if best_path and (best_path in claimed or not os.path.exists(best_path)):
            best_path = None
        if best_path is None:
            # Fallback: cheap peek over the project dir, full parse only on
            # the chosen candidate.
            proj_dir = os.path.expanduser(f"~/.claude/projects/{munge(asg['cwd'])}")
            candidates = []
            for path in glob.glob(os.path.join(proj_dir, "*.jsonl")):
                if path in claimed:
                    continue
                first_ts, marker = peek(path)
                if first_ts is None:
                    continue
                # Identity beats window; a transcript with an rfm injection
                # marker can never belong to a control assignment.
                if marker and marker == asg.get("ab_session"):
                    candidates = [(0.0, path)]
                    break
                if asg["arm"] == "control" and marker:
                    continue
                if asg["start"] - 60 <= first_ts <= asg["end"] + 60:
                    candidates.append((abs(first_ts - asg["start"]), path))
            if not candidates:
                continue
            _, best_path = min(candidates)
        best = transcript_metrics(best_path)
        if best["user_turns"] < args.min_turns:
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
          f"(from {len(assignments)} randomized assignments)")
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
