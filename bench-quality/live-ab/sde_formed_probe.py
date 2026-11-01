#!/usr/bin/env python3
"""Track 27 — SDE-bench formed-memory reach: does forming decisions first put
the decision itself in front of the agent?

The reach probe (sde_reach_probe.py) found raw chat turns carry the decision
on 1 of 33 tasks: similarity finds the opening symptom, not the terse later
ruling. This forms memories from each chat, then asks the same retrieval the
same question, scoring what is delivered instead of where it came from. No
coding sessions; LLM calls for formation and judging only.

Arms, all delivered by the shipped per-turn rule (K=2, floor 0.35):
  raw      chat turns, for calibration against the hand count (1 full, 3 part)
  shipped  sweep.EXTRACT with material as the sweep builds it: the last three
           long assistant turns, no user turns, and a prompt that says never
           to name the task's function or file
  decision a prompt asking for the developer's rulings, over the whole chat

The judge sees the task's policy and the delivered text, never the arm. It
rules full, partial or none.

Bars, written before the first call:
  F1  decision arm: full on at least 20 of 33. Below that a paid A/B would
      measure retrieval, and the stop rule applies.
  F2  decision arm: full or partial on at least 25 of 33.
  F3  decision arm, 6 amended tasks: the amended memory outranks the stale
      one on at least 4.
Prediction, no bar: shipped lands well below decision, since its material
drops the user turns and its prompt forbids the specifics.

Each chat is formed alone, with no consolidation across chats, so an amended
task carries both its stale and its amended memories. Noise is the commits
plus the decoy chats formed by the decision prompt, in every formed arm.

The first run was void: its noise held history-task commits that state the
conversation tasks' rules, so a shipped arm with no memories scored 32 of 33
full. The bars above are unchanged. Added after that run, the noise arm is a
negative control: noise alone, which must score about zero.

Usage: sde_formed_probe.py SDE_BENCH_DIR AMB_OUTPUTS_SDEBENCH_DIR BOLTONS_GIT
"""
import collections
import concurrent.futures
import json
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "track27")
TMP = tempfile.mkdtemp(prefix="rfm-track27-")
os.environ["RFM_MEMORY_DB"] = os.path.join(TMP, "unused.db")
os.environ["RFM_LOG"] = "0"
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "integrations", "claude-code"))
import sde_reach_probe as S  # noqa: E402
import sweep                 # noqa: E402

EXTRACT_MODEL = "haiku"
JUDGE_MODEL = "sonnet"
WORKERS = 6
CHAT_CAP = 12000

DECISION = """You decide what enters the long-term memory of a coding agent
that will work on this repository later. Below is a past conversation between
a developer and an agent.

Record the decisions the developer reached that the code alone does not
explain: exact rules, values, orderings and exceptions. Ignore proposals the
conversation rejected; where a later turn overrides an earlier one, keep only
the final rule. Each memory must stand alone for someone who never saw this
conversation: name the module or function and the symptom it answers, and
state the rule in full, with its exact values.

--- BEGIN CONVERSATION ---
{chat}
--- END CONVERSATION ---

Reply with a JSON list only, at most 3 items, possibly empty:
[{{"content": "the memory"}}]"""

VERDICT = """A project decided the following rule:

{policy}

An engineer fixing a bug is shown only this text from the project's memory:

--- BEGIN TEXT ---
{text}
--- END TEXT ---

Does the text state the rule, so the engineer could implement it without
guessing? "full" means all of its essential values and conditions are stated.
"partial" means some are. "none" means it describes the problem, or a
different or rejected approach, without the rule.

Reply with JSON only: {{"verdict": "full" | "partial" | "none"}}"""


def llm(prompt, model):
    r = subprocess.run(["claude", "-p", "--model", model, prompt],
                       env={**os.environ, "RFM_HOOKS_OFF": "1"}, cwd=TMP,
                       capture_output=True, text=True, timeout=300)
    return (r.stdout or "").strip()


def cached(name, keys, fn):
    """{key: fn(key)}, resumable: every answer is kept as it arrives."""
    path = os.path.join(OUT, name + ".json")
    done = json.load(open(path)) if os.path.exists(path) else {}
    todo = [k for k in keys if k not in done]

    def one(key):
        return key, fn(key)
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        for n, (key, value) in enumerate(pool.map(one, todo), 1):
            done[key] = value
            if n % 20 == 0 or n == len(todo):
                print(f"{name}: {n}/{len(todo)}", flush=True)
                json.dump(done, open(path, "w"), indent=0)
    return done


def transcript(chat):
    return "\n\n".join(f"{t['role'].upper()}: {t['text']}"
                       for t in chat)[:CHAT_CAP]


