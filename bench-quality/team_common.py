"""Shared engine for the team-memory replication evals (STAR, MultiDoc2Dial,
FloDial) — the ABCD protocol (abcd_eval.py + abcd_manual.py combined),
parameterised by dataset loader. Scoring must not differ across datasets.

Each call dict: {query, memory, label, agent, ts?, gold?}
  label  the annotated procedure/doc/flowchart for the call (oracle judge)
  agent  which human agent handled it (real IDs where the dataset has them)
  ts     natural Unix time if the dataset has one; else stream spacing
  gold   set of acceptable labels for a hit (defaults to {label})
Each manual entry: {label, text} — the AUTHORED knowledge base, created at
stream start (never aged: the ABCD title-mapping postmortem applies).

Conditions (superset of the two ABCD scripts):
  solo_sim/solo_rfm    per-agent stores (candidate restriction, one store)
  team_sim/team_rfm    one pooled store over all past calls
  manual_sim           RAG over the authored manual only
  both_sim/both_rfm    manual + experience compete in one ranking
rfm arms use the frozen bounded composition (rfm_beta0.3) and record
accesses + oracle evidence-hit outcomes (+1 label match / -1 other) after
metrics — leakage-free sequential protocol, no LLM anywhere.
"""
import json
import os
from collections import defaultdict

import numpy as np

import common

BASE_TS = 1_700_000_000.0
CALL_SPACING = 300.0

CONDITIONS = ["solo_sim", "solo_rfm", "team_sim", "team_rfm",
              "manual_sim", "both_sim", "both_rfm"]


def embed_corpus(cache_dir, tag, manual, calls):
    embedder = common.get_embedder()
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, f"{tag}.npz")
    if os.path.exists(cache):
        z = np.load(cache)
        return z["manual"], z["memories"], z["queries"]
    man_embs = common.encode(embedder, [m["text"] for m in manual])
    mem_embs = common.encode(embedder, [c["memory"] for c in calls])
    q_embs = common.encode(embedder, [c["query"] for c in calls], kind="query")
    np.savez_compressed(cache, manual=man_embs, memories=mem_embs, queries=q_embs)
    return man_embs, mem_embs, q_embs


