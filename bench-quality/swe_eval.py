#!/usr/bin/env python3
"""SWE-Bench-CL memory-retrieval eval — coding-agent experience selection.

SWE-Bench-CL (arXiv 2507.00014, MIT) reorganizes SWE-bench Verified into 8
per-repo chronological task sequences (273 tasks). Each task may declare
`dependencies`: earlier tasks in the same repo whose solutions touched the
same files. We treat prior tasks' experience records as memories and ask:
when a new issue arrives, does retrieval surface the genuinely related prior
tasks?

DISCLOSED CAVEATS: (1) the gold links are heuristic — file-overlap between
gold patches, not human-verified issue/PR references (SWE-ContextBench has
factual links but its data is unreleased as of July 2026). (2) Memories are
issue text + modified-file lists, not real agent trajectories. This measures
experience *selection*, the variable SWE-ContextBench showed is decisive
(oracle selection +8pp resolution; poor selection net-negative) — it does not
run agents.

Protocol per repo sequence: process tasks chronologically (created_at as the
clock). For task t with declared dependencies: query = t's problem statement;
candidates = ALL prior tasks' memories; gold = t.dependencies. Metrics before
feedback; then stateful conditions record accesses on retrieved, M-on records
+1/-1 outcomes vs gold. Every task (with deps or not) still triggers
retrieval+feedback — real usage doesn't skip quiet tasks; metrics just aren't
scored where gold is empty.

Conditions: sim, rfm_wv0, rfm. Usage: swe_eval.py [--k 5] [--out results-swe]
"""
import argparse
import datetime as dt
import json
import os
from collections import defaultdict

import numpy as np

import common

DATA = os.path.join(common.HERE, "data", "SWE-Bench-CL-Curriculum.json")
CACHE = os.path.join(common.HERE, "cache-swe" + common.cache_suffix())
CONDITIONS = ["sim", "rfm_wv0", "rfm"]


def parse_ts(s: str) -> float:
    return dt.datetime.fromisoformat(s).timestamp()


def memory_text(task) -> str:
    """The experience record for a completed task: issue + what was touched.
    A stand-in for a real trajectory summary (SWE-ContextBench style)."""
    files = ", ".join(task["continual_learning"].get("modified_files", [])[:20])
    problem = task["task"]["problem_statement"]
    return f"{problem[:1500]}\n[resolved by changes to: {files}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--out", default="results-swe")
    args = ap.parse_args()

    data = json.load(open(DATA))
    embedder = common.get_embedder()
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    sink = open(os.path.join(args.out, "per_task.jsonl"), "w")
    agg = defaultdict(lambda: defaultdict(list))
    paired = defaultdict(list)

    for seq in data["sequences"]:
        tasks = sorted(seq["tasks"],
                       key=lambda t: parse_ts(t["metadata"]["created_at"]))
        id_of = {t["metadata"]["instance_id"]: i + 1 for i, t in enumerate(tasks)}

        cache = os.path.join(CACHE, f"{seq['id']}.npz")
        if os.path.exists(cache):
            z = np.load(cache)
            mem_embs, q_embs = z["memories"], z["queries"]
        else:
            mem_embs = common.encode(embedder, [memory_text(t) for t in tasks])
            q_embs = common.encode(
                embedder, [t["task"]["problem_statement"] for t in tasks], kind="query")
            np.savez_compressed(cache, memories=mem_embs, queries=q_embs)

        rows = [(id_of[t["metadata"]["instance_id"]], memory_text(t),
                 parse_ts(t["metadata"]["created_at"])) for t in tasks]
        stores = {c: common.MemoryStore(rows, mem_embs) for c in CONDITIONS}
        scored = 0

        for ti, task in enumerate(tasks):
            if ti == 0:
                continue
            now = parse_ts(task["metadata"]["created_at"])
            prior_ids = [id_of[t["metadata"]["instance_id"]] for t in tasks[:ti]]
            gold = {id_of[d] for d in task["continual_learning"].get("dependencies", [])
                    if d in id_of}
            per_cond = {}
            for cond in CONDITIONS:
                store = stores[cond]
                store.freeze(now)
                retrieved = common.rank(store, cond, q_embs[ti], prior_ids,
                                        now, args.k)
                if gold:
                    m = common.recall_ndcg(retrieved, gold, args.k)
                    per_cond[cond] = m
                    sink.write(json.dumps({
                        "sequence": seq["id"],
                        "instance_id": task["metadata"]["instance_id"],
                        "condition": cond, "n_gold": len(gold), **m}) + "\n")
                    for key in ("recall", "hit", "ndcg"):
                        if m[key] is not None:
                            agg[cond][key].append(m[key])
                if cond != "sim":
                    store.record_accesses(retrieved)
                    if cond == "rfm" and gold:
                        store.record_outcomes(
                            [(m_, 1.0 if m_ in gold else -1.0) for m_ in retrieved])
            if gold:
                scored += 1
                for base in ("sim", "rfm_wv0"):
                    a, b = per_cond.get("rfm"), per_cond.get(base)
                    if a and b and a["ndcg"] is not None and b["ndcg"] is not None:
                        paired[base].append(a["ndcg"] - b["ndcg"])
        for store in stores.values():
            store.close()
        print(f"{seq['id']}: {len(tasks)} tasks, {scored} scored", flush=True)
    sink.close()

    n = len(agg["sim"]["ndcg"])
    print(f"\n=== SWE-Bench-CL experience selection, k={args.k}, {n} scored tasks ===")
    print("| condition | recall | hit | NDCG |")
    print("|---|---|---|---|")
    for cond in CONDITIONS:
        a = agg[cond]
        print(f"| {cond} | {np.mean(a['recall']):.3f} | {np.mean(a['hit']):.3f} | "
              f"{np.mean(a['ndcg']):.3f} |")
    print("\npaired NDCG deltas (rfm minus baseline), mean [95% CI]:")
    for base, deltas in sorted(paired.items()):
        lo, hi = common.bootstrap_ci(deltas)
        print(f"  vs {base:8s} {np.mean(deltas):+.4f} [{lo:+.4f}, {hi:+.4f}] n={len(deltas)}")


if __name__ == "__main__":
    main()
