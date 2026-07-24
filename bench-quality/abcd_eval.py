#!/usr/bin/env python3
"""ABCD team-memory eval (exploratory, NOT pre-registered): does outcome-
ranked memory surface the right support procedure across successive calls,
and does a TEAM-shared store beat per-agent solo stores?

Data: ABCD (asappresearch/abcd, MIT) — real support conversations, each
annotated with the agent-manual procedure ("subflow", 55 canonical intents)
that applied. No LLM anywhere: after each call a procedure memory is written
(customer's opening lines + resolution actions, all from the transcript);
before each call the store is queried with the new call's opening lines;
retrieval is a HIT if top-k contains a memory from a call with the same
annotated intent. Feedback (+1 same-intent / -1 other) is recorded after
metrics — leakage-free sequential protocol as in the other evals.

Conditions (2x2):
  solo_sim / solo_rfm    8 agents round-robin; each retrieves only from own
                         past calls (one store per condition; candidate
                         restriction isolates state exactly, since a memory
                         is only ever a candidate for its own agent)
  team_sim / team_rfm    one shared store over all past calls

Caveats disclosed: no natural ordering in ABCD (seeded shuffle imposed);
oracle evidence-hit outcomes; first N calls of train for tractability.

Usage: abcd_eval.py [--n 3000] [--k 5] [--agents 8]
"""
import argparse
import json
import os
import random
from collections import defaultdict

import numpy as np

import common

DATA = os.path.join(common.HERE, "data", "abcd_v1.1.json")
CACHE = os.path.join(common.HERE, "cache-abcd" + common.cache_suffix())
BASE_TS = 1_700_000_000.0
CALL_SPACING = 300.0


def load_calls(n):
    data = json.load(open(DATA))["train"]
    random.Random(13).shuffle(data)
    calls = []
    for c in data:
        intent = None
        for t in c["delexed"]:
            if t.get("targets") and t["targets"][0]:
                intent = t["targets"][0]
                break
        cust = [txt for spk, txt in c["original"] if spk == "customer"][:3]
        acts = [txt for spk, txt in c["original"] if spk == "action"][:4]
        if not intent or not cust:
            continue
        calls.append({
            "convo_id": c["convo_id"], "intent": intent,
            "flow": c["scenario"]["flow"],
            "query": " ".join(cust[:2]),
            "memory": "customer issue: " + " ".join(cust) +
                      " | resolved via: " + ("; ".join(acts) or "(no logged actions)"),
        })
        if len(calls) >= n:
            break
    return calls


