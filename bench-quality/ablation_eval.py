#!/usr/bin/env python3
"""Component ablation: does each part of mem-rfm earn its place?
(PROTOCOL.md Amendment 12.)

Three bars are easy to conflate. A mechanism can be IMPLEMENTED (the code
runs), CONNECTED (something reads its output), and EARN ITS PLACE (removing
it makes results worse). Comparable systems generally claim the first; the
nearest one's own audit concedes only "exercised on every run", explicitly
not "measured to help". This measures the third for our components.

Every arm runs through the shipped extension via rfm_config — so what is
ablated is the code that ships, not a re-implementation of it. BEAM dev with
the sequential feedback protocol, so both scoring axes are live: ablating
the value axis on a dataset where it is inert would measure nothing.

Usage: ablation_eval.py [--conversations 20] [--k 10]
"""
import argparse
import json
import math
import os
import random
from collections import defaultdict

import numpy as np

import common
from beam_eval import CACHE, DATA, QUESTION_SPACING, load_conversation, load_questions

# name -> rfm_config overrides applied to that arm's store
ARMS = {
    "full":          {},
    "no_value":      {"w_v": 0.0},
    "no_activation": {"w_a": 0.0},
    "no_prior":      {"beta": 0.0},
    "no_shrink":     {"shrink_k": 0.0},
    "no_decay":      {"decay": 0.01},
    "fast_decay":    {"decay": 0.9},
    # ADDITIVE arms: mechanisms mem-rfm does NOT have. These ask "does adding
    # it help?" rather than "does removing it hurt". Implemented harness-side
    # so they can be measured before earning any extension surface — the
    # nearest comparable project ships both and has never measured either.
    "plus_hebbian":       {},
    "plus_consolidation": {},
    "plus_both":          {},
}

HEBBIAN = {"plus_hebbian", "plus_both"}
CONSOLIDATION = {"plus_consolidation", "plus_both"}

