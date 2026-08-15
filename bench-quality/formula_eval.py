#!/usr/bin/env python3
"""Does ACT-R earn its complexity, or would marketers' RFM do?
(PROTOCOL.md Amendment 13.)

ACT-R unifies recency and frequency into ln(Σ t^-d) and needs the Petrov k=2
approximation plus a bla_cache column to compute cheaply. Classical RFM keeps
the axes separate. BOTH are O(1) from one summary row, so Petrov buys a
functional form, not speed — and this asks whether the form is worth it.

Run primarily on STAR, the corpus where Amendment 12b showed activation
demonstrably earns its place. A simpler form must prove itself where the
complex one works.

Usage: formula_eval.py [--corpus star|beam] [--n 1500] [--k 5]
"""
import argparse
import math
import os
from collections import defaultdict

import numpy as np

import common
from team_common import BASE_TS, CALL_SPACING

BETA = 0.3
TAU = 86_400.0
ARMS = ["actr", "simple_rfm", "quintile_rfm", "decile_rfm", "percentile_rfm",
        "binary_rfm", "tercile_rfm", "recency_only", "frequency_only",
        # Implementable forms of the rank-bucket idea (Amendment 13d):
        "A_shortlist",     # buckets over a similarity shortlist, not the store
        "B_cuts_100",      # maintained global cutpoints, refreshed every 100
        "B_cuts_500",      # ... every 500
        "B_cuts_once",     # ... computed once, never refreshed (worst case)
        "C_parametric"]    # logistic on maintained median/IQR

# Per-arm state for the maintained-statistic arms. Row-local scoring needs
# these to exist, but they are refreshed on a schedule rather than per query —
# which is the whole point, and the staleness cost is what we are measuring.
STATE = {}


def refresh_cuts(arm, rec, freq, val01, nbuckets=5):
    STATE.setdefault(arm, {})["cuts"] = {
        "rec": np.quantile(rec, np.linspace(0, 1, nbuckets + 1)[1:-1]),
        "freq": np.quantile(freq, np.linspace(0, 1, nbuckets + 1)[1:-1]),
        "val": np.quantile(val01, np.linspace(0, 1, nbuckets + 1)[1:-1]),
    }


def refresh_moments(arm, rec, freq, val01):
    st = STATE.setdefault(arm, {})
    st["mom"] = {}
    for name, x in (("rec", rec), ("freq", freq), ("val", val01)):
        q1, med, q3 = np.percentile(x, [25, 50, 75])
        st["mom"][name] = (med, max((q3 - q1) / 2.0, 1e-6))


def bucket_by_cuts(x, cuts, nbuckets=5):
    """Row-local: 'how many maintained cutpoints does this value exceed'."""
    return np.searchsorted(cuts, x, side="right") / float(nbuckets - 1)

# Amendment 13b: the squash is ACT-R's retrieval threshold and noise, which
# the architecture fits per model. Overridable so a fitted value chosen on one
# corpus can be evaluated on another.
THETA, S = 0.0, 1.0


def buckets(x, b):
    """Marketing RFM scores each axis by rank bucket, not raw value.
    b=5 quintiles, b=10 deciles, b=0 continuous percentile (the limit case)."""
    n = len(x)
    if n < 2:
        return np.zeros(n)
    order = np.argsort(np.argsort(x))
    if b == 0:
        return order / (n - 1.0)
    if n < b:
        return order / (n - 1.0)
    return np.floor(order * float(b) / n) / (b - 1.0)


