#!/usr/bin/env python3
"""Track 35 — does the verify pass tell a true memory from a false one?

The pass (integrations/claude-code/verify.py) checks a formed memory against
the conversation it came from and marks it confirmed, contradicted or
unsupported. Only `contradicted` changes delivery, so its precision is what
matters, and its sensitivity decides whether it can do the job the ledger
cannot: retire a rule the source itself overrides (Track 31, L4).

The ground truth is made, not judged. Memories are formed from a sample of
the operator's own interactive sessions as Track 33 did; then half of them,
drawn with seed 35, are falsified mechanically: a number in the memory is
changed, or a rule is negated. A falsified memory still carries its true
quote, so the quote check cannot catch it, and the pass has to read. Every
memory, falsified or not, is then verified against its window. Outputs
quote private work, so they go to OUT_DIR, never the repository; only
counts are reported.

Bars, written before the first call:
  V1  sensitivity: at least 70% of falsified memories are not confirmed
      (contradicted or unsupported). Below that the pass misses a wrong
      memory more often than it catches one.
  V2  precision of contradicted: at most 10% of unfalsified memories are
      marked contradicted. These are what the delivery gate hides, and a
      judge found 37% of unfalsified memories unsupported (Track 33), so
      the bar is on contradicted alone.
  V3  evidence stands: every contradicted verdict's evidence is a verbatim
      span of the window (the code enforces it; this counts how often the
      model needed the downgrade). Reported, no bar.
  V4  the operator's reading: for the first 20 verdicts of `contradicted`
      on unfalsified memories, written to review.jsonl, the operator agrees
      the source overrides the memory on at least 80%. Scored after the run,
      by hand; unscored until then.
Also counted, no bar: the share of falsified memories the pass called
contradicted (the model saw the fault) against unsupported (it only
withheld belief), and the proposed corrections that equal the original.

Usage: verify_probe.py OUT_DIR [--n 8] [--exclude PATH ...]
"""
import concurrent.futures
import glob
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
sys.path.insert(0, os.path.join(INTEGRATION, "hooks"))
import decisions as D   # noqa: E402
import sweep            # noqa: E402
import verify as V      # noqa: E402

WORKERS = 6
NEGATIONS = [(r"\bmust not\b", "must"), (r"\bmust\b", "must not"),
             (r"\bnever\b", "always"), (r"\balways\b", "never"),
             (r"\bshould not\b", "should"), (r"\bshould\b", "should not"),
             (r"\bbefore\b", "after"), (r"\bafter\b", "before"),
             (r"\benabled\b", "disabled"), (r"\bdisabled\b", "enabled"),
             (r"\btrue\b", "false"), (r"\bfalse\b", "true")]


def falsify(memory, rng):
    """A wrong version of the memory, or None if nothing mechanical applies.
    Numbers first: decision memories state values, and a changed value is
    the stalest kind of memory there is."""
    nums = list(re.finditer(r"(?<![\w.])(\d+)(?![\w.])", memory))
    if nums:
        m = rng.choice(nums)
        n = int(m.group(1))
        new = n + rng.choice([1, 2, 3, 5, 10]) if n < 2 else \
            max(0, n + rng.choice([-1, 1, 2, 5, 10]) * (1 if n > 1 else 1))
        if new == n:
            new = n + 1
        return memory[:m.start()] + str(new) + memory[m.end():]
    for pat, rep in NEGATIONS:
        if re.search(pat, memory, re.I):
            return re.sub(pat, rep, memory, count=1, flags=re.I)
    return None


def interactive(path):
    with open(path) as f:
        for n, line in enumerate(f):
            if n > 50:
                return False
            if '"entrypoint"' in line:
                return json.loads(line).get("entrypoint") == "cli"
    return False


def main():
    out = sys.argv[1]
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 8
    exclude = {os.path.abspath(a) for a in sys.argv[2:] if a.endswith(".jsonl")}
    os.makedirs(out, exist_ok=True)
    pool = []
    for path in sorted(glob.glob(os.path.expanduser(
            "~/.claude/projects/*/*.jsonl"))):
        if os.path.abspath(path) in exclude or not interactive(path):
            continue
        chat = D.chat_of(path)
        if len(chat) > D.CAP:
            pool.append((path, chat))
    rng = random.Random(35)
    sample = rng.sample(pool, min(n, len(pool)))
    print(f"interactive sessions over one window: {len(pool)}, sampled "
          f"{len(sample)}")

    jobs = []
    for s, (path, chat) in enumerate(sample):
        parts = D.windows(chat)
        skipped = max(0, len(parts) - D.MAX_WINDOWS)
        for w in range(skipped, len(parts)):
            jobs.append((s, w, parts[w]))
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
        formed = list(ex.map(
            lambda j: D.form_items(j[2], sweep.llm, sweep.parse_json), jobs))

    items = []
    for (s, w, part), ms in zip(jobs, formed):
        for m in ms:
            items.append({"session": s, "window": w, "text": part,
                          "content": m["content"], "quote": m["quote"],
                          "falsified": None})
    rng.shuffle(items)
    for it in items[: len(items) // 2]:
        it["falsified"] = falsify(it["content"], rng)
    print(f"windows {len(jobs)}, memories {len(items)}, falsifiable "
          f"{sum(1 for i in items if i['falsified'])}")

    def judge(it):
        memory = it["falsified"] or it["content"]
        return V.judge(it["text"], memory, it["quote"], sweep.llm,
                       sweep.parse_json)
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
        verdicts = list(ex.map(judge, items))

    rows = []
    for it, v in zip(items, verdicts):
        rows.append({**it, **v})
    with open(os.path.join(out, "verified.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    false_rows = [r for r in rows if r["falsified"]]
    true_rows = [r for r in rows if not r["falsified"]]
    caught = [r for r in false_rows if r["verdict"] != "confirmed"]
    seen_fault = [r for r in false_rows if r["verdict"] == "contradicted"]
    wrong_contra = [r for r in true_rows if r["verdict"] == "contradicted"]
    restored = [r for r in false_rows
                if r.get("correction") and " ".join(r["correction"].split())
                == " ".join(r["content"].split())]
    nf, nt = max(1, len(false_rows)), max(1, len(true_rows))
    print(f"V1 {'PASS' if len(caught) / nf >= 0.7 else 'FAIL'} falsified not "
          f"confirmed {len(caught)}/{len(false_rows)} = {len(caught) / nf:.0%}"
          f" (contradicted {len(seen_fault)}, unsupported "
          f"{len(caught) - len(seen_fault)})")
    print(f"V2 {'PASS' if len(wrong_contra) / nt <= 0.1 else 'FAIL'} "
          f"unfalsified marked contradicted {len(wrong_contra)}/"
          f"{len(true_rows)} = {len(wrong_contra) / nt:.0%}")
    byv = {}
    for r in true_rows:
        byv[r["verdict"]] = byv.get(r["verdict"], 0) + 1
    print(f"   unfalsified verdicts: {byv}")
    print(f"corrections restoring the original: {len(restored)}/"
          f"{len(false_rows)}")
    with open(os.path.join(out, "review.jsonl"), "w") as f:
        for r in wrong_contra[:20]:
            f.write(json.dumps({"content": r["content"],
                                "evidence": r["evidence"],
                                "window": r["text"], "operator": None}) + "\n")
    print(f"V4: {min(20, len(wrong_contra))} contradicted verdicts on "
          f"unfalsified memories written to review.jsonl for the operator")


if __name__ == "__main__":
    sys.exit(main())
