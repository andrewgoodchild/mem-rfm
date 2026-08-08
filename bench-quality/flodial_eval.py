#!/usr/bin/env python3
"""FloDial team-memory eval (pre-registered replication, diagnosis domain).

Data: FloDial (dair-iitd, CDLA-Sharing-1.0) — 1,844 troubleshooting dialogs
grounded in 12 genuinely AUTHORED flowcharts (car/laptop repair) plus
supporting FAQs. A domain unlike ABCD's policy work or MD2D's document QA:
diagnostic decision trees.

Query = the user's opening problem description; memory = problem + the
agent's grounded diagnostic steps; label = the dialog's flowchart. Manual =
one entry per flowchart (problem description + node utterances + FAQs).
Only 12 label classes, so hit@5 saturates by construction — hit@1 is the
metric that matters here (disclosed; the pre-registration binds endpoints
to hit@1 for this dataset). No natural order or agent IDs: seeded shuffle +
round-robin agents (disclosed). No LLM; oracle outcomes (disclosed).

Usage: flodial_eval.py [--n 1844] [--k 5] [--agents 8]
"""
import argparse
import glob
import json
import os
import random

import common
import team_common

DATA = os.path.join(common.HERE, "data", "flodial")
CACHE = os.path.join(common.HERE, "cache-flodial" + common.cache_suffix())


def load_calls(n, agents):
    dialogs = json.load(open(os.path.join(DATA, "dialogs", "dialogs.json")))
    items = list(dialogs.items())
    random.Random(13).shuffle(items)
    calls = []
    for _did, d in items:
        utts = d["utterences"]
        user = [u["utterance"] for u in utts if u["speaker"] == "user"]
        agent_utts = [u["utterance"] for u in utts if u["speaker"] == "agent"]
        if not user:
            continue
        calls.append({
            "label": d["flowchart"],
            "query": " ".join(user[:2]),
            "memory": "reported problem: " + " ".join(user[:2]) +
                      " | diagnosis steps: " + "; ".join(agent_utts[:4]),
        })
        if len(calls) >= n:
            break
    for i, c in enumerate(calls):
        c["agent"] = i % agents
    return calls


def load_manual():
    entries = []
    for f in sorted(glob.glob(os.path.join(DATA, "knowledge-sources", "*.json"))):
        ks = json.load(open(f))
        nodes = "; ".join(nd["utterance"] for nd in ks["nodes"].values())
        faqs = " ".join(
            f"{q.get('question', '')} {q.get('answer', '')}"
            for q in (ks.get("supporting_faqs") or [])[:6]
            if isinstance(q, dict))
        entries.append({
            "label": ks["name"],
            "text": (f"troubleshooting flowchart: {ks['name']} "
                     f"({ks['category']}). {ks['problem_description']} "
                     f"steps: {nodes} {faqs}")[:1500],
        })
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1844)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--agents", type=int, default=8)
    args = ap.parse_args()

    calls = load_calls(args.n, args.agents)
    manual = load_manual()
    labels = {c["label"] for c in calls}
    covered = {m["label"] for m in manual}
    missing = labels - covered
    if missing:
        raise RuntimeError(f"manual does not cover flowcharts: {sorted(missing)}")

    team_common.run(
        "FloDial", calls, manual, args.k,
        CACHE, f"n{args.n}",
        results_path=os.path.join(common.HERE, "results-flodial",
                                  "per_call.jsonl") if args.n >= 1500 else None)


if __name__ == "__main__":
    os.makedirs(os.path.join(common.HERE, "results-flodial"), exist_ok=True)
    main()
