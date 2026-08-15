#!/usr/bin/env python3
"""Model-variant bake-off: ACT-R parameters we had hardcoded (Amendment 11).

Sweeps the variants declared in PROTOCOL.md Amendment 11 on the DEV set only
(BEAM), reporting paired NDCG@k deltas against the frozen configuration.
Nothing here touches the test benchmarks: freeze one configuration per
variant first, then run one shot on test, exactly as the original
composition experiment did.

  V1 squash  (theta, s) — ACT-R's retrieval threshold and activation noise,
             which the architecture fits per model and we hardcoded at (0, 1).
             With second-scale lags that puts a whole store in the squash's
             left tail (P(B) ≈ 0.006–0.016), so the activation axis uses about
             a sixth of its range.
  V2 kind    procedural weighting (w_a_proc, w_v_proc) — does ACT-R's
             declarative/procedural split earn its keep?
  V3 kernel  power-law t^-d (ACT-R) vs exponential 2^-λt (LRFU). Never tested
             in agent memory; the recommender literature rejects the
             exponential at p<.001 on human access streams.

V4 (Petrov k > 2) needs the extension to fetch extra lags and is not here.

Scoring is done in-process from each memory's access history rather than
through the extension, so a variant can be evaluated without rebuilding: the
activation path is re-implemented from the same equations (verified against
`math.rs` on the frozen configuration — see `--selfcheck`).

Usage: model_eval.py [--variant squash|kind|kernel|all] [--k 10] [--selfcheck]
"""
import argparse
import math
import os
from collections import defaultdict

import numpy as np

import common
from beam_eval import DATA, QUESTION_SPACING, load_conversation, load_questions

FROZEN_THETA, FROZEN_S = 0.0, 1.0
FROZEN_WA, FROZEN_WV = 0.7, 0.3
DECAY = 0.5
SHRINK_K = 3.0

SQUASH_GRID = [(t, s) for t in (0.0, -2.0, -4.0, None) for s in (0.2, 0.5, 1.0)]
KIND_GRID = [(0.3, 0.7), (0.5, 0.5), (0.7, 0.3)]
HALF_LIVES = (1.0, 7.0, 30.0)


def bla_power(lags, lifetime):
    """ACT-R base-level activation: ln(Σ t^−d).

    A never-accessed memory is NOT a sentinel — the extension falls back to
    -d·ln(lifetime), treating creation as one virtual use. Getting this wrong
    made an earlier version of this sweep meaningless: most BEAM memories are
    never retrieved, so every kernel collapsed to the same constant and all
    variants scored identically."""
    if not lags:
        return -DECAY * math.log(max(lifetime, 1e-3))
    return math.log(sum(max(t, 1e-3) ** -DECAY for t in lags))


def bla_exponential(lags, lifetime, half_life_days):
    """LRFU kernel: same accumulate-over-history shape, exponential instead of
    power-law. Logged so it lands on the same scale as the ACT-R form."""
    lam = 1.0 / (half_life_days * 86_400.0)
    if not lags:
        return math.log(max(2.0 ** (-lam * max(lifetime, 1e-3)), 1e-12))
    return math.log(max(sum(2.0 ** (-lam * max(t, 1e-3)) for t in lags), 1e-12))


def bla_count(lags, lifetime):
    """Codex's model: rank by citation count with no decay — the LFU corner of
    the LRFU spectrum, and what Codex actually ships (usage_count DESC,
    refreshed on citation). Never-cited memories sit at the bottom, which is
    also Codex's behaviour."""
    return math.log(len(lags)) if lags else -30.0


def squash(b, theta, s):
    return 1.0 / (1.0 + math.exp(-(b - theta) / max(s, 1e-9)))


def replay(items, k, activation, theta, s, w_a, w_v):
    """Sequential protocol, identical in shape to every other eval here:
    similarity × bounded prior, accesses recorded as retrieval happens.
    Returns per-question NDCG."""
    out, acts = [], []
    for turns, embs, qas, q_embs in items:
        history = defaultdict(list)          # mem id -> access wall times
        ids = [m for m, _t, _ts in turns]
        row_of = {m: i for i, (m, _t, _ts) in enumerate(turns)}
        created = {m: ts for m, _t, ts in turns}
        for qi, qa in enumerate(qas):
            now = qa["now"]
            sims = embs[[row_of[m] for m in ids]] @ q_embs[qa["qi"]]
            scores = []
            for m, sim in zip(ids, sims):
                lags = [now - t for t in history[m] if now >= t]
                b = activation(lags, max(now - created[m], 1e-3))
                acts.append(b)
                sc = w_a * squash(b, theta, s) + w_v * 0.5   # no outcomes on dev
                scores.append(max(sim, 0.0) * (0.7 + 0.3 * sc))
            top = [ids[i] for i in np.argsort(-np.array(scores), kind="stable")[:k]]
            out.append(common.recall_ndcg(top, qa["evidence"], k)["ndcg"] or 0.0)
            for m in top:
                history[m].append(now)
    return out, acts


