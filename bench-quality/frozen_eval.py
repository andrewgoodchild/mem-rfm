#!/usr/bin/env python3
"""One-shot test evaluation of the FROZEN composition (PROTOCOL.md /
RESULTS.md): beta-blend β=0.3. Run once per (benchmark, embedder) cell in the
declared test plan; no re-tuning.

Benches: locomo, swe (sequential protocol; conditions sim / frozen ON /
frozen OFF) and ku (knowledge-update forgetting: sim / no_signal /
stale_penalty under the frozen composition).

Usage: frozen_eval.py --bench locomo|swe|ku [--k 10]
"""
import argparse
import json
import os
import random
from collections import defaultdict

import numpy as np

import common
import locomo_eval
import swe_eval

FROZEN = "rfm_beta0.3"
QUESTION_SPACING = 60.0


def run_sequential(bench, k, out):
    conditions = ["sim", "frozen_on", "frozen_off"]
    embedder = common.get_embedder()
    slug = common.cache_suffix() or "-minilm"
    os.makedirs(out, exist_ok=True)
    sink = open(os.path.join(out, f"{bench}{slug}.jsonl"), "w")
    agg = defaultdict(lambda: defaultdict(list))
    cost_pairs = defaultdict(list)
    adapt_pairs = defaultdict(list)

    if bench == "locomo":
        data = json.load(open(os.path.join(common.HERE, "data", "locomo10.json")))
        units = []
        for conv in data:
            rows, dia_to_mem, last_ts = locomo_eval.load_conversation(conv)
            qas = [q for q in conv["qa"] if q.get("category") != 5 and q.get("evidence")]
            random.Random(13).shuffle(qas)
            cache = os.path.join(locomo_eval.CACHE, f"{conv['sample_id']}.npz")
            if os.path.exists(cache):
                z = np.load(cache)
                t_embs, q_embs = z["turns"], z["questions"]
            else:
                t_embs = common.encode(embedder, [t for _m, t, _ts in rows])
                q_embs = common.encode(embedder, [q["question"] for q in qas], kind="query")
                os.makedirs(locomo_eval.CACHE, exist_ok=True)
                np.savez_compressed(cache, turns=t_embs, questions=q_embs)
            golds = [{dia_to_mem[d] for d in q["evidence"] if d in dia_to_mem} for q in qas]
            units.append((conv["sample_id"], rows, t_embs, q_embs, golds, last_ts, None))
    else:  # swe
        data = json.load(open(swe_eval.DATA))
        units = []
        for seq in data["sequences"]:
            tasks = sorted(seq["tasks"], key=lambda t: swe_eval.parse_ts(t["metadata"]["created_at"]))
            id_of = {t["metadata"]["instance_id"]: i + 1 for i, t in enumerate(tasks)}
            cache = os.path.join(swe_eval.CACHE, f"{seq['id']}.npz")
            if os.path.exists(cache):
                z = np.load(cache)
                m_embs, q_embs = z["memories"], z["queries"]
            else:
                m_embs = common.encode(embedder, [swe_eval.memory_text(t) for t in tasks])
                q_embs = common.encode(
                    embedder, [t["task"]["problem_statement"] for t in tasks], kind="query")
                os.makedirs(swe_eval.CACHE, exist_ok=True)
                np.savez_compressed(cache, memories=m_embs, queries=q_embs)
            rows = [(id_of[t["metadata"]["instance_id"]], swe_eval.memory_text(t),
                     swe_eval.parse_ts(t["metadata"]["created_at"])) for t in tasks]
            golds = [{id_of[d] for d in t["continual_learning"].get("dependencies", [])
                      if d in id_of} for t in tasks]
            units.append((seq["id"], rows, m_embs, q_embs, golds, None, tasks))

    for name, rows, t_embs, q_embs, golds, last_ts, tasks in units:
        all_ids = [m for m, _t, _ts in rows]
        stores = {c: common.MemoryStore(rows, t_embs) for c in conditions}
        seen_evidence = set()
        for qi in range(len(golds)):
            gold = golds[qi]
            if bench == "swe":
                if qi == 0:
                    continue
                now = swe_eval.parse_ts(tasks[qi]["metadata"]["created_at"])
                candidates = all_ids[:qi]
            else:
                now = last_ts + 3600.0 + qi * QUESTION_SPACING
                candidates = all_ids
            overlap = bool(gold & seen_evidence)
            per_cond = {}
            for cond in conditions:
                store = stores[cond]
                store.freeze(now)
                rank_name = "sim" if cond == "sim" else FROZEN
                retrieved = common.rank(store, rank_name, q_embs[qi], candidates, now, k)
                if gold:
                    m = common.recall_ndcg(retrieved, gold, k)
                    per_cond[cond] = m
                    sink.write(json.dumps({
                        "unit": name, "q_idx": qi, "condition": cond,
                        "overlap": overlap, **m}) + "\n")
                    for key in ("recall", "hit", "ndcg"):
                        if m[key] is not None:
                            agg[(cond, "all")][key].append(m[key])
                            agg[(cond, f"overlap={overlap}")][key].append(m[key])
                if cond != "sim":
                    store.record_accesses(retrieved)
                    if cond == "frozen_on" and gold:
                        store.record_outcomes(
                            [(m_, 1.0 if m_ in gold else -1.0) for m_ in retrieved])
            if gold and per_cond:
                s, on, off = per_cond["sim"], per_cond["frozen_on"], per_cond["frozen_off"]
                if not overlap and s["ndcg"] is not None and on["ndcg"] is not None:
                    cost_pairs["frozen"].append(s["ndcg"] - on["ndcg"])
                if overlap and on["ndcg"] is not None and off["ndcg"] is not None:
                    adapt_pairs["frozen"].append(on["ndcg"] - off["ndcg"])
                seen_evidence |= gold
        for store in stores.values():
            store.close()
        print(f"{name} done", flush=True)
    sink.close()

    print(f"\n=== FROZEN test: {bench}, {common.EMBEDDER_ID}, k={k} ===")
    for cond in conditions:
        a = agg[(cond, "all")]
        if a["ndcg"]:
            print(f"{cond}: NDCG {np.mean(a['ndcg']):.3f} (n={len(a['ndcg'])})")
    c, a = cost_pairs["frozen"], adapt_pairs["frozen"]
    if c:
        lo, hi = common.bootstrap_ci(c)
        print(f"PRIMARY cost vs sim (overlap=False): {np.mean(c):+.4f} [{lo:+.4f},{hi:+.4f}] n={len(c)}")
    if a:
        lo, hi = common.bootstrap_ci(a)
        print(f"adaptivity ON-OFF (overlap=True): {np.mean(a):+.4f} [{lo:+.4f},{hi:+.4f}] n={len(a)}")


