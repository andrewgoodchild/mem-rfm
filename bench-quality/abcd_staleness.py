#!/usr/bin/env python3
"""ABCD staleness eval (exploratory): when procedures CHANGE mid-stream, do
stale memories keep getting recommended, and does outcome feedback retire
them faster than similarity alone?

Simulation: same 3,000-call stream as abcd_eval.py, team store only. At call
REVISION_AT, a "policy revision" hits the affected intents (the highest-
volume ones): from then on the correct procedure is the revised variant —
memories written before the change are WRONG for those intents (a retrieval
of one counts as a miss, and in the rfm arm earns -1, the ticket-reopen
signal); post-change calls write revised memories (content carries a
revision marker, as a real updated playbook would).

Metrics on affected-intent calls only: hit@1/hit@5 where a hit requires a
POST-revision memory of the correct intent, reported in post-change bins —
the recovery curve. team_sim has no mechanism to retire stale memories
except dilution; team_rfm demotes them with negative outcomes.

Usage: abcd_staleness.py [--n 3000] [--k 5] [--revision-at 1500]
"""
import argparse
import os
from collections import Counter, defaultdict

import numpy as np

import common
from abcd_eval import BASE_TS, CALL_SPACING, load_calls

CACHE = os.path.join(common.HERE, "cache-abcd" + common.cache_suffix())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--revision-at", type=int, default=1500)
    ap.add_argument("--affected", type=int, default=8,
                    help="how many top-volume intents get revised")
    args = ap.parse_args()

    calls = load_calls(args.n)
    counts = Counter(c["intent"] for c in calls)
    affected = {i for i, _n in counts.most_common(args.affected)}
    print(f"{len(calls)} calls; revised intents at call {args.revision_at}: "
          f"{sorted(affected)}", flush=True)

    # Post-revision calls of affected intents use the revised playbook; their
    # memories say so (as a real updated procedure doc would).
    texts = []
    for i, c in enumerate(calls):
        revised = c["intent"] in affected and i >= args.revision_at
        texts.append(c["memory"] + (" | NOTE: uses revised R2 procedure" if revised else ""))

    embedder = common.get_embedder()
    os.makedirs(CACHE, exist_ok=True)
    cache = os.path.join(CACHE, f"stale-n{args.n}-r{args.revision_at}-a{args.affected}.npz")
    if os.path.exists(cache):
        z = np.load(cache)
        mem_embs, q_embs = z["memories"], z["queries"]
    else:
        mem_embs = common.encode(embedder, texts)
        q_embs = common.encode(embedder, [c["query"] for c in calls], kind="query")
        np.savez_compressed(cache, memories=mem_embs, queries=q_embs)

    rows = [(i + 1, texts[i], BASE_TS + i * CALL_SPACING) for i in range(len(calls))]
    intent_of = {i + 1: calls[i]["intent"] for i in range(len(calls))}

    def correct(mem_id, gold, call_idx):
        """Is retrieving mem_id a correct recommendation for this call?"""
        if intent_of[mem_id] != gold:
            return False
        if gold in affected and call_idx >= args.revision_at:
            return mem_id - 1 >= args.revision_at  # must be a revised memory
        return True

    conditions = ["team_sim", "team_rfm"]
    stores = {c: common.MemoryStore(rows, mem_embs) for c in conditions}
    # affected-intent calls, post-revision: (bin, condition) -> hits
    rec1 = defaultdict(list)
    rec5 = defaultdict(list)
    pre1 = defaultdict(list)  # affected intents, pre-revision baseline

    for ci in range(len(calls)):
        gold = calls[ci]["intent"]
        now = BASE_TS + ci * CALL_SPACING
        cands = list(range(1, ci + 1))
        if not cands:
            continue
        for cond in conditions:
            store = stores[cond]
            store.freeze(now)
            rank_name = "sim" if cond.endswith("sim") else "rfm_beta0.3"
            retrieved = common.rank(store, rank_name, q_embs[ci], cands, now, args.k)
            hit5 = any(correct(m, gold, ci) for m in retrieved)
            hit1 = bool(retrieved) and correct(retrieved[0], gold, ci)
            if gold in affected:
                if ci < args.revision_at:
                    pre1[cond].append(hit1)
                else:
                    bin_idx = (ci - args.revision_at) // 250
                    rec1[(cond, bin_idx)].append(hit1)
                    rec5[(cond, bin_idx)].append(hit5)
            if cond.endswith("rfm"):
                store.record_accesses(retrieved)
                store.record_outcomes(
                    [(m, 1.0 if correct(m, gold, ci) else -1.0) for m in retrieved])
        if (ci + 1) % 500 == 0:
            print(f"{ci + 1}/{len(calls)}", flush=True)

    for store in stores.values():
        store.close()

    nbins = max(b for (_c, b) in rec1) + 1
    print(f"\n=== Staleness recovery (affected intents, k={args.k}) ===")
    for cond in conditions:
        print(f"{cond}: pre-revision hit@1 baseline = {np.mean(pre1[cond]):.3f}")
    print("\nhit@1 by 250-call bins after the revision:")
    print("| condition | " + " | ".join(f"+{(b+1)*250}" for b in range(nbins)) + " |")
    print("|---" * (nbins + 1) + "|")
    for cond in conditions:
        cells = [f"{np.mean(rec1[(cond, b)]):.3f}" if rec1[(cond, b)] else "-"
                 for b in range(nbins)]
        print(f"| {cond} | " + " | ".join(cells) + " |")
    print("\nhit@5 by bins:")
    for cond in conditions:
        cells = [f"{np.mean(rec5[(cond, b)]):.3f}" if rec5[(cond, b)] else "-"
                 for b in range(nbins)]
        print(f"  {cond}: " + " ".join(cells))


if __name__ == "__main__":
    main()
