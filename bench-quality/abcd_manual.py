#!/usr/bin/env python3
"""Manual-RAG vs experience-memory vs both (ABCD, exploratory).

Three knowledge sources for routing an incoming support call to the right
procedure:
  manual_sim   RAG over the 55 AUTHORED procedure entries from the agent
               guidelines (data/abcd_guidelines.json) — the "decent shared
               knowledge base". Static; no learning; no cold start.
  team_sim /   experience memory over past calls (as abcd_eval.py):
  team_rfm     accretes from work, cold-starts empty; rfm = outcome-ranked.
  both_sim /   union corpus: manual entries AND past-call experiences
  both_rfm     compete in one ranking; in the rfm arm the manual entries
               themselves earn accesses/outcomes like any memory.

Hit = a top-k item (manual entry or experience) whose procedure matches the
call's gold intent. Same leakage-free sequential protocol; no LLM.

Hypotheses stated up front: the manual embeds far from messy customer
phrasing (it describes agent actions), so manual_sim underperforms
experience at steady state — but has no cold start, so `both` should
dominate the early stream and converge to experience later.

Usage: abcd_manual.py [--n 3000] [--k 5]
"""
import argparse
import json
import os
from collections import defaultdict

import numpy as np

import common
from abcd_eval import BASE_TS, CALL_SPACING, load_calls

CACHE = os.path.join(common.HERE, "cache-abcd" + common.cache_suffix())
GUIDELINES = os.path.join(common.HERE, "data", "abcd_guidelines.json")


# Titles whose word-sets don't match their canonical intent (v1 of this
# script missed these 22, silently dropping manual coverage for 52.7% of
# calls — caught in pre-publication review; results were re-run).
TITLE_ALIASES = {
    "Return Due to Stain": "return_stain", "Return Due to Color": "return_color",
    "Return Due to Size": "return_size", "Reset Two-Factor Auth": "reset_2fa",
    "Invalid Credit Card": "credit_card", "Cart Not Updating": "shopping_cart",
    "Search Not Working": "search_results", "Website Too Slow": "slow_speed",
    "Out-of-Stock General": "out_of_stock_general",
    "Out-of-Stock One Item": "out_of_stock_one_item",
    "Shipping Status": "status", "Manage Shipping": "manage",
    "Missing Item": "missing", "Shipping Cost": "cost",
    "Boots FAQ": "boots", "Shirt FAQ": "shirt", "Jeans FAQ": "jeans",
    "Jacket FAQ": "jacket", "Pricing FAQ": "pricing",
    "Membership FAQ": "membership", "Timing FAQ": "timing",
    "Policy FAQ": "policy",
}