def load_items():
    """BEAM dev tier, embedded once and reused across every variant."""
    embedder = common.get_embedder()
    cache_dir = os.path.join(common.HERE, "cache-beam" + common.cache_suffix())
    os.makedirs(cache_dir, exist_ok=True)
    import random
    items = []
    for i in range(1, 21):
        conv_dir = os.path.join(DATA, str(i))
        if not os.path.isdir(conv_dir):
            continue
        rows, chatid_to_mem, last_ts = load_conversation(conv_dir)
        qas = load_questions(conv_dir)
        # Same seeded shuffle as beam_eval, so the question order — and hence
        # the access history each variant accumulates — matches the baseline.
        random.Random(13).shuffle(qas)
        if not rows or not qas:
            continue
        cache = os.path.join(cache_dir, f"conv{i}.npz")
        if os.path.exists(cache):
            z = np.load(cache)
            t_embs, q_embs = z["turns"], z["questions"]
        else:
            t_embs = common.encode(embedder, [t for _m, t, _ts in rows])
            q_embs = common.encode(embedder, [q["question"] for q in qas], kind="query")
            np.savez_compressed(cache, turns=t_embs, questions=q_embs)
        # Resolve evidence to memory ids and stamp each question's clock.
        prepared = []
        for qi, qa in enumerate(qas):
            ev = {chatid_to_mem[c] for c in qa["evidence"] if c in chatid_to_mem}
            if not ev:
                continue
            prepared.append({"evidence": ev,
                             "now": last_ts + 3600.0 + qi * QUESTION_SPACING,
                             "qi": qi})
        if prepared:
            items.append((rows, t_embs, prepared, q_embs))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["squash", "kind", "kernel", "all"], default="all")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--selfcheck", action="store_true",
                    help="verify this file's activation math against src/math.rs")
    args = ap.parse_args()

    if args.selfcheck:
        return selfcheck()

    print(f"DEV SET ONLY (BEAM) — embedder={common.EMBEDDER_ID}")
    print("Paired against the frozen configuration. Selection rule and "
          "endpoints: PROTOCOL.md Amendment 11.\n")
    items = load_items()
    print(f"{len(items)} conversations, "
          f"{sum(len(q) for _r, _e, q, _qe in items)} questions\n")

    results = {}

    def run(label, activation, theta, s, w_a, w_v):
        nd, acts = replay(items, args.k, activation, theta, s, w_a, w_v)
        results[label] = nd
        return float(np.mean(nd)), acts

    base, base_acts = run("frozen", bla_power, FROZEN_THETA, FROZEN_S,
                          FROZEN_WA, FROZEN_WV)
    med = float(np.median(base_acts))
    print(f"frozen baseline NDCG@{args.k} = {base:.4f}")
    print(f"activation distribution: median B = {med:.3f}, "
          f"P(B) at median = {squash(med, 0.0, 1.0):.4f}\n")

    if args.variant in ("squash", "all"):
        print("=== V1 squash (theta, s) ===")
        for theta, s in SQUASH_GRID:
            t = med if theta is None else theta
            lbl = f"theta={'med' if theta is None else theta},s={s}"
            m, _ = run(lbl, bla_power, t, s, FROZEN_WA, FROZEN_WV)
            print(f"  {lbl:22s} NDCG={m:.4f}  {delta(results, lbl)}")

    if args.variant in ("kind", "all"):
        print("\n=== V2 procedural weighting ===")
        for wa, wv in KIND_GRID:
            lbl = f"w_a={wa},w_v={wv}"
            m, _ = run(lbl, bla_power, FROZEN_THETA, FROZEN_S, wa, wv)
            print(f"  {lbl:22s} NDCG={m:.4f}  {delta(results, lbl)}")

    if args.variant in ("kernel", "all"):
        print("\n=== V3 decay kernel (power-law is the baseline) ===")
        for hl in HALF_LIVES:
            lbl = f"exp,half-life={hl}d"
            m, _ = run(lbl, lambda lg, lt, hl=hl: bla_exponential(lg, lt, hl),
                       FROZEN_THETA, FROZEN_S, FROZEN_WA, FROZEN_WV)
            print(f"  {lbl:22s} NDCG={m:.4f}  {delta(results, lbl)}")
        m, _ = run("codex,count-only", bla_count, FROZEN_THETA, FROZEN_S,
                   FROZEN_WA, FROZEN_WV)
        print(f"  {'codex,count-only':22s} NDCG={m:.4f}  "
              f"{delta(results, 'codex,count-only')}")

    print("\nNo selection applied here — freeze first, then one shot on test.")


def delta(results, label):
    a, b = results[label], results["frozen"]
    n = min(len(a), len(b))
    d = np.array(a[:n]) - np.array(b[:n])
    lo, hi = common.bootstrap_ci(list(d))
    return f"Δ={d.mean():+.4f} [{lo:+.4f},{hi:+.4f}]"


def selfcheck():
    """The in-process activation must agree with the shipped extension on the
    frozen configuration, or none of the deltas above mean anything."""
    import sqlite3
    db = sqlite3.connect(":memory:")
    db.enable_load_extension(True)
    db.load_extension(common.DYLIB)
    db.execute("SELECT rfm_init()")
    now = 1_000_000.0
    db.execute("INSERT INTO rfm_memories(id, content, created_at) VALUES (1,'x',0.0)")
    lags = []
    worst = 0.0
    for step, t in enumerate((100.0, 5_000.0, 900_000.0)):
        db.execute("SELECT rfm_config('now', ?)", (t,))
        db.execute("SELECT rfm_record_access(1)")
        lags.append(t)
        db.execute("SELECT rfm_config('now', ?)", (now,))
        ext = list(db.execute("SELECT rfm_activation(1)"))[0][0]
        mine = bla_power([now - x for x in lags])
        worst = max(worst, abs(ext - mine))
        print(f"  n={step+1}  extension={ext:+.6f}  in-process={mine:+.6f}  "
              f"diff={abs(ext-mine):.2e}")
    db.close()
    # n>2 uses Petrov's k=2 approximation in the extension and the exact sum
    # here, so they diverge by design; n<=2 must agree exactly.
    print(f"\nmax |diff| = {worst:.2e} "
          f"(n<=2 exact; n=3 diverges because the extension approximates)")


if __name__ == "__main__":
    main()
