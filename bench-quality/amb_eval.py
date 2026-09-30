#!/usr/bin/env python3
"""AMB head-to-head: mem-rfm vs Hindsight on Vectorize's own harness data.

Hindsight's published LoCoMo / LongMemEval numbers come from AMB
(github.com/vectorize-io/agent-memory-benchmark): ingest -> retrieve ->
Gemini 3.1 Pro answers from the retrieved context -> Gemini 2.5 Flash-Lite
judges. AMB publishes every run's per-question retrieved context, so the
retrieval stage of Hindsight and of AMB's hybrid-search baseline can be
replayed exactly. This script holds the answer and judge models fixed across
arms, so the only thing that differs is the context:

  hindsight      published context (AMB run "locomo-hindsight" / "hindsight")
  hybrid-search  published context (Qwen3-0.6B dense + BM42 sparse, RRF)
  mem-rfm        computed here: one memory per dialogue turn, dated,
                 ranked by sim x rfm_prior(id) with accesses recorded as the
                 shipped memory_search does, filled to the SAME token budget
                 hybrid-search used for that question (budget parity).

Answer + judge prompts are AMB's own (imported from its dataset classes).
The answer/judge LLMs are Claude via `claude -p` because no Gemini key is
available, so absolute numbers are not comparable to the leaderboard; the
paired arm-vs-arm deltas are.

Stages (resumable; every LLM result is cached in --out):
  retrieve  build mem-rfm contexts          (local, no LLM)
  answer    answer every (arm, question)    (claude -p, --answer-model)
  judge     judge every answer              (claude -p, --judge-model)
  report    accuracy per arm, per category, paired bootstrap CIs

Usage:
  AMB_DIR=/path/to/agent-memory-benchmark uv run --python 3.12 \
    --with fastembed,numpy,rich,tiktoken,scipy python amb_eval.py \
    --dataset locomo --n 200 --stage all

  Further mem-rfm arms share the baselines' cached answers, e.g. the
  LongMemEval truncation follow-up (RESULTS.md):
    ... --dataset longmemeval --stage retrieve --arm mem-rfm-trunc300-top10 \
        --trunc-assistant 300 --full-top 10 --emb-cache /tmp/lme-emb
    ... --dataset longmemeval --stage all
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import functools
import gzip
import hashlib
import json
import os
import random
import re
import sqlite3
import subprocess
import sys
import threading
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
AMB = os.environ.get("AMB_DIR", "")
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import rfm  # noqa: E402
import common  # noqa: E402

SPLIT = {"locomo": "locomo10", "longmemeval": "s"}
PUBLISHED = {
    "locomo": {"hindsight": "locomo-hindsight", "hybrid-search": "hybrid-search"},
    "longmemeval": {"hindsight": "hindsight", "hybrid-search": "hybrid-search"},
}
BASELINES = ["hindsight", "hybrid-search"]
LOCK = threading.Lock()


# ---------------------------------------------------------------- data

def load_gz(path):
    with gzip.open(path) as f:
        return json.loads(f.read())


def amb_dataset(name):
    """Import AMB's dataset class without its package __init__, which pulls
    every dataset and LLM client (google-genai, groq, ...)."""
    import types
    sys.path.insert(0, os.path.join(AMB, "src"))
    pkg = types.ModuleType("memory_bench.dataset")
    pkg.__path__ = [os.path.join(AMB, "src", "memory_bench", "dataset")]
    sys.modules["memory_bench.dataset"] = pkg
    if name == "locomo":
        from memory_bench.dataset.locomo import LoComoDataset
        return LoComoDataset()
    from memory_bench.dataset.longmemeval import LongMemEvalDataset
    return LongMemEvalDataset()


def published(dataset, arm):
    """AMB's published run for a baseline, per-question context included.
    Fetched once from the URL in the checkout's blob-manifest.json into
    $AMB_DIR/pub/ (curl, since some Python builds lack CA certificates)."""
    run = PUBLISHED[dataset][arm]
    key = f"outputs/{dataset}/{run}/rag/{SPLIT[dataset]}.json.gz"
    path = os.path.join(AMB, "pub", key.replace("/", "_"))
    if not os.path.exists(path):
        url = json.load(open(os.path.join(AMB, "blob-manifest.json")))[key]["url"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(["curl", "-sSfL", "-o", path, url], check=True)
    return {r["query_id"]: r for r in load_gz(path)["results"]}


def category(q):
    return q["meta"].get("category") or q["meta"].get("question_type") or "?"


def sample(queries, n, seed=7):
    """Stratified by category, deterministic."""
    if not n or n >= len(queries):
        return [q["id"] for q in queries]
    by = defaultdict(list)
    for q in queries:
        by[category(q)].append(q["id"])
    rng = random.Random(seed)
    out = []
    for cat in sorted(by):
        ids = sorted(by[cat])
        rng.shuffle(ids)
        out += ids[:max(1, round(n * len(ids) / len(queries)))]
    return sorted(out)


# ---------------------------------------------------------------- mem-rfm arm

def iso_ts(s):
    return dt.datetime.fromisoformat(s).timestamp() if s else 0.0


def turns_of(doc):
    """One memory per dialogue turn, stamped with its session date."""
    date = (doc.get("timestamp") or "")[:10]
    try:
        turns = json.loads(doc["content"])
    except json.JSONDecodeError:
        return [("?", f"[{date}] {doc['content']}")]
    out = []
    for t in turns:
        who = t.get("speaker") or t.get("role") or "?"
        text = t.get("text") or t.get("content") or ""
        if t.get("blip_caption"):
            text += f" [shares an image: {t['blip_caption']}]"
        out.append((t.get("role"), f"[{date}] {who}: {text}"))
    return out


def ntok(s):
    """Tokens as AMB counts them (tiktoken cl100k_base, its
    utils.count_tokens), so a budget taken from a published run's
    context_tokens is spent in the same unit. The first runs used len/4,
    which gave mem-rfm ~1.26x hybrid-search's context on LoCoMo (RESULTS.md)."""
    return max(1, len(_ENC().encode(s, disallowed_special=())))


