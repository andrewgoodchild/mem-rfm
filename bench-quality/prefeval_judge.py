#!/usr/bin/env python3
"""PrefEval applicability judge (PROTOCOL.md Amendment 16, registered
before the run): one haiku call per question over the sim top-50,
rerank judged-applicable first, score against the Amendment 15 sim
baseline.

Usage: prefeval_judge.py [--jobs 8] [--limit N] [--out results-prefeval]
"""
import argparse
import concurrent.futures as cf
import glob
import json
import os
import re
import subprocess
import threading

import numpy as np

import common

DATA = os.path.join(common.HERE, "data", "prefeval")
WINDOW = 50
LOCK = threading.Lock()

PROMPT = """A user asked an assistant:

REQUEST: {question}

The assistant has a store of this user's stated preferences. Which of
the numbered preferences below CONSTRAIN how the request should be
answered? A preference constrains the answer if ignoring it while
answering would violate what the user wants — topical similarity alone
does not count.

{candidates}

Reply with JSON only: {{"applicable": [numbers, most constraining
first]}} — AT MOST 3 numbers; usually exactly one preference truly
constrains the answer, and topical relatives do not belong in the
list. An empty list if none apply."""


def parse(text):
    m = re.search(r"\{.*\}", (text or ""), re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return [int(x) for x in v.get("applicable", [])]
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="results-prefeval")
    a = ap.parse_args()

    items = []
    for f in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        for r in json.load(open(f)):
            items.append((r["preference"], r["question"]))
    emb = common.get_embedder()
    p = common.encode(emb, [x for x, _ in items], "doc")
    q = common.encode(emb, [y for _, y in items], "query")
    sims = q @ p.T
    n = a.limit or len(items)
    # Amendment 16c: PrefEval's topic files contain semantic twins of
    # each other's preferences (33% have one at cosine >= 0.85, verified
    # by inspection); a twin of gold satisfies the user identically, so
    # scoring is equivalence-aware. EQ[i] = gold's equivalence set.
    pp = p @ p.T
    EQ = [set(np.where(pp[i] >= 0.85)[0]) | {i} for i in range(len(items))]

    path = os.path.join(a.out, "judge.jsonl")
    os.makedirs(a.out, exist_ok=True)
    done = set()
    if os.path.exists(path):
        done = {json.loads(l)["q"] for l in open(path)}

    def ask(i):
        top = list(np.argsort(-sims[i])[:WINDOW])
        cands = "\n".join(f"{j + 1}. {items[m][0][:220]}"
                          for j, m in enumerate(top))
        try:
            r = subprocess.run(
                ["claude", "-p", "--model", "haiku",
                 PROMPT.format(question=items[i][1][:400],
                               candidates=cands)],
                env={**os.environ, "RFM_HOOKS_OFF": "1"},
                capture_output=True, text=True, timeout=180)
            nums = parse((r.stdout or "").strip())
        except subprocess.TimeoutExpired:
            nums = None
        applicable = [top[k - 1] for k in (nums or [])
                      if 1 <= k <= len(top)]
        rest = [m for m in top if m not in applicable]
        rerank = applicable + rest
        eq = EQ[i]
        return {"q": i, "gold": i,
                "gold_in_window": bool(eq & set(top)),
                "judged": len(applicable),
                "gold_judged": bool(eq & set(applicable)),
                "parsed": nums is not None,
                "h1": int(bool(rerank) and rerank[0] in eq),
                "h5": int(bool(eq & set(rerank[:5])))}

    todo = [i for i in range(n) if i not in done]
    print(f"{len(done)} done, {len(todo)} to judge (window {WINDOW})")
    sink = open(path, "a")
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for k, rec in enumerate(ex.map(ask, todo), 1):
            with LOCK:
                sink.write(json.dumps(rec) + "\n")
                sink.flush()
            if k % 100 == 0:
                print(f"  {k}/{len(todo)}", flush=True)
    sink.close()

    rows = [json.loads(l) for l in open(path)]
    h1 = np.mean([r["h1"] for r in rows])
    h5 = np.mean([r["h5"] for r in rows])
    inw = [r for r in rows if r["gold_in_window"]]
    jr = np.mean([r["gold_judged"] for r in inw]) if inw else 0
    unparsed = sum(1 for r in rows if not r["parsed"])
    print(f"\nn={len(rows)}  hit@1={h1:.3f}  hit@5={h5:.3f}  "
          f"judge-recall(gold in window)={jr:.3f}  "
          f"mean judged={np.mean([r['judged'] for r in rows]):.1f}  "
          f"unparsed={unparsed}")
    print("\nREGISTERED (Amendment 16):")
    print(f"  PJ-P1 hit@5 >= 0.40 (sim 0.246): "
          f"{'PASS' if h5 >= 0.40 else 'FAIL'} — {h5:.3f}")
    print(f"  PJ-P2 hit@1 >= 0.20 (sim 0.088): "
          f"{'PASS' if h1 >= 0.20 else 'FAIL'} — {h1:.3f}")
    print(f"  PJ-P3 judge recall >= 0.70: "
          f"{'PASS' if jr >= 0.70 else 'FAIL'} — {jr:.3f}")
    print(f"  PJ-P4 one call per question: PASS by construction")


if __name__ == "__main__":
    main()
