#!/usr/bin/env python3
"""Track 12 — the M-rule comparison (registered concept; unblocked by
Track 22's positive causal panel). The project is named for the M axis;
this asks whether EARNED-outcome M is a better ranking signal than the
write-time alternatives the field ships — Generative Agents' importance
score, Zep's fact ratings — and than per-token value.

On LoCoMo's sequential-feedback protocol (where M is genuinely earned),
compare ranking rules on late-third hit@1 (adaptivity — the window where
accumulated M can help):

  sim         cosine only (no memory state)
  rfm         sim x earned-outcome M (the shipped rule)
  importance  sim x a WRITE-TIME importance prior (haiku 0..1 per memory,
              scored once, cached) — the Generative Agents / Zep approach
  pertoken    sim x (earned-M / token length) — value density
  genagents   Park et al. recency+relevance (baseline, already in common)

Earned-M vs importance is the decisive pair: does measuring what helped
beat judging importance at write time?

Usage: track12_eval.py [--convs N] [--k 10] [--jobs 8]
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import threading

import numpy as np

import common
import locomo_eval as L

DATA = os.path.join(common.HERE, "data", "locomo10.json")
IMP_CACHE = os.path.join(common.HERE, "results-track12", "importance.jsonl")
CONDITIONS = ["sim", "genagents", "rfm", "pertoken", "importance"]
LOCK = threading.Lock()

IMP_PROMPT = """On a scale of 1-10, rate how IMPORTANT this memory is to
remember about a person's life — 1 is mundane chatter, 10 is a major life
event or defining fact (Generative Agents poignancy). Memory: "{t}"
Reply JSON only: {{"importance": <1-10>}}"""


def score_importance(texts, jobs):
    os.makedirs(os.path.dirname(IMP_CACHE), exist_ok=True)
    cache = {}
    if os.path.exists(IMP_CACHE):
        for l in open(IMP_CACHE):
            r = json.loads(l)
            cache[r["t"]] = r["imp"]
    todo = [t for t in texts if t not in cache]
    if todo:
        sink = open(IMP_CACHE, "a")

        def one(t):
            try:
                r = subprocess.run(
                    ["claude", "-p", IMP_PROMPT.format(t=t[:300]),
                     "--model", "haiku"],
                    env={**os.environ, "RFM_HOOKS_OFF": "1"},
                    capture_output=True, text=True, timeout=60)
                m = re.search(r'"importance"\s*:\s*([0-9.]+)', r.stdout or "")
                return t, (float(m.group(1)) / 10.0 if m else 0.5)
            except Exception:
                return t, 0.5
        with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
            for t, imp in ex.map(one, todo):
                with LOCK:
                    sink.write(json.dumps({"t": t, "imp": imp}) + "\n")
                    sink.flush()
                cache[t] = imp
        sink.close()
    return cache


def rank12(store, cond, qemb, ids, now, k, imp, toklen):
    sims = np.maximum(store.sims(qemb, ids), 0.0)
    if cond == "importance":
        scores = sims * np.array([imp.get(i, 0.5) for i in ids])
    elif cond == "pertoken":
        m = store.rfm_scores(ids)
        scores = sims * (m / np.array([max(toklen.get(i, 20), 1)
                                       for i in ids]))
    else:
        return L.rank(store, cond, qemb, ids, now, k)
    top = np.argsort(-scores, kind="stable")[:k]
    return [ids[i] for i in top]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--convs", type=int, default=10)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    data = json.load(open(DATA))[:a.convs]
    emb = common.get_embedder()

    # collect all memory texts for importance scoring
    all_texts = []
    for conv in data:
        rows, _, _ = L.load_conversation(conv)
        all_texts += [t for _i, t, _ts in rows]
    print(f"scoring write-time importance for {len(set(all_texts))} "
          f"memories...", flush=True)
    imp_by_text = score_importance(list(set(all_texts)), a.jobs)

    hits = {c: {"early": [], "late": []} for c in CONDITIONS}
    for conv in data:
        rows, dia_to_mem, _ = L.load_conversation(conv)
        texts = [t for _i, t, _ts in rows]
        embs = common.encode(emb, texts, "doc")
        stores = {c: common.MemoryStore(rows, embs) for c in CONDITIONS}
        ids = [i for i, _t, _ts in rows]
        imp = {i: imp_by_text.get(t, 0.5) for (i, t, _ts) in rows}
        toklen = {i: len(t.split()) for (i, t, _ts) in rows}

        qa = [q for q in conv["qa"] if q.get("evidence")
              and str(q.get("category")) != "5"]
        import random
        random.Random(7).shuffle(qa)
        for step, q in enumerate(qa):
            ev = [dia_to_mem[d] for d in q["evidence"] if d in dia_to_mem]
            if not ev:
                continue
            qemb = common.encode(emb, [q["question"]], "query")[0]
            t = 1e9 + 60.0 * step
            third = "late" if step >= 2 * len(qa) // 3 else \
                ("early" if step < len(qa) // 3 else None)
            for c in CONDITIONS:
                st = stores[c]
                st.freeze(t)
                top = rank12(st, c, qemb, ids, t, a.k, imp, toklen)
                hit = int(top[0] in ev) if top else 0
                if third:
                    hits[c][third].append(hit)
                # earn M for the value-axis conditions
                if c in ("rfm", "pertoken"):
                    st.record_accesses(top[:a.k])
                    st.record_outcomes([(m, 1.0 if m in ev else -1.0)
                                        for m in top[:a.k]])
                elif c == "importance":
                    st.record_accesses(top[:a.k])
        for st in stores.values():
            st.close()

    print(f"\n{'condition':<12}{'late hit@1':>12}{'early hit@1':>13}")
    for c in CONDITIONS:
        lh = np.mean(hits[c]["late"]) if hits[c]["late"] else 0
        eh = np.mean(hits[c]["early"]) if hits[c]["early"] else 0
        print(f"{c:<12}{lh:>12.4f}{eh:>13.4f}")
    lr = np.mean(hits["rfm"]["late"])
    li = np.mean(hits["importance"]["late"])
    print(f"\nDECISIVE — earned-M vs write-time importance (late hit@1): "
          f"rfm {lr:.4f} vs importance {li:.4f}  "
          f"(delta {lr-li:+.4f})")
    print(f"earned-M vs per-token: rfm {lr:.4f} vs "
          f"pertoken {np.mean(hits['pertoken']['late']):.4f}")


if __name__ == "__main__":
    main()