@functools.lru_cache(maxsize=1)
def _ENC():
    import tiktoken
    return tiktoken.get_encoding("cl100k_base")


def shown(role, text, rank, trunc, full_top):
    """What the answer model sees for one memory. Retrieval always uses the
    full turn; with --trunc-assistant, assistant turns outside the top
    `full_top` hits are cut, since their verbose replies otherwise eat most
    of the budget (83.5% of it on LongMemEval-S) while the evidence sits in
    user turns."""
    if trunc and role == "assistant" and rank >= full_top and len(text) > trunc + 14:
        return text[:trunc + 14] + " …"     # + the "[yyyy-mm-dd] assistant: " prefix
    return text


# ---------------------------------------------------------------- write-time facts
#
# The LongMemEval gap to Hindsight is cross-session aggregation (counting,
# totalling, latest-value) and relative dates, not retrieval recall
# (RESULTS.md, AMB follow-up). Hindsight answers both at WRITE time: an LLM
# turns each chunk into short, dated, self-contained facts (its
# fact_extraction.py, MIT). This is that idea in mem-rfm's shape: one haiku
# call per few sessions, facts stored beside the raw turns as ordinary
# memories, ranked by the same sim x rfm_prior. Nothing calls a model at
# ranking time.

FACT_PROMPT = """You extract durable facts about the USER from chat sessions, for a long-term memory that will later answer questions about the user's life.

For each numbered session below (each has its date), list the facts a future question could need: events, purchases, amounts, counts, names, places, possessions, jobs, plans, preferences, and changes of state.

Rules:
- One fact per item. If the user mentions three things, write three facts.
- Self-contained: name people and things explicitly ("the user's colleague Priya", "the user's Honda Civic"), never "it" or "they".
- Absolute dates: convert relative time ("yesterday", "last Saturday", "two weeks ago", "next month") to a calendar date using the session date, and write the date inside the fact.
- Keep exact numbers, prices, durations and titles verbatim.
- Record changes as changes: "the user switched from X to Y", "the user no longer has Z", "the user's rent rose to $1,850".
- Include what the assistant said only when the user adopted it or it answered a personal question.
- Skip greetings, generic advice, and anything not about the user. A session with nothing about the user yields no facts.

Return JSON: {{"facts": [{{"s": <session number>, "fact": "<one sentence>"}}]}}

{sessions}"""
# The first version of this prompt used two gold answers from the
# LongMemEval sample as its examples, written after reading the failures
# (RESULTS.md, adversarial review). These examples appear in no question or
# gold answer of either dataset. Extracted facts are cached under a hash of
# the prompt, so changing it can never reuse facts the old one produced.
FACT_PROMPT_ID = hashlib.sha1(FACT_PROMPT.encode()).hexdigest()[:10]
FACT_BATCH = 4
FACT_ASSISTANT_CHARS = 300


