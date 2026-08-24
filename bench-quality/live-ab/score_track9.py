#!/usr/bin/env python3
"""Score Track 9 (extraction framing) against v1, on the tightened truth.

Reports BOTH truths everywhere. The tightened one was chosen on linguistic
grounds before any v2 call and moves v1's recall by only 8 points, but a
ground truth refined after seeing results has to show its work rather than
be asserted.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import label_harvest as L        # noqa: E402  (STRONG_ENV, gold_identity)
import score_track8 as S8        # noqa: E402  (leaks)

OUT = os.path.join(HERE, "track8")


def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return {}
    return {r["key"]: r for r in (json.loads(l) for l in open(p))}


def main():
    lab = [json.loads(l) for l in open(os.path.join(HERE, "harvest-labelled.jsonl"))]
    for i, r in enumerate(lab):
        r["key"] = f"{r['label_run']}#{i}"
    tight = {r["key"] for r in lab if L.STRONG_ENV.search(r["block"])}
    loose = {r["key"] for r in lab if r["has_env"]}
    inst = {r["key"]: r["instance_id"] for r in lab}

    print(f"blocks {len(lab)}   tight-truth env-bearing {len(tight)} "
          f"({100*len(tight)/len(lab):.0f}%)   loose {len(loose)} "
          f"({100*len(loose)/len(lab):.0f}%)\n")
    print(f"{'arm':<18}{'recall/tight':>13}{'recall/loose':>13}"
          f"{'specificity':>12}{'stored':>8}{'leak':>7}{'clean':>7}")
    res = {}
    for model in ("haiku", "sonnet"):
        for variant, fname in (("v1", f"arm-{model}.jsonl"),
                               ("v2", f"arm-{model}-v2.jsonl")):
            arm = load(fname)
            if not arm:
                continue
            keys = set(arm)
            stored = [k for k in keys if arm[k]["store"]]
            rt = sum(1 for k in tight & keys if arm[k]["store"])
            rl = sum(1 for k in loose & keys if arm[k]["store"])
            pure = keys - tight
            sp = sum(1 for k in pure if not arm[k]["store"])
            leak = [k for k in stored
                    if S8.leaks(arm[k].get("memory") or "", inst[k])]
            clean = len(stored) - len(leak)
            res[(model, variant)] = {
                "recall_t": rt / max(len(tight & keys), 1),
                "spec": sp / max(len(pure), 1),
                "leak": len(leak) / max(len(stored), 1),
                "clean": clean, "stored": len(stored)}
            print(f"{model+' '+variant:<18}"
                  f"{f'{rt}/{len(tight&keys)} {100*rt/max(len(tight&keys),1):.0f}%':>13}"
                  f"{f'{rl}/{len(loose&keys)} {100*rl/max(len(loose&keys),1):.0f}%':>13}"
                  f"{f'{100*sp/max(len(pure),1):.0f}%':>12}"
                  f"{len(stored):>8}"
                  f"{f'{100*len(leak)/max(len(stored),1):.0f}%':>7}"
                  f"{clean:>7}")

    print("\n" + "=" * 62)
    print("REGISTERED PREDICTIONS — Track 9")
    h1, h2 = res.get(("haiku", "v1")), res.get(("haiku", "v2"))
    s2 = res.get(("sonnet", "v2"))
    v = []

    def sc(tag, ok, detail):
        v.append(ok)
        print(f"  {tag}: {'PASS' if ok else 'FAIL'} — {detail}")

    sc("T9-P1 haiku recall >=65%", h2["recall_t"] >= 0.65,
       f"{100*h2['recall_t']:.0f}% (v1 was {100*h1['recall_t']:.0f}%)")
    sc("T9-P2 haiku leakage <26%", h2["leak"] < 0.26,
       f"{100*h2['leak']:.0f}% of {h2['stored']} (v1 {100*h1['leak']:.0f}%)")
    sc("T9-P3 specificity >=80%", h2["spec"] >= 0.80, f"{100*h2['spec']:.0f}%")
    sc("T9-P4 clean memories >=25", h2["clean"] >= 25,
       f"{h2['clean']} (v1 {h1['clean']})")
    if s2:
        sc("T9-P5 haiku <= sonnet leakage", h2["leak"] <= s2["leak"],
           f"haiku {100*h2['leak']:.0f}% vs sonnet {100*s2['leak']:.0f}%")
    print(f"\n  {sum(v)}/{len(v)} PASS")

    arm = load("arm-haiku-v2.jsonl")
    clean = [k for k in arm if arm[k]["store"] and arm[k].get("memory")
             and not S8.leaks(arm[k]["memory"], inst[k])]
    print(f"\n--- haiku v2 clean extractions ({len(clean)}) ---")
    for k in clean[:4]:
        print(f"  [{inst[k]}] {arm[k]['memory'][:200]}")


if __name__ == "__main__":
    main()
