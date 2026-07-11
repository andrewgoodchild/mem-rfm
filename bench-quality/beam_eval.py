#!/usr/bin/env python3
"""BEAM (128K tier) sequential-feedback retrieval eval.

BEAM (ICLR 2026, CC BY-SA 4.0 data) ships message-level gold evidence: every
probing question carries `source_chat_ids` referencing turn ids in chat.json,
so retrieval recall needs no LLM judge (the official pipeline never uses these
ids — the retrieval metric here is ours). Caveats, disclosed: the annotations
were produced by GPT-4.1-mini during question generation with human review of
question validity, and for most categories only user turns were shown to the
generator, so evidence skews toward user turns.

Protocol mirrors locomo_eval.py: ingest all turns (created_at = the batch's
time anchor), then ask the conversation's probing questions (deterministically
shuffled, abstention excluded — unanswerable by design) in sequence. Stateful
conditions record accesses on each retrieval; the M-on condition additionally
records evidence-hit outcomes. Metrics are computed before that question's
feedback lands. With only ~18 usable questions per conversation the feedback
stream is short — expect smaller M effects than LoCoMo's ~150-question runs;
that contrast is part of the point.

Conditions: sim, rfm_wv0, rfm. Usage: beam_eval.py [--k 10] [--out results-beam]
"""
import argparse
import datetime as dt
import json
import os
import random
from collections import defaultdict

import numpy as np

import common

DATA = os.path.join(common.HERE, "data", "beam")
CACHE = os.path.join(common.HERE, "cache-beam" + common.cache_suffix())
CONDITIONS = ["sim", "rfm_wv0", "rfm"]
QUESTION_SPACING = 60.0


def parse_anchor(s: str) -> float:
    # e.g. "March-15-2024"
    return dt.datetime.strptime(s, "%B-%d-%Y").timestamp()


def flatten_evidence(ids):
    """source_chat_ids varies by category: flat list, dict of lists, and in a
    few conversations nested lists — flatten recursively, keep int-coercible."""
    out = []
    def walk(x):
        if x is None:
            return
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        else:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                pass
    walk(ids)
    return out


def load_conversation(conv_dir):
    """Flatten one BEAM conversation to (rows, chatid_to_mem, last_ts)."""
    chat = json.load(open(os.path.join(conv_dir, "chat.json")))
    rows, chatid_to_mem = [], {}
    last_anchor = None
    last_ts = 0.0
    for batch in chat:
        # Batch time anchor: the batch's own, else the first user turn's,
        # else carry the previous batch's forward.
        anchor = batch.get("time_anchor")
        if not anchor:
            anchor = next(
                (m.get("time_anchor") for ex in batch["turns"]
                 for m in ex if m.get("time_anchor")), last_anchor)
        last_anchor = anchor
        ts = parse_anchor(anchor) if anchor else last_ts
        last_ts = max(last_ts, ts)
        for exchange in batch["turns"]:
            for msg in exchange:
                cid = int(msg["id"])
                mem = cid + 1  # keep ids strictly positive
                rows.append((mem, f"{msg['role']}: {msg['content']}", ts))
                chatid_to_mem[cid] = mem
    return rows, chatid_to_mem, last_ts


def load_questions(conv_dir):
    pq = json.load(open(os.path.join(conv_dir, "probing_questions.json")))
    out = []
    for cat, questions in sorted(pq.items()):
        if cat == "abstention":
            continue
        for q in questions:
            ev = flatten_evidence(q.get("source_chat_ids"))
            if ev:
                out.append({"category": cat, "question": q["question"], "evidence": ev})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--conversations", type=int, default=20)
    ap.add_argument("--out", default="results-beam")
    args = ap.parse_args()

    embedder = common.get_embedder()
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    sink = open(os.path.join(args.out, "per_question.jsonl"), "w")
    agg = defaultdict(lambda: defaultdict(list))
    paired = defaultdict(list)

    for ci in range(1, args.conversations + 1):
        conv_dir = os.path.join(DATA, str(ci))
        if not os.path.isdir(conv_dir):
            continue
        rows, chatid_to_mem, last_ts = load_conversation(conv_dir)
        qas = load_questions(conv_dir)
        random.Random(13).shuffle(qas)

        cache = os.path.join(CACHE, f"conv{ci}.npz")
        if os.path.exists(cache):
            z = np.load(cache)
            turn_embs, q_embs = z["turns"], z["questions"]
        else:
            turn_embs = common.encode(embedder, [t for _m, t, _ts in rows])
            q_embs = common.encode(embedder, [q["question"] for q in qas], kind="query")
            np.savez_compressed(cache, turns=turn_embs, questions=q_embs)

        all_ids = [m for m, _t, _ts in rows]
        stores = {c: common.MemoryStore(rows, turn_embs) for c in CONDITIONS}
        seen_evidence = set()

        for qi, qa in enumerate(qas):
            evidence_mems = {chatid_to_mem[c] for c in qa["evidence"] if c in chatid_to_mem}
            if not evidence_mems:
                continue
            overlap = bool(evidence_mems & seen_evidence)
            now = last_ts + 3600.0 + qi * QUESTION_SPACING
            per_cond = {}
            for cond in CONDITIONS:
                store = stores[cond]
                store.freeze(now)
                retrieved = common.rank(store, cond, q_embs[qi], all_ids, now, args.k)
                m = common.recall_ndcg(retrieved, evidence_mems, args.k)
                per_cond[cond] = m
                sink.write(json.dumps({
                    "conversation": ci, "q_idx": qi, "category": qa["category"],
                    "condition": cond, "overlap": overlap, **m}) + "\n")
                for key in ("recall", "hit", "ndcg"):
                    if m[key] is not None:
                        agg[(cond, "all")][key].append(m[key])
                        agg[(cond, f"overlap={overlap}")][key].append(m[key])
                if cond != "sim":
                    store.record_accesses(retrieved)
                    if cond == "rfm":
                        store.record_outcomes(
                            [(m_, 1.0 if m_ in evidence_mems else -1.0) for m_ in retrieved])
            for base in ("sim", "rfm_wv0"):
                a, b = per_cond["rfm"], per_cond[base]
                if a["ndcg"] is not None and b["ndcg"] is not None:
                    paired[(base, "all")].append(a["ndcg"] - b["ndcg"])
                    paired[(base, f"overlap={overlap}")].append(a["ndcg"] - b["ndcg"])
            seen_evidence |= evidence_mems
        for store in stores.values():
            store.close()
        print(f"conversation {ci}: {len(qas)} questions done", flush=True)
    sink.close()

    print(f"\n=== BEAM 128K sequential feedback, k={args.k} ===")
    print("| condition | split | recall | hit | NDCG | n |")
    print("|---|---|---|---|---|---|")
    for cond in CONDITIONS:
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
