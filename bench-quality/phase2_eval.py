#!/usr/bin/env python3
"""Phase 2: test M variants surfaced by the signal screen, on the sequential
protocols (LoCoMo + BEAM), leakage-free as before.

Outcome-source conditions (does M survive without oracle labels?):
  rfm_oracle  outcomes = evidence-hit (+1/-1)      — the upper bound
  rfm_align   outcomes = answer-alignment: +1 if the retrieved memory's cosine
              to the question's gold answer is above the conversation's 90th
              percentile for that answer, else -1. Gold answers stand in for
              the generated answers production would use; automatic, no labels
              beyond what any QA log has.
  rfm_wv0     no outcomes (value axis off)
  sim         similarity only

Cold-start prior conditions (harness-side shrink-toward-prior; the extension
is untouched — this decides whether a value_prior column earns a v0.2 slot):
  rfm_prior_isuser    prior = +0.5 for user turns, -0.5 assistant (BEAM only;
                      LoCoMo has no assistant turns)
  rfm_prior_distinct  prior = distinctiveness percentile mapped to [-0.5, 0.5]
Both use v_eff = (n·v_ewma + k·prior)/(n + k), k = shrink_k = 3, with oracle
outcomes — i.e. they test the prior's marginal effect on top of rfm_oracle,
which shows up in the EARLY stream before feedback accumulates.

Usage: phase2_eval.py --bench locomo|beam [--k 10]
"""
import argparse
import json
import os
import random
from collections import defaultdict

import numpy as np

import beam_eval
import common
import locomo_eval

W_A, W_V, SHRINK_K = 0.7, 0.3, 3.0
ALIGN_PCT = 90.0
QUESTION_SPACING = 60.0
EARLY_FRACTION = 0.25

OUTCOME_CONDS = ["sim", "rfm_wv0", "rfm_oracle", "rfm_align"]
PRIOR_CONDS = {"locomo": ["rfm_prior_distinct"],
               "beam": ["rfm_prior_distinct", "rfm_prior_isuser"]}


def logistic(b):
    return 1.0 / (1.0 + np.exp(-b))


def prior_rank(store, q_emb, ids, k, priors):
    """sim × (w_a·P(B) + w_v·value01(blend(prior, earned))) — harness-side
    mirror of rfm_score with a generalized shrink prior."""
    sims = np.maximum(store.sims(q_emb, ids), 0.0)
    b = store.activations(ids)
    v, n = store.value_state(ids)
    v_eff = (n * v + SHRINK_K * priors) / (n + SHRINK_K)
    v01 = np.clip((v_eff + 1.0) / 2.0, 0.0, 1.0)
    scores = sims * (W_A * logistic(b) + W_V * v01)
    top = np.argsort(-scores, kind="stable")[:k]
    return [ids[i] for i in top]


def distinct_priors(embs):
    sim = embs @ embs.T
    np.fill_diagonal(sim, -1.0)
    d = 1.0 - sim.max(axis=1)
    ranks = np.argsort(np.argsort(d)) / max(len(d) - 1, 1)
    return ranks - 0.5  # percentile mapped to [-0.5, +0.5]