def shipped_material(chat):
    prose = [t["text"] for t in chat
             if t["role"] == "assistant" and len(t["text"]) >= 200]
    return "\n\n".join(prose[-3:])[:6000]


def shipped_prompt(chat):
    return sweep.EXTRACT.format(
        instruction=sweep.CONFIG["instruction"],
        ontology=", ".join(sweep.CONFIG["ontology"]),
        max_per_session=sweep.CONFIG["max_per_session"],
        project="boltons", material=shipped_material(chat))


def contents(reply):
    items = sweep.parse_json(reply)
    if not isinstance(items, list):
        return []
    return [i["content"] for i in items
            if isinstance(i, dict) and isinstance(i.get("content"), str)]


def delivered(qvec, docs):
    return [docs[i] for s, i in S.rank(qvec, docs) if s >= S.FLOOR][:S.K]


def main():
    sde, outputs, host = sys.argv[1:4]
    os.makedirs(OUT, exist_ok=True)
    tasks = S.load_tasks(sde)
    decoys = json.load(open(os.path.join(sde, "gen",
                                         "decoy_conversations.json")))
    chats = {}
    for task in tasks:
        for tag, chat in zip(("stale", "gold"), S.chats_of(task)):
            if chat is not None:
                chats[f"{task['task_id']}/{tag}"] = chat
    for n, decoy in enumerate(decoys):
        chats[f"decoy-{n}"] = decoy["turns"]
    task_keys = [k for k in chats if not k.startswith("decoy-")]

    formed = {
        "decision": cached("decision", list(chats), lambda k: llm(
            DECISION.format(chat=transcript(chats[k])), EXTRACT_MODEL)),
        "shipped": cached("shipped", task_keys, lambda k: llm(
            shipped_prompt(chats[k]), EXTRACT_MODEL)),
    }

    enc = S.embedder()
    commits = S.commits(outputs, host)
    noise = [{"key": "noise", "text": t} for t in commits]
    for key, reply in formed["decision"].items():
        if key.startswith("decoy-"):
            noise.extend({"key": "noise", "text": c} for c in contents(reply))
    raw_noise = [{"key": "noise", "text": t} for t in commits]
    for decoy in decoys:
        raw_noise.extend({"key": "noise", "text": t["text"]}
                         for t in decoy["turns"])

    arms = {"raw": raw_noise + [{"key": k, "text": t["text"]}
                                for k in task_keys for t in chats[k]]}
    arms["noise"] = [dict(d) for d in noise]
    for arm in ("shipped", "decision"):
        arms[arm] = noise + [{"key": k, "text": c} for k in task_keys
                             for c in contents(formed[arm][k])]
    for docs in arms.values():
        for d, v in zip(docs, enc([d["text"] for d in docs])):
            d["vec"] = v

    by_id = {t["task_id"]: t for t in tasks}
    qvecs = dict(zip(by_id, enc([t["bug_report"] for t in tasks])))
    shown = {}
    for arm, docs in arms.items():
        for tid in by_id:
            shown[f"{arm}|{tid}"] = "\n\n".join(
                d["text"] for d in delivered(qvecs[tid], docs))

    keys = list(shown)
    random.Random(26).shuffle(keys)

    def judge(key):
        tid = key.split("|")[1]
        reply = llm(VERDICT.format(policy=by_id[tid]["policy"],
                                   text=shown[key] or "(nothing)"),
                    JUDGE_MODEL)
        parsed = sweep.parse_json(reply)
        return parsed.get("verdict") if isinstance(parsed, dict) else None
    verdicts = cached("verdicts", keys, judge)
    json.dump(shown, open(os.path.join(OUT, "shown.json"), "w"), indent=0)

    for arm, docs in arms.items():
        count = collections.Counter(verdicts[f"{arm}|{t}"] for t in by_id)
        amended_first = 0
        for task in tasks:
            if task["source"] != "conversation-amended":
                continue
            order = [docs[i]["key"] for _s, i in S.rank(qvecs[task["task_id"]],
                                                        docs)]
            gold, stale = (f"{task['task_id']}/{t}" for t in ("gold", "stale"))
            if gold in order and (stale not in order or
                                  order.index(gold) < order.index(stale)):
                amended_first += 1
        memories = sum(d["key"] != "noise" for d in docs)
        print(f"{arm:9} {len(docs):5} docs, {memories:4} task docs: "
              f"{dict(count)}  amended first {amended_first}/6")
        if arm == "decision":
            full = count["full"]
            print(f"F1 {'PASS' if full >= 20 else 'FAIL'} full {full}/33  "
                  f"F2 {'PASS' if full + count['partial'] >= 25 else 'FAIL'} "
                  f"full+partial {full + count['partial']}/33  "
                  f"F3 {'PASS' if amended_first >= 4 else 'FAIL'}")


if __name__ == "__main__":
    sys.exit(main())