def score_arm(arm, act, rec, freq, val01, shortlist_sims=None):
    """Every arm keeps the same outcome axis and the same bounded prior;
    only the activation term differs."""
    if arm == "actr":
        prior_core = 0.7 * (1.0 / (1.0 + np.exp(-(act - THETA) / max(S, 1e-9)))) + 0.3 * val01
    elif arm == "simple_rfm":
        fmax = max(freq.max(), 1e-9)
        prior_core = 0.35 * rec + 0.35 * (freq / fmax) + 0.3 * val01
    elif arm in ("quintile_rfm", "decile_rfm", "percentile_rfm",
                 "binary_rfm", "tercile_rfm"):
        b = {"binary_rfm": 2, "tercile_rfm": 3, "quintile_rfm": 5,
             "decile_rfm": 10, "percentile_rfm": 0}[arm]
        prior_core = (buckets(rec, b) + buckets(freq, b) + buckets(val01, b)) / 3.0
    elif arm == "A_shortlist":
        # Buckets computed over a similarity shortlist rather than the store.
        # Different quantity from what we measured — shortlist membership is
        # query-dependent, so a memory's bucket changes with the query.
        k = min(100, len(rec))
        top = np.argsort(-shortlist_sims)[:k]
        prior_core = np.full(len(rec), 0.5)
        sub = (buckets(rec[top], 5) + buckets(freq[top], 5)
               + buckets(val01[top], 5)) / 3.0
        prior_core[top] = sub
    elif arm.startswith("B_cuts"):
        st = STATE.get(arm, {}).get("cuts")
        if st is None:
            prior_core = np.full(len(rec), 0.5)
        else:
            prior_core = (bucket_by_cuts(rec, st["rec"])
                          + bucket_by_cuts(freq, st["freq"])
                          + bucket_by_cuts(val01, st["val"])) / 3.0
    elif arm == "C_parametric":
        m = STATE.get(arm, {}).get("mom")
        if m is None:
            prior_core = np.full(len(rec), 0.5)
        else:
            def lg(x, k):
                med, iqr = m[k]
                return 1.0 / (1.0 + np.exp(-(x - med) / iqr))
            prior_core = (lg(rec, "rec") + lg(freq, "freq") + lg(val01, "val")) / 3.0
    elif arm == "recency_only":
        prior_core = 0.7 * rec + 0.3 * val01
    elif arm == "frequency_only":
        fmax = max(freq.max(), 1e-9)
        prior_core = 0.7 * (freq / fmax) + 0.3 * val01
    else:
        raise ValueError(arm)
    return (1.0 - BETA) + BETA * prior_core