def load_bench(bench, embedder):
    """Yield per-conversation dicts with rows, questions, embeddings, extras."""
    if bench == "locomo":
        data = json.load(open(os.path.join(common.HERE, "data", "locomo10.json")))
        for conv in data:
            rows, dia_to_mem, last_ts = locomo_eval.load_conversation(conv)
            qas = [q for q in conv["qa"] if q.get("category") != 5 and q.get("evidence")]
            random.Random(13).shuffle(qas)
            cache = os.path.join(locomo_eval.CACHE, f"{conv['sample_id']}.npz")
            z = np.load(cache)
            answers = [str(q.get("answer", "")) for q in qas]
            yield {
                "name": conv["sample_id"], "rows": rows, "last_ts": last_ts,
                "turn_embs": z["turns"], "q_embs": z["questions"],
                "answer_embs": common.encode(embedder, answers),
                "questions": [
                    {"evidence": {dia_to_mem[d] for d in q["evidence"] if d in dia_to_mem}}
                    for q in qas],
                "is_user": np.ones(len(rows)),
            }
    else:
        for ci in range(1, 21):
            conv_dir = os.path.join(beam_eval.DATA, str(ci))
            if not os.path.isdir(conv_dir):
                continue
            rows, chatid_to_mem, last_ts = beam_eval.load_conversation(conv_dir)
            qas = beam_eval.load_questions(conv_dir)
            random.Random(13).shuffle(qas)
            pq = json.load(open(os.path.join(conv_dir, "probing_questions.json")))
            answer_of = {}
            for cat, qs in pq.items():
                for q in qs:
                    ans = q.get("answer") or q.get("ideal_response") or q.get("ideal_answer")
                    answer_of[q["question"]] = str(ans) if ans else ""
            z = np.load(os.path.join(beam_eval.CACHE, f"conv{ci}.npz"))
            yield {
                "name": f"conv{ci}", "rows": rows, "last_ts": last_ts,
                "turn_embs": z["turns"], "q_embs": z["questions"],
                "answer_embs": common.encode(
                    embedder, [answer_of.get(q["question"], "") for q in qas]),
                "questions": [
                    {"evidence": {chatid_to_mem[c] for c in q["evidence"] if c in chatid_to_mem}}
                    for q in qas],
                "is_user": np.array([1.0 if t.startswith("user:") else 0.0
                                     for _m, t, _ts in rows]),
            }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", choices=["locomo", "beam"], required=True)
    ap.add_argument("--k", type=int, default=10)
    args = ap.parse_args()
    conditions = OUTCOME_CONDS + PRIOR_CONDS[args.bench]
    embedder = common.get_embedder()
    agg = defaultdict(lambda: defaultdict(list))
    paired = defaultdict(list)

    for conv in load_bench(args.bench, embedder):
        rows, questions = conv["rows"], conv["questions"]
        all_ids = [m for m, _t, _ts in rows]
        id_row = {m: i for i, (m, _t, _ts) in enumerate(rows)}
        n_q = len(questions)
        early_cut = max(1, int(n_q * EARLY_FRACTION))
        # Per-answer alignment threshold: 90th percentile of all turns' cosine
        # to that answer (self-calibrating, one knob).
        align_all = conv["turn_embs"] @ conv["answer_embs"].T  # turns x questions
        thresholds = np.percentile(align_all, ALIGN_PCT, axis=0)
        priors = {
            "rfm_prior_distinct": distinct_priors(conv["turn_embs"]),
            "rfm_prior_isuser": conv["is_user"] - 0.5,
        }
        stores = {c: common.MemoryStore(rows, conv["turn_embs"]) for c in conditions}

        for qi, q in enumerate(questions):
            evidence = q["evidence"]
            if not evidence:
                continue
            now = conv["last_ts"] + 3600.0 + qi * QUESTION_SPACING
            window = "early" if qi < early_cut else "late"
            per_cond = {}
            for cond in conditions:
                store = stores[cond]
                store.freeze(now)
                if cond.startswith("rfm_prior_"):
                    retrieved = prior_rank(store, conv["q_embs"][qi], all_ids,
                                           args.k, priors[cond])
                else:
                    rank_name = {"sim": "sim", "rfm_wv0": "rfm_wv0"}.get(cond, "rfm")
                    retrieved = common.rank(store, rank_name, conv["q_embs"][qi],
                                            all_ids, now, args.k)
                m = common.recall_ndcg(retrieved, evidence, args.k)
                per_cond[cond] = m
                for key in ("recall", "hit", "ndcg"):
                    if m[key] is not None:
                        agg[(cond, "all")][key].append(m[key])
                        agg[(cond, window)][key].append(m[key])
                if cond == "sim":
                    continue
                store.record_accesses(retrieved)
                if cond == "rfm_wv0":
                    continue
                if cond == "rfm_align":
                    outcomes = [
                        (m_, 1.0 if align_all[id_row[m_], qi] >= thresholds[qi] else -1.0)
                        for m_ in retrieved]
                else:  # oracle: rfm_oracle and both prior conditions
                    outcomes = [(m_, 1.0 if m_ in evidence else -1.0) for m_ in retrieved]
                store.record_outcomes(outcomes)
            for ref in ("rfm_oracle", "sim"):
                for cond in conditions:
                    if cond == ref:
                        continue
                    a, b = per_cond[ref], per_cond[cond]
                    if a["ndcg"] is not None and b["ndcg"] is not None:
                        paired[(ref, cond, "all")].append(a["ndcg"] - b["ndcg"])
                        paired[(ref, cond, window)].append(a["ndcg"] - b["ndcg"])
        for store in stores.values():
            store.close()
        print(f"{conv['name']}: {n_q} questions done", flush=True)

    print(f"\n=== Phase 2 ({args.bench}), k={args.k} ===")
    print("| condition | window | recall | hit | NDCG | n |")
    print("|---|---|---|---|---|---|")
    for cond in conditions:
        for window in ("all", "early", "late"):
            a = agg[(cond, window)]
            if a["ndcg"]:
                print(f"| {cond} | {window} | {np.mean(a['recall']):.3f} | "
                      f"{np.mean(a['hit']):.3f} | {np.mean(a['ndcg']):.3f} | {len(a['ndcg'])} |")
    print("\npaired NDCG deltas (reference minus condition), mean [95% CI]:")
    for (ref, cond, window), deltas in sorted(paired.items()):
        lo, hi = common.bootstrap_ci(deltas)
        print(f"  {ref:10s} - {cond:20s} {window:6s} "
              f"{np.mean(deltas):+.4f} [{lo:+.4f}, {hi:+.4f}] n={len(deltas)}")


if __name__ == "__main__":
    main()
