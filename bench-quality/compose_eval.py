#!/usr/bin/env python3
"""Composition bake-off (PROTOCOL.md Phase: dev). BEAM 128K only — LoCoMo,
LongMemEval, and SWE-Bench-CL are untouched test sets.

Candidates (declared in PROTOCOL.md): beta-blend (β ∈ {0.1,0.2,0.3,0.5}),
rrf (k=60), shortlist (N = 3k). Each in feedback-ON and feedback-OFF
variants; `sim` as the reference. Sequential protocol identical to
beam_eval.py. Embedder comes from RFM_EMBEDDER; run once per embedder.

Usage: compose_eval.py [--k 10] [--out results-compose]
"""
import argparse
import json
import os
import random
from collections import defaultdict

import numpy as np

import beam_eval
import common

K_RRF = 60
BETAS = (0.1, 0.2, 0.3, 0.5)
QUESTION_SPACING = 60.0


def candidate_names():
    names = [f"beta{b}" for b in BETAS] + ["rrf", "shortlist"]
    return names


def compose(name, sims, priors, k):
    """Return indices (into the candidate arrays) of the top-k under a
    composition. priors = rfm_score per candidate."""
    s = np.maximum(sims, 0.0)
    if name.startswith("beta"):
        b = float(name[4:])
        scores = s * ((1.0 - b) + b * priors)
        return np.argsort(-scores, kind="stable")[:k]
    if name == "rrf":
        r_s = np.argsort(np.argsort(-sims, kind="stable"))
        r_p = np.argsort(np.argsort(-priors, kind="stable"))
        scores = 1.0 / (K_RRF + 1 + r_s) + 1.0 / (K_RRF + 1 + r_p)
        return np.argsort(-scores, kind="stable")[:k]
    if name == "shortlist":
        n = 3 * k
        by_sim = np.argsort(-sims, kind="stable")
        head, tail = by_sim[:n], by_sim[n:]
        head = head[np.argsort(-priors[head], kind="stable")]
        return np.concatenate([head, tail])[:k]
    raise ValueError(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--out", default="results-compose")
    args = ap.parse_args()

    embedder = common.get_embedder()
    slug = common.cache_suffix() or "-minilm"
    os.makedirs(args.out, exist_ok=True)
    sink = open(os.path.join(args.out, f"per_question{slug}.jsonl"), "w")

    conditions = ["sim"] + [f"{c}_{fb}" for c in candidate_names()
                            for fb in ("on", "off")]
    agg = defaultdict(lambda: defaultdict(list))
    cost_pairs = defaultdict(list)   # candidate -> ndcg(sim)-ndcg(cand_on), overlap=False
    adapt_pairs = defaultdict(list)  # candidate -> ndcg(on)-ndcg(off), overlap=True

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
        stores = {c: common.MemoryStore(rows, turn_embs) for c in conditions}
        seen_evidence = set()

        for qi, qa in enumerate(qas):
            evidence = {chatid_to_mem[c] for c in qa["evidence"] if c in chatid_to_mem}
            if not evidence:
                continue
            overlap = bool(evidence & seen_evidence)
            now = last_ts + 3600.0 + qi * QUESTION_SPACING
            per_cond = {}
            for cond in conditions:
                store = stores[cond]
                store.freeze(now)
                sims = store.sims(q_embs[qi], all_ids)
                if cond == "sim":
                    top = np.argsort(-sims, kind="stable")[: args.k]
                else:
                    priors = store.rfm_scores(all_ids)
                    top = compose(cond.rsplit("_", 1)[0], sims, priors, args.k)
                retrieved = [all_ids[i] for i in top]
                m = common.recall_ndcg(retrieved, evidence, args.k)
                per_cond[cond] = m
                sink.write(json.dumps({
                    "conversation": ci, "q_idx": qi, "condition": cond,
                    "overlap": overlap, **m}) + "\n")
                for key in ("recall", "hit", "ndcg"):
                    if m[key] is not None:
                        agg[(cond, "all")][key].append(m[key])
                        agg[(cond, f"overlap={overlap}")][key].append(m[key])
                if cond != "sim":
                    store.record_accesses(retrieved)
                    if cond.endswith("_on"):
                        store.record_outcomes(
                            [(m_, 1.0 if m_ in evidence else -1.0)
                             for m_ in retrieved])
            for cand in candidate_names():
                on, off = per_cond[f"{cand}_on"], per_cond[f"{cand}_off"]
                ref = per_cond["sim"]
                if not overlap and ref["ndcg"] is not None and on["ndcg"] is not None:
                    cost_pairs[cand].append(ref["ndcg"] - on["ndcg"])
                if overlap and on["ndcg"] is not None and off["ndcg"] is not None:
                    adapt_pairs[cand].append(on["ndcg"] - off["ndcg"])
            seen_evidence |= evidence
        for store in stores.values():
            store.close()
        print(f"conversation {ci} done", flush=True)
    sink.close()

    print(f"\n=== Composition bake-off (dev: BEAM), embedder={common.EMBEDDER_ID}, k={args.k} ===")
    print("| candidate | NDCG all | cost vs sim (overlap=F) [CI] | adaptivity ON-OFF (overlap=T) [CI] |")
    print("|---|---|---|---|")
    for cand in candidate_names():
        nd = np.mean(agg[(f"{cand}_on", "all")]["ndcg"])
        c = cost_pairs[cand]
        a = adapt_pairs[cand]
        clo, chi = common.bootstrap_ci(c)
        alo, ahi = common.bootstrap_ci(a)
        print(f"| {cand} | {nd:.3f} | {np.mean(c):+.4f} [{clo:+.4f},{chi:+.4f}] "
              f"| {np.mean(a):+.4f} [{alo:+.4f},{ahi:+.4f}] |")
    print(f"| sim | {np.mean(agg[('sim', 'all')]['ndcg']):.3f} | — | — |")


if __name__ == "__main__":
    main()