def load_manual(intents):
    """All 55 authored procedure entries, mapped to canonical intents by
    word-set (titles reorder words: 'Initiate Refund' -> refund_initiate)
    with explicit aliases for the rest. Raises if any title fails to map —
    silent partial coverage invalidates the manual arm."""
    g = json.load(open(GUIDELINES))
    by_words = {frozenset(i.split("_")): i for i in intents}
    entries, unmapped = [], []
    for flow_name, flow in g.items():
        for title, spec in flow["subflows"].items():
            words = frozenset(w.lower() for w in title.split())
            intent = TITLE_ALIASES.get(title) or by_words.get(words)
            if intent is None or intent not in intents:
                unmapped.append(title)
                continue
            steps = "; ".join(a["text"] for a in spec["actions"][:6])
            text = (f"procedure: {title} ({flow_name}). "
                    f"{' '.join(spec.get('instructions', [])[:2])} steps: {steps}")
            entries.append({"intent": intent, "text": text[:1500]})
    if unmapped:
        raise RuntimeError(f"unmapped manual titles: {unmapped}")
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    calls = load_calls(args.n)
    intents = {c["intent"] for c in calls}
    manual = load_manual(intents)
    print(f"{len(calls)} calls; manual entries mapped: {len(manual)}", flush=True)

    embedder = common.get_embedder()
    os.makedirs(CACHE, exist_ok=True)
    cache = os.path.join(CACHE, f"manual-n{args.n}.npz")
    if os.path.exists(cache):
        z = np.load(cache)
        man_embs, mem_embs, q_embs = z["manual"], z["memories"], z["queries"]
    else:
        man_embs = common.encode(embedder, [m["text"] for m in manual])
        mem_embs = common.encode(embedder, [c["memory"] for c in calls])
        q_embs = common.encode(embedder, [c["query"] for c in calls], kind="query")
        np.savez_compressed(cache, manual=man_embs, memories=mem_embs, queries=q_embs)

    n_man = len(manual)
    # rows: manual entries first (ids 1..n_man, created AT stream start — an
    # earlier draft aged them 30 days, handicapping them in rfm arms via
    # recency decay; fixed in review), then call experiences (ids n_man+1..).
    rows = [(i + 1, manual[i]["text"], BASE_TS)
            for i in range(n_man)]
    rows += [(n_man + i + 1, calls[i]["memory"], BASE_TS + i * CALL_SPACING)
             for i in range(len(calls))]
    all_embs = np.concatenate([man_embs, mem_embs])
    intent_of = {i + 1: manual[i]["intent"] for i in range(n_man)}
    intent_of.update({n_man + i + 1: calls[i]["intent"] for i in range(len(calls))})
    manual_ids = list(range(1, n_man + 1))

    conditions = ["manual_sim", "team_sim", "team_rfm", "both_sim", "both_rfm"]
    stores = {c: common.MemoryStore(rows, all_embs) for c in conditions}
    hits = defaultdict(list)
    hits1 = defaultdict(list)

    for ci in range(len(calls)):
        gold = calls[ci]["intent"]
        now = BASE_TS + ci * CALL_SPACING
        exp_ids = [n_man + j + 1 for j in range(ci)]
        cand_of = {
            "manual_sim": manual_ids,
            "team_sim": exp_ids, "team_rfm": exp_ids,
            "both_sim": manual_ids + exp_ids, "both_rfm": manual_ids + exp_ids,
        }
        for cond in conditions:
            cands = cand_of[cond]
            if not cands:
                continue
            store = stores[cond]
            store.freeze(now)
            rank_name = "sim" if cond.endswith("sim") else "rfm_beta0.3"
            retrieved = common.rank(store, rank_name, q_embs[ci], cands, now, args.k)
            hits[cond].append(any(intent_of[m] == gold for m in retrieved))
            hits1[cond].append(bool(retrieved) and intent_of[retrieved[0]] == gold)
            if cond.endswith("rfm"):
                store.record_accesses(retrieved)
                store.record_outcomes(
                    [(m, 1.0 if intent_of[m] == gold else -1.0) for m in retrieved])
        if (ci + 1) % 500 == 0:
            print(f"{ci + 1}/{len(calls)}", flush=True)

    for store in stores.values():
        store.close()

    print(f"\n=== Manual-RAG vs experience vs both, k={args.k}, {common.EMBEDDER_ID} ===")
    print("| condition | hit@5 | hit@1 | hit@5 first500 | hit@5 last500 | n |")
    print("|---|---|---|---|---|---|")
    for cond in conditions:
        h, h1 = hits[cond], hits1[cond]
        pad = len(calls) - len(h)  # empty-candidate skips at stream start
        first = np.mean(h[:500 - pad]) if len(h) > 100 else float("nan")
        print(f"| {cond} | {np.mean(h):.3f} | {np.mean(h1):.3f} | "
              f"{first:.3f} | {np.mean(h[-500:]):.3f} | {len(h)} |")

    print("\nlearning curves hit@1 by quintile:")
    print("| condition | Q1 | Q2 | Q3 | Q4 | Q5 |")
    print("|---" * 6 + "|")
    for cond in conditions:
        qs = np.array_split(np.array(hits1[cond], dtype=float), 5)
        print(f"| {cond} | " + " | ".join(f"{q.mean():.3f}" for q in qs) + " |")

    def paired(a, b, table, tail=None):
        n = min(len(table[a]), len(table[b]))
        d = np.array(table[a][-n:], dtype=float) - np.array(table[b][-n:], dtype=float)
        if tail:
            d = d[-tail:]
        lo, hi = common.bootstrap_ci(list(d))
        return f"{d.mean():+.4f} [{lo:+.4f},{hi:+.4f}] n={len(d)}"

    print("\npaired deltas:")
    print("  [h@1] team_sim  - manual_sim:", paired("team_sim", "manual_sim", hits1))
    print("  [h@1] both_rfm  - team_rfm:  ", paired("both_rfm", "team_rfm", hits1))
    print("  [h@1] both_rfm  - manual_sim:", paired("both_rfm", "manual_sim", hits1))
    print("  [h@1] both_rfm  - both_sim:  ", paired("both_rfm", "both_sim", hits1))
    # Cold-start window: align by call index (team skips call 1, both doesn't).
    skew = len(hits["both_rfm"]) - len(hits["team_rfm"])
    w = min(500, len(hits["team_rfm"]))
    d = (np.array(hits["both_rfm"][skew:skew + w], dtype=float)
         - np.array(hits["team_rfm"][:w], dtype=float))
    lo, hi = common.bootstrap_ci(list(d))
    print(f"  [h@5] both_rfm - team_rfm (first {w} aligned calls): "
          f"{d.mean():+.4f} [{lo:+.4f},{hi:+.4f}]")


if __name__ == "__main__":
    main()
