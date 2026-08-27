#!/usr/bin/env python3
"""Score Track 16 (structured extraction) against its registered bars,
anchored to Track 9's achieved haiku-v2 numbers.

Usage: score_track16.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import label_harvest as L        # noqa: E402  (STRONG_ENV, tight truth)
import score_track8 as S8        # noqa: E402  (leaks)

ARM = os.path.join(HERE, "track16", "arm-haiku-v3.jsonl")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main():
    lab = {f"{r['label_run']}#{i}": r
           for i, r in enumerate(json.loads(l)
                                 for l in open(os.path.join(
                                     HERE, "harvest-labelled.jsonl")))}
    arm = {r["key"]: r for r in (json.loads(l) for l in open(ARM))}
    keys = set(lab) & set(arm)
    tight = {k for k in keys if L.STRONG_ENV.search(lab[k]["block"])}
    unparsed = [k for k in keys if not arm[k]["parsed"]]
    stored = [k for k in keys if arm[k]["store"]]
    print(f"blocks {len(keys)}   tight env-bearing {len(tight)}   "
          f"stored {len(stored)}   unparsed {len(unparsed)}")

    rt = sum(1 for k in tight if arm[k]["store"])
    recall = rt / max(len(tight), 1)

    def mem_text(r):
        return " ".join([r.get("condition_class") or "",
                         r.get("action") or "", r.get("evidence") or ""])
    leak = [k for k in stored
            if S8.leaks(mem_text(arm[k]), arm[k]["instance_id"])]

    named = [k for k in stored if lab[k]["block_classes"]]
    cond_ok = [k for k in named
               if any(norm(c) in norm(arm[k]["condition_class"])
                      or norm(arm[k]["condition_class"]) in norm(c)
                      for c in lab[k]["block_classes"]
                      if norm(arm[k]["condition_class"]))]

    complete = [k for k in stored
                if (arm[k]["condition_class"] or "").strip()
                and (arm[k]["action"] or "").strip()]

    pure = set(keys) - tight
    refused = sum(1 for k in pure if not arm[k]["store"])
    spec = refused / max(len(pure), 1)

    print("\n" + "=" * 62)
    print("REGISTERED PREDICTIONS — Track 16")
    v = []

    def sc(tag, ok, detail):
        v.append(ok)
        print(f"  {tag}: {'PASS' if ok else 'FAIL'} — {detail}")

    sc("T16-P1 recall/tight >= 80% (v2: 88%)", recall >= 0.80,
       f"{rt}/{len(tight)} = {100 * recall:.0f}%")
    lr = len(leak) / max(len(stored), 1)
    sc("T16-P2 leakage < 19% (v2 achieved)", lr < 0.19,
       f"{len(leak)}/{len(stored)} = {100 * lr:.0f}%")
    cr = len(cond_ok) / max(len(named), 1)
    sc("T16-P3 condition matches named class >= 70%",
       cr >= 0.70, f"{len(cond_ok)}/{len(named)} = {100 * cr:.0f}%"
       f" (denominator: stored blocks naming a class)")
    comp = len(complete) / max(len(stored), 1)
    sc("T16-P4 condition+action complete >= 80%", comp >= 0.80,
       f"{len(complete)}/{len(stored)} = {100 * comp:.0f}%")
    sc("T16-P5 specificity >= 70% (v2: 62%)", spec >= 0.70,
       f"{refused}/{len(pure)} pure per-bug blocks refused = "
       f"{100 * spec:.0f}%")
    print(f"\n  {sum(v)}/{len(v)} PASS")

    print("\n--- sample stored rows ---")
    for k in stored[:6]:
        r = arm[k]
        print(f"  [{r['instance_id']}] class={r['condition_class'][:40]!r} "
              f"era={r['era'][:20]!r}\n"
              f"      action={r['action'][:90]!r}")


if __name__ == "__main__":
    main()
