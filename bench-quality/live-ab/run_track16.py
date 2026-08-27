#!/usr/bin/env python3
"""Track 16 — structured extraction (REVALIDATION.md, registered before
any call). Track 9's extraction framing, output changed to the
DESIGN_NOTES schema {condition_class, scope, era, action, evidence}.
Same 86 blocks, same ground truth, neither seen by the model. Haiku only.

Usage: run_track16.py [--jobs 4] [--limit N]
"""
import argparse
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_track8 as t8  # noqa: E402  (parse_json, MAX_BLOCK, LABELLED)

OUT = os.path.join(HERE, "track16")
MODEL = "haiku"
LOCK = threading.Lock()

PROMPT_V3 = """You are extracting durable environment knowledge for a \
coding agent that will later work on DIFFERENT tasks in the `{repo}` \
repository.

Below is an explanation the agent wrote while finishing one task. Most of \
it is about the specific bug it fixed. Ignore all of that.

Your only job: does ANY part of it describe a RECURRING CONDITION of the \
environment, tooling, installation, or test setup — something that would \
still hold on an unrelated task in this repository? Durable conditions \
look like: a package version mismatch, a workaround needed to run the \
test suite, an import-path quirk, a test that always fails for \
environmental reasons and why, a required PYTHONPATH or stub. Even if 95% \
of the text is about the bug, extract the condition if one is there; a \
single sentence buried at the end still counts.

Do NOT extract: anything about the bug's code, the function that was \
wrong, the fix that was applied, or a failure whose cause is not \
explained.

If you extract, every field must STAND ALONE for someone who has never \
seen this task — never mention the bug, the function, or the source file \
being fixed.

--- BEGIN EXPLANATION ---
{block}
--- END EXPLANATION ---

Reply with JSON only, no other text:
{{"store": true or false, \
"condition_class": "the observable recurring condition, named as \
concretely as possible — an error class (e.g. VersionRequirementError, \
ModuleNotFoundError, pkg_resources) or a state (e.g. not-installed, \
era-pinned-venv, too-new-packages); empty if store is false", \
"scope": "the repo, venv, or checkout this applies to", \
"era": "the checkout era or version range it applies to, or empty", \
"action": "the runnable command or concrete step that addresses the \
condition, standing alone; empty if the block gives none", \
"evidence": "one sentence: what the session observed that shows this \
condition", \
"reason": "under 15 words"}}"""


def ask(row, cwd):
    prompt = PROMPT_V3.format(repo=row["repo"],
                              block=row["block"][:t8.MAX_BLOCK])
    env = {**os.environ, "RFM_HOOKS_OFF": "1"}
    try:
        r = subprocess.run(["claude", "-p", "--model", MODEL, prompt],
                           cwd=cwd, env=env, capture_output=True, text=True,
                           timeout=180)
        raw = (r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        raw = ""
    v = t8.parse_json(raw)
    g = (v or {}).get
    return {"key": row["key"], "instance_id": row["instance_id"],
            "truth": row["truth"], "model": MODEL,
            "store": bool(g("store")) if v else None,
            "condition_class": g("condition_class", ""),
            "scope": g("scope", ""), "era": g("era", ""),
            "action": g("action", ""), "evidence": g("evidence", ""),
            "reason": g("reason", ""),
            "parsed": v is not None,
            "raw": "" if v else raw[:300]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(t8.LABELLED)]
    for i, r in enumerate(rows):
        r["key"] = f"{r['label_run']}#{i}"
    if a.limit:
        rows = rows[:a.limit]
    os.makedirs(OUT, exist_ok=True)
    cwd = os.path.join(OUT, "sandbox")
    os.makedirs(cwd, exist_ok=True)

    path = os.path.join(OUT, "arm-haiku-v3.jsonl")
    done = set()
    if os.path.exists(path):
        done = {json.loads(l)["key"] for l in open(path)}
    todo = [r for r in rows if r["key"] not in done]
    print(f"[{MODEL} v3] {len(done)} done, {len(todo)} to run", flush=True)
    if not todo:
        return
    sink = open(path, "a")
    n = 0
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for res in ex.map(lambda r: ask(r, cwd), todo):
            with LOCK:
                sink.write(json.dumps(res) + "\n")
                sink.flush()
            n += 1
            if n % 10 == 0:
                print(f"[{MODEL} v3] {n}/{len(todo)}", flush=True)
    sink.close()
    print(f"[{MODEL} v3] complete", flush=True)


if __name__ == "__main__":
    main()
