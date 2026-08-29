#!/usr/bin/env python3
"""Track 21a — judge adjudication of Track 20 (REVALIDATION.md). No new
sessions: parses full [ANSWER k] lines from the committed Track 20
session logs, adjudicates each against the expected answer with a haiku
judge (arm-blind), and scores the registered bars.

Usage: score_track21a.py [--jobs 8]
"""
import argparse
import concurrent.futures as cf
import glob
import json
import math
import os
import re
import subprocess
import sys
import threading

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "track20")
MT = os.path.join(HERE, "..", "data", "memtrack", "Memtrak")
OUT = os.path.join(HERE, "track21a")
LOCK = threading.Lock()

JUDGE = """Grade one short answer from a software-team assistant.

QUESTION: {q}
EXPECTED ANSWER: {expected}
GIVEN ANSWER: {given}

Is the given answer correct — does it convey the expected answer, allowing
for phrasing, formatting, extra words, or equivalent values? Reply JSON
only: {{"correct": true or false}}"""


def instances():
    out = {}
    for f in sorted(glob.glob(os.path.join(MT, "test_configs", "*.yaml"))):
        c = yaml.safe_load(open(f))
        b = c.get("benchmark") or {}
        if b.get("questions"):
            iid = os.path.basename(f)[:-5].replace("config_", "")
            out[iid] = {"questions": b["questions"],
                        "answers": b.get("expected_answers") or []}
    return out


def parse_answers(log_path):
    if not os.path.exists(log_path):
        return {}
    out = {}
    for m in re.finditer(r"\[ANSWER (\d+)\]\s*(.+)", open(log_path).read()):
        out[int(m.group(1))] = m.group(2).strip()
    return out


def judge(q, expected, given):
    if not given:
        return False
    try:
        r = subprocess.run(
            ["claude", "-p", "--model", "haiku",
             JUDGE.format(q=q[:300], expected=str(expected)[:200],
                          given=given[:300])],
            env={**os.environ, "RFM_HOOKS_OFF": "1"},
            capture_output=True, text=True, timeout=120)
        mm = re.search(r"\{.*\}", r.stdout or "", re.S)
        return bool(json.loads(mm.group(0)).get("correct")) if mm else False
    except Exception:
        return False


def sign_p(wins, decided):
    return sum(math.comb(decided, k) for k in range(wins, decided + 1)) \
        / 2 ** decided if decided else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    inst = instances()

    # results.jsonl gives which instances have both arms + exact flags
    by = {}
    for l in open(os.path.join(DIR, "results.jsonl")):
        r = json.loads(l)
        by.setdefault(r["id"], {})[r["arm"]] = r
    pairs = {k: v for k, v in by.items() if len(v) == 2 and k in inst}

    tasks = []
    for iid in pairs:
        for arm in ("control", "rfm"):
            ans = parse_answers(os.path.join(DIR, "sessions",
                                             f"{iid}.{arm}.log"))
            for k, expected in enumerate(inst[iid]["answers"], 1):
                tasks.append((iid, arm, k, inst[iid]["questions"][k - 1]
                              if k - 1 < len(inst[iid]["questions"]) else "",
                              expected, ans.get(k, "")))

    path = os.path.join(OUT, "judged.jsonl")
    done = set()
    if os.path.exists(path):
        for l in open(path):
            r = json.loads(l)
            done.add((r["id"], r["arm"], r["q"]))
    todo = [t for t in tasks if (t[0], t[1], t[2]) not in done]
    print(f"{len(tasks)} answers, {len(todo)} to judge", flush=True)
    sink = open(path, "a")

    def work(t):
        iid, arm, k, q, expected, given = t
        return {"id": iid, "arm": arm, "q": k,
                "judged": judge(q, expected, given), "given": given[:80]}

    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for i, rec in enumerate(ex.map(work, todo), 1):
            with LOCK:
                sink.write(json.dumps(rec) + "\n")
                sink.flush()
            if i % 40 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
    sink.close()

    rows = [json.loads(l) for l in open(path)]
    jc = {"control": 0, "rfm": 0}
    per_inst = {}
    for r in rows:
        jc[r["arm"]] += r["judged"]
        per_inst.setdefault(r["id"], {"control": 0, "rfm": 0})
        per_inst[r["id"]][r["arm"]] += r["judged"]
    ec = {arm: sum(v[arm]["exact_correct"] for v in pairs.values())
          for arm in ("control", "rfm")}

    deltas = [per_inst[i]["rfm"] - per_inst[i]["control"] for i in per_inst]
    rfm_up = sum(1 for d in deltas if d > 0)
    ctl_up = sum(1 for d in deltas if d < 0)

    print(f"\nexact-match:  control {ec['control']}  rfm {ec['rfm']}")
    print(f"judged:       control {jc['control']}  rfm {jc['rfm']}  "
          f"(of {len(rows)//2} questions/arm)")
    print(f"per-instance: rfm higher on {rfm_up}, control higher on "
          f"{ctl_up}, tied on {len(deltas)-rfm_up-ctl_up}")

    print("\nREGISTERED — Track 21a")
    p1 = jc["control"] >= ec["control"] and jc["rfm"] >= ec["rfm"]
    print(f"  T21a-P1 adjudication lifts both arms: "
          f"{'PASS' if p1 else 'FAIL'}")
    p = sign_p(max(rfm_up, ctl_up), rfm_up + ctl_up)
    benefit = jc["rfm"] > jc["control"] and rfm_up > ctl_up and p <= 0.10
    print(f"  T21a-P2 benefit (rfm>control, sign p<=0.10): "
          f"{'PASS' if benefit else 'PARITY/FAIL'} — "
          f"rfm {jc['rfm']} vs control {jc['control']}, "
          f"per-instance {rfm_up}/{ctl_up}, sign p={p:.3f}")
    # P3 needs exact-hit subset agreement
    exact_hits = {(json.loads(l)["id"], json.loads(l)["arm"], i + 1)
                  for l in open(os.path.join(DIR, "results.jsonl"))
                  for i, ok in enumerate(json.loads(l).get("per_q", []))
                  if ok}
    agree = [r for r in rows if (r["id"], r["arm"], r["q"]) in exact_hits]
    agree_rate = (sum(1 for r in agree if r["judged"]) / len(agree)
                  if agree else 1.0)
    print(f"  T21a-P3 judge agrees with exact hits >=90%: "
          f"{'PASS' if agree_rate >= 0.90 else 'FAIL'} — "
          f"{agree_rate:.2f} on {len(agree)} exact hits")


if __name__ == "__main__":
    main()
