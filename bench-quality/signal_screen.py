#!/usr/bin/env python3
"""Screen candidate value signals against gold evidence on all three
benchmarks: does each signal separate evidence turns from non-evidence turns?

Signals (all computable from cached embeddings + text; no LLM, no keys):
  demand      max cosine to user turns in strictly LATER sessions — exogenous
              recurrence ("the user keeps bringing this up"); immune to the
              retrieval feedback loop by construction
  answer_align cosine to the gold answer text — the CEILING of the
              answer-alignment family (production would use generated answers)
  distinct    1 - max cosine to any other turn (uniqueness / diversity)
  hub         mean cosine to all other turns (semantic "richness"/hubness;
              predicted nil-or-negative)
  length      characters (verbosity as a richness proxy)
  is_user     the turn is a user turn (type/provenance heuristic; note BEAM
              evidence skews to user turns by construction — read with care)

Metric: per-conversation AUC (Mann-Whitney) of signal vs is-evidence, macro-
averaged; AUC 0.5 = useless, >0.6 = promising prior. Evidence = union of all
questions' gold turns for that conversation/instance.

Usage: signal_screen.py [--lme-instances 100]
"""
import argparse
import json
import os
from collections import defaultdict

import numpy as np

import common
import locomo_eval
import beam_eval


