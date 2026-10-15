#!/usr/bin/env python3
"""Show-on-error (RFM_JIT) replay over the surviving live-A/B record.

EXPLORATORY, not pre-registered. Reads data only; runs nothing.

The question: if memories were surfaced at the moment a tool call failed
with their condition class (hooks/post_tool_use.py::jit_inject, keyed by
session_end.error_signature / signature_match) instead of top-3 at
session start, which positive outcomes would still have been delivered,
and what would the trigger have surfaced that earned nothing?

The ideal replay walks every failing tool result in the session
transcripts. Those transcripts no longer exist (Claude Code's retention
removed them; ab_sessions.jsonl points at deleted files), so this replay
works at SESSION level from what survives:

  coverage   every positive outcome in every run log (outcome_inferred +1
             and feedback helped=true), joined to the run's store: does
             the memory carry a condition class at all (JIT can never
             surface an unconditioned memory), was it already in the
             session-start top-3, and how many same-class rivals share
             its class in that store (signature keys must separate them).
  precision  Track 19, the one run whose session_end lines log the
             condition classes that fired: per session, what JIT would
             surface on those classes (no keys recoverable, so only
             SPECIFIC classes can surface anything — the conservative
             reading), and whether the surfaced memory earned an outcome.
             Track 19's paired results give the wall-clock tax of the
             session-start injection that JIT would have withheld.

Usage: jit_replay.py [--data DIR] [--ab DIR]
  --data  the live-ab directory holding the untracked run dirs
          (default: this script's directory)
  --ab    the ab/ directory holding ab_log.jsonl / ab_sessions.jsonl
"""
import argparse
import collections
import json
import os
import sqlite3
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
os.environ.setdefault("RFM_LOG", "0")
os.environ.setdefault("RFM_MEMORY_DB", os.path.join(HERE, "_none.db"))
sys.path.insert(0, os.path.join(REPO, "integrations", "claude-code", "hooks"))
sys.path.insert(0, os.path.join(REPO, "integrations", "claude-code"))
sys.path.insert(0, REPO)
import session_end as se  # noqa: E402

RUNS = ["pilot2", "pilot3", "pilot4", "reval-pytest", "reval-sphinx",
        "reval-xarray", "synth", "synth6", "track10", "track11", "track13",
        "track19"]


def store(data, run):
    p = os.path.join(data, run, "rfm-memory.db")
    if not os.path.exists(p):
        return {}
    db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    cols = {r[1] for r in db.execute("PRAGMA table_info(rfm_memories)")}
    cc = "condition_class" if "condition_class" in cols else "NULL"
    out = {}
    for mid, content, created, cond in db.execute(
            f"SELECT id, content, created_at, {cc} FROM rfm_memories"):
        cond = se.derive_condition(content) if cond is None else cond
        out[mid] = {"content": content, "created": created,
                    "classes": {c for c in cond.split(",") if c}}
    db.close()
    return out


def sessions(data, run):
    """[(session, t, injected ids, searched ids, positives, end record)]
    in log order. Outcome and feedback lines between an injection and its
    session_end belong to that session."""
    out, cur = [], None
    path = os.path.join(data, run, "rfm-log.jsonl")
    if not os.path.exists(path):
        return out
    for line in open(path):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        op = r.get("op")
        if op == "injection":
            cur = {"session": r.get("session"), "t": r["t"],
                   "injected": [d["id"] for d in r.get("results", [])],
                   "searched": set(), "pos": [], "end": None}
            out.append(cur)
        elif cur is None:
            continue
        elif op == "search":
            cur["searched"].update(d["id"] for d in r.get("results", []))
        elif op == "outcome_inferred" and r.get("outcome", 0) > 0:
            cur["pos"].append((r["id"], "inferred"))
        elif op == "feedback" and r.get("outcome", 0) > 0:
            cur["pos"].append((r["id"], "explicit"))
        elif op == "session_end":
            cur["end"] = r
            cur = None
    return out