def session_key(doc):
    """Facts depend on the content AND the date relative phrases resolve
    against, so the same filler session under two dates is two keys."""
    return hashlib.sha1(((doc.get("timestamp") or "")[:10] + "\x1f"
                         + doc["content"]).encode()).hexdigest()


def render_session(i, doc):
    """User turns whole, assistant turns cut: the facts are about the user,
    and the raw assistant turns stay in the retrieval pool regardless."""
    lines = [f"### Session {i} (date {(doc.get('timestamp') or '')[:10]})"]
    try:
        turns = json.loads(doc["content"])
    except json.JSONDecodeError:
        return "\n".join(lines + [doc["content"][:6000]])
    for t in turns:
        role = t.get("role") or t.get("speaker") or "?"
        text = " ".join(str(t.get("content") or t.get("text") or "").split())
        if role == "assistant" and len(text) > FACT_ASSISTANT_CHARS:
            text = text[:FACT_ASSISTANT_CHARS] + " …"
        lines.append(f"{role}: {text[:3000]}")
    return "\n".join(lines)


def extract_facts(docs, out, model, jobs):
    """{session_key: [fact, ...]} for every doc, cached in facts.jsonl."""
    path = os.path.join(out, "facts.jsonl")
    todo, seen = [], set()
    for d in docs:
        k = session_key(d)
        if k not in seen:
            seen.add(k)
            todo.append((k, d))
    batches = [todo[i:i + FACT_BATCH] for i in range(0, len(todo), FACT_BATCH)]

    def one(batch):
        body = "\n\n".join(render_session(i + 1, d) for i, (_k, d) in enumerate(batch))
        v = claude_json(FACT_PROMPT.format(sessions=body), model, ["facts"])
        if v is None or not isinstance(v["facts"], list):
            return None
        by = {k: [] for k, _ in batch}
        for f in v["facts"]:
            try:
                n = int(f["s"])
            except (KeyError, ValueError, TypeError):
                continue
            if not 1 <= n <= len(batch):     # s=0 would index batch[-1]
                continue
            k = batch[n - 1][0]
            fact = " ".join(str(f.get("fact") or "").split())
            if fact:
                by[k].append(fact)
        return {"by": by}

    items = [(FACT_PROMPT_ID + ":" + "|".join(k for k, _ in b), b) for b in batches]
    cache = run_cached(path, jobs, one, items)
    facts = {}
    for rec in cache.values():
        facts.update(rec.get("by", {}))
    return facts


def cached_encode(emb, texts, path, legacy_ok=False):
    """Embeddings for `texts`, cached at `path` under a hash of the texts:
    a matching length alone would pair stale vectors with re-extracted
    facts. legacy_ok accepts a pre-hash cache on length, safe only where
    the texts are a deterministic function of the dataset (the turns)."""
    h = hashlib.sha1("\x1f".join(texts).encode()).hexdigest()
    e = None
    if path and os.path.exists(path):
        z = np.load(path)
        stored = str(z["h"]) if "h" in z.files else None
        if stored == h or (stored is None and legacy_ok and len(z["e"]) == len(texts)):
            e = z["e"]
    if e is None:
        e = common.encode(emb, texts)
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            np.savez(path, e=e, h=h)
    return e


def fill(order, cap, used, picked, render):
    """Append rows in `order` while the token total stays within `cap`."""
    for rank, i in enumerate(order):
        t = render(rank, i)
        if used + ntok(t) > cap:
            break
        picked.append((i, t))
        used += ntok(t)
    return used


