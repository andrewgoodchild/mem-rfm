#!/usr/bin/env python3
"""Substrate-less venue probe, SDE-bench half: free, no sessions.

SDE-bench's conversation tasks hinge on a decision made only in a past
developer chat. Before paying for a session, ask the two things that decide
whether the venue can show anything for mem-rfm:

  headroom  from the published no-memory runs: corrections per task on the
            conversation stratum.
  reach     can the shipped per-turn retrieval (cosine with the same embedder
            and truncation, K=2, floor 0.35) put the deciding chat in front of
            the agent, given only the bug report? Memory is seeded verbatim:
            this is the upper bound of delivery, with no formation loss.

Bars, written before this script first ran:
  P1  top-K with the floor reaches the deciding chat on at least 60% of the
      33 conversation tasks. Below that the delivery path is the bottleneck
      and a paid arm would measure retrieval, not memory.
  P2  the top 8, the judge's prefilter (no floor), reach it on at least 80%.
  P3  on the 6 amended tasks, the amended chat outranks the stale one on at
      least 4.

Documents are chat turns, the unit a memory is closer to than a whole chat;
a task's gold is any turn of its deciding chat, which is generous. Whole
chats are also scored, truncated as the embedder truncates them. Noise is
every other task's chats, the 140 decoys, and the host's commits. rfm priors are flat here: nothing has been used yet.

Usage: sde_reach_probe.py SDE_BENCH_DIR AMB_OUTPUTS_SDEBENCH_DIR BOLTONS_GIT
"""
import collections
import glob
import gzip
import json
import math
import os
import re
import statistics
import subprocess
import sys

EMBEDDER = "sentence-transformers/all-MiniLM-L6-v2"
MAX_TOKENS = 256
CHARS = 2000
K = 2
FLOOR = 0.35
PREFILTER = 8
HOST_REF = "979fa9b613fa8c0a455ae16ea6f2ec91c11ecafe"


def load_tasks(root):
    out = []
    for path in sorted(glob.glob(os.path.join(root, "*/tasks/*/task.json"))):
        task = json.load(open(path))
        if task["source"] != "history":
            out.append(task)
    return out


def chats_of(task):
    """(stale chat or None, deciding chat)."""
    convs = task["conversations"]
    return (convs[0], convs[1]) if isinstance(convs[0], list) else (None, convs)


def corrections(root):
    """{(run prefix, source): [interventions per task-run]}."""
    out = collections.defaultdict(list)
    for prefix in ("vanilla-claude", "hindsight-claude"):
        for run in glob.glob(os.path.join(root, prefix + "-[0-9]")):
            data = json.load(gzip.open(
                os.path.join(run, "coding", "boltons.json.gz")))
            for row in data["results"]:
                m = re.search(r"interventions=(\d+)", row.get("reasoning") or "")
                if m:
                    out[prefix, row["meta"]["source"]].append(int(m.group(1)))
    return out


def commits(root, host):
    """The host's real history plus the commits a conversation task's own
    repository carries. Never a history task's: those state the rationale of
    their conversation twins, and including them leaked every answer into
    the noise (Track 27's first run)."""
    data = json.load(gzip.open(os.path.join(
        root, "vanilla-claude-1", "coding", "boltons.json.gz")))
    seen = {}
    for row in data["results"]:
        if row["meta"]["source"] == "history":
            continue
        for c in row.get("git_history") or []:
            text = (c.get("subject", "") + "\n" + c.get("body", "")).strip()
            if text:
                seen[c["sha"]] = text
    log = subprocess.run(
        ["git", "-C", host, "log", "--format=%H%n%B%x00", HOST_REF],
        capture_output=True, text=True, check=True).stdout
    for entry in log.split("\0"):
        sha, _, text = entry.strip().partition("\n")
        if text.strip():
            seen[sha] = text.strip()
    return list(seen.values())