def run_ku(k, out):
    """Knowledge-update forgetting under the frozen composition."""
    import ku_eval
    os.makedirs(out, exist_ok=True)
    embedder = common.get_embedder()
    # Embedder-suffixed cache dir (loop-invariant): the plain "cache/" dir is
    # MiniLM-only, so cache_suffix() keeps MiniLM back-compatible.
    cache_dir = os.path.join(common.HERE, "cache" + common.cache_suffix())
    os.makedirs(cache_dir, exist_ok=True)
    data = [i for i in json.load(open(ku_eval.DATA)) if i["question_type"] == "knowledge-update"]
    agg = defaultdict(lambda: defaultdict(list))
    conditions = ["sim", "no_signal", "stale_penalty"]
    for inst in data:
        order = sorted(range(len(inst["haystack_sessions"])),
                       key=lambda i: ku_eval.parse_ts(inst["haystack_dates"][i]))
        ev_sids = set(inst["answer_session_ids"])
        ev_order = [si for si in order if inst["haystack_session_ids"][si] in ev_sids]
        if len(ev_order) != 2:
            continue
        early_si, late_si = ev_order
        rows, stale, fresh = [], set(), set()
        mem_id = 0
        for si in range(len(inst["haystack_sessions"])):
            ts = ku_eval.parse_ts(inst["haystack_dates"][si])
            for turn in inst["haystack_sessions"][si]:
                mem_id += 1
                rows.append((mem_id, turn["content"], ts))
                if turn.get("has_answer"):
                    (stale if si == early_si else fresh if si == late_si else set()).add(mem_id)
        if not stale or not fresh:
            continue
        cache = os.path.join(cache_dir, f"{inst['question_id']}.npz")
        if os.path.exists(cache):
            z = np.load(cache)
            turn_embs, q_emb = z["turns"], z["question"]
        else:
            turn_embs = common.encode(embedder, [t for _m, t, _ts in rows])
            q_emb = common.encode(embedder, [inst["question"]], kind="query")[0]
            np.savez_compressed(cache, turns=turn_embs, question=q_emb)
        late_ts = ku_eval.parse_ts(inst["haystack_dates"][late_si])
        q_ts = ku_eval.parse_ts(inst["question_date"])
        all_ids = [m for m, _t, _ts in rows]
        for cond in conditions:
            store = common.MemoryStore(rows, turn_embs)
            if cond == "stale_penalty":
                store.freeze(late_ts)
                store.record_accesses(sorted(stale))
                store.record_outcomes([(m, -1.0) for m in sorted(stale)])
            store.freeze(q_ts)
            rank_name = "sim" if cond == "sim" else FROZEN
            retrieved = common.rank(store, rank_name, q_emb, all_ids, q_ts, k)
            ev_ranked = [m for m in retrieved if m in stale | fresh]
            agg[cond]["update_pref"].append(1.0 if ev_ranked and ev_ranked[0] in fresh else 0.0)
            fresh_m = common.recall_ndcg(retrieved, fresh, k)
            agg[cond]["fresh_recall"].append(fresh_m["recall"])
            agg[cond]["stale_in_topk"].append(
                1.0 if any(m in stale for m in retrieved) else 0.0)
            store.close()
    print(f"\n=== FROZEN test: knowledge-update, {common.EMBEDDER_ID}, k={k} ===")
    for cond in conditions:
        a = agg[cond]
        print(f"{cond}: update-pref {np.mean(a['update_pref']):.3f}, "
              f"fresh recall {np.mean(a['fresh_recall']):.3f}, "
              f"stale-in-topk {np.mean(a['stale_in_topk']):.3f} (n={len(a['update_pref'])})")
    deltas = [x - y for x, y in zip(agg["stale_penalty"]["update_pref"],
                                    agg["no_signal"]["update_pref"])]
    lo, hi = common.bootstrap_ci(deltas)
    print(f"update-pref delta (penalty - no_signal): {np.mean(deltas):+.4f} [{lo:+.4f},{hi:+.4f}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", choices=["locomo", "swe", "ku"], required=True)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--out", default="results-frozen")
    args = ap.parse_args()
    if args.bench == "ku":
        run_ku(args.k, args.out)
    else:
        run_sequential(args.bench, args.k, args.out)


if __name__ == "__main__":
    main()
