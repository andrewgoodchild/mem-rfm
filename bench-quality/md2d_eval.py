#!/usr/bin/env python3
"""MultiDoc2Dial team-memory eval (pre-registered replication, large label
space).

Data: MultiDoc2Dial (IBM, CC-BY-3.0) — 4,796 dialogs grounded in 488 REAL
authored government documents (dmv/ssa/va/studentaid), per-turn grounding
annotations. The manual arm is native: the manual IS the 488 documents.

Per dialog: query = the user's opening utterance; the dialog's memory is
labeled with the first agent turn's primary grounding doc; a retrieval HIT
accepts any document the dialog's agent turns actually cited (dialogs span
multiple docs by construction — a stricter single-doc criterion is reported
by the primary label only through per-call output). No natural order or
agent IDs: seeded shuffle + round-robin agents as in ABCD (disclosed).
No LLM anywhere; oracle evidence-hit outcomes (disclosed).

Usage: md2d_eval.py [--n 4700] [--k 5] [--agents 8]
"""
import argparse
import json
import os
import random

import common
import team_common

DATA = os.path.join(common.HERE, "data", "multidoc2dial")
CACHE = os.path.join(common.HERE, "cache-md2d" + common.cache_suffix())


def load_calls(n, agents):
    dialogs = []
    for split in ("train", "validation"):
        d = json.load(open(os.path.join(DATA, f"multidoc2dial_dial_{split}.json")))
        for domain, convs in d["dial_data"].items():
            dialogs.extend(convs)
    random.Random(13).shuffle(dialogs)
    calls = []
    for c in dialogs:
        turns = c["turns"]
        user = [t["utterance"] for t in turns if t["role"] == "user"]
        agent_turns = [t for t in turns if t["role"] == "agent"]
        cited = [r["doc_id"] for t in agent_turns for r in t.get("references", [])]
        if not user or not cited:
            continue
        calls.append({
            "label": cited[0],
            "gold": set(cited),
            "query": " ".join(user[:2]),
            "memory": "user question: " + " ".join(user[:2]) +
                      " | answered from: " + cited[0].split("#")[0] +
                      " | agent: " + " ".join(t["utterance"] for t in agent_turns[:2]),
        })
        if len(calls) >= n:
            break
    for i, c in enumerate(calls):
        c["agent"] = i % agents
    return calls


def load_manual():
    docs = json.load(open(os.path.join(DATA, "multidoc2dial_doc.json")))
    entries = []
    for domain, dd in docs["doc_data"].items():
        for doc_id, doc in dd.items():
            entries.append({
                "label": doc_id,
                "text": (f"document ({domain}): {doc['title']}. "
                         f"{doc['doc_text']}")[:1500],
            })
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4700)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--agents", type=int, default=8)
    args = ap.parse_args()

    calls = load_calls(args.n, args.agents)
    manual = load_manual()

    team_common.run(
        "MultiDoc2Dial", calls, manual, args.k,
        CACHE, f"n{args.n}",
        results_path=os.path.join(
            common.HERE, "results-md2d",
            f"per_call{common.cache_suffix()}.jsonl") if args.n >= 4000 else None)


if __name__ == "__main__":
    os.makedirs(os.path.join(common.HERE, "results-md2d"), exist_ok=True)
    main()
