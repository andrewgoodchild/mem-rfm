#!/usr/bin/env python3
"""Track 28 — SDE-bench delivery: do source grouping and supersession close
the two gaps Track 27 found? Top-2 memories split a chat's decision (15 of 33
full), and a stale decision outranks its amendment (1 of 6).

Reuses Track 27's formed memories, noise and judge prompt. Two changes:
  grouped     rank memories as shipped, take the K=2 best sources over the
              floor 0.35, and deliver every memory of those sources, cut to
              BUDGET. A commit is its own source; a decoy chat is one source.
  supersede   memories arrive in a seeded random order, stale before amended.
              Each is compared with its 3 nearest earlier memories from other
              sources, cosine >= 0.55, and a haiku judge names any it replaces.
              Replaced memories leave delivery.

BUDGET is 2400 characters, twice the shipped per-turn CHAR_BUDGET, the price of
delivering a group. Track 27 applied no budget, so its 15 is not a capped number.

Bars, written before the first call:
  G1  full on at least 20 of 33.
  G2  full or partial on at least 25 of 33.
  G3  on at least 4 of the 6 amended tasks the stale memories are all replaced
      and an amended memory is delivered.
  G4  at most 5 memories wrongly replaced, across all tasks and decoys: any
      replacement other than an amended task's stale chat by its own amended
      chat. A wrongly replaced memory of a conversation task counts double.
  G5  the noise-only control stays at 0 full.
The same judge sees the delivered text and never the arm. A grouped-only arm
shows what each change contributes.

Usage: sde_group_probe.py SDE_BENCH_DIR AMB_OUTPUTS_SDEBENCH_DIR BOLTONS_GIT
"""
import collections
import json
import os
import random
import sys

import sde_formed_probe as F

S = F.S
OUT = F.OUT
BUDGET = 2400
NEAREST = 3
SIMILAR = 0.55
EXTRACT_MODEL = F.EXTRACT_MODEL

REPLACES = """A project's memory holds these older notes:

{older}

A later decision was recorded:

{newer}

List the numbers of the older notes this later decision replaces: notes about
the same rule, whose instruction must no longer be followed because the later
decision changed it. A note on a different rule, or one the later decision
agrees with or merely resembles, is not replaced.

Reply with JSON only: {{"replaced": [numbers]}}"""


def ordered(keys):
    order = list(keys)
    random.Random(27).shuffle(order)
    for key in keys:
        if key.endswith("/stale"):
            gold = key[:-5] + "gold"
            a, b = order.index(key), order.index(gold)
            if a > b:
                order[a], order[b] = order[b], order[a]
    return order


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def group(scored, docs, floor=S.FLOOR, k=S.K):
    """The K best sources over the floor, each with all its live memories."""
    tops, seen = [], set()
    for score, i in scored:
        src = docs[i]["key"]
        if score < floor:
            break
        if src not in seen:
            seen.add(src)
            tops.append(src)
        if len(tops) == k:
            break
    text = []
    for src in tops:
        text.extend(d["text"] for d in docs if d["key"] == src)
    return "\n\n".join(text)[:BUDGET], tops