def build_rfm_contexts(queries, docs, wanted, budgets, out, arm="mem-rfm",
                       trunc=0, full_top=0, emb_cache=None, facts=None, fact_share=0.0):
    """Per isolation unit: fresh store, turns inserted with their session
    time, every query of the unit asked in dataset order (accesses recorded
    on what comes back, as memory_search does); only `wanted` are kept.

    Contexts are cached per arm and reused unit by unit, so the cache is
    keyed by the parameters that built it (params-<arm>.json): reusing an
    arm name with different settings is refused instead of silently
    reporting the old contexts."""
    path = os.path.join(out, f"contexts-{arm}.json")
    ppath = os.path.join(out, f"params-{arm}.json")
    params = {"trunc": trunc, "full_top": full_top,
              "facts": FACT_PROMPT_ID if facts is not None else False,
              "fact_share": fact_share, "embedder": common.EMBEDDER_ID,
              "tokens": "cl100k"}
    ctx = json.load(open(path)) if os.path.exists(path) else {}
    stored = json.load(open(ppath)) if os.path.exists(ppath) else None
    if ctx and stored != params:
        sys.exit(f"arm {arm!r} was built with {stored}, not {params}; "
                 f"pick another --arm or delete {path}")
    json.dump(params, open(ppath, "w"))
    emb = common.get_embedder()
    by_unit = defaultdict(list)
    for d in docs:
        by_unit[d["user_id"]].append(d)
    q_by_unit = defaultdict(list)
    for q in queries:
        q_by_unit[q["user_id"]].append(q)
    units = [u for u in q_by_unit if any(q["id"] in wanted for q in q_by_unit[u])]
    for ui, unit in enumerate(units):
        if all(q["id"] in ctx for q in q_by_unit[unit] if q["id"] in wanted):
            continue
        rows = []
        for d in sorted(by_unit[unit], key=lambda d: d.get("timestamp") or ""):
            ts = iso_ts(d.get("timestamp"))
            for role, t in turns_of(d):
                rows.append((len(rows) + 1, t, ts, role))
        embs = cached_encode(emb, [r[1] for r in rows],
                             emb_cache and os.path.join(emb_cache, f"{unit}.npz"),
                             legacy_ok=True)
        if facts is not None:
            frows = []
            for d in sorted(by_unit[unit], key=lambda d: d.get("timestamp") or ""):
                date = (d.get("timestamp") or "")[:10]
                for f in facts.get(session_key(d), []):
                    frows.append((len(rows) + len(frows) + 1, f"[{date}] fact: {f}",
                                  iso_ts(d.get("timestamp")), "fact"))
            if frows:
                femb = cached_encode(emb, [r[1] for r in frows], emb_cache and os.path.join(
                    emb_cache, f"{unit}.facts.npz"))
                rows += frows
                embs = np.vstack([embs, femb])
        db = sqlite3.connect(":memory:")
        rfm.register(db)
        db.execute("SELECT rfm_init()")
        db.executemany(
            "INSERT INTO rfm_memories(id, content, created_at) VALUES (?,?,?)",
            [(m, t[:200], ts) for m, t, ts, _ in rows])
        ids = [r[0] for r in rows]
        for q in q_by_unit[unit]:
            db.execute("SELECT rfm_config('now', ?)",
                       (iso_ts(q["meta"].get("query_timestamp")) or rows[-1][2],))
            qe = common.encode(emb, [q["query"]], kind="query")[0]
            sims = np.maximum(embs @ qe, 0.0)
            pri = dict(db.execute("SELECT id, rfm_prior(id) FROM rfm_memories"))
            score = sims * np.array([pri[m] for m in ids])
            order = np.argsort(-score, kind="stable")
            budget = budgets.get(q["id"], 20_000)
            picked, used = [], 0
            if fact_share:
                # Facts first, up to their share of the budget: raw turns
                # are long, and pooled on score alone they left facts 5.8%
                # of the context tokens (RESULTS.md, write-time facts).
                used = fill([i for i in order if rows[i][3] == "fact"],
                            fact_share * budget, used, picked,
                            lambda _r, i: rows[i][1])
                taken = {i for i, _ in picked}
                order = [i for i in order if i not in taken]
            fill(order, budget, used, picked,
                 lambda r, i: shown(rows[i][3], rows[i][1], r, trunc, full_top))
            for i, _ in picked[:50]:           # shipped memory_search: top hits record access
                db.execute("SELECT rfm_record_access(?)", (ids[i],))
            if q["id"] in wanted:
                ctx[q["id"]] = "\n\n".join(
                    f"## Memory {j + 1}\n{t}" for j, (_, t) in enumerate(picked))
        db.close()
        print(f"  unit {ui + 1}/{len(units)} ({len(rows)} turns)", flush=True)
        json.dump(ctx, open(path, "w"))
    return ctx


# ---------------------------------------------------------------- LLM

