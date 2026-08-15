#!/usr/bin/env python3
"""Does the value axis recover true utility from REAL outcomes?
(PROTOCOL.md Amendment 14.)

Every other outcome number in this repo is oracle-derived: a memory "helped"
if its label matched. This is the first test against real, test-verified
outcomes — the terminalbench corpus, where each of 89 tasks has ~586
independent binary trials, giving a ground-truth success rate the EWMA can be
scored against.

Note what this corpus cannot do: attempts per task are uniform, so there is no
frequency signal, and the attempts come from different models rather than one
agent learning, so there is no retrieval experiment here. What it has is
ground-truth utility, which nothing else we own provides.

Usage: calibration_eval.py [--data data/terminalbench]
"""
import argparse
import glob
import os
from collections import defaultdict

import numpy as np

import common

LAMBDAS = [0.1, 0.2, 0.3, 0.5]
SHRINKS = [0.0, 1.0, 3.0, 10.0]
CHECKPOINTS = [5, 10, 25, 50]


def load_trials(path):
    import pandas as pd
    files = sorted(glob.glob(os.path.join(path, "*.parquet")))
    df = pd.concat([pd.read_parquet(f, columns=["task_name", "reward", "started_at"])
                    for f in files])
    df = df.dropna(subset=["started_at"]).sort_values("started_at")
    by_task = defaultdict(list)
    for task, reward in zip(df.task_name, df.reward):
        by_task[task].append(int(reward))
    return by_task


def replay(rewards, lam, shrink_k, checkpoints):
    """Feed real rewards through the shipped extension's EWMA and read the
    effective value at each checkpoint. Uses the extension, not a
    re-implementation, so what is measured is what ships."""
    st = common.MemoryStore([(1, "task", 0.0)], np.zeros((1, 8), dtype=np.float32))
    st.db.execute("SELECT rfm_config('lambda', ?)", (lam,))
    st.db.execute("SELECT rfm_config('shrink_k', ?)", (shrink_k,))
    out = {}
    for i, r in enumerate(rewards, start=1):
        st.freeze(float(i))
        st.db.execute("SELECT rfm_record_access(1)")
        st.db.execute("SELECT rfm_record_outcome(1, ?)", (1.0 if r else -1.0,))
        if i in checkpoints:
            v, n = list(st.db.execute(
                "SELECT value_score, outcome_count FROM rfm_memories WHERE id=1"))[0]
            eff = v * n / (n + shrink_k) if (n + shrink_k) > 0 else 0.0
            out[i] = (eff + 1.0) / 2.0        # [-1,1] -> [0,1], comparable to a rate
    st.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/terminalbench")
    args = ap.parse_args()

    by_task = load_trials(args.data)
    truth = {t: float(np.mean(r)) for t, r in by_task.items()}
    print(f"{len(by_task)} tasks, {sum(len(v) for v in by_task.values())} trials")
    print(f"true success rate: min {min(truth.values()):.3f} "
          f"median {np.median(list(truth.values())):.3f} "
          f"max {max(truth.values()):.3f}\n")

    print("=== C1 calibration: mean |effective value − true rate| ===")
    print("| lambda | shrink_k | " + " | ".join(f"n={c}" for c in CHECKPOINTS) + " |")
    print("|---" * (len(CHECKPOINTS) + 2) + "|")
    best = {}
    est_at = {}
    for lam in LAMBDAS:
        for k in SHRINKS:
            errs = defaultdict(list)
            ests = defaultdict(dict)
            for task, rewards in by_task.items():
                got = replay(rewards, lam, k, set(CHECKPOINTS))
                for n, v in got.items():
                    errs[n].append(abs(v - truth[task]))
                    ests[n][task] = v
            row = [np.mean(errs[c]) if errs[c] else float("nan") for c in CHECKPOINTS]
            est_at[(lam, k)] = ests
            for c, e in zip(CHECKPOINTS, row):
                if c not in best or e < best[c][0]:
                    best[c] = (e, lam, k)
            flag = "  <- frozen" if (lam == 0.3 and k == 3.0) else ""
            print(f"| {lam} | {k} | " + " | ".join(f"{e:.4f}" for e in row) + f" |{flag}")

    print("\nbest configuration per checkpoint:")
    for c in CHECKPOINTS:
        e, lam, k = best[c]
        print(f"  n={c:3d}: lambda={lam} shrink_k={k}  MAE={e:.4f}")

    print("\n=== C2 ranking: Spearman(effective value, true rate) across tasks ===")
    tasks = sorted(truth)
    tv = np.array([truth[t] for t in tasks])
    def spearman(a, b):
        ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b))
        return float(np.corrcoef(ra, rb)[0, 1])
    for k in SHRINKS:
        cells = []
        for c in CHECKPOINTS:
            ests = est_at[(0.3, k)][c]
            if len(ests) < len(tasks):
                cells.append("  n/a")
                continue
            ev = np.array([ests[t] for t in tasks])
            cells.append(f"{spearman(ev, tv):+.3f}")
        print(f"  lambda=0.3 shrink_k={k:4.1f}: " +
              "  ".join(f"n={c} {v}" for c, v in zip(CHECKPOINTS, cells)))


if __name__ == "__main__":
    main()
