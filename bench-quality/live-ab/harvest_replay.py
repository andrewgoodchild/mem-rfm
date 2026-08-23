#!/usr/bin/env python3
"""Offline harvest: what would a prose channel capture that the miner cannot?

The correction miner reads Bash events. It has never read a word of what the
agent WROTE. Track 5 showed why that matters: nudged to record a root cause,
the model produced a precise causal explanation — into its response text,
and never into memory. Measuring the corpus afterwards, 64% of sessions
already contain such an explanation, written unprompted, and 34% mention
environment or tooling. The trigger we spent two registered tracks on fires
in 3%.

So the synthesis this project has been trying to elicit already exists, for
free, in most sessions. This tool asks what harvesting it would yield —
offline, over recorded transcripts, before any session is spent. Same
discipline as miner_replay.py: evaluate a formation change on the corpus we
already own.

It deliberately stops at the point where a judgement is needed. Separating
environment knowledge (transfers; ~22 outcomes on our best memory) from
per-bug knowledge (~6% transfer, measured) is a classification call on short
clean prose. That is the one formation job the literature does NOT argue
against an LLM doing — and it is a different job from topic segmentation
(heuristics win), structured extraction from raw transcripts (0.237 vs
0.830 on clean text), or admission filtering (an oracle filter buys ~0).
Conflating those four is what produced this project's earlier blanket
scepticism of LLM formation.

Usage: harvest_replay.py [--min-chars 200] [--show N]
"""
import argparse
import collections
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
AB = os.path.abspath(os.path.join(HERE, "..", "..",
                                  "integrations", "claude-code", "ab"))

# A causal explanation announces itself. Deliberately broad — the point is to
# measure the ceiling of the channel, not to ship this as the final filter.
CAUSE = re.compile(r"\b(root cause|the cause|caused by|fails because|"
                   r"the problem is|the issue is|due to|because)\b", re.I)
# Environment/tooling vocabulary: the class our corpus says transfers.
ENV = re.compile(r"\b(PYTHONPATH|virtualenv|venv|site-packages|pkg_resources|"
                 r"setuptools|pip install|import path|conftest|plugin|"
                 r"version mismatch|dependency|stub|editable install|"
                 r"ModuleNotFoundError|ImportError|ExtensionError)\b", re.I)
# Per-bug vocabulary: the class our corpus says does NOT transfer (~6%).
BUG = re.compile(r"\b(the bug|the fix|regression|patch|signature|"
                 r"docstring|refactor|edge case|off.by.one)\b", re.I)


def sessions():
    ablog = {r["ab_session"]: r.get("label", "")
             for r in (json.loads(l) for l in open(f"{AB}/ab_log.jsonl"))}
    for line in open(f"{AB}/ab_sessions.jsonl"):
        s = json.loads(line)
        lab, tp = ablog.get(s["ab_session"], ""), s.get("transcript_path")
        if lab and tp and os.path.exists(tp):
            yield lab, s["arm"], tp


def explanations(tp, min_chars):
    """Assistant prose blocks that read as causal explanation."""
    out = []
    for line in open(tp, errors="replace"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("type") != "assistant":
            continue
        c = (r.get("message") or {}).get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text":
                t = (b.get("text") or "").strip()
                if len(t) >= min_chars and CAUSE.search(t):
                    out.append(t)
    return out


def classify(text):
    """Cheap deterministic proxy for the judgement an LLM would make.

    MEASURED RESULT: this proxy does not work, and its failure is the most
    useful thing this tool produced. Run over the corpus it labels 34% of
    harvested explanations "environment", but inspection shows obvious
    per-bug explanations among them — a `_MockObject.__getitem__` type
    coercion and a `do_prompt` validator bug both scored environment,
    because per-bug explanations freely use words like plugin, version and
    conftest.

    Keyword matching cannot separate "this checkout's venv is broken in way
    X" from "this function had a bug". That separation is a semantic
    judgement on short clean prose — and it is precisely the one formation
    job the literature does not argue against an LLM doing. Kept here as the
    baseline any classifier must beat."""
    e, b = len(ENV.findall(text)), len(BUG.findall(text))
    if e and e >= b:
        return "environment"
    if b:
        return "per-bug"
    return "unclear"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-chars", type=int, default=200)
    ap.add_argument("--show", type=int, default=3)
    a = ap.parse_args()

    kinds = collections.Counter()
    per_session = collections.Counter()
    env_samples, total = [], 0
    for lab, arm, tp in sessions():
        total += 1
        ex = explanations(tp, a.min_chars)
        if not ex:
            per_session["none"] += 1
            continue
        # One memory per session at most: take the longest explanation, the
        # same "one per session" discipline the nudge used.
        best = max(ex, key=len)
        k = classify(best)
        kinds[k] += 1
        per_session["harvested"] += 1
        if k == "environment":
            env_samples.append((lab, best))

    print(f"transcripts scanned: {total}")
    print(f"  would harvest an explanation: {per_session['harvested']} "
          f"({100*per_session['harvested']/max(total,1):.0f}%)")
    print(f"  no qualifying prose:          {per_session['none']}\n")
    print("harvested explanations by class (deterministic proxy):")
    for k, n in kinds.most_common():
        print(f"  {k:12} {n:4}  ({100*n/max(sum(kinds.values()),1):.0f}%)")

    print(f"\n--- environment-class samples (the transferable class) ---")
    for lab, t in env_samples[:a.show]:
        print(f"\n[{lab}]\n{t[:500]}")

    print(f"\nFor comparison: the struggle trigger of Tracks 5-6 fired in 3 of "
          f"102 sessions (3%). This channel reaches "
          f"{100*per_session['harvested']/max(total,1):.0f}% and needs no "
          f"trigger, no nudge, and no LLM call to obtain the raw material.")


if __name__ == "__main__":
    main()
