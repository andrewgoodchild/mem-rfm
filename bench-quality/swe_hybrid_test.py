#!/usr/bin/env python3
"""Amendment 2 one-shot: frozen hybrid_w0.3 on the six held-out SWE repos.
Arms: sim, hybrid (frozen), hybrid x rfm_prior (feedback ON, sequential)."""
import json, os
from collections import defaultdict
import numpy as np
import common, swe_eval

DEV_REPOS = ("django/django", "sympy/sympy")
W, K = 0.3, 5

def norm(x):
    span = x.max() - x.min()
    return (x - x.min()) / span if span > 0 else np.zeros_like(x)

data = json.load(open(swe_eval.DATA))
arms = ["sim", "hybrid", "hybrid_prior"]
agg = defaultdict(list)
paired = defaultdict(list)
for seq in data["sequences"]:
    if seq["repo"] in DEV_REPOS:
        continue
    tasks = sorted(seq["tasks"], key=lambda t: swe_eval.parse_ts(t["metadata"]["created_at"]))
    id_of = {t["metadata"]["instance_id"]: i + 1 for i, t in enumerate(tasks)}
    z = np.load(os.path.join(swe_eval.CACHE, f"{seq['id']}.npz"))
    m_embs, q_embs = z["memories"], z["queries"]
    rows = [(id_of[t["metadata"]["instance_id"]], swe_eval.memory_text(t),
             swe_eval.parse_ts(t["metadata"]["created_at"])) for t in tasks]
    stores = {a: common.MemoryStore(rows, m_embs, fts=True) for a in arms}
    for ti, task in enumerate(tasks):
        if ti == 0:
            continue
        gold = {id_of[d] for d in task["continual_learning"].get("dependencies", []) if d in id_of}
        now = swe_eval.parse_ts(task["metadata"]["created_at"])
        prior_ids = [r[0] for r in rows[:ti]]
        per = {}
        for arm in arms:
            store = stores[arm]
            store.freeze(now)
            sims = store.sims(q_embs[ti], prior_ids)
            if arm == "sim":
                scores = sims
            else:
                fused = W * norm(sims) + (1 - W) * norm(store.bm25_scores(
                    task["task"]["problem_statement"], prior_ids))
                if arm == "hybrid_prior":
                    pri = store.rfm_scores(prior_ids)
                    fused = fused * (0.7 + 0.3 * pri)
                scores = fused
            top = np.argsort(-scores, kind="stable")[:K]
            retrieved = [prior_ids[i] for i in top]
            if gold:
                m = common.recall_ndcg(retrieved, gold, K)
                per[arm] = m
                if m["ndcg"] is not None:
                    agg[arm].append(m["ndcg"])
            if arm == "hybrid_prior":
                store.record_accesses(retrieved)
                if gold:
                    store.record_outcomes([(m_, 1.0 if m_ in gold else -1.0) for m_ in retrieved])
        if gold and all(a in per for a in arms):
            paired["prior_vs_sim"].append(per["hybrid_prior"]["ndcg"] - per["sim"]["ndcg"])
            paired["prior_vs_hybrid"].append(per["hybrid_prior"]["ndcg"] - per["hybrid"]["ndcg"])
    for s in stores.values():
        s.close()
print(f"=== Amendment 2 ONE-SHOT (6 held-out repos), {common.EMBEDDER_ID}, k={K} ===")
for arm in arms:
    print(f"{arm}: NDCG {np.mean(agg[arm]):.4f} (n={len(agg[arm])})")
for name, d in paired.items():
    lo, hi = common.bootstrap_ci(d)
    print(f"{name}: {np.mean(d):+.4f} [{lo:+.4f},{hi:+.4f}] n={len(d)}")
