#!/usr/bin/env python3
"""Amendment 2 dev: BM25+vector fusion on SWE-Bench-CL DEV repos only
(django, sympy). Stateless arms, same rule as Amendment 1."""
import json, os, random
from collections import defaultdict
import numpy as np
import common, swe_eval

DEV_REPOS = ("django/django", "sympy/sympy")
WS = (0.3, 0.5, 0.7)
K = 5

def norm(x):
    span = x.max() - x.min()
    return (x - x.min()) / span if span > 0 else np.zeros_like(x)

data = json.load(open(swe_eval.DATA))
embedder = common.get_embedder()
arms = ["sim", "bm25"] + [f"hybrid_w{w}" for w in WS] + ["rrf"]
agg = defaultdict(list)
for seq in data["sequences"]:
    if seq["repo"] not in DEV_REPOS:
        continue
    tasks = sorted(seq["tasks"], key=lambda t: swe_eval.parse_ts(t["metadata"]["created_at"]))
    id_of = {t["metadata"]["instance_id"]: i + 1 for i, t in enumerate(tasks)}
    z = np.load(os.path.join(swe_eval.CACHE, f"{seq['id']}.npz"))
    m_embs, q_embs = z["memories"], z["queries"]
    rows = [(id_of[t["metadata"]["instance_id"]], swe_eval.memory_text(t),
             swe_eval.parse_ts(t["metadata"]["created_at"])) for t in tasks]
    store = common.MemoryStore(rows, m_embs, fts=True)
    for ti, task in enumerate(tasks):
        gold = {id_of[d] for d in task["continual_learning"].get("dependencies", []) if d in id_of}
        if ti == 0 or not gold:
            continue
        prior_ids = [r[0] for r in rows[:ti]]
        sims = store.sims(q_embs[ti], prior_ids)
        bm = store.bm25_scores(task["task"]["problem_statement"], prior_ids)
        scores = {"sim": sims, "bm25": bm}
        ns, nb = norm(sims), norm(bm)
        for w in WS:
            scores[f"hybrid_w{w}"] = w * ns + (1 - w) * nb
        r_s = np.argsort(np.argsort(-sims, kind="stable"))
        r_b = np.argsort(np.argsort(-bm, kind="stable"))
        scores["rrf"] = 1.0/(61 + r_s) + 1.0/(61 + r_b)
        for arm in arms:
            top = np.argsort(-scores[arm], kind="stable")[:K]
            m = common.recall_ndcg([prior_ids[i] for i in top], gold, K)
            if m["ndcg"] is not None:
                agg[arm].append(m["ndcg"])
    store.close()
print(f"=== SWE hybrid dev (django+sympy), {common.EMBEDDER_ID}, k={K} ===")
for arm in arms:
    print(f"{arm}: NDCG {np.mean(agg[arm]):.4f} (n={len(agg[arm])})")
