#!/usr/bin/env python3
"""STAR team-memory eval (pre-registered replication of the ABCD result).

Data: STAR (RasaHQ/STAR, MIT) — 6,652 wizard-of-oz task-oriented dialogs
across 24 tasks; human wizards followed genuinely AUTHORED task flowcharts.
Two properties ABCD lacked: real per-dialog wizard worker IDs (the solo/team
split follows the dataset's own ~90 wizards, no round-robin imposed) and
real Unix timestamps (the stream is the actual collection order, no seeded
shuffle). Multi-task dialogs are excluded (ambiguous label).

Query = the customer's opening utterances; memory = opening utterances +
the wizard's responses; label = the scenario's wizard task. Manual = the 24
authored task definitions (task name + reply templates). Retrieval is a HIT
if top-k contains an item (manual entry or past-dialog memory) whose task
matches. No LLM anywhere; oracle evidence-hit outcomes (disclosed).

Usage: star_eval.py [--n 6500] [--k 5]
"""
import argparse
import glob
import json
import os

import common
import team_common

DATA = os.path.join(common.HERE, "data", "star")
CACHE = os.path.join(common.HERE, "cache-star" + common.cache_suffix())


def load_calls(n):
    calls = []
    for f in sorted(glob.glob(os.path.join(DATA, "dialogues", "*.json"))):
        d = json.load(open(f))
        if d["Scenario"].get("MultiTask"):
            continue
        task = d["Scenario"]["WizardCapabilities"][0]["Task"]
        user, wizard, t_first = [], [], None
        for e in d["Events"]:
            if t_first is None and "UnixTime" in e:
                t_first = e["UnixTime"]
            if not e.get("Text"):
                continue
            if e.get("Agent") == "User" and e.get("Action") == "utter":
                user.append(e["Text"])
            elif (e.get("Agent") == "Wizard"
                  and e.get("Action") in ("utter", "pick_suggestion")):
                wizard.append(e["Text"])
        if not user or t_first is None:
            continue
        calls.append({
            "label": task,
            "agent": d["AnonymizedWizardWorkerID"],
            "ts": float(t_first),
            "query": " ".join(user[:2]),
            "memory": "customer request: " + " ".join(user[:3]) +
                      " | handled via: " + ("; ".join(wizard[:4]) or "(no wizard turns)"),
        })
    calls.sort(key=lambda c: c["ts"])
    return calls[:n]


def load_manual():
    """The 24 authored task definitions given to wizards. Task dirs map to
    scenario task names by directory name; assert full coverage — silent
    partial coverage invalidates the manual arm (the ABCD postmortem)."""
    entries = []
    for tdir in sorted(glob.glob(os.path.join(DATA, "tasks", "*"))):
        name = os.path.basename(tdir)
        spec_path = os.path.join(tdir, name + ".json")
        if not os.path.exists(spec_path):
            continue
        spec = json.load(open(spec_path))
        replies = "; ".join(str(v) for v in spec.get("replies", {}).values())
        entries.append({"label": name,
                        "text": f"task procedure: {name}. replies: {replies}"[:1500]})
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6500)
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    calls = load_calls(args.n)
    manual = load_manual()
    labels = {c["label"] for c in calls}
    covered = {m["label"] for m in manual}
    missing = labels - covered
    if missing:
        raise RuntimeError(f"manual does not cover tasks: {sorted(missing)}")

    team_common.run(
        "STAR", calls, [m for m in manual if m["label"] in labels], args.k,
        CACHE, f"n{args.n}",
        results_path=os.path.join(
            common.HERE, "results-star",
            f"per_call{common.cache_suffix()}.jsonl") if args.n >= 6000 else None)


if __name__ == "__main__":
    os.makedirs(os.path.join(common.HERE, "results-star"), exist_ok=True)
    main()
