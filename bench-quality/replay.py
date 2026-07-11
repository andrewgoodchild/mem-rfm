#!/usr/bin/env python3
"""LongMemEval retrieval-quality benchmark for sqlite-rfm.

Protocol (per instance): ingest haystack sessions in timestamp order. As each
session arrives, simulate agent usage: retrieve top-USAGE_K prior memories for
the session's opening user turn under the condition's own ranking, and record
those accesses (rfm_record_access) with the clock frozen to the session date.
At question_date, retrieve top-k for the question and score against the gold
evidence (per-turn has_answer flags / answer_session_ids) — no LLM judge.

Conditions (same embedder + turns, only ranking differs):
  sim          cosine similarity only
  sim_recency  sim * exp(-age/7d)  (simple industry-style recency hybrid)
  genagents    min-max normalized recency+relevance (Park et al. 2023;
               recency 0.995^hours since last retrieval; the paper's LLM-rated
               importance term is a constant here, so min-max removes it)
  rfm          sim * rfm_score(id)         (ours)
  rfm_wv0      sim * rfm_score_w(id,0.7,0) (ablation: no value axis)

The value (M) axis cannot earn quality gains in this protocol: LongMemEval has
one labeled question per instance, so no outcome stream exists to learn from.
--feedback-demo runs a separate mechanism experiment: record gold outcomes on
the first retrieval, re-rank, and report how evidence turns move.

Usage: replay.py [--instances N] [--k 10] [--feedback-demo] [--out results]
"""
import argparse
import datetime as dt
import json
import math
import os
import sqlite3
from collections import defaultdict

import numpy as np

import common

HERE = os.path.dirname(os.path.abspath(__file__))
DYLIB = common.DYLIB
DATA = os.path.join(HERE, "data", "longmemeval_s_cleaned.json")
CACHE = os.path.join(HERE, "cache")
USAGE_K = 5

CONDITIONS = ["sim", "sim_recency", "genagents", "rfm", "rfm_wv0"]


def parse_ts(s: str) -> float:
    return dt.datetime.strptime(s, "%Y/%m/%d (%a) %H:%M").timestamp()


def get_embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")


def embed_instance(inst, embedder):
    """Embed all turns, the question, and each session's opening user turn
    (the simulated-usage queries), cached per instance."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{inst['question_id']}.npz")
    if os.path.exists(path):
        z = np.load(path)
        return z["turns"], z["question"], z["openers"]
    texts = [t["content"][:2000] for sess in inst["haystack_sessions"] for t in sess]
    turns = embedder.encode(texts, normalize_embeddings=True, batch_size=128,
                            show_progress_bar=False).astype(np.float32)
    question = embedder.encode([inst["question"]], normalize_embeddings=True)[0].astype(np.float32)
    opener_texts = [
        next((t["content"][:2000] for t in sess if t["role"] == "user"), "")
        for sess in inst["haystack_sessions"]
    ]
    openers = embedder.encode(opener_texts, normalize_embeddings=True, batch_size=128,
                              show_progress_bar=False).astype(np.float32)
    np.savez_compressed(path, turns=turns, question=question, openers=openers)
    return turns, question, openers


class Memory:
    """One instance's memory store under one condition."""

    def __init__(self, inst, turn_embs):
        self.db = sqlite3.connect(":memory:")
        self.db.enable_load_extension(True)
        self.db.load_extension(DYLIB)
        self.db.enable_load_extension(False)
        self.db.execute("SELECT rfm_init()")
        order = sorted(range(len(inst["haystack_sessions"])),
                       key=lambda i: parse_ts(inst["haystack_dates"][i]))
        self.sessions = []  # (ts, [(mem_id, turn)], orig_session_idx)
        self.mem_meta = {}  # mem_id -> (session_id, is_evidence_turn)
        self.embs = turn_embs
        rows = []
        for si in order:
            sess = inst["haystack_sessions"][si]
            ts = parse_ts(inst["haystack_dates"][si])
            sid = inst["haystack_session_ids"][si]
            turns = []
            for ti, turn in enumerate(sess):
                mid = self._flat_id(inst, si, ti)
                rows.append((mid, turn["content"][:200], ts))
                self.mem_meta[mid] = (sid, bool(turn.get("has_answer")))
                turns.append((mid, turn))
            self.sessions.append((ts, turns, si))
        self.db.executemany(
            "INSERT INTO rfm_memories(id, content, created_at) VALUES (?,?,?)", rows)
        # embedding row order == flat enumeration order of haystack_sessions
        self.flat_index = {}
        i = 0
        for si, sess in enumerate(inst["haystack_sessions"]):
            for ti in range(len(sess)):
                self.flat_index[self._flat_id(inst, si, ti)] = i
                i += 1

    @staticmethod
    def _flat_id(inst, si, ti):
        return si * 10_000 + ti + 1

    def freeze(self, t: float):
        self.db.execute("SELECT rfm_config('now', ?)", (t,))

    def sims(self, query_emb, ids):
        idx = [self.flat_index[m] for m in ids]
        return self.embs[idx] @ query_emb

    def rfm_scores(self, ids, w=None):
        fn = "rfm_score(id)" if w is None else f"rfm_score_w(id, {w[0]}, {w[1]})"
        placeholders = ",".join("?" * len(ids))
        got = dict(self.db.execute(
            f"SELECT id, {fn} FROM rfm_memories WHERE id IN ({placeholders})", ids))
        return np.array([got[m] for m in ids])

    def access_state(self, ids):
        placeholders = ",".join("?" * len(ids))
        got = {r[0]: (r[1], r[2]) for r in self.db.execute(
            f"SELECT id, created_at, last_access FROM rfm_memories WHERE id IN ({placeholders})",
            ids)}
        return [got[m] for m in ids]

    def record_accesses(self, ids):
        for m in ids:
            self.db.execute("SELECT rfm_record_access(?)", (m,))

    def record_outcomes(self, pairs):
        for m, o in pairs:
            self.db.execute("SELECT rfm_record_outcome(?, ?)", (m, o))


