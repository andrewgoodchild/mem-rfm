#!/usr/bin/env python3
"""LongMemEval knowledge-update eval — does the M axis implement forgetting?

All 78 knowledge-update instances have exactly two evidence sessions: the
earlier contains the now-outdated fact, the later contains the update the
gold answer reflects. Protocol: ingest sessions chronologically; when the
LATER evidence session arrives, an oracle contradiction detector fires — the
stale evidence turns receive rfm_record_access + rfm_record_outcome(-1)
(an agent noticing "this supersedes what I stored"). The fresh turns receive
nothing. At question time, measure which fact retrieval prefers.

This is an ORACLE upper bound for the contradiction signal (perfect detector);
in production the detection would come from an LLM check at write time. What
it tests without leakage is the mechanism the benchmark category exists for:
down-ranking superseded knowledge. The question itself never feeds back.

Conditions: sim, rfm_no_signal (extension loaded, no feedback recorded),
rfm_stale_penalty (the oracle protocol above). Metrics: update-preference
rate (top-ranked evidence turn is from the later session), fresh recall@k,
stale-in-top-k rate.

Usage: ku_eval.py [--k 10] [--out results-ku]
"""
import argparse
import datetime as dt
import json
import os
from collections import defaultdict

import numpy as np

import common

DATA = os.path.join(common.HERE, "data", "longmemeval_s_cleaned.json")
CACHE = os.path.join(common.HERE, "cache")  # shares replay.py's per-instance cache
CONDITIONS = ["sim", "rfm_no_signal", "rfm_stale_penalty"]


def parse_ts(s: str) -> float:
    return dt.datetime.strptime(s, "%Y/%m/%d (%a) %H:%M").timestamp()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--instances", type=int, default=None)
    ap.add_argument("--out", default="results-ku")
    args = ap.parse_args()

    data = [i for i in json.load(open(DATA)) if i["question_type"] == "knowledge-update"]
    if args.instances:
        data = data[: args.instances]
    embedder = common.get_embedder()
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    sink = open(os.path.join(args.out, "per_question.jsonl"), "w")
    agg = defaultdict(lambda: defaultdict(list))

    for n, inst in enumerate(data):
        order = sorted(range(len(inst["haystack_sessions"])),
                       key=lambda i: parse_ts(inst["haystack_dates"][i]))
        # Identify the two evidence sessions and their chronological order.
        ev_sids = set(inst["answer_session_ids"])
        ev_order = [si for si in order if inst["haystack_session_ids"][si] in ev_sids]
        if len(ev_order) != 2:
            continue
        early_si, late_si = ev_order

        # Flatten turns; remember evidence turn ids per evidence session.
        rows, flat = [], {}
        stale_mems, fresh_mems = set(), set()
        mem_id = 0
        for si in range(len(inst["haystack_sessions"])):
            ts = parse_ts(inst["haystack_dates"][si])
            for ti, turn in enumerate(inst["haystack_sessions"][si]):
                mem_id += 1
                rows.append((mem_id, turn["content"], ts))
                flat[(si, ti)] = mem_id
                if turn.get("has_answer"):
                    if si == early_si:
                        stale_mems.add(mem_id)
                    elif si == late_si:
                        fresh_mems.add(mem_id)
        if not stale_mems or not fresh_mems:
            continue

        cache = os.path.join(CACHE, f"{inst['question_id']}.npz")
        if os.path.exists(cache):
            z = np.load(cache)
            turn_embs, q_emb = z["turns"], z["question"]
        else:
            turn_embs = common.encode(embedder, [t for _m, t, _ts in rows])
            q_emb = common.encode(embedder, [inst["question"]])[0]
            np.savez_compressed(cache, turns=turn_embs, question=q_emb)

        late_ts = parse_ts(inst["haystack_dates"][late_si])
        q_ts = parse_ts(inst["question_date"])
        all_ids = [m for m, _t, _ts in rows]

        for cond in CONDITIONS:
            store = common.MemoryStore(rows, turn_embs)
            if cond == "rfm_stale_penalty":
                # Oracle contradiction event at ingestion of the later
                # evidence session: the agent re-reads the stale fact and
                # marks it superseded.
                store.freeze(late_ts)
                store.record_accesses(sorted(stale_mems))
                store.record_outcomes([(m, -1.0) for m in sorted(stale_mems)])
            store.freeze(q_ts)
            rank_cond = "sim" if cond == "sim" else "rfm"
            retrieved = common.rank(store, rank_cond, q_emb, all_ids, q_ts, args.k)

            ev_ranked = [m for m in retrieved if m in stale_mems | fresh_mems]
            update_pref = 1.0 if ev_ranked and ev_ranked[0] in fresh_mems else 0.0
            fresh = common.recall_ndcg(retrieved, fresh_mems, args.k)
            stale_in_topk = 1.0 if any(m in stale_mems for m in retrieved) else 0.0
            row = {
                "question_id": inst["question_id"], "condition": cond,
                "update_preference": update_pref, "fresh_recall": fresh["recall"],
                "fresh_ndcg": fresh["ndcg"], "stale_in_topk": stale_in_topk,
            }
            sink.write(json.dumps(row) + "\n")
            for key in ("update_preference", "fresh_recall", "fresh_ndcg", "stale_in_topk"):
                if row[key] is not None:
                    agg[cond][key].append(row[key])
            store.close()
        if (n + 1) % 25 == 0:
            print(f"{n + 1}/{len(data)}", flush=True)
    sink.close()

    print(f"\n=== LongMemEval knowledge-update (n={len(agg[CONDITIONS[0]]['update_preference'])}), k={args.k} ===")
    print("| condition | update-pref | fresh recall | fresh NDCG | stale in top-k |")
    print("|---|---|---|---|---|")
    for cond in CONDITIONS:
        a = agg[cond]
        print(f"| {cond} | {np.mean(a['update_preference']):.3f} | "
              f"{np.mean(a['fresh_recall']):.3f} | {np.mean(a['fresh_ndcg']):.3f} | "
              f"{np.mean(a['stale_in_topk']):.3f} |")
    on = agg["rfm_stale_penalty"]["update_preference"]
    off = agg["rfm_no_signal"]["update_preference"]
    deltas = [a - b for a, b in zip(on, off)]
    lo, hi = common.bootstrap_ci(deltas)
    print(f"\npaired update-preference delta (stale_penalty - no_signal): "
          f"{np.mean(deltas):+.4f} [{lo:+.4f}, {hi:+.4f}] n={len(deltas)}")


if __name__ == "__main__":
    main()