def main():
    sde, outputs, host = sys.argv[1:4]
    tasks = S.load_tasks(sde)
    by_id = {t["task_id"]: t for t in tasks}
    formed = json.load(open(os.path.join(OUT, "decision.json")))
    enc = S.embedder()

    commits = [{"key": f"commit-{n}", "text": t}
               for n, t in enumerate(S.commits(outputs, host))]
    memories = []
    for source in ordered(list(formed)):
        for n, text in enumerate(F.contents(formed[source])):
            memories.append({"key": source, "id": f"{source}#{n}", "text": text})
    for d, v in zip(memories + commits,
                    enc([d["text"] for d in memories + commits])):
        d["vec"] = v

    def candidates(n):
        mem = memories[n]
        near = sorted(((dot(mem["vec"], o["vec"]), o["id"], o["text"])
                       for o in memories[:n] if o["key"] != mem["key"]),
                      reverse=True)
        return [x for x in near[:NEAREST] if x[0] >= SIMILAR]
    work = {memories[n]["id"]: (n, candidates(n)) for n in range(len(memories))}

    def replaced(mid):
        n, near = work[mid]
        older = "\n".join(f"{i}. {x[2]}" for i, x in enumerate(near, 1))
        reply = F.llm(REPLACES.format(older=older, newer=memories[n]["text"]),
                      EXTRACT_MODEL)
        parsed = F.sweep.parse_json(reply)
        nums = parsed.get("replaced") if isinstance(parsed, dict) else []
        return [near[i - 1][1] for i in nums or []
                if isinstance(i, int) and 1 <= i <= len(near)]
    asked = [m for m, (_n, near) in work.items() if near]
    print(f"{len(memories)} memories, {len(asked)} with a near earlier one")
    verdicts = F.cached("replaces", asked, replaced)

    retired = collections.defaultdict(list)
    for newer, olds in verdicts.items():
        for old in olds:
            retired[old].append(newer)
    wrong, right = [], 0
    for old, newers in retired.items():
        src = old.split("#")[0]
        own = src.endswith("/stale") and any(
            n.startswith(src[:-5] + "gold") for n in newers)
        right += own
        if not own:
            wrong.append((old, newers[0]))
    weight = sum(2 if not w[0].startswith("decoy-") else 1 for w in wrong)

    live = [m for m in memories if m["id"] not in retired]
    noise = commits + [m for m in memories if m["key"].startswith("decoy-")]
    arms = {"control": noise, "grouped": memories + commits,
            "supersede": live + commits}
    qvecs = dict(zip(by_id, enc([t["bug_report"] for t in tasks])))
    shown, sizes, tops = {}, collections.defaultdict(list), {}
    for arm, docs in arms.items():
        for tid in by_id:
            text, top = group(S.rank(qvecs[tid], docs), docs)
            shown[f"{arm}|{tid}"] = text
            sizes[arm].append(len(text))
            tops[f"{arm}|{tid}"] = top
    keys = list(shown)
    random.Random(28).shuffle(keys)

    def judge(key):
        reply = F.llm(F.VERDICT.format(
            policy=by_id[key.split("|")[1]]["policy"],
            text=shown[key] or "(nothing)"), F.JUDGE_MODEL)
        parsed = F.sweep.parse_json(reply)
        return parsed.get("verdict") if isinstance(parsed, dict) else None
    marks = F.cached("group-verdicts", keys, judge)
    json.dump({"shown": shown, "tops": tops, "wrong": wrong},
              open(os.path.join(OUT, "group-shown.json"), "w"), indent=0)

    for arm in arms:
        count = collections.Counter(marks[f"{arm}|{t}"] for t in by_id)
        print(f"{arm:10} {dict(count)}  mean chars "
              f"{sum(sizes[arm]) / len(sizes[arm]):.0f}")
    amended = 0
    for task in tasks:
        if task["source"] != "conversation-amended":
            continue
        tid = task["task_id"]
        gone = not any(m["key"] == f"{tid}/stale" for m in live)
        amended += gone and f"{tid}/gold" in tops[f"supersede|{tid}"]
    final = collections.Counter(marks[f"supersede|{t}"] for t in by_id)
    control = sum(marks[f"control|{t}"] == "full" for t in by_id)
    full, both = final["full"], final["full"] + final["partial"]
    print(f"replaced: {len(retired)} ({right} correct, {len(wrong)} wrong, "
          f"weighted {weight})")
    print(f"G1 {'PASS' if full >= 20 else 'FAIL'} {full}/33  "
          f"G2 {'PASS' if both >= 25 else 'FAIL'} {both}/33  "
          f"G3 {'PASS' if amended >= 4 else 'FAIL'} {amended}/6  "
          f"G4 {'PASS' if weight <= 5 else 'FAIL'} {weight}  "
          f"G5 {'PASS' if control == 0 else 'FAIL'} {control}")


if __name__ == "__main__":
    sys.exit(main())
