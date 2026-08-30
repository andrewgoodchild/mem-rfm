#!/usr/bin/env python3
"""LoCoMo sequential-feedback eval — the leakage-free test of the M axis.

LoCoMo (snap-research, CC BY-NC 4.0) has ~1,986 questions over 10
conversations, each question annotated with gold evidence dia_ids. Because
many questions share evidence turns (measured: ~49% of questions have
evidence that already served an earlier question), outcome feedback earned on
question k can legitimately improve retrieval for questions k+1..n — no label
leakage: feedback and evaluation never touch the same question.

Protocol per conversation: ingest all sessions chronologically, then ask the
(deterministically shuffled) category-1..4 questions in sequence. For every
condition the retrieved top-k of question k earns rfm_record_access; in the
M-on condition it additionally earns outcomes from question k's gold evidence
(+1 evidence turn, -1 otherwise). Metrics are always computed BEFORE the
feedback for that question is recorded.

Conditions: sim (no state), rfm_wv0 (accesses recorded, value axis off),
rfm (accesses + outcomes, value axis on). M's isolated contribution is the
paired per-question delta rfm - rfm_wv0; both carry identical access-recording
protocol and scoring floor... rfm_wv0 has no value floor, so the cleaner
comparison set is all three; report paired deltas vs both baselines, split by
whether the question's evidence overlapped any earlier question's evidence.

Usage: locomo_eval.py [--k 10] [--out results-locomo]
"""
import argparse
import datetime as dt
import json
import os
import random
from collections import defaultdict

import numpy as np

import common

DATA = os.path.join(common.HERE, "data", "locomo10.json")
CACHE = os.path.join(common.HERE, "cache-locomo" + common.cache_suffix())
CONDITIONS = ["sim", "rfm_wv0", "rfm"]
QUESTION_SPACING = 60.0  # seconds between successive questions in frozen time


def parse_ts(s: str) -> float:
    # e.g. "1:56 pm on 8 May, 2023"
    return dt.datetime.strptime(s, "%I:%M %p on %d %B, %Y").timestamp()