def confusable_families(calls):
    """Subflows sharing a name-prefix within the same flow (approximates the
    verified confusable groups: return_*, refund_*, manage_*, status_*...)."""
    groups = defaultdict(set)
    for c in calls:
        prefix = c["intent"].rsplit("_", 1)[0] if "_" in c["intent"] else c["intent"]
        groups[(c["flow"], prefix)].add(c["intent"])
    return {i for (f, p), members in groups.items() if len(members) >= 2
            for i in members}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--agents", type=int, default=8)
    args = ap.parse_args()

    calls = load_calls(args.n)
    confusable = confusable_families(calls)
    print(f"{len(calls)} calls, {len({c['intent'] for c in calls})} intents, "
          f"{len(confusable)} confusable intents", flush=True)

    embedder = common.get_embedder()
    os.makedirs(CACHE, exist_ok=True)
    cache = os.path.join(CACHE, f"n{args.n}.npz")
    if os.path.exists(cache):
        z = np.load(cache)
        mem_embs, q_embs = z["memories"], z["queries"]
    else:
        mem_embs = common.encode(embedder, [c["memory"] for c in calls])
        q_embs = common.encode(embedder, [c["query"] for c in calls], kind="query")
        np.savez_compressed(cache, memories=mem_embs, queries=q_embs)

    rows = [(i + 1, calls[i]["memory"], BASE_TS + i * CALL_SPACING)
            for i in range(len(calls))]
    intent_of = {i + 1: calls[i]["intent"] for i in range(len(calls))}
    agent_of = {i + 1: i % args.agents for i in range(len(calls))}

    conditions = ["solo_sim", "solo_rfm", "team_sim", "team_rfm"]
    stores = {c: common.MemoryStore(rows, mem_embs) for c in conditions}
    hits = defaultdict(list)          # condition -> [0/1 per call in order]
    hits_conf = defaultdict(list)
    hits1 = defaultdict(list)
    hits1_conf = defaultdict(list)

    for ci in range(len(calls)):
        call_id = ci + 1
        gold = calls[ci]["intent"]
        now = BASE_TS + ci * CALL_SPACING
        agent = agent_of[call_id]
        prior_all = list(range(1, call_id))
        prior_solo = [m for m in prior_all if agent_of[m] == agent]
        for cond in conditions:
            cands = prior_solo if cond.startswith("solo") else prior_all
            if not cands:
                continue
            store = stores[cond]
            store.freeze(now)
            rank_name = "sim" if cond.endswith("sim") else "rfm_beta0.3"
            retrieved = common.rank(store, rank_name, q_embs[ci], cands, now, args.k)
            hit = any(intent_of[m] == gold for m in retrieved)
            hit1 = bool(retrieved) and intent_of[retrieved[0]] == gold
            hits[cond].append(hit)
            hits1[cond].append(hit1)
            if gold in confusable:
                hits_conf[cond].append(hit)
                hits1_conf[cond].append(hit1)
            if cond.endswith("rfm"):
                store.record_accesses(retrieved)
                store.record_outcomes(
                    [(m, 1.0 if intent_of[m] == gold else -1.0) for m in retrieved])
        if (ci + 1) % 500 == 0:
            print(f"{ci + 1}/{len(calls)}", flush=True)

    for store in stores.values():
        store.close()

    print(f"\n=== ABCD team memory, k={args.k}, {args.agents} agents, "
          f"{common.EMBEDDER_ID} ===")
    print("| condition | hit@k | hit@1 | hit@k conf | hit@1 conf | n |")
    print("|---|---|---|---|---|---|")
    for cond in conditions:
        print(f"| {cond} | {np.mean(hits[cond]):.3f} | {np.mean(hits1[cond]):.3f} | "
              f"{np.mean(hits_conf[cond]):.3f} | {np.mean(hits1_conf[cond]):.3f} | "
              f"{len(hits[cond])} |")

    print("\nlearning curves (hit@k by call-index quintile):")
    print("| condition | " + " | ".join(f"Q{i+1}" for i in range(5)) + " |")
    print("|---" * 6 + "|")
    for cond in conditions:
        h = hits[cond]
        qs = np.array_split(np.array(h, dtype=float), 5)
        print(f"| {cond} | " + " | ".join(f"{q.mean():.3f}" for q in qs) + " |")

    # paired deltas on the shared call set
    def paired(a, b, tail=None, table=None):
        table = table if table is not None else hits
        n = min(len(table[a]), len(table[b]))
        da = np.array(table[a][-n:], dtype=float) - np.array(table[b][-n:], dtype=float)
        if tail:
            da = da[-tail:]
        lo, hi = common.bootstrap_ci(list(da))
        return f"{da.mean():+.4f} [{lo:+.4f},{hi:+.4f}] n={len(da)}"

    print("\npaired hit-rate deltas:")
    print("  team_sim - solo_sim (pooling):        ", paired("team_sim", "solo_sim"))
    print("  team_rfm - team_sim (ranking, all):   ", paired("team_rfm", "team_sim"))
    print("  team_rfm - team_sim (last 1000):      ", paired("team_rfm", "team_sim", 1000))
    print("  solo_rfm - solo_sim (ranking, solo):  ", paired("solo_rfm", "solo_sim"))
    print("  [hit@1] team_rfm - team_sim:          ", paired("team_rfm", "team_sim", table=hits1))
    print("  [hit@1] team_rfm - team_sim last1000: ", paired("team_rfm", "team_sim", 1000, table=hits1))
    print("  [hit@1 conf] team_rfm - team_sim:     ", paired("team_rfm", "team_sim", table=hits1_conf))


if __name__ == "__main__":
    main()
