#!/usr/bin/env python3
"""The recurrence gradient: does the activation axis earn its place as
recurrence rises? (PROTOCOL.md Amendment 12b.)

Amendment 12 found ACT-R activation within noise on BEAM in both the
recurring and non-recurring strata. The surviving defence is that BEAM's
recurrence is weak — evidence re-used across a few probing questions is not a
procedure recurring 150 times. This runs the same ablation across four
corpora spanning ~45x in recurrence per label.

Stream length is FIXED at --n for every corpus, so the quantity that varies
is recurrence per label rather than the amount of history available. Letting
each corpus run to its natural size would confound the two.

Usage: gradient_eval.py [--n 1500] [--k 5]
"""
import argparse
import os
from collections import Counter, defaultdict

import numpy as np

import common
from team_common import BASE_TS, CALL_SPACING

ARMS = {
    "full":          {},
    "no_value":      {"w_v": 0.0},
    "no_activation": {"w_a": 0.0},
    "no_prior":      {"beta": 0.0},
}


def load(name, n):
    """Each corpus's own loader, normalised to (query, memory, label)."""
    if name == "flodial":
        from flodial_eval import load_calls
        calls = load_calls(n, 8)
    elif name == "star":
        from star_eval import load_calls
        calls = load_calls(n)
    elif name == "abcd":
        from abcd_eval import load_calls
        calls = load_calls(n)
        for c in calls:
            c["label"] = c["intent"]
    elif name == "md2d":
        from md2d_eval import load_calls
        calls = load_calls(n, 8)
    else:
        raise ValueError(name)
    return calls[:n]


def run_corpus(name, n, k):
    calls = load(name, n)
    labels = [c["label"] for c in calls]
    n_labels = len(set(labels))
    recurrence = len(calls) / max(n_labels, 1)

    cache_dir = os.path.join(common.HERE, f"cache-grad-{name}" + common.cache_suffix())
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, f"n{n}.npz")
    if os.path.exists(cache):
        z = np.load(cache)
        mem_embs, q_embs = z["memories"], z["queries"]
    else:
        emb = common.get_embedder()
        mem_embs = common.encode(emb, [c["memory"] for c in calls])
        q_embs = common.encode(emb, [c["query"] for c in calls], kind="query")
        np.savez_compressed(cache, memories=mem_embs, queries=q_embs)

    times = [c.get("ts", BASE_TS + i * CALL_SPACING) for i, c in enumerate(calls)]
    rows = [(i + 1, calls[i]["memory"], times[i]) for i in range(len(calls))]
    label_of = {i + 1: labels[i] for i in range(len(calls))}

    stores = {}
    for arm, cfg in ARMS.items():
        st = common.MemoryStore(rows, mem_embs)
        for key, val in cfg.items():
            st.db.execute("SELECT rfm_config(?, ?)", (key, val))
        stores[arm] = st

    hit1 = defaultdict(list)
    hitk = defaultdict(list)
    for ci in range(len(calls)):
        gold = labels[ci]
        now = times[ci]
        cands = list(range(1, ci + 1))
        if not cands:
            continue
        for arm, store in stores.items():
            store.freeze(now)
            priors = store.priors(cands)
            sims = np.maximum(store.sims(q_embs[ci], cands), 0.0)
            order = np.argsort(-(sims * priors), kind="stable")[:k]
            got = [cands[i] for i in order]
            hitk[arm].append(any(label_of[m] == gold for m in got))
            hit1[arm].append(bool(got) and label_of[got[0]] == gold)
            store.record_accesses(got)
            store.record_outcomes(
                [(m, 1.0 if label_of[m] == gold else -1.0) for m in got])
        if (ci + 1) % 500 == 0:
            print(f"  {name}: {ci+1}/{len(calls)}", flush=True)
    for st in stores.values():
        st.close()
    return recurrence, n_labels, hit1, hitk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    print(f"Recurrence gradient — stream length fixed at n={args.n}, k={args.k}\n")
    results = []
    for name in ("flodial", "star", "abcd", "md2d"):
        try:
            rec, nl, hit1, hitk = run_corpus(name, args.n, args.k)
        except Exception as e:
            print(f"  {name}: SKIPPED ({e})")
            continue
        results.append((name, rec, nl, hit1, hitk))
        print(f"  {name}: {nl} labels, recurrence {rec:.1f}/label\n")

    def delta(table, arm):
        a, b = table[arm], table["full"]
        n = min(len(a), len(b))
        d = np.array(a[:n], float) - np.array(b[:n], float)
        lo, hi = common.bootstrap_ci(list(d))
        return d.mean(), lo, hi

    for metric, label in ((4, "hit@k"), (3, "hit@1")):
        print(f"\n=== Δ {label} vs full, by recurrence ===")
        print("| corpus | recurrence/label | " +
              " | ".join(a for a in ARMS if a != "full") + " |")
        print("|---" * (len(ARMS) + 1) + "|")
        for name, rec, _nl, hit1, hitk in sorted(results, key=lambda r: -r[1]):
            table = hitk if metric == 4 else hit1
            cells = []
            for arm in ARMS:
                if arm == "full":
                    continue
                m, lo, hi = delta(table, arm)
                star = "*" if (hi < 0 or lo > 0) else " "
                cells.append(f"{m:+.4f}{star}")
            print(f"| {name} | {rec:.1f} | " + " | ".join(cells) + " |")
        print("  (* = CI excludes zero)")


if __name__ == "__main__":
    main()