def run(dataset, calls, manual, k, cache_dir, tag, results_path=None):
    """Run all conditions over the stream; print the report tables."""
    natural_ts = "ts" in calls[0]
    times = ([c["ts"] for c in calls] if natural_ts
             else [BASE_TS + i * CALL_SPACING for i in range(len(calls))])
    t0 = min(times) - 1.0

    man_embs, mem_embs, q_embs = embed_corpus(cache_dir, tag, manual, calls)

    n_man = len(manual)
    rows = [(i + 1, manual[i]["text"], t0) for i in range(n_man)]
    rows += [(n_man + i + 1, calls[i]["memory"], times[i])
             for i in range(len(calls))]
    all_embs = np.concatenate([man_embs, mem_embs])
    label_of = {i + 1: manual[i]["label"] for i in range(n_man)}
    label_of.update({n_man + i + 1: calls[i]["label"] for i in range(len(calls))})
    agent_of = {n_man + i + 1: calls[i]["agent"] for i in range(len(calls))}
    manual_ids = list(range(1, n_man + 1))

    stores = {c: common.MemoryStore(rows, all_embs) for c in CONDITIONS}
    hits = defaultdict(list)
    hits1 = defaultdict(list)
    out = open(results_path, "w") if results_path else None

    for ci in range(len(calls)):
        gold = calls[ci].get("gold") or {calls[ci]["label"]}
        now = times[ci]
        exp_ids = [n_man + j + 1 for j in range(ci)]
        solo_ids = [m for m in exp_ids if agent_of[m] == calls[ci]["agent"]]
        cand_of = {
            "solo_sim": solo_ids, "solo_rfm": solo_ids,
            "team_sim": exp_ids, "team_rfm": exp_ids,
            "manual_sim": manual_ids,
            "both_sim": manual_ids + exp_ids, "both_rfm": manual_ids + exp_ids,
        }
        for cond in CONDITIONS:
            cands = cand_of[cond]
            if not cands:
                continue
            store = stores[cond]
            store.freeze(now)
            rank_name = "sim" if cond.endswith("sim") else "rfm_beta0.3"
            retrieved = common.rank(store, rank_name, q_embs[ci], cands, now, k)
            hit = any(label_of[m] in gold for m in retrieved)
            hit1 = bool(retrieved) and label_of[retrieved[0]] in gold
            hits[cond].append(hit)
            hits1[cond].append(hit1)
            if out:
                out.write(json.dumps({
                    "i": ci, "condition": cond, "hit": int(hit),
                    "hit1": int(hit1), "label": calls[ci]["label"]}) + "\n")
            if cond.endswith("rfm"):
                store.record_accesses(retrieved)
                store.record_outcomes(
                    [(m, 1.0 if label_of[m] in gold else -1.0) for m in retrieved])
        if (ci + 1) % 500 == 0:
            print(f"{ci + 1}/{len(calls)}", flush=True)

    for store in stores.values():
        store.close()
    if out:
        out.close()

    print(f"\n=== {dataset} team memory, k={k}, {common.EMBEDDER_ID} ===")
    print(f"{len(calls)} calls, {len({c['label'] for c in calls})} labels, "
          f"{len({c['agent'] for c in calls})} agents, manual={n_man}")
    print("| condition | hit@k | hit@1 | hit@k first500 | hit@k last500 | n |")
    print("|---|---|---|---|---|---|")
    for cond in CONDITIONS:
        h, h1 = hits[cond], hits1[cond]
        pad = len(calls) - len(h)  # empty-candidate skips at stream start
        first = np.mean(h[:500 - pad]) if len(h) > 100 else float("nan")
        print(f"| {cond} | {np.mean(h):.3f} | {np.mean(h1):.3f} | "
              f"{first:.3f} | {np.mean(h[-500:]):.3f} | {len(h)} |")

    for name, table in (("hit@k", hits), ("hit@1", hits1)):
        print(f"\nlearning curves {name} by quintile:")
        print("| condition | Q1 | Q2 | Q3 | Q4 | Q5 |")
        print("|---" * 6 + "|")
        for cond in CONDITIONS:
            qs = np.array_split(np.array(table[cond], dtype=float), 5)
            print(f"| {cond} | " + " | ".join(f"{q.mean():.3f}" for q in qs) + " |")

    def paired(a, b, table, tail=None):
        n = min(len(table[a]), len(table[b]))
        d = np.array(table[a][-n:], dtype=float) - np.array(table[b][-n:], dtype=float)
        if tail:
            d = d[-tail:]
        lo, hi = common.bootstrap_ci(list(d))
        return f"{d.mean():+.4f} [{lo:+.4f},{hi:+.4f}] n={len(d)}"

    print("\npaired deltas (pre-registered endpoints first):")
    print("  P1 [h@k] team_sim - solo_sim (pooling):   ", paired("team_sim", "solo_sim", hits))
    print("  P2 [h@1] team_sim - manual_sim:           ", paired("team_sim", "manual_sim", hits1))
    print("  P3 [h@1] team_rfm - team_sim:             ", paired("team_rfm", "team_sim", hits1))
    print("  P4 [h@1] both_rfm - manual_sim:           ", paired("both_rfm", "manual_sim", hits1))
    print("  s1 [h@1] team_rfm - team_sim (last 1000): ", paired("team_rfm", "team_sim", hits1, 1000))
    print("  s2 [h@k] team_rfm - team_sim:             ", paired("team_rfm", "team_sim", hits))
    print("  s3 [h@1] both_rfm - both_sim:             ", paired("both_rfm", "both_sim", hits1))
    print("  s4 [h@1] both_rfm - team_rfm:             ", paired("both_rfm", "team_rfm", hits1))
    # Cold-start window: align by call index (team skips call 1, both doesn't).
    skew = len(hits["both_rfm"]) - len(hits["team_rfm"])
    w = min(500, len(hits["team_rfm"]))
    d = (np.array(hits["both_rfm"][skew:skew + w], dtype=float)
         - np.array(hits["team_rfm"][:w], dtype=float))
    lo, hi = common.bootstrap_ci(list(d))
    print(f"  s5 [h@k] both_rfm - team_rfm (first {w} aligned): "
          f"{d.mean():+.4f} [{lo:+.4f},{hi:+.4f}]")
    return hits, hits1