def load(corpus, n):
    if corpus == "star":
        from star_eval import load_calls
        calls = load_calls(n)[:n]
        ts = [c["ts"] for c in calls]
    elif corpus == "abcd":
        from abcd_eval import load_calls
        from team_common import BASE_TS, CALL_SPACING
        calls = load_calls(n)[:n]
        for c in calls:
            c["label"] = c["intent"]
        ts = [BASE_TS + i * CALL_SPACING for i in range(len(calls))]
    elif corpus in ("flodial", "md2d"):
        from team_common import BASE_TS, CALL_SPACING
        if corpus == "flodial":
            from flodial_eval import load_calls
        else:
            from md2d_eval import load_calls
        calls = load_calls(n, 8)[:n]
        ts = [BASE_TS + i * CALL_SPACING for i in range(len(calls))]
    else:
        raise ValueError(corpus)
    return ([(i + 1, calls[i]["memory"], ts[i]) for i in range(len(calls))],
            [c["label"] for c in calls], [c["query"] for c in calls],
            [c["memory"] for c in calls])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="star")
    ap.add_argument("--theta", type=float, default=None)
    ap.add_argument("--s", type=float, default=None)
    ap.add_argument("--arms", default="actr,binary_rfm,tercile_rfm,quintile_rfm,decile_rfm,percentile_rfm")
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    global THETA, S, ARMS
    if args.theta is not None:
        THETA = args.theta
    if args.s is not None:
        S = args.s
    ARMS = [a for a in args.arms.split(",") if a]
    print(f"squash: theta={THETA} s={S}")
    rows, labels, queries, memories = load(args.corpus, args.n)
    label_of = {r[0]: labels[i] for i, r in enumerate(rows)}
    times = [r[2] for r in rows]

    cache_dir = os.path.join(common.HERE, f"cache-formula-{args.corpus}"
                             + common.cache_suffix())
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, f"n{args.n}.npz")
    if os.path.exists(cache):
        z = np.load(cache)
        mem_embs, q_embs = z["memories"], z["queries"]
    else:
        emb = common.get_embedder()
        mem_embs = common.encode(emb, memories)
        q_embs = common.encode(emb, queries, kind="query")
        np.savez_compressed(cache, memories=mem_embs, queries=q_embs)

    stores = {a: common.MemoryStore(rows, mem_embs) for a in ARMS}
    hit1, hitk = defaultdict(list), defaultdict(list)
    spread = defaultdict(list)      # dynamic range of the prior, per arm

    for ci in range(len(rows)):
        gold = labels[ci]
        now = times[ci]
        cands = list(range(1, ci + 1))
        if not cands:
            continue
        ph = ",".join("?" * len(cands))
        for arm in ARMS:
            st = stores[arm]
            st.freeze(now)
            # Pull all three axes from the extension in one pass so every arm
            # reads identical underlying state.
            got = {r[0]: r[1:] for r in st.db.execute(
                f"SELECT id, rfm_activation(id), rfm_recency(id), "
                f"rfm_frequency(id), rfm_value(id) FROM rfm_memories "
                f"WHERE id IN ({ph})", cands)}
            sims_pre = np.maximum(st.sims(q_embs[ci], cands), 0.0)
            act = np.array([got[m][0] for m in cands])
            rec = np.array([got[m][1] for m in cands])
            freq = np.array([got[m][2] for m in cands])
            val01 = np.clip((np.array([got[m][3] for m in cands]) + 1) / 2, 0, 1)

            # Refresh maintained statistics on the arm's own schedule.
            if arm.startswith("B_cuts") and len(cands) >= 20:
                every = {"B_cuts_100": 100, "B_cuts_500": 500,
                         "B_cuts_once": 10**9}[arm]
                if arm not in STATE or (ci % every == 0):
                    if arm not in STATE or ci % every == 0:
                        refresh_cuts(arm, rec, freq, val01)
            if arm == "C_parametric" and len(cands) >= 20:
                if arm not in STATE or ci % 100 == 0:
                    refresh_moments(arm, rec, freq, val01)
            prior = score_arm(arm, act, rec, freq, val01, sims_pre)
            if len(cands) > 20:
                spread[arm].append(float(prior.max() - prior.min()))
            sims = np.maximum(st.sims(q_embs[ci], cands), 0.0)
            order = np.argsort(-(sims * prior), kind="stable")[:args.k]
            top = [cands[i] for i in order]
            hitk[arm].append(any(label_of[m] == gold for m in top))
            hit1[arm].append(bool(top) and label_of[top[0]] == gold)
            st.record_accesses(top)
            st.record_outcomes(
                [(m, 1.0 if label_of[m] == gold else -1.0) for m in top])
        if (ci + 1) % 500 == 0:
            print(f"  {ci+1}/{len(rows)}", flush=True)

    for st in stores.values():
        st.close()

    print(f"\n=== {args.corpus}, n={len(rows)}, k={args.k}, "
          f"{common.EMBEDDER_ID} ===")
    print("| arm | hit@1 | Δ hit@1 vs actr | hit@k | Δ hit@k |")
    print("|---|---|---|---|---|")
    for arm in ARMS:
        cells = []
        for table in (hit1, hitk):
            a, b = table[arm], table["actr"]
            n = min(len(a), len(b))
            d = np.array(a[:n], float) - np.array(b[:n], float)
            lo, hi = common.bootstrap_ci(list(d))
            star = "*" if (hi < 0 or lo > 0) else ""
            cells.append((np.mean(a), f"{d.mean():+.4f}{star} [{lo:+.4f},{hi:+.4f}]"))
        print(f"| {arm} | {cells[0][0]:.4f} | {cells[0][1]} "
              f"| {cells[1][0]:.4f} | {cells[1][1]} |")
    print("\n(* = CI excludes zero. Ties favour the simpler form — see "
          "Amendment 13's asymmetric bar.)")
    print("\nprior dynamic range (max-min across candidates, mean per query):")
    print("  near-zero spread = that arm's prior is effectively constant, so")
    print("  its ranking is similarity-only regardless of what it computes.")
    for arm in ARMS:
        if spread[arm]:
            print(f"  {arm:16s} {np.mean(spread[arm]):.4f}")


if __name__ == "__main__":
    main()