def embedder():
    from fastembed import TextEmbedding
    model = TextEmbedding(model_name=EMBEDDER)
    model.model.tokenizer.enable_truncation(max_length=MAX_TOKENS)

    def enc(texts):
        out = []
        for v in model.embed([t[:CHARS] for t in texts]):
            n = math.sqrt(sum(float(x) * float(x) for x in v)) or 1.0
            out.append([float(x) / n for x in v])
        return out
    return enc


def rank(qvec, docs):
    """Doc indices by descending cosine, with their scores."""
    scored = [(sum(a * b for a, b in zip(qvec, d["vec"])), i)
              for i, d in enumerate(docs)]
    scored.sort(reverse=True)
    return scored


def score(tasks, docs, enc, label):
    qvecs = enc([t["bug_report"] for t in tasks])
    hit_k, hit_8, ranks, amended, floors = 0, 0, [], [], []
    for task, qvec in zip(tasks, qvecs):
        scored = rank(qvec, docs)
        gold = task["task_id"] + "/gold"
        stale = task["task_id"] + "/stale"
        first = next((n for n, (_s, i) in enumerate(scored)
                      if docs[i]["key"] == gold), None)
        ranks.append(first)
        top = [i for s, i in scored if s >= FLOOR][:K]
        floors.append(len(top))
        hit_k += any(docs[i]["key"] == gold for i in top)
        hit_8 += any(docs[i]["key"] == gold for _s, i in scored[:PREFILTER])
        if task["source"] == "conversation-amended":
            old = next(n for n, (_s, i) in enumerate(scored)
                       if docs[i]["key"] == stale)
            amended.append(first < old)
    n = len(tasks)
    print(f"{label}: {len(docs)} docs, {n} tasks")
    print(f"  top-{K} floor {FLOOR}: {hit_k}/{n} = {hit_k / n:.0%}"
          f"  (shown on average {statistics.mean(floors):.2f})")
    print(f"  top-{PREFILTER}: {hit_8}/{n} = {hit_8 / n:.0%}"
          f"  median gold rank {statistics.median(ranks) + 1:.0f}")
    print(f"  amended beats stale: {sum(amended)}/{len(amended)}")
    return hit_k / n, hit_8 / n, sum(amended)


def main():
    sde, outputs, host = sys.argv[1:4]
    tasks = load_tasks(sde)
    print("published corrections per task (mean, % needing none):")
    for (prefix, source), vals in sorted(corrections(outputs).items()):
        none = 100 * sum(v == 0 for v in vals) / len(vals)
        print(f"  {prefix:18} {source:21} n={len(vals):3} "
              f"{statistics.mean(vals):.2f}  {none:.0f}%")

    enc = embedder()
    noise = commits(outputs, host)
    for decoy in json.load(open(os.path.join(sde, "gen",
                                             "decoy_conversations.json"))):
        noise.extend(t["text"] for t in decoy["turns"])
    turn_docs = [{"key": "noise", "text": t} for t in noise]
    chat_docs = [{"key": "noise", "text": t} for t in noise]
    for task in tasks:
        for tag, chat in zip(("stale", "gold"), chats_of(task)):
            if chat is None:
                continue
            key = f"{task['task_id']}/{tag}"
            turn_docs.extend({"key": key, "text": t["text"]} for t in chat)
            chat_docs.append({"key": key,
                              "text": "\n".join(t["text"] for t in chat)})
    for docs in (turn_docs, chat_docs):
        for d, v in zip(docs, enc([d["text"] for d in docs])):
            d["vec"] = v

    p1, p2, p3 = score(tasks, turn_docs, enc, "turns")
    score(tasks, chat_docs, enc, "whole chats")
    print(f"P1 {'PASS' if p1 >= 0.60 else 'FAIL'}  "
          f"P2 {'PASS' if p2 >= 0.80 else 'FAIL'}  "
          f"P3 {'PASS' if p3 >= 4 else 'FAIL'}")


if __name__ == "__main__":
    sys.exit(main())