def claude_json(prompt, model, keys):
    shape = ", ".join(f'"{k}": ...' for k in keys)
    full = (prompt + f"\n\nRespond with ONLY a JSON object of the form "
            f"{{{shape}}} and nothing else.")
    for _ in range(3):
        try:
            r = subprocess.run(
                ["claude", "-p", "--model", model, "--tools", "",
                 "--strict-mcp-config", "--setting-sources", "",
                 "--system-prompt", "You answer strictly in JSON."],
                input=full, env={**os.environ, "RFM_HOOKS_OFF": "1"},
                capture_output=True, text=True, timeout=300)
            m = re.search(r"\{.*\}", r.stdout or "", re.S)
            if m:
                v = json.loads(m.group(0))
                if all(k in v for k in keys):
                    return v
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
    return None


def load_jsonl(path):
    """{record["key"]: record} for a results file; empty if absent."""
    if not os.path.exists(path):
        return {}
    return {r["key"]: r for r in map(json.loads, open(path))}


def run_cached(path, jobs, fn, items):
    cache = load_jsonl(path)
    todo = [it for it in items if it[0] not in cache]
    print(f"  {len(items) - len(todo)} cached, {len(todo)} to run", flush=True)
    done = [0]

    def work(it):
        v = fn(*it[1:])
        if v is None:
            return
        rec = {"key": it[0], **v}
        with LOCK:
            with open(path, "a") as f:
                f.write(json.dumps(rec) + "\n")
            cache[it[0]] = rec
            done[0] += 1
            if done[0] % 25 == 0:
                print(f"    {done[0]}/{len(todo)}", flush=True)

    with cf.ThreadPoolExecutor(jobs) as ex:
        list(ex.map(work, todo))
    return cache


# ---------------------------------------------------------------- report