# Ranking conditions live in common.rank (shared with locomo_eval/ku_eval);
# Memory duck-types common.MemoryStore's scoring surface.
rank = common.rank


def replay_instance(inst, turn_embs, q_emb, opener_embs, condition, k):
    mem = Memory(inst, turn_embs)
    seen: list[int] = []
    for ts, turns, si in mem.sessions:
        if seen and any(t["role"] == "user" for _m, t in turns):
            # Simulated usage: opening user turn triggers retrieval over prior
            # memory; retrieved memories get accesses under this condition's
            # own ranking (self-consistent, like a real deployment).
            mem.freeze(ts)
            hits = rank(mem, condition, opener_embs[si], seen, ts, USAGE_K)
            mem.record_accesses(hits)
        seen.extend(m for m, _t in turns)
    q_ts = parse_ts(inst["question_date"])
    mem.freeze(q_ts)
    retrieved = rank(mem, condition, q_emb, seen, q_ts, k)
    return mem, retrieved, seen


def metrics(mem: Memory, retrieved, k):
    ev_turns = {m for m, (_s, ev) in mem.mem_meta.items() if ev}
    ev_sessions = {s for m, (s, ev) in mem.mem_meta.items() if ev}
    got_turns = [m for m in retrieved if m in ev_turns]
    got_sessions = {mem.mem_meta[m][0] for m in retrieved}
    dcg = sum(1.0 / math.log2(i + 2) for i, m in enumerate(retrieved) if m in ev_turns)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(ev_turns), k)))
    return {
        "turn_recall": len(set(got_turns)) / len(ev_turns) if ev_turns else None,
        "turn_hit": 1.0 if got_turns else 0.0,
        "session_recall": (len(got_sessions & ev_sessions) / len(ev_sessions)
                           if ev_sessions else None),
        "ndcg": dcg / ideal if ideal > 0 else None,
    }


def feedback_demo(mem: Memory, retrieved, seen, q_emb, q_ts, k):
    """Mechanism check (label leakage by design — measures adaptation, not
    generalization): give gold outcomes for the first retrieval, re-rank."""
    ev = {m for m, (_s, e) in mem.mem_meta.items() if e}
    mem.record_accesses(retrieved)
    mem.record_outcomes([(m, 1.0 if m in ev else -1.0) for m in retrieved])
    again = rank(mem, "rfm", q_emb, seen, q_ts, k)
    return metrics(mem, again, k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", type=int, default=500)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--feedback-demo", action="store_true")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    data = json.load(open(DATA))[: args.instances]
    embedder = get_embedder()
    os.makedirs(args.out, exist_ok=True)
    sink = open(os.path.join(args.out, "per_question.jsonl"), "w")
    agg = defaultdict(lambda: defaultdict(list))

    for n, inst in enumerate(data):
        turn_embs, q_emb, opener_embs = embed_instance(inst, embedder)
        for cond in CONDITIONS:
            mem, retrieved, seen = replay_instance(inst, turn_embs, q_emb, opener_embs,
                                                   cond, args.k)
            m = metrics(mem, retrieved, args.k)
            if args.feedback_demo and cond == "rfm":
                m["after_feedback"] = feedback_demo(mem, retrieved, seen, q_emb,
                                                    parse_ts(inst["question_date"]), args.k)
            sink.write(json.dumps({
                "question_id": inst["question_id"], "question_type": inst["question_type"],
                "condition": cond, "retrieved": retrieved, **m}) + "\n")
            for key, val in m.items():
                if isinstance(val, (int, float)):
                    agg[cond][key].append(val)
                    agg[(cond, inst["question_type"])][key].append(val)
            mem.db.close()
        if (n + 1) % 25 == 0:
            print(f"{n + 1}/{len(data)} instances", flush=True)
    sink.close()

    print(f"\n=== k={args.k}, {len(data)} instances ===")
    print(f"| condition | turn recall | turn hit | session recall | NDCG |")
    print(f"|---|---|---|---|---|")
    for cond in CONDITIONS:
        a = agg[cond]
        print(f"| {cond} | " + " | ".join(
            f"{np.mean(a[m]):.3f}" for m in ["turn_recall", "turn_hit", "session_recall", "ndcg"])
            + " |")
    qtypes = sorted({qt for (c, qt) in [k for k in agg if isinstance(k, tuple)]})
    print("\nturn recall by question type:")
    print("| condition | " + " | ".join(qtypes) + " |")
    print("|---" * (len(qtypes) + 1) + "|")
    for cond in CONDITIONS:
        cells = [f"{np.mean(agg[(cond, qt)]['turn_recall']):.3f}" if agg[(cond, qt)]["turn_recall"]
                 else "-" for qt in qtypes]
        print(f"| {cond} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
