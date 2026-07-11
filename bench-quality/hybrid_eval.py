#!/usr/bin/env python3
"""Step H dev run (PROTOCOL.md Amendment 1): BM25+vector fusion on BEAM.

Stateless arms (fusion is a relevance question; no accesses/outcomes here):
sim, bm25, hybrid_w (w ∈ {0.3,0.5,0.7} on per-query min-max-normalized
signals), rrf(k=60). Selection: max NDCG@10 overall, must beat the better
single signal on both embedders. Run once per embedder via RFM_EMBEDDER.

Usage: hybrid_eval.py [--k 10]
"""
import argparse
import random
from collections import defaultdict

import numpy as np

import beam_eval
import common

WS = (0.3, 0.5, 0.7)
K_RRF = 60


def norm(x):
    span = x.max() - x.min()
    return (x - x.min()) / span if span > 0 else np.zeros_like(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    args = ap.parse_args()
    arms = ["sim", "bm25"] + [f"hybrid_w{w}" for w in WS] + ["rrf"]
    agg = defaultdict(list)

    import os
    for ci in range(1, 21):
        conv_dir = os.path.join(beam_eval.DATA, str(ci))
        if not os.path.isdir(conv_dir):
            continue
        rows, chatid_to_mem, _last_ts = beam_eval.load_conversation(conv_dir)
        qas = beam_eval.load_questions(conv_dir)
        random.Random(13).shuffle(qas)
        z = np.load(os.path.join(beam_eval.CACHE, f"conv{ci}.npz"))
        turn_embs, q_embs = z["turns"], z["questions"]
        all_ids = [m for m, _t, _ts in rows]
        store = common.MemoryStore(rows, turn_embs, fts=True)

        for qi, qa in enumerate(qas):
            evidence = {chatid_to_mem[c] for c in qa["evidence"] if c in chatid_to_mem}
            if not evidence:
                continue
            sims = store.sims(q_embs[qi], all_ids)
            bm = store.bm25_scores(qa["question"], all_ids)
            scores = {"sim": sims, "bm25": bm}
            ns, nb = norm(sims), norm(bm)
            for w in WS:
                scores[f"hybrid_w{w}"] = w * ns + (1 - w) * nb
            r_s = np.argsort(np.argsort(-sims, kind="stable"))
            r_b = np.argsort(np.argsort(-bm, kind="stable"))
            scores["rrf"] = 1.0 / (K_RRF + 1 + r_s) + 1.0 / (K_RRF + 1 + r_b)
            for arm in arms:
                top = np.argsort(-scores[arm], kind="stable")[: args.k]
                m = common.recall_ndcg([all_ids[i] for i in top], evidence, args.k)
                if m["ndcg"] is not None:
                    agg[arm].append(m["ndcg"])
        store.close()
        print(f"conversation {ci} done", flush=True)

    print(f"\n=== Step H dev (BEAM), {common.EMBEDDER_ID}, k={args.k} ===")
    for arm in arms:
        print(f"{arm}: NDCG {np.mean(agg[arm]):.4f} (n={len(agg[arm])})")


if __name__ == "__main__":
    main()
