#!/usr/bin/env python3
"""Consolidate extracted memories before they reach the store.

Why this is not optional. Lexical dedup finds almost nothing here — 51
clusters from 53 memories at a 0.65 similarity ratio — because the model
rephrases the same fact every time. But the xarray set contains three
separate memories saying linters are not installed and two saying dask is
not installed, and injection is top-K=3. Unlike a useless memory, which
this project's oracle-subtraction result shows costs ~0 because it simply
sits unused, a near-duplicate COMPETES FOR AN INJECTION SLOT and can crowd
out the one fact that matters (`import xarray` fails without a
pkg_resources shim). So duplicates are expensive exactly where junk is
cheap, and the dedup has to be semantic.

One call per repo scope. Output is written to a file and is meant to be
read before it is trusted.

Usage: dedup_memories.py --repo xarray [--model haiku]
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_track8 as R  # noqa: E402  (parse_json)

PROMPT = """Below are {n} memories a coding agent extracted about the \
`{repo}` repository's development environment. Several state the same \
underlying fact in different words.

Merge them into a minimal set of DISTINCT facts. Rules:
- Two memories describing the same condition become ONE, keeping every \
specific detail from both (exact package names, paths, flags, counts).
- Keep facts that are genuinely different, even if related.
- Drop anything that is about a specific code bug rather than the \
environment.
- Each output memory must stand alone and state a condition and, where \
one is given, its workaround.

MEMORIES:
{body}

Reply with JSON only, no other text:
{{"memories": ["fact one", "fact two", ...]}}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="xarray")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--arm", default="track8/arm-haiku-v2.jsonl")
    a = ap.parse_args()

    lab = [json.loads(l) for l in open(os.path.join(HERE, "harvest-labelled.jsonl"))]
    for i, r in enumerate(lab):
        r["key"] = f"{r['label_run']}#{i}"
    meta = {r["key"]: r for r in lab}
    arm = {r["key"]: r for r in
           (json.loads(l) for l in open(os.path.join(HERE, a.arm)))}

    mems = [arm[k]["memory"].strip() for k in arm
            if arm[k]["store"] and (arm[k].get("memory") or "").strip()
            and meta[k]["repo"] == a.repo]
    if not mems:
        sys.exit(f"no memories for repo {a.repo}")
    body = "\n".join(f"{i+1}. {m}" for i, m in enumerate(mems))
    prompt = PROMPT.format(n=len(mems), repo=a.repo, body=body)

    cwd = os.path.join(HERE, "track8", "sandbox")
    os.makedirs(cwd, exist_ok=True)
    r = subprocess.run(["claude", "-p", "--model", a.model, prompt],
                       cwd=cwd, env={**os.environ, "RFM_HOOKS_OFF": "1"},
                       capture_output=True, text=True, timeout=300)
    v = R.parse_json(r.stdout or "")
    if not v or "memories" not in v:
        sys.exit(f"unparseable consolidation:\n{(r.stdout or '')[:500]}")
    out = [m.strip() for m in v["memories"] if m and m.strip()]

    path = os.path.join(HERE, f"store-{a.repo}.json")
    json.dump({"repo": a.repo, "source_count": len(mems),
               "memories": out}, open(path, "w"), indent=2)
    print(f"{len(mems)} extracted -> {len(out)} distinct   ({path})\n")
    for i, m in enumerate(out):
        print(f"[{i+1}] {m}\n")


if __name__ == "__main__":
    main()
