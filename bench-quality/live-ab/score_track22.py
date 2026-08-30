#!/usr/bin/env python3
"""Score Track 22 (substrate removal) — judge-adjudicated, arm-blind.
Usage: score_track22.py [--jobs 8]
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
_B, _M = "6", "claude-fable-5"
for _i, _a in enumerate(sys.argv):
    if _a == "--budget":
        _B = sys.argv[_i + 1]
    if _a == "--model":
        _M = sys.argv[_i + 1]
_MT = "" if _M == "claude-fable-5" else "-" + _M.replace(
    "claude-", "").split("-")[0]
DIR = os.path.join(HERE, "track22" + ("" if _B == "6" else f"-b{_B}") + _MT)
MT = os.path.join(HERE, "..", "data", "memtrack", "Memtrak")
LOCK = threading.Lock()

JUDGE = """Grade one short answer from a software-team assistant.
QUESTION: {q}
EXPECTED: {expected}
GIVEN: {given}
Correct if the given answer conveys the expected (allow phrasing/format).
Reply JSON only: {{"correct": true or false}}"""


def instances():
    out = {}
    for f in sorted(glob.glob(os.path.join(MT, "test_configs", "*.yaml"))):
        c = yaml.safe_load(open(f))
        b = c.get("benchmark") or {}
        if b.get("questions"):
            out[os.path.basename(f)[:-5].replace("config_", "")] = {
                "questions": b["questions"], "answers": b.get("expected_answers") or []}
    return out


def judge(q, expected, given):
    if not given:
        return False
    try:
        r = subprocess.run(
            ["claude", "-p", JUDGE.format(q=q[:300], expected=str(expected)[:200],
                                          given=given[:300]), "--model", "haiku"],
            env={**os.environ, "RFM_HOOKS_OFF": "1"},
            capture_output=True, text=True, timeout=120)
        mm = re.search(r"\{.*\}", r.stdout or "", re.S)
        return bool(json.loads(mm.group(0)).get("correct")) if mm else False
    except Exception:
        return False


def sign_p(w, n):
    return sum(math.comb(n, k) for k in range(w, n + 1)) / 2 ** n if n else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    inst = instances()
    by = {}
    for l in open(os.path.join(DIR, "results.jsonl")):
        r = json.loads(l)
        by.setdefault(r["id"], {})[r["arm"]] = r
    pairs = {k: v for k, v in by.items() if len(v) == 2 and k in inst}

    def given_of(iid, arm):
        p = os.path.join(DIR, "sessions", f"{iid}.{arm}.json")
        return json.load(open(p))["given"] if os.path.exists(p) else []

    tasks = []
    for iid in pairs:
        for arm in ("control", "rfm"):
            g = given_of(iid, arm)
            for k, exp in enumerate(inst[iid]["answers"]):
                q = inst[iid]["questions"][k] if k < len(inst[iid]["questions"]) else ""
                tasks.append((iid, arm, k, q, exp, g[k] if k < len(g) else ""))

    path = os.path.join(DIR, "judged.jsonl")
    done = set()
    if os.path.exists(path):
        for l in open(path):
            r = json.loads(l)
            done.add((r["id"], r["arm"], r["q"]))
    todo = [t for t in tasks if (t[0], t[1], t[2]) not in done]
    print(f"{len(tasks)} answers, {len(todo)} to judge")
    sink = open(path, "a")
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for rec in ex.map(lambda t: {"id": t[0], "arm": t[1], "q": t[2],
                                     "judged": judge(t[3], t[4], t[5])}, todo):
            with LOCK:
                sink.write(json.dumps(rec) + "\n")
                sink.flush()
    sink.close()

    rows = [json.loads(l) for l in open(path)]
    jc = {"control": 0, "rfm": 0}
    per = {}
    for r in rows:
        jc[r["arm"]] += r["judged"]
        per.setdefault(r["id"], {"control": 0, "rfm": 0})[r["arm"]] += r["judged"]
    deltas = [per[i]["rfm"] - per[i]["control"] for i in per]
    up = sum(1 for d in deltas if d > 0)
    dn = sum(1 for d in deltas if d < 0)
    ct = sum(v["control"].get("turns") or 0 for v in pairs.values())
    rt = sum(v["rfm"].get("turns") or 0 for v in pairs.values())

    print(f"\ncomplete pairs {len(pairs)}")
    print(f"judged correct: control {jc['control']}, rfm {jc['rfm']} "
          f"of {len(rows)//2}")
    print(f"per-instance: rfm up {up}, control up {dn}, tied {len(deltas)-up-dn}")
    print(f"query turns: control {ct}, rfm {rt} "
          f"({100*(rt-ct)/max(ct,1):+.0f}%)")
    p = sign_p(up, up + dn)
    print("\nREGISTERED — Track 22")
    print("  T22-P1 enforcement: PASS (probe, REVALIDATION.md)")
    print(f"  T22-P2 benefit (rfm>control, sign p<=0.05): "
          f"{'PASS' if jc['rfm'] > jc['control'] and up > dn and p <= 0.05 else 'PARITY/FAIL'}"
          f" — rfm {jc['rfm']} vs control {jc['control']}, {up}/{dn}, p={p:.3f}")


if __name__ == "__main__":
    main()
