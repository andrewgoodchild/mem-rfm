#!/usr/bin/env python3
"""PersonalizationV4: the applicability venue (Track 37, RESULTS.md; registered
2026-11-17 before any download, budget amended in 37b before the first call).

PV4 (Memorilla, arXiv 2610.21375; CC BY 4.0) asks scenario questions about a
user whose 200 two-turn chats show, but never state, the facts an answer
needs; every question needs two or more. PrefEval found this kind of
retrieval fails on applicability (a question rarely resembles the fact that
answers it), so the arms here are the three answers to that:

  sim     cosine top-K whole chats, the benchmark's own RAG baseline shape;
  rfm     cosine x rfm_prior with the benchmark's verdict after each question
          recorded as +1/-1 on the chats delivered for it. ORACLE outcomes, as
          in ABCD: the venue has no live outcome, so this is the mechanism's
          ceiling, not its live yield;
  judge   cosine prefilter of 8, then one model call picks the chats that
          bear on the question (Amendment 16's judge, this venue's wording),
          at most K.

Per user: one store per arm, each chat a dated memory in topic order; the
user's questions in an order drawn with seed 37 + user id; the clock advances
a minute per question. Answerer for every arm: claude-haiku-5.5 through
OpenRouter with the benchmark's persona prompt, 256 tokens. Scoring is the
benchmark's: the answer and the five candidates embedded with
Qwen3-Embedding-4B, nearest candidate must be the reference (metrics.py's
choice_predictions, mirrored; no instruction prompt on either side).

Cost per call is what OpenRouter reports as the upstream charge. Outputs:
results-pv4/per_question.jsonl (one row per user, question, arm) and
metrics.json from --score. A user whose rows are all present is skipped, so
an interrupted run resumes.

Usage: pv4_eval.py [--users N] [--limit Q] [--arms sim,rfm,judge] [--workers 4]
                   [--scorer MODEL] [--out results-pv4] | --score
  --scorer other than the default is for wiring tests and never for the record.
"""
import argparse
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict

import numpy as np
import pandas as pd

import common

DATA = os.path.join(common.HERE, "data", "pv4", "test.parquet")
T0 = 1_750_000_000.0
ARMS = ["sim", "rfm", "judge"]
K = 5                       # Track 37b: five whole chats, the RAG top-5 shape
JUDGE_PREFILTER = 8
MODEL = "anthropic/claude-haiku-5.5"
SCORER = "Qwen/Qwen3-Embedding-4B"
PERSONA_PROMPT = ("You are a personalized AI assistant. Answer the question "
                  "about the user based on your understanding of the user.")
JUDGE_PROMPT = """A personal assistant is asked about a user:

QUESTION: {question}

The assistant has these past conversations with the user. Which are NEEDED to
answer the question correctly? A conversation is needed if what it shows about
the user changes or completes the answer; topical relation alone does not
count.

{candidates}

Reply JSON only: {{"needed": [numbers, most useful first]}}, at most {k},
an empty list if none apply."""

_KEY = {"v": None}