def auc(scores, labels):
    """Mann-Whitney AUC with average ranks for ties (a constant signal
    scores exactly 0.5)."""
    from scipy.stats import rankdata
    scores, labels = np.asarray(scores, float), np.asarray(labels, bool)
    n_pos, n_neg = int(labels.sum()), int((~labels).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = rankdata(scores)  # average ranks on ties
    u = ranks[labels].sum() - n_pos * (n_pos + 1) / 2
    return u / (n_pos * n_neg)


def signals_for(embs, texts, timestamps, is_user, answer_embs):
    """Compute all candidate signals for one conversation's turns."""
    sim = embs @ embs.T
    np.fill_diagonal(sim, -1.0)
    out = {}
    out["distinct"] = 1.0 - sim.max(axis=1)
    np.fill_diagonal(sim, 0.0)
    out["hub"] = sim.sum(axis=1) / (len(embs) - 1)
    out["length"] = np.array([len(t) for t in texts], float)
    out["is_user"] = np.array(is_user, float)
    # demand: max similarity to user turns in strictly later sessions
    ts = np.asarray(timestamps)
    demand = np.zeros(len(embs))
    user_idx = np.where(np.array(is_user))[0]
    for i in range(len(embs)):
        later = user_idx[ts[user_idx] > ts[i]]
        if len(later):
            demand[i] = float((embs[later] @ embs[i]).max())
    out["demand"] = demand
    # answer_align: max cosine to any gold answer of this conversation
    if answer_embs is not None and len(answer_embs):
        out["answer_align"] = (embs @ answer_embs.T).max(axis=1)
    return out


def screen(name, conversations, results):
    """conversations: iterable of dicts with embs/texts/ts/is_user/answers/evidence."""
    per_signal = defaultdict(list)
    n_ev = n_turns = 0
    for conv in conversations:
        labels = conv["evidence_mask"]
        if labels.sum() == 0:
            continue
        n_ev += int(labels.sum())
        n_turns += len(labels)
        sigs = signals_for(conv["embs"], conv["texts"], conv["ts"],
                           conv["is_user"], conv.get("answer_embs"))
        for sig, vals in sigs.items():
            a = auc(vals, labels)
            if a is not None:
                per_signal[sig].append(a)
    for sig, aucs in sorted(per_signal.items()):
        results.append((name, sig, float(np.mean(aucs)), len(aucs), n_ev, n_turns))


def locomo_conversations(embedder):
    data = json.load(open(os.path.join(common.HERE, "data", "locomo10.json")))
    for conv in data:
        rows, dia_to_mem, _ = locomo_eval.load_conversation(conv)
        cache = os.path.join(locomo_eval.CACHE, f"{conv['sample_id']}.npz")
        embs = np.load(cache)["turns"] if os.path.exists(cache) else common.encode(
            embedder, [t for _m, t, _ts in rows])
        qas = [q for q in conv["qa"] if q.get("category") != 5 and q.get("evidence")]
        ev_mems = {dia_to_mem[d] for q in qas for d in q["evidence"] if d in dia_to_mem}
        mem_ids = [m for m, _t, _ts in rows]
        answers = [str(q["answer"]) for q in qas if q.get("answer")]
        yield {
            "embs": embs,
            "texts": [t for _m, t, _ts in rows],
            "ts": [ts for _m, _t, ts in rows],
            # LoCoMo has two human speakers, no assistant: every turn is
            # "user-authored", so is_user is uninformative here — mark all True.
            "is_user": [True] * len(rows),
            "answer_embs": common.encode(embedder, answers) if answers else None,
            "evidence_mask": np.array([m in ev_mems for m in mem_ids]),
        }


def beam_conversations(embedder):
    for ci in range(1, 21):
        conv_dir = os.path.join(beam_eval.DATA, str(ci))
        if not os.path.isdir(conv_dir):
            continue
        rows, chatid_to_mem, _ = beam_eval.load_conversation(conv_dir)
        cache = os.path.join(beam_eval.CACHE, f"conv{ci}.npz")
        embs = np.load(cache)["turns"] if os.path.exists(cache) else common.encode(
            embedder, [t for _m, t, _ts in rows])
        qas = beam_eval.load_questions(conv_dir)
        ev_mems = {chatid_to_mem[c] for q in qas for c in q["evidence"] if c in chatid_to_mem}
        pq = json.load(open(os.path.join(conv_dir, "probing_questions.json")))
        answers = []
        for cat, qs in pq.items():
            if cat == "abstention":
                continue
            for q in qs:
                ans = q.get("answer") or q.get("ideal_response") or q.get("ideal_answer")
                if ans:
                    answers.append(str(ans))
        mem_ids = [m for m, _t, _ts in rows]
        yield {
            "embs": embs,
            "texts": [t for _m, t, _ts in rows],
            "ts": [ts for _m, _t, ts in rows],
            "is_user": [t.startswith("user:") for _m, t, _ts in rows],
            "answer_embs": common.encode(embedder, answers) if answers else None,
            "evidence_mask": np.array([m in ev_mems for m in mem_ids]),
        }


def lme_instances(embedder, limit):
    import datetime as dt
    data = json.load(open(os.path.join(common.HERE, "data", "longmemeval_s_cleaned.json")))
    for inst in data[:limit]:
        cache = os.path.join(common.HERE, "cache", f"{inst['question_id']}.npz")
        texts, ts, is_user, ev_mask = [], [], [], []
        for si, sess in enumerate(inst["haystack_sessions"]):
            t = dt.datetime.strptime(inst["haystack_dates"][si], "%Y/%m/%d (%a) %H:%M").timestamp()
            for turn in sess:
                texts.append(turn["content"])
                ts.append(t)
                is_user.append(turn["role"] == "user")
                ev_mask.append(bool(turn.get("has_answer")))
        embs = np.load(cache)["turns"] if os.path.exists(cache) else common.encode(embedder, texts)
        answers = [str(inst["answer"])] if inst.get("answer") else []
        yield {
            "embs": embs, "texts": texts, "ts": ts, "is_user": is_user,
            "answer_embs": common.encode(embedder, answers) if answers else None,
            "evidence_mask": np.array(ev_mask),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lme-instances", type=int, default=100)
    args = ap.parse_args()
    embedder = common.get_embedder()
    results = []
    screen("LoCoMo", locomo_conversations(embedder), results)
    print("LoCoMo done", flush=True)
    screen("BEAM", beam_conversations(embedder), results)
    print("BEAM done", flush=True)
    screen("LongMemEval", lme_instances(embedder, args.lme_instances), results)
    print("LongMemEval done", flush=True)

    print("\n=== Signal screen: AUC of signal vs gold-evidence, macro over conversations ===")
    print("| signal | LoCoMo | BEAM | LongMemEval |")
    print("|---|---|---|---|")
    by_sig = defaultdict(dict)
    for bench, sig, a, _n, _ne, _nt in results:
        by_sig[sig][bench] = a
    for sig in sorted(by_sig):
        row = by_sig[sig]
        print(f"| {sig} | " + " | ".join(
            f"{row.get(b, float('nan')):.3f}" for b in ("LoCoMo", "BEAM", "LongMemEval")) + " |")
    for bench, _s, _a, n, ne, nt in results[:1]:
        pass
    stats = {b: (ne, nt) for b, _s, _a, _n, ne, nt in results}
    for b, (ne, nt) in stats.items():
        print(f"{b}: {ne} evidence turns / {nt} total")


if __name__ == "__main__":
    main()
