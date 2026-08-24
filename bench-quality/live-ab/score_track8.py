#!/usr/bin/env python3
"""Score Track 8 against REVALIDATION.md correction C2.

Truth is `has_env` from label_harvest.py: does this block carry durable
environment knowledge worth extracting? Arms are scored on three things,
all computed without a human judge:

  RECALL       of the env-bearing blocks, how many did the arm act on
  SPECIFICITY  of the pure fix summaries, how many did it correctly refuse
  CLEANLINESS  of the text it chose to store, how much leaks the task's own
               gold-patch identifiers — the per-bug content that must NOT
               end up in a memory. The arm never saw the gold patch, so a
               leak is entirely its own doing. This is the measure that
               separates extraction from classification: an arm that can
               only pick whole blocks scores 100% leakage by construction,
               because every block names gold-patch code.

Arm A is the shipped regex `classify()`. It has no extraction step, so its
"stored text" is the whole block — that is not a handicap imposed here, it
is the actual limit of a block-level classifier.

Usage: score_track8.py
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest_replay as h        # noqa: E402  (classify = arm A)
import label_harvest as L         # noqa: E402  (gold_identity)

OUT = os.path.join(HERE, "track8")


def gold_for(instance_id):
    for t in L.TASKS:
        if t["instance_id"] == instance_id:
            return L.gold_identity(t)
    return set(), set()


def leaks(text, instance_id):
    """Does this memory text name the task's own bug code?"""
    if not text:
        return False
    files, syms = gold_for(instance_id)
    low = text.lower()
    return bool({f for f in files if f.lower() in low} |
                {s for s in syms if re.search(rf"\b{re.escape(s)}\b", text)})


def pct(n, d):
    return f"{100*n/d:.0f}%" if d else "n/a"


def report(name, decisions, truth, texts):
    """decisions/texts keyed by block key; truth keyed the same."""
    env = [k for k in decisions if truth[k]["has_env"]]
    pure = [k for k in decisions if not truth[k]["has_env"]]
    rec = sum(1 for k in env if decisions[k])
    spec = sum(1 for k in pure if not decisions[k])
    stored = [k for k in decisions if decisions[k]]
    leaked = [k for k in stored if leaks(texts.get(k, ""), truth[k]["instance_id"])]
    print(f"\n=== {name} ===")
    print(f"  blocks scored         {len(decisions)}")
    print(f"  RECALL (env-bearing)  {rec}/{len(env)}   {pct(rec, len(env))}")
    print(f"  SPECIFICITY (pure)    {spec}/{len(pure)}   {pct(spec, len(pure))}")
    print(f"  stored                {len(stored)}")
    print(f"  CLEANLINESS: leaked   {len(leaked)}/{len(stored)}   "
          f"{pct(len(leaked), len(stored))} of stored text names gold-patch code")
    return {"recall": rec / len(env) if env else 0,
            "spec": spec / len(pure) if pure else 0,
            "leak": len(leaked) / len(stored) if stored else 0,
            "stored": len(stored), "decisions": decisions}


def main():
    lab = [json.loads(l) for l in open(os.path.join(HERE, "harvest-labelled.jsonl"))]
    truth, blocks = {}, {}
    for i, r in enumerate(lab):
        k = f"{r['label_run']}#{i}"
        truth[k] = r
        blocks[k] = r["block"]

    # --- Arm A: shipped deterministic classifier, whole-block decisions ---
    a_dec = {k: h.classify(b) == "environment" for k, b in blocks.items()}
    a_txt = {k: blocks[k] for k in a_dec}          # no extraction step exists
    A = report("Arm A — deterministic classify()", a_dec, truth, a_txt)

    # --- Arm B: LLM, per model ---
    arms = {}
    for path in sorted(os.listdir(OUT)) if os.path.isdir(OUT) else []:
        if not path.startswith("arm-") or not path.endswith(".jsonl"):
            continue
        model = path[4:-6]
        rows = [json.loads(l) for l in open(os.path.join(OUT, path))]
        rows = [r for r in rows if r["key"] in truth]
        if not rows:
            continue
        dec = {r["key"]: bool(r["store"]) for r in rows}
        txt = {r["key"]: (r.get("memory") or "") for r in rows}
        unparsed = sum(1 for r in rows if not r["parsed"])
        arms[model] = report(f"Arm B — LLM ({model})", dec, truth, txt)
        if unparsed:
            print(f"  NOTE: {unparsed} responses did not parse (counted as refuse)")

    # --- Registered predictions (correction C2) ---
    print("\n" + "=" * 62)
    print("REGISTERED PREDICTIONS — correction C2")
    verdicts = []

    def score(tag, ok, detail):
        verdicts.append(ok)
        print(f"  {tag}: {'PASS' if ok else 'FAIL'} — {detail}")

    for model, m in arms.items():
        score(f"C2-P1 recall >=70% [{model}]", m["recall"] >= 0.70,
              f"{100*m['recall']:.0f}%")
        score(f"C2-P2 specificity >=60% [{model}]", m["spec"] >= 0.60,
              f"{100*m['spec']:.0f}%")
        score(f"C2-P3 leakage <30% [{model}]", m["leak"] < 0.30,
              f"{100*m['leak']:.0f}% of {m['stored']} stored")

    if len(arms) >= 2:
        (m1, a1), (m2, a2) = list(arms.items())[:2]
        common = set(a1["decisions"]) & set(a2["decisions"])
        agree = sum(1 for k in common
                    if a1["decisions"][k] == a2["decisions"][k])
        score(f"C2-P4 {m1}/{m2} agree >=70%",
              len(common) and agree / len(common) >= 0.70,
              f"{agree}/{len(common)} = {pct(agree, len(common))}")
    else:
        print("  C2-P4: NOT TRIGGERED — only one model arm present")

    score("C2-P5 arm A leaks 100%", A["leak"] >= 0.999,
          f"{100*A['leak']:.0f}% of {A['stored']} stored "
          f"(a block-level classifier cannot excise anything)")

    print(f"\n  {sum(verdicts)}/{len(verdicts)} predictions PASS")

    # --- What the extracted memories actually say ---
    for model in arms:
        rows = [json.loads(l) for l in
                open(os.path.join(OUT, f"arm-{model}.jsonl"))]
        clean = [r for r in rows if r.get("store") and r.get("memory")
                 and not leaks(r["memory"], r["instance_id"])]
        print(f"\n--- {model}: sample clean extractions "
              f"({len(clean)} total) ---")
        for r in clean[:3]:
            print(f"  [{r['instance_id']}] {r['memory'][:220]}")


if __name__ == "__main__":
    main()
