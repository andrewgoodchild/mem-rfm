#!/usr/bin/env python3
"""Track 8 — prose harvest, deterministic arm vs LLM arm.

Registered in REVALIDATION.md before either arm ran. Ground truth comes
from harvest-labelled.jsonl, built by label_harvest.py from each task's
gold_patch. NEITHER ARM SEES THE GOLD PATCH — the prompt below carries the
prose block and the repo name and nothing else. That is the whole reason
this comparison is worth anything: an LLM arm graded by an LLM judge would
score points the regex arm could never score, and the result would mean
nothing.

Arm A is `classify()` from harvest_replay.py, already shipped and already
known by its own author to be wrong. Arm B is `claude -p` at two sizes,
because this would run at every SessionEnd and "does formation need a big
model?" decides whether it is affordable.

Resumable: results append to track8/arm-<model>.jsonl and completed block
ids are skipped, so an interrupted run continues rather than re-spending.

Usage: run_track8.py [--models haiku,sonnet] [--jobs 6] [--limit N]
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest_replay as h  # noqa: E402

OUT = os.path.join(HERE, "track8")
LABELLED = os.path.join(HERE, "harvest-labelled.jsonl")
MAX_BLOCK = 4000          # keep calls cheap; explanations are far shorter
LOCK = threading.Lock()

# The block and the repo. No gold patch, no task id, no hint of the answer.
PROMPT = """You decide what goes into the long-term memory of a coding \
agent that works in the `{repo}` repository. It will face DIFFERENT tasks \
in this same repository later.

Below is an explanation the agent wrote while finishing a task.

Store it ONLY if it is durable knowledge about the environment, tooling, \
installation, or test setup that would still help on an unrelated task in \
this repository. Do NOT store knowledge about the specific bug that was \
fixed — the code, the function, the logic — because a later task will be a \
different bug in a different place, and that knowledge will not apply.

--- BEGIN EXPLANATION ---
{block}
--- END EXPLANATION ---

Reply with JSON only, no other text:
{{"store": true or false, "class": "environment" or "per-bug", \
"reason": "under 15 words", "memory": "the memory text if store is true, \
else empty string"}}"""


# --- v2 (Track 9) ------------------------------------------------------
# v1 asked for a verdict on the whole block: "store it ONLY if it IS
# durable knowledge". Every block is ~90% fix summary, so that framing
# reads as "no" even when a nugget is present, and recall came in at 39%
# against blocks that demonstrably name an environment condition. v2 asks
# for EXTRACTION instead of classification, says explicitly that most of
# the text should be ignored, and tells the model to write the memory so it
# stands alone — which also targets the 26% of v1 stores that leaked the
# task's own bug identifiers.
PROMPT_V2 = """You are extracting durable environment knowledge for a \
coding agent that will later work on DIFFERENT tasks in the `{repo}` \
repository.

Below is an explanation the agent wrote while finishing one task. Most of \
it is about the specific bug it fixed. Ignore all of that.

Your only job: does ANY part of it describe the environment, tooling, \
installation, or test setup in a way that would still be true and useful \
on an unrelated task in this repository? Durable facts look like: a \
package version mismatch, a workaround needed to run the test suite, an \
import-path quirk, a test that always fails for environmental reasons and \
why, a required PYTHONPATH or stub.

Even if 95% of the text is about the bug, extract the durable fact if one \
is there. A single sentence buried at the end still counts.

Do NOT extract: anything about the bug's code, the function that was \
wrong, the fix that was applied, or a test failure whose cause is not \
explained.

If you extract, write the memory so it STANDS ALONE for someone who has \
never seen this task: state the condition and the workaround. Do not \
mention the bug, the function, or the source file that was being fixed.

--- BEGIN EXPLANATION ---
{block}
--- END EXPLANATION ---

Reply with JSON only, no other text:
{{"store": true or false, "class": "environment" or "per-bug", \
"reason": "under 15 words", "memory": "the memory text if store is true, \
else empty string"}}"""


def parse_json(text):
    """Models fence JSON, prefix it, or emit it bare. Take the first object."""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def ask(model, row, cwd, variant="v1"):
    tmpl = PROMPT if variant == "v1" else PROMPT_V2
    prompt = tmpl.format(repo=row["repo"], block=row["block"][:MAX_BLOCK])
    env = {**os.environ, "RFM_HOOKS_OFF": "1"}
    try:
        r = subprocess.run(["claude", "-p", "--model", model, prompt],
                           cwd=cwd, env=env, capture_output=True, text=True,
                           timeout=180)
        raw = (r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        raw = ""
    v = parse_json(raw)
    return {"key": row["key"], "instance_id": row["instance_id"],
            "truth": row["truth"], "model": model,
            "store": bool(v.get("store")) if v else None,
            "pred_class": (v or {}).get("class"),
            "reason": (v or {}).get("reason"),
            "memory": (v or {}).get("memory", ""),
            "parsed": v is not None,
            "raw": "" if v else raw[:300]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="haiku,sonnet")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--variant", default="v1", choices=("v1", "v2"))
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(LABELLED)]
    for i, r in enumerate(rows):
        r["key"] = f"{r['label_run']}#{i}"
    if a.limit:
        rows = rows[:a.limit]
    os.makedirs(OUT, exist_ok=True)
    # Neutral cwd: running claude inside the repo would let it read the
    # project and this experiment's own files.
    cwd = os.path.join(OUT, "sandbox")
    os.makedirs(cwd, exist_ok=True)

    for model in [m.strip() for m in a.models.split(",") if m.strip()]:
        suffix = "" if a.variant == "v1" else f"-{a.variant}"
        path = os.path.join(OUT, f"arm-{model}{suffix}.jsonl")
        done = set()
        if os.path.exists(path):
            done = {json.loads(l)["key"] for l in open(path)}
        todo = [r for r in rows if r["key"] not in done]
        print(f"[{model}] {len(done)} done, {len(todo)} to run", flush=True)
        if not todo:
            continue
        sink = open(path, "a")
        n = 0
        with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
            for res in ex.map(lambda r: ask(model, r, cwd, a.variant), todo):
                with LOCK:
                    sink.write(json.dumps(res) + "\n")
                    sink.flush()
                n += 1
                if n % 10 == 0:
                    print(f"[{model}] {n}/{len(todo)}", flush=True)
        sink.close()
        print(f"[{model}] complete", flush=True)


if __name__ == "__main__":
    main()
