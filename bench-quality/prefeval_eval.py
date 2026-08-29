#!/usr/bin/env python3
"""PrefEval profile-scale retrieval eval — the substrate-less venue,
frozen form. (Registered in PROTOCOL.md Amendment 15 before the run.)

PrefEval (amazon-science, arXiv 2502.09597) ships ~1,000 explicit
preference↔question pairs across 20 topics. Structure: each preference
is gold for exactly ONE question — so, like LongMemEval, gold evidence
never recurs and the LoCoMo adaptivity protocol cannot port. What the
corpus DOES have that LongMemEval lacks is a shared store: all 1,000
preferences form one user profile, every question retrieves against all
of them, and a preference that surface-matches many foreign questions
recurs as a DISTRACTOR. Distractor recurrence is learnable: wrongly
retrieved preferences earn signed negatives and sink. That is the one
channel the value axis has here, and the eval measures it.

Protocol: one profile store per condition (1,000 preferences,
staggered created_at); questions in deterministically shuffled order,
clock advancing per question; metrics computed BEFORE that question's
feedback is recorded. Conditions:
  sim      similarity only, no state
  rfm_wv0  retrieved top-k earn rfm_record_access; value axis unused
  rfm      accesses plus oracle outcomes from the gold mapping:
           +1 the question's own gold preference when retrieved,
           −1 any other retrieved preference (the distractor signal)

Usage: prefeval_eval.py [--k 10] [--out results-prefeval]
"""
import argparse
import glob
import json
import os
import random
from collections import defaultdict

import numpy as np

import common

DATA = os.path.join(common.HERE, "data", "prefeval")
T0 = 1_750_000_000.0
CONDITIONS = ["sim", "rfm_wv0", "rfm"]


def load():
    items = []
    for f in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        topic = os.path.basename(f)[:-5]
        for i, r in enumerate(json.load(open(f))):
            items.append({"topic": topic, "preference": r["preference"],
                          "question": r["question"]})
    for i, it in enumerate(items):
        it["mem_id"] = i
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--out", default="results-prefeval")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    items = load()
    print(f"{len(items)} preference-question pairs, "
          f"{len({i['topic'] for i in items})} topics")
    emb = common.get_embedder()
    pref_embs = common.encode(emb, [i["preference"] for i in items], "doc")
    q_embs = common.encode(emb, [i["question"] for i in items], "query")

    order = list(range(len(items)))
    random.Random(7).shuffle(order)

    rows = [(i["mem_id"], i["preference"], T0 - 3600 * (len(items) - n))
            for n, i in enumerate(items)]
    stores = {c: common.MemoryStore(rows, pref_embs) for c in CONDITIONS}
    ids = [i["mem_id"] for i in items]

    sink = open(os.path.join(a.out, "per_question.jsonl"), "w")
    hits = defaultdict(lambda: defaultdict(list))
    for step, qi in enumerate(order):
        t = T0 + 600.0 * (step + 1)
        gold = items[qi]["mem_id"]
        rec = {"step": step, "q": qi, "gold": gold,
               "topic": items[qi]["topic"]}
        for c in CONDITIONS:
            st = stores[c]
            st.freeze(t)
            sims = np.maximum(st.sims(q_embs[qi], ids), 0)
            score = sims if c == "sim" else sims * st.priors(ids)
            top = [ids[j] for j in np.argsort(-score)[:a.k]]
            rec[f"{c}_h1"] = int(top[0] == gold)
            rec[f"{c}_h5"] = int(gold in top[:5])
            hits[c]["h1"].append(rec[f"{c}_h1"])
            hits[c]["h5"].append(rec[f"{c}_h5"])
            if c != "sim":
                for m in top:
                    st.db.execute("SELECT rfm_record_access(?)", (m,))
                    if c == "rfm":
                        st.db.execute("SELECT rfm_record_outcome(?, ?)",
                                      (m, 1.0 if m == gold else -1.0))
        sink.write(json.dumps(rec) + "\n")
        if (step + 1) % 200 == 0:
            print(f"  {step + 1}/{len(order)}")
    sink.close()

    def third(xs, which):
        n = len(xs) // 3
        return {"early": xs[:n], "mid": xs[n:2 * n],
                "late": xs[2 * n:]}[which]

    def boot_delta(xa, xb, reps=2000):
        d = np.array(xa) - np.array(xb)
        rng = np.random.default_rng(7)
        means = [d[rng.integers(0, len(d), len(d))].mean()
                 for _ in range(reps)]
        return d.mean(), np.percentile(means, 2.5), np.percentile(means, 97.5)

    print(f"\n{'condition':<10}{'hit@1':>8}{'hit@5':>8}"
          f"{'h1 late':>9}{'h5 late':>9}")
    for c in CONDITIONS:
        print(f"{c:<10}{np.mean(hits[c]['h1']):>8.4f}"
              f"{np.mean(hits[c]['h5']):>8.4f}"
              f"{np.mean(third(hits[c]['h1'], 'late')):>9.4f}"
              f"{np.mean(third(hits[c]['h5'], 'late')):>9.4f}")

    print("\npaired deltas [95% CI]:")
    verdicts = {}
    for tag, xa, xb in [
            ("PE-P1 rfm-sim h5 overall", hits["rfm"]["h5"], hits["sim"]["h5"]),
            ("PE-P2 rfm-wv0 h1 late third",
             third(hits["rfm"]["h1"], "late"),
             third(hits["rfm_wv0"]["h1"], "late")),
            ("PE-P3 wv0-sim h5 overall", hits["rfm_wv0"]["h5"],
             hits["sim"]["h5"]),
            ("(desc) rfm-wv0 h1 overall", hits["rfm"]["h1"],
             hits["rfm_wv0"]["h1"])]:
        m, lo, hi = boot_delta(xa, xb)
        verdicts[tag.split()[0]] = m
        print(f"  {tag}: {m:+.4f} [{lo:+.4f}, {hi:+.4f}]")

    print("\nREGISTERED (PROTOCOL.md Amendment 15):")
    print(f"  PE-P1 rank-safety (rfm-sim h5 >= -0.005): "
          f"{'PASS' if verdicts['PE-P1'] >= -0.005 else 'FAIL'}")
    print(f"  PE-P2 distractor demotion (late-third h1 rfm-wv0 > 0): "
          f"{'PASS' if verdicts['PE-P2'] > 0 else 'FAIL'}")
    print(f"  PE-P3 usage-prior-alone harmless (|wv0-sim h5| <= 0.01): "
          f"{'PASS' if abs(verdicts['PE-P3']) <= 0.01 else 'FAIL'}")
    for st in stores.values():
        st.close()


if __name__ == "__main__":
    main()