def api_key():
    if _KEY["v"]:
        return _KEY["v"]
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        env = os.path.join(common.HERE, "..", ".env")
        if os.path.exists(env):
            for line in open(env):
                if line.lower().startswith("openrouter_api_key="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is not set and .env has none")
    _KEY["v"] = key
    return key


def chat(messages, max_tokens=512, model=MODEL, tries=7):
    """(text, cost_usd) from OpenRouter; retries on 429 and 5xx.

    Reasoning is off (37c): the benchmark's answerer was a model without
    thinking at 256 new tokens, and Haiku 5.5 thinks by default, so on the
    real prompts its thinking consumed the whole cap and 81% of answers came
    back empty in the first attempt. An empty answer that stopped on length
    is retried once with four times the cap."""
    body = json.dumps({"model": model, "messages": messages,
                       "max_tokens": max_tokens,
                       "reasoning": {"enabled": False},
                       "usage": {"include": True}}).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {api_key()}",
                 "Content-Type": "application/json",
                 "HTTP-Referer": "https://github.com/andrewgoodchild/mem-rfm",
                 "X-Title": "mem-rfm Track 37"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            text = msg.get("content") or ""
            usage = data.get("usage") or {}
            cost = (usage.get("cost_details") or {}).get("upstream_inference_cost")
            if not cost:
                cost = usage.get("cost") or 0.0
            if not text.strip() and choice.get("finish_reason") == "length" \
                    and max_tokens < 2048:
                more, c2 = chat(messages, max_tokens=max_tokens * 4, model=model,
                                tries=tries)
                return more, float(cost or 0.0) + c2
            return text, float(cost or 0.0)
        except urllib.error.HTTPError as e:
            if e.code in (408, 429, 500, 502, 503, 529) and attempt < tries - 1:
                time.sleep(min(60, 2 ** attempt) + random.random())
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < tries - 1:
                time.sleep(min(60, 2 ** attempt) + random.random())
                continue
            raise
    return "", 0.0


def answer(question, chats):
    context = "\n\n".join(chats)
    user = (f"Past conversations with the user:\n\n{context}\n\n"
            f"Question: {question}") if chats else question
    return chat([{"role": "system", "content": PERSONA_PROMPT},
                 {"role": "user", "content": user}])


def judge(question, cands):
    """cands: [(doc index, text)]. The subset the judge calls needed, judge
    order, or None on any failure (the caller falls back to cosine)."""
    numbered = "\n".join(f"{n + 1}. {text[:600]}" for n, (_i, text) in enumerate(cands))
    try:
        text, cost = chat([{"role": "user", "content": JUDGE_PROMPT.format(
            question=question[:600], candidates=numbered, k=K)}], max_tokens=200)
        m = re.search(r"\{.*\}", text, re.S)
        nums = json.loads(m.group(0)).get("needed", []) if m else None
    except Exception:
        return None, 0.0
    if not isinstance(nums, list):
        return None, cost
    picks = [cands[n - 1][0] for n in nums
             if isinstance(n, int) and 1 <= n <= len(cands)]
    return picks[:K], cost


class Scorer:
    """The benchmark's nearest-candidate scoring, one model, one lock."""

    def __init__(self, name):
        import torch
        from sentence_transformers import SentenceTransformer
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        # Half precision first for the 4B model's memory; a backend that
        # returns NaN in it (seen with some models on MPS) falls back to
        # float32, which 64 GB holds.
        self.model = None
        for dtype in ((torch.bfloat16, torch.float32) if device == "mps"
                      else (torch.float32,)):
            m = SentenceTransformer(name, device=device,
                                    model_kwargs={"torch_dtype": dtype})
            probe = m.encode(["a probe sentence"], normalize_embeddings=True,
                             convert_to_numpy=True)
            if np.isfinite(probe).all():
                self.model = m
                break
        if self.model is None:
            raise SystemExit(f"scorer {name} returns non-finite embeddings")
        self.lock = threading.Lock()
        self.name = name

    def correct(self, prediction, choices, reference):
        texts = [t for t in choices if t.strip()]
        ref = [t.strip() for t in choices].index(reference.strip())
        with self.lock:
            vecs = self.model.encode([prediction or " "] + texts,
                                     normalize_embeddings=True,
                                     convert_to_numpy=True)
        sims = np.full(len(choices), -np.inf)
        live = [i for i, t in enumerate(choices) if t.strip()]
        sims[live] = vecs[1:] @ vecs[0]
        return int(np.argmax(sims)) == ref


def run_user(uid, rows, emb, scorer, arms, sink, lock, limit=None):
    docs = list(rows.iloc[0].documents)
    doc_embs = common.encode(emb, docs, "doc")
    order = list(range(len(rows)))
    random.Random(37 + int(uid)).shuffle(order)
    if limit:
        order = order[:limit]
    half = len(order) // 2
    q_embs = common.encode(emb, list(rows.question), "query")
    mem_rows = [(i, docs[i], T0 - 3600 * (len(docs) - i)) for i in range(len(docs))]
    ids = [i for i, _t, _ts in mem_rows]
    stores = {a: common.MemoryStore(mem_rows, doc_embs) for a in arms}
    out = []
    for step, qi in enumerate(order):
        row = rows.iloc[qi]
        now = T0 + 60.0 * (step + 1)
        for a in arms:
            st = stores[a]
            st.freeze(now)
            cost = 0.0
            if a == "sim":
                top = common.rank(st, "sim", q_embs[qi], ids, now, K)
            elif a == "rfm":
                top = common.rank(st, "rfm_beta0.3", q_embs[qi], ids, now, K)
                st.record_accesses(top)
            else:
                pre = common.rank(st, "sim", q_embs[qi], ids, now, JUDGE_PREFILTER)
                picks, cost = judge(row.question, [(i, docs[i]) for i in pre])
                top = picks if picks else pre[:K]
            if a != "judge":
                picks = None
            pred, c = answer(row.question, [docs[i] for i in top])
            cost += c
            ok = scorer.correct(pred, list(row.choices), row.answer)
            if a == "rfm":
                st.record_outcomes([(i, 1.0 if ok else -1.0) for i in top])
            out.append({"user": int(uid), "step": step, "q": int(qi), "arm": a,
                        "correct": bool(ok), "hard": bool(row.hard),
                        "empty": not pred.strip(),
                        "judge_fell_back": a == "judge" and not picks,
                        "half": "first" if step < half else "second",
                        "delivered": [int(i) for i in top], "cost_usd": cost,
                        "pred": pred[:300]})
    for st in stores.values():
        st.close()
    with lock:
        for r in out:
            sink.write(json.dumps(r) + "\n")
        sink.flush()
    return out


def score(out):
    path = os.path.join(out, "per_question.jsonl")
    rows = [json.loads(l) for l in open(path)]
    by = defaultdict(dict)                       # (user, q) -> arm -> row
    for r in rows:
        by[(r["user"], r["q"])][r["arm"]] = r
    acc = defaultdict(list)
    cost = defaultdict(list)
    for r in rows:
        acc[r["arm"]].append(r["correct"])
        cost[r["arm"]].append(r["cost_usd"])
    print(f"questions scored: {len(by)}; rows {len(rows)}")
    empties = sum(1 for r in rows if r.get("empty"))
    fell = sum(1 for r in rows if r.get("judge_fell_back"))
    print(f"  empty answers {empties} of {len(rows)}; judge fell back to cosine on "
          f"{fell} of {sum(1 for r in rows if r['arm'] == 'judge')} judge rows")
    if empties > 0.02 * len(rows):
        print("  WARNING: more than 2% empty answers; the answerer is not answering")
    for a in sorted(acc):
        hard = [r["correct"] for r in rows if r["arm"] == a and r["hard"]]
        print(f"  {a:<6} accuracy {np.mean(acc[a]):.3f} (n={len(acc[a])})  "
              f"hard {np.mean(hard) if hard else float('nan'):.3f} (n={len(hard)})  "
              f"cost/question ${np.mean(cost[a]):.5f}")

    def paired(arm, ref, where):
        d = [int(v[arm]["correct"]) - int(v[ref]["correct"]) for v in by.values()
             if arm in v and ref in v and where(v[ref])]
        return (np.mean(d) if d else float("nan"), common.bootstrap_ci(d), len(d))

    bars = {}
    if "judge" in acc and "sim" in acc:
        m, ci, n = paired("judge", "sim", lambda r: r["hard"])
        bars["A1"] = {"delta_hard": m, "ci": ci, "n": n,
                      "verdict": "PASS" if m >= 0.05 and ci[0] > 0 else "FAIL"}
        print(f"A1 {bars['A1']['verdict']}: judge - sim on hard {m:+.3f} "
              f"CI [{ci[0]:+.3f}, {ci[1]:+.3f}] n={n} (bar +0.05, CI > 0)")
    if "rfm" in acc and "sim" in acc:
        m, ci, n = paired("rfm", "sim", lambda r: r["half"] == "second")
        bars["A2"] = {"delta_second_half": m, "ci": ci, "n": n,
                      "verdict": "PASS" if ci[0] > 0 else "FAIL"}
        print(f"A2 {bars['A2']['verdict']}: rfm - sim, second half {m:+.3f} "
              f"CI [{ci[0]:+.3f}, {ci[1]:+.3f}] n={n}")
        m, ci, n = paired("rfm", "sim", lambda r: r["half"] == "first")
        bars["A3"] = {"delta_first_half": m, "ci": ci, "n": n,
                      "verdict": "PASS" if ci[0] > -0.01 else "FAIL"}
        print(f"A3 {bars['A3']['verdict']}: rfm - sim, first half {m:+.3f} "
              f"CI [{ci[0]:+.3f}, {ci[1]:+.3f}] n={n} (bar: lower bound > -0.01)")
    if "judge" in cost and "sim" in cost and np.mean(cost["sim"]) > 0:
        ratio = np.mean(cost["judge"]) / np.mean(cost["sim"])
        bars["A4"] = {"cost_ratio": ratio, "verdict": "PASS" if ratio <= 3 else "FAIL"}
        print(f"A4 {bars['A4']['verdict']}: judge/sim cost per question {ratio:.2f}x (bar 3x)")
    gains = {a: common.gain(np.mean(acc["sim"]), np.mean(acc[a]))
             for a in acc if a != "sim" and "sim" in acc}
    if gains:
        print("normalized gain against sim (ceiling 1.0): "
              + "  ".join(f"{a}={g if g is None else round(g, 3)}" for a, g in gains.items()))
    with open(os.path.join(out, "metrics.json"), "w") as f:
        json.dump({"accuracy": {a: float(np.mean(v)) for a, v in acc.items()},
                   "cost_per_question": {a: float(np.mean(v)) for a, v in cost.items()},
                   "bars": bars, "gain_vs_sim": gains, "rows": len(rows)},
                  f, indent=1, default=str)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--users", type=int, default=None, help="first N users only")
    ap.add_argument("--limit", type=int, default=None, help="questions per user")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--scorer", default=SCORER)
    ap.add_argument("--out", default=os.path.join(common.HERE, "results-pv4"))
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    if a.score:
        return score(a.out)
    if not os.path.exists(DATA):
        raise SystemExit(f"no data at {DATA}; see bench-quality/README.md")
    arms = a.arms.split(",")
    os.makedirs(a.out, exist_ok=True)
    if a.scorer != SCORER:
        print(f"WARNING: scorer {a.scorer} is not the benchmark's; this run is "
              "a wiring test and must not be reported", flush=True)
    df = pd.read_parquet(DATA)
    users = sorted(df.user_id.unique())[: a.users] if a.users else sorted(df.user_id.unique())
    path = os.path.join(a.out, "per_question.jsonl")
    done = defaultdict(int)
    if os.path.exists(path):
        for line in open(path):
            done[json.loads(line)["user"]] += 1
    todo = []
    for uid in users:
        rows = df[df.user_id == uid].reset_index(drop=True)
        want = (a.limit or len(rows)) * len(arms)
        if done.get(int(uid), 0) >= want:
            continue
        todo.append((uid, rows))
    print(f"users {len(users)}, to run {len(todo)}, arms {arms}, K={K}, "
          f"model {MODEL}, scorer {a.scorer}", flush=True)
    if not todo:
        return score(a.out)
    emb = common.get_embedder()
    scorer = Scorer(a.scorer)
    sink = open(path, "a")
    lock = threading.Lock()
    import concurrent.futures
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(run_user, uid, rows, emb, scorer, arms, sink, lock,
                          a.limit): uid for uid, rows in todo}
        failed = []
        for n, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            try:
                rows = fut.result()
            except Exception as e:          # one user's failure is not the run's
                failed.append(futs[fut])
                print(f"user {futs[fut]} FAILED ({n}/{len(todo)}): "
                      f"{type(e).__name__}: {str(e)[:200]}", flush=True)
                continue
            spent = sum(r["cost_usd"] for r in rows)
            print(f"user {futs[fut]} done ({n}/{len(todo)}): {len(rows)} rows, "
                  f"${spent:.3f}, {time.time() - t0:.0f}s", flush=True)
        if failed:
            print(f"{len(failed)} user(s) failed and wrote no rows; rerun to "
                  f"resume them: {failed}", flush=True)
    sink.close()
    score(a.out)


if __name__ == "__main__":
    main()