def coverage(data):
    print("=== coverage: positive outcomes JIT could have delivered ===")
    print("(conditioned = the memory names a condition class; only those "
          "can ever be surfaced on error)\n")
    tot = collections.Counter()
    by_class = collections.Counter()
    for run in RUNS:
        mems = store(data, run)
        c = collections.Counter()
        for s in sessions(data, run):
            for mid, kind in s["pos"]:
                m = mems.get(mid)
                c["pos"] += 1
                if m is None:
                    c["deleted"] += 1
                    continue
                c["in_top3"] += mid in s["injected"]
                c["searched_only"] += (mid not in s["injected"]
                                       and mid in s["searched"])
                if not m["classes"]:
                    c["unconditioned"] += 1
                    continue
                c["conditioned"] += 1
                by_class[",".join(sorted(m["classes"]))] += 1
                specific = bool(m["classes"] & se.SPECIFIC_CLASSES)
                c["generic_only"] += not specific
                rivals = [o for o, om in mems.items() if o != mid
                          and om["classes"] & m["classes"]
                          and (om["created"] or 0) <= s["t"]]
                c["conditioned_w_rivals"] += bool(rivals)
        if c["pos"]:
            print(f"{run:13s} +{c['pos']:3d}  in session-start top-3 "
                  f"{c['in_top3']:3d}  via search only {c['searched_only']:2d}"
                  f"  conditioned {c['conditioned']:3d} "
                  f"(with same-class rivals {c['conditioned_w_rivals']:3d})"
                  f"  unconditioned {c['unconditioned']:3d}"
                  f"  deleted {c['deleted']}")
        tot.update(c)
    print(f"{'ALL':13s} +{tot['pos']:3d}  in session-start top-3 "
          f"{tot['in_top3']:3d}  via search only {tot['searched_only']:2d}"
          f"  conditioned {tot['conditioned']:3d} "
          f"(with same-class rivals {tot['conditioned_w_rivals']:3d})"
          f"  unconditioned {tot['unconditioned']:3d}"
          f"  deleted {tot['deleted']}")
    print(f"conditioned on a GENERIC class only (needs a shared signature "
          f"key to surface): {tot['generic_only']}")
    print("by class:", dict(by_class.most_common()))
    print("\nNo positive can exist for a memory never shown, so 'in top-3 or "
          "searched' is 100% by construction:\nthe log cannot show a memory "
          "JIT would have delivered that session start missed.\n")
    return tot


def track19(data, ab):
    print("=== precision + tax: Track 19 (fired classes logged per session) ===")
    run = "track19"
    mems = store(data, run)
    label = {}
    ablog = {}
    for line in open(os.path.join(ab, "ab_log.jsonl")):
        r = json.loads(line)
        ablog[r["ab_session"]] = str(r.get("label", ""))
    for line in open(os.path.join(ab, "ab_sessions.jsonl")):
        s = json.loads(line)
        lab = ablog.get(s["ab_session"], "")
        if lab.startswith("track19-") and s.get("session_id"):
            label[s["session_id"][:8]] = lab[len("track19-"):]
    wall = collections.defaultdict(dict)
    for line in open(os.path.join(data, run, "results.jsonl")):
        r = json.loads(line)
        wall[r["instance_id"]][r["arm"]] = r["wall_s"]

    eligible = set()            # passed the quarantine = was ever injected
    fires, surfaced, earned = 0, collections.Counter(), 0
    tax = {"jit_fires": [], "jit_silent": []}
    n = 0
    for s in sessions(data, run):
        if not s["end"]:
            continue
        n += 1
        eligible.update(s["injected"])
        fired = s["end"].get("conditions") or []
        sig = {"classes": tuple(fired), "keys": frozenset()} if fired else None
        pick = None
        for mid in sorted(eligible):
            m = se.signature_match(sig, mems[mid]["content"],
                                   ",".join(sorted(mems[mid]["classes"])))
            if m is not None:
                pick = mid
                break
        if pick is not None:
            fires += 1
            surfaced[pick] += 1
            earned += any(p == pick for p, _ in s["pos"])
        task = label.get(s["session"], "").rsplit("-", 1)[0]
        w = wall.get(task, {})
        if "sweep" in w and "control" in w and s["injected"]:
            key = "jit_fires" if pick is not None else "jit_silent"
            tax[key].append(w["sweep"] - w["control"])
    print(f"sessions {n}; session-start injected in "
          f"{sum(1 for s in sessions(data, run) if s['injected'])}; "
          f"JIT would fire in {fires}; surfaced {dict(surfaced)}; "
          f"surfaced memory earned an outcome in {earned} of {fires}")
    for k, v in tax.items():
        if v:
            print(f"  injected sessions where JIT would be {k[4:]:6s}: "
                  f"n={len(v):2d}  sweep-control wall median "
                  f"{statistics.median(v):+.0f}s  mean "
                  f"{statistics.mean(v):+.0f}s  slower in "
                  f"{sum(x > 0 for x in v)}")
    print("(firing is endogenous to injection here — Track 19's control arm "
          "saw the era class in 1 of 20 sessions)\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=HERE)
    ap.add_argument("--ab", default=os.path.join(
        REPO, "integrations", "claude-code", "ab"))
    a = ap.parse_args()
    coverage(a.data)
    track19(a.data, a.ab)


if __name__ == "__main__":
    main()