HEBB_WEIGHT = 0.3        # how far association may move a score
REPLAY_EVERY = 10        # questions between consolidation passes
REPLAY_N = 5             # memories refreshed per pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conversations", type=int, default=20)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--out", default="results-ablation")
    args = ap.parse_args()

    embedder = common.get_embedder()
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)
    sink = open(os.path.join(args.out, "per_question.jsonl"), "w")

    ndcg = defaultdict(list)
    # Stratified by recurrence: a question is `overlap` when its evidence
    # already served an EARLIER question, i.e. the memory is being re-used.
    # That is exactly the condition the activation axis is supposed to
    # exploit, so averaging across both strata dilutes the very effect the
    # ablation is trying to detect.
    ndcg_overlap = defaultdict(list)
    ndcg_fresh = defaultdict(list)
    live = defaultdict(lambda: {"scored": 0, "nonzero": 0})

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
        seen_evidence = set()
        # Hebbian state, per arm: co-retrieval counts and per-memory fan.
        co = {a: defaultdict(lambda: defaultdict(int)) for a in ARMS}
        fan = {a: defaultdict(int) for a in ARMS}
        context = {a: [] for a in ARMS}       # previous turn's retrieved set
        stores = {}
        for arm, cfg in ARMS.items():
            st = common.MemoryStore(rows, turn_embs)
            for key, val in cfg.items():
                st.db.execute("SELECT rfm_config(?, ?)", (key, val))
            stores[arm] = st

        for qi, qa in enumerate(qas):
            evidence = {chatid_to_mem[c] for c in qa["evidence"] if c in chatid_to_mem}
            if not evidence:
                continue
            now = last_ts + 3600.0 + qi * QUESTION_SPACING
            is_overlap = bool(evidence & seen_evidence)
            for arm, store in stores.items():
                store.freeze(now)
                # Liveness check: an ablation is only meaningful if the signal
                # it removes was actually varying. A silent dead channel makes
                # every arm identical and invalidates the whole study, which is
                # how a comparable project lost months of A/B results.
                priors = store.priors(all_ids)
                live[arm]["scored"] += len(priors)
                live[arm]["nonzero"] += int(np.count_nonzero(
                    np.abs(priors - priors[0]) > 1e-12))
                sims = np.maximum(store.sims(q_embs[qi], all_ids), 0.0)
                scores = sims * priors

                if arm in HEBBIAN and context[arm]:
                    # Spreading activation by co-retrieval. ACT-R's fan effect
                    # discounts a source that associates with everything:
                    # Sji = S - ln(fan). A memory co-retrieved with the current
                    # context gets a bounded boost; promiscuous ones get less.
                    boost = np.ones(len(all_ids))
                    for idx, mid in enumerate(all_ids):
                        strength = 0.0
                        for c in context[arm]:
                            n_co = co[arm][mid].get(c, 0)
                            if n_co:
                                strength += n_co / (1.0 + math.log(1.0 + fan[arm][c]))
                        if strength:
                            boost[idx] = 1.0 + HEBB_WEIGHT * (
                                strength / (1.0 + strength))
                    scores = scores * boost

                order = np.argsort(-scores, kind="stable")[:args.k]
                retrieved = [all_ids[i] for i in order]
                m = common.recall_ndcg(retrieved, evidence, args.k)
                val = m["ndcg"] or 0.0
                ndcg[arm].append(val)
                (ndcg_overlap if is_overlap else ndcg_fresh)[arm].append(val)
                sink.write(json.dumps({"conversation": ci, "q_idx": qi,
                                       "arm": arm, "ndcg": m["ndcg"],
                                       "hit": m["hit"],
                                       "overlap": is_overlap}) + "\n")
                store.record_accesses(retrieved)
                store.record_outcomes(
                    [(mid, 1.0 if mid in evidence else -1.0) for mid in retrieved])

                if arm in HEBBIAN:
                    for a_i in retrieved:
                        fan[arm][a_i] += 1
                        for b_i in retrieved:
                            if a_i != b_i:
                                co[arm][a_i][b_i] += 1
                    context[arm] = retrieved

                if arm in CONSOLIDATION and qi and qi % REPLAY_EVERY == 0:
                    # Interleaved replay (complementary learning systems):
                    # refresh valuable-but-cold memories so they do not decay
                    # past recovery. Only memories that PROVED useful are
                    # replayed — replaying everything is just a slower clock.
                    vals, counts = store.value_state(all_ids)
                    acts = store.activations(all_ids)
                    useful = [(acts[i], all_ids[i]) for i in range(len(all_ids))
                              if counts[i] > 0 and vals[i] > 0]
                    useful.sort()
                    for _a, mid in useful[:REPLAY_N]:
                        store.record_accesses([mid])
            seen_evidence |= evidence
        for st in stores.values():
            st.close()
        print(f"conv {ci} done", flush=True)

    sink.close()

    print(f"\n=== Component ablation (BEAM dev, k={args.k}, "
          f"{common.EMBEDDER_ID}) ===")
    print(f"{len(ndcg['full'])} questions per arm\n")
    print("| arm | NDCG@k | Δ vs full | verdict |")
    print("|---|---|---|---|")
    base = ndcg["full"]
    for arm in ARMS:
        vals = ndcg[arm]
        n = min(len(vals), len(base))
        d = np.array(vals[:n]) - np.array(base[:n])
        lo, hi = common.bootstrap_ci(list(d))
        # Sign means opposite things for the two families of arm, and getting
        # this backwards publishes a false claim: for a `no_*` arm the delta is
        # the cost of REMOVING a component, for a `plus_*` arm it is the effect
        # of ADDING one.
        if arm == "full":
            verdict = "baseline"
        elif arm.startswith("plus_"):
            if lo > 0:
                verdict = "**adding it helps**"
            elif hi < 0:
                verdict = "**adding it HURTS**"
            else:
                verdict = "no effect"
        else:
            if hi < 0:
                verdict = "**earns its place**"
            elif lo > 0:
                verdict = "**HARMFUL — removing it helps**"
            else:
                verdict = "within noise — unproven"
        print(f"| {arm} | {np.mean(vals):.4f} | {d.mean():+.4f} "
              f"[{lo:+.4f},{hi:+.4f}] | {verdict} |")

    for label, table in (("RECURRING evidence (overlap=True)", ndcg_overlap),
                         ("FRESH evidence (overlap=False)", ndcg_fresh)):
        b = table["full"]
        print(f"\n=== {label} — n={len(b)} ===")
        print("| arm | NDCG@k | Δ vs full |")
        print("|---|---|---|")
        for arm in ARMS:
            vals = table[arm]
            n = min(len(vals), len(b))
            if not n:
                continue
            d = np.array(vals[:n]) - np.array(b[:n])
            lo, hi = common.bootstrap_ci(list(d))
            print(f"| {arm} | {np.mean(vals):.4f} | {d.mean():+.4f} "
                  f"[{lo:+.4f},{hi:+.4f}] |")

    print("\nsignal liveness (fraction of scored rows whose prior varied):")
    for arm in ARMS:
        s = live[arm]
        frac = s["nonzero"] / max(s["scored"], 1)
        flag = "  <-- DEAD SIGNAL" if frac < 0.001 else ""
        print(f"  {arm:15s} {frac:.4f}{flag}")


if __name__ == "__main__":
    main()