def boot(d, n=10_000, seed=7):
    d = np.asarray(d, float)
    rng = np.random.default_rng(seed)
    m = d[rng.integers(0, len(d), (n, len(d)))].mean(1)
    return d.mean(), np.percentile(m, 2.5), np.percentile(m, 97.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=list(SPLIT), required=True)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--stage", default="all",
                    choices=["extract", "retrieve", "answer", "judge", "report", "all"])
    ap.add_argument("--answer-model", default="sonnet")
    ap.add_argument("--judge-model", default="haiku")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--out", default=os.path.join(HERE, "results-amb"))
    ap.add_argument("--arm", default="mem-rfm",
                    help="name of the mem-rfm arm built by this run")
    ap.add_argument("--trunc-assistant", type=int, default=0,
                    help="cut assistant turns to N chars in the context")
    ap.add_argument("--full-top", type=int, default=0,
                    help="...except the top K ranked hits, shown in full")
    ap.add_argument("--facts", action="store_true",
                    help="add write-time extracted facts to the memory pool "
                         "(stage extract builds them; cached in facts.jsonl)")
    ap.add_argument("--fact-model", default="haiku")
    ap.add_argument("--fact-share", type=float, default=0.0,
                    help="reserve this share of the budget for top-ranked "
                         "facts, placed first (0 = pool facts with turns)")
    ap.add_argument("--emb-cache", default=None,
                    help="directory for per-unit embedding caches")
    a = ap.parse_args()
    if not AMB:
        sys.exit("set AMB_DIR to an agent-memory-benchmark checkout")
    out = os.path.join(a.out, a.dataset)
    os.makedirs(out, exist_ok=True)

    base = os.path.join(AMB, "data", a.dataset, SPLIT[a.dataset])
    queries = load_gz(os.path.join(base, "queries.json.gz"))
    pub = {arm: published(a.dataset, arm) for arm in BASELINES}
    queries = [q for q in queries if all(q["id"] in pub[arm] for arm in pub)]
    wanted = set(sample(queries, a.n))
    qmap = {q["id"]: q for q in queries}
    print(f"{a.dataset}: {len(wanted)} questions "
          f"(of {len(queries)} with published contexts for both baselines)")
    ds = amb_dataset(a.dataset)
    split = SPLIT[a.dataset]

    contexts = {arm: {qid: pub[arm][qid]["context"] for qid in wanted}
                for arm in pub}
    budgets = {qid: pub["hybrid-search"][qid]["context_tokens"] for qid in qmap}
    facts = None
    if a.stage in ("extract", "retrieve", "all"):
        docs = load_gz(os.path.join(base, "documents.json.gz"))
    if a.facts and a.stage in ("extract", "retrieve", "all"):
        units = {qmap[q]["user_id"] for q in wanted}
        facts = extract_facts([d for d in docs if d["user_id"] in units], out,
                              a.fact_model, a.jobs)
        print(f"  facts: {sum(map(len, facts.values()))} over {len(facts)} sessions")
    if a.stage in ("retrieve", "all"):
        build_rfm_contexts(queries, docs, wanted, budgets, out, a.arm,
                           a.trunc_assistant, a.full_top, a.emb_cache, facts,
                           a.fact_share)
    for f in sorted(os.listdir(out)):              # every mem-rfm arm built so far
        if f.startswith("contexts-") and f.endswith(".json"):
            contexts[f[len("contexts-"):-len(".json")]] = json.load(open(os.path.join(out, f)))
    arms = list(contexts)

    ans_path = os.path.join(out, "answers.jsonl")
    if a.stage in ("answer", "all"):
        def answer(arm, qid):
            q = qmap[qid]
            prompt = ds.build_rag_prompt(q["query"], contexts[arm][qid], "open",
                                         split, None, dict(q["meta"]))
            # AMB's schema is {reasoning, answer}; asking the CLI for a
            # "reasoning" field trips its reasoning-extraction guard, so the
            # think-first slot is phrased as the evidence it rests on.
            return claude_json(prompt, a.answer_model, ["evidence", "answer"])
        items = [(f"{arm}|{qid}", arm, qid) for arm in contexts for qid in sorted(wanted)
                 if qid in contexts[arm]]
        run_cached(ans_path, a.jobs, answer, items)

    answers = load_jsonl(ans_path)

    jud_path = os.path.join(out, "judgments.jsonl")
    if a.stage in ("judge", "all"):
        def judge(key):
            arm, qid = key.split("|", 1)
            q = qmap[qid]
            if hasattr(ds, "get_judge_prompt_fn"):
                fn = ds.get_judge_prompt_fn(category(q), meta=q["meta"])
            else:
                fn = ds.build_judge_prompt
            v = claude_json(fn(q["query"], q["gold_answers"], str(answers[key]["answer"])),
                            a.judge_model, ["reason", "correct"])
            if v is not None:
                v["correct"] = v["correct"] in (True, "true", "True", "yes")
            return v
        run_cached(jud_path, a.jobs, judge, [(k, k) for k in sorted(answers)])

    if a.stage in ("report", "all"):
        jud = {k: bool(r["correct"]) for k, r in load_jsonl(jud_path).items()}
        qids = sorted(q for q in wanted
                      if all(f"{arm}|{q}" in jud for arm in arms))
        report = {"dataset": a.dataset, "n": len(qids),
                  "answer_model": a.answer_model, "judge_model": a.judge_model,
                  "arms": {}, "paired": {}, "by_category": {}, "context_tokens": {},
                  "published_accuracy_same_qids": {}}
        for arm in arms:
            acc = [jud[f"{arm}|{q}"] for q in qids]
            m, lo, hi = boot(acc)
            report["arms"][arm] = [round(m, 4), round(lo, 4), round(hi, 4)]
            report["context_tokens"][arm] = round(float(np.mean(
                [ntok(contexts[arm][q]) for q in qids])), 1)
            if arm in pub:
                report["published_accuracy_same_qids"][arm] = round(float(np.mean(
                    [pub[arm][q]["correct"] for q in qids])), 4)
        pairs = [(x, y) for x in arms if x not in BASELINES for y in BASELINES]
        pairs += [("hybrid-search", "hindsight")]
        pairs += [(x, "mem-rfm") for x in arms if x not in BASELINES + ["mem-rfm"]]
        for x, y in pairs:
            d = [int(jud[f"{x}|{q}"]) - int(jud[f"{y}|{q}"]) for q in qids]
            report["paired"][f"{x} - {y}"] = [round(v, 4) for v in boot(d)]
        cats = defaultdict(list)
        for q in qids:
            cats[category(qmap[q])].append(q)
        for c, qs in sorted(cats.items()):
            report["by_category"][c] = {"n": len(qs), **{
                arm: round(float(np.mean([jud[f"{arm}|{q}"] for q in qs])), 3)
                for arm in arms}}
        json.dump(report, open(os.path.join(out, "report.json"), "w"), indent=2)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