def load_conversation(conv):
    """Flatten one LoCoMo conversation to (rows, dia_to_mem, last_ts)."""
    c = conv["conversation"]
    sessions = []
    for key in c:
        if key.startswith("session_") and not key.endswith("_date_time"):
            idx = int(key.split("_")[1])
            sessions.append((idx, parse_ts(c[f"{key}_date_time"]), c[key]))
    sessions.sort(key=lambda s: (s[1], s[0]))
    rows, dia_to_mem = [], {}
    mem_id = 1
    last_ts = 0.0
    for _idx, ts, turns in sessions:
        last_ts = max(last_ts, ts)
        for turn in turns:
            text = f"{turn['speaker']}: {turn['text']}"
            if turn.get("blip_caption"):
                text += f" [shares an image: {turn['blip_caption']}]"
            rows.append((mem_id, text, ts))
            dia_to_mem[turn["dia_id"]] = mem_id
            mem_id += 1
    return rows, dia_to_mem, last_ts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--conversations", type=int, default=10)
    ap.add_argument("--out", default="results-locomo")
    ap.add_argument("--m-rules", action="store_true",
                    help="Track 12 (Amendment 17): additionally score the "
                         "`importance` (write-time prior) and `pertoken` "
                         "(value density) rules. Off by default so the "
                         "committed conditions stay bit-identical.")
    ap.add_argument("--feedback-batch", type=int, default=1,
                    help="record outcomes every G questions (session-level "
                         "credit: one outcome per memory per batch, +1 if it "
                         "was evidence for any batch question it was retrieved "
                         "for). Simulates coarse production feedback.")
    args = ap.parse_args()

    data = json.load(open(DATA))[: args.conversations]
    conditions = list(CONDITIONS)
    imp_by_text = {}
    if args.m_rules:
        conditions += ["importance", "pertoken"]
        cache_path = os.path.join(common.HERE, "results-track12",
                                  "importance.jsonl")
        for line in open(cache_path):
            r = json.loads(line)
            imp_by_text[r["t"]] = r["imp"]
        print(f"m-rules: {len(imp_by_text)} cached write-time scores")
    embedder = common.get_embedder()
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    sink = open(os.path.join(args.out, "per_question.jsonl"), "w")
    agg = defaultdict(lambda: defaultdict(list))
    paired = defaultdict(list)  # (baseline, split) -> list of rfm-minus-baseline ndcg deltas

    for conv in data:
        rows, dia_to_mem, last_ts = load_conversation(conv)
        # Category 5 is adversarial/unanswerable (no evidence) — standard drop.
        qas = [q for q in conv["qa"] if q.get("category") != 5 and q.get("evidence")]
        order = list(range(len(qas)))
        random.Random(13).shuffle(order)
        qas = [qas[i] for i in order]

        cache = os.path.join(CACHE, f"{conv['sample_id']}.npz")
        if os.path.exists(cache):
            z = np.load(cache)
            turn_embs, q_embs = z["turns"], z["questions"]
        else:
            turn_embs = common.encode(embedder, [t for _m, t, _ts in rows])
            q_embs = common.encode(embedder, [q["question"] for q in qas], kind="query")
            np.savez_compressed(cache, turns=turn_embs, questions=q_embs)

        all_ids = [m for m, _t, _ts in rows]
        stores = {c: common.MemoryStore(rows, turn_embs) for c in conditions}
        aux = None
        if args.m_rules:
            toklen = {m: len(t.split()) for m, t, _ts in rows}
            import statistics as _st
            aux = {"imp": {m: imp_by_text.get(t, 0.5)
                           for m, t, _ts in rows},
                   "toklen": toklen,
                   "median_len": _st.median(toklen.values()) or 1}
        seen_evidence = set()
        per_q = defaultdict(dict)  # question idx -> condition -> metrics
        batch_pos, batch_all = set(), set()  # coarse-feedback accumulators

        for qi, qa in enumerate(qas):
            evidence_mems = {dia_to_mem[d] for d in qa["evidence"] if d in dia_to_mem}
            if not evidence_mems:
                continue
            overlap = bool(evidence_mems & seen_evidence)
            now = last_ts + 3600.0 + qi * QUESTION_SPACING
            for cond in conditions:
                store = stores[cond]
                store.freeze(now)
                retrieved = common.rank(store, cond, q_embs[qi], all_ids,
                                        now, args.k, aux)
                m = common.recall_ndcg(retrieved, evidence_mems, args.k)
                m["overlap"] = overlap
                per_q[qi][cond] = m
                sink.write(json.dumps({
                    "conversation": conv["sample_id"], "q_idx": qi,
                    "category": qa["category"], "condition": cond,
                    "overlap": overlap, **{k: v for k, v in m.items() if k != "overlap"},
                }) + "\n")
                for key in ("recall", "hit", "ndcg"):
                    if m[key] is not None:
                        agg[(cond, "all")][key].append(m[key])
                        agg[(cond, f"overlap={overlap}")][key].append(m[key])
                        agg[(cond, f"cat{qa['category']}")][key].append(m[key])
                # Feedback AFTER measuring: accesses for stateful conditions,
                # outcomes only in the M-on condition. With --feedback-batch G
                # outcomes land every G questions (coarse credit), one per
                # memory: +1 if it was evidence for any batch question it was
                # retrieved for.
                if cond != "sim":
                    store.record_accesses(retrieved)
                    if cond in ("rfm", "pertoken"):
                        if args.feedback_batch <= 1:
                            store.record_outcomes(
                                [(m_, 1.0 if m_ in evidence_mems else -1.0)
                                 for m_ in retrieved])
                        else:
                            batch_all.update(retrieved)
                            batch_pos.update(m_ for m_ in retrieved
                                             if m_ in evidence_mems)
                            if (qi + 1) % args.feedback_batch == 0:
                                store.record_outcomes(
                                    [(m_, 1.0 if m_ in batch_pos else -1.0)
                                     for m_ in sorted(batch_all)])
                                batch_pos, batch_all = set(), set()
            for base in ("sim", "rfm_wv0"):
                a, b = per_q[qi].get("rfm"), per_q[qi].get(base)
                if a and b and a["ndcg"] is not None and b["ndcg"] is not None:
                    paired[(base, "all")].append(a["ndcg"] - b["ndcg"])
                    paired[(base, f"overlap={overlap}")].append(a["ndcg"] - b["ndcg"])
            seen_evidence |= evidence_mems
        for store in stores.values():
            store.close()
        print(f"{conv['sample_id']}: {len(qas)} questions done", flush=True)
    sink.close()

    print(f"\n=== LoCoMo sequential feedback, k={args.k} ===")
    print("| condition | split | recall | hit | NDCG | n |")
    print("|---|---|---|---|---|---|")
    for cond in conditions:
        for split in ("all", "overlap=True", "overlap=False"):
            a = agg[(cond, split)]
            if a["ndcg"]:
                print(f"| {cond} | {split} | {np.mean(a['recall']):.3f} | "
                      f"{np.mean(a['hit']):.3f} | {np.mean(a['ndcg']):.3f} | {len(a['ndcg'])} |")
    print("\npaired NDCG deltas (rfm minus baseline), mean [95% bootstrap CI]:")
    for (base, split), deltas in sorted(paired.items()):
        lo, hi = common.bootstrap_ci(deltas)
        print(f"  vs {base:8s} {split:15s} {np.mean(deltas):+.4f}  [{lo:+.4f}, {hi:+.4f}]  n={len(deltas)}")


if __name__ == "__main__":
    main()
