#!/usr/bin/env python3
"""Step P dev (Amendment 1+3): confident-negative exclusion on BEAM.
Arms: sim, frozen (rfm_beta0.3 ON), frozen+exclude(V,N) grid. Cost bar:
overlap=False paired NDCG vs sim <= 0.010 per embedder."""
import json, os, random
from collections import defaultdict
import numpy as np
import beam_eval, common

GRID = [(-0.5, 1), (-0.8, 1), (-0.5, 2), (-0.8, 2), (-0.5, 3), (-0.8, 3)]
K = 10
QUESTION_SPACING = 60.0

def main():
    arms = ["sim", "frozen"] + [f"ex_v{v}_n{n}" for v, n in GRID]
    agg = defaultdict(lambda: defaultdict(list))
    cost = defaultdict(list)
    for ci in range(1, 21):
        conv_dir = os.path.join(beam_eval.DATA, str(ci))
        if not os.path.isdir(conv_dir):
            continue
        rows, chatid_to_mem, last_ts = beam_eval.load_conversation(conv_dir)
        qas = beam_eval.load_questions(conv_dir)
        random.Random(13).shuffle(qas)
        z = np.load(os.path.join(beam_eval.CACHE, f"conv{ci}.npz"))
        turn_embs, q_embs = z["turns"], z["questions"]
        all_ids = [m for m, _t, _ts in rows]
        stores = {a: common.MemoryStore(rows, turn_embs) for a in arms}
        seen = set()
        for qi, qa in enumerate(qas):
            evidence = {chatid_to_mem[c] for c in qa["evidence"] if c in chatid_to_mem}
            if not evidence:
                continue
            overlap = bool(evidence & seen)
            now = last_ts + 3600.0 + qi * QUESTION_SPACING
            per = {}
            for arm in arms:
                store = stores[arm]
                store.freeze(now)
                cands = all_ids
                if arm.startswith("ex_"):
                    v_thr = float(arm.split("_")[1][1:])
                    n_thr = int(arm.split("_")[2][1:])
                    vals, nouts = store.value_state(all_ids)
                    keep = ~((vals <= v_thr) & (nouts >= n_thr))
                    cands = [m for m, k in zip(all_ids, keep) if k] or all_ids
                rank_name = "sim" if arm == "sim" else "rfm_beta0.3"
                retrieved = common.rank(store, rank_name, q_embs[qi], cands, now, K)
                m = common.recall_ndcg(retrieved, evidence, K)
                per[arm] = m
                if m["ndcg"] is not None:
                    agg[arm]["ndcg"].append(m["ndcg"])
                if arm != "sim":
                    store.record_accesses(retrieved)
                    store.record_outcomes(
                        [(m_, 1.0 if m_ in evidence else -1.0) for m_ in retrieved])
            for arm in arms:
                if arm == "sim" or overlap:
                    continue
                if per["sim"]["ndcg"] is not None and per[arm]["ndcg"] is not None:
                    cost[arm].append(per["sim"]["ndcg"] - per[arm]["ndcg"])
            seen |= evidence
        for s in stores.values():
            s.close()
        print(f"conv {ci} done", flush=True)
    print(f"\n=== Step P dev (BEAM), {common.EMBEDDER_ID}, k={K} ===")
    for arm in arms:
        line = f"{arm}: NDCG {np.mean(agg[arm]['ndcg']):.4f}"
        if arm in cost:
            lo, hi = common.bootstrap_ci(cost[arm])
            line += f"  cost {np.mean(cost[arm]):+.4f} [{lo:+.4f},{hi:+.4f}]"
        print(line)

if __name__ == "__main__":
    main()
