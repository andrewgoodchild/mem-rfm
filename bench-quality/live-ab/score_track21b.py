#!/usr/bin/env python3
"""Score Track 21b (per-turn precomputed judged retrieval) against its
registered bars. Judge-adjudicated (the 21a judge), arm-blind.

Usage: score_track21b.py [--jobs 8]
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
DIR = os.path.join(HERE, "track21b")
MT = os.path.join(HERE, "..", "data", "memtrack", "Memtrak")
JUDGE_MAP = os.path.join(DIR, "judged_map.json")
LOCK = threading.Lock()

JUDGE = """Grade one short answer from a software-team assistant.
QUESTION: {q}
EXPECTED: {expected}
GIVEN: {given}
Is the given answer correct — does it convey the expected answer, allowing
for phrasing/formatting/equivalent values? Reply JSON only:
{{"correct": true or false}}"""


def instances():
    out = {}
    for f in sorted(glob.glob(os.path.join(MT, "test_configs", "*.yaml"))):
        c = yaml.safe_load(open(f))
        b = c.get("benchmark") or {}
        if b.get("questions"):
            out[os.path.basename(f)[:-5].replace("config_", "")] = {
                "questions": b["questions"],
                "answers": b.get("expected_answers") or []}
    return out


def judge(q, expected, given):
    if not given:
        return False
    try:
        r = subprocess.run(
            ["claude", "-p", JUDGE.format(q=q[:300], expected=str(expected)[:200],
                                          given=given[:300]),
             "--model", "haiku"],
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
    inst = instances()
    res = {}
    for l in open(os.path.join(DIR, "results.jsonl")):
        r = json.loads(l)
        res.setdefault(r["id"], {})[r["arm"]] = r
    pairs = {k: v for k, v in res.items() if len(v) == 2 and k in inst}
    judged_map = json.load(open(JUDGE_MAP)) if os.path.exists(JUDGE_MAP) else {}

    def given_of(iid, arm):
        p = os.path.join(DIR, "sessions", f"{iid}.{arm}.json")
        return json.load(open(p))["given"] if os.path.exists(p) else \
            pairs[iid][arm].get("given", [])

    tasks = []
    for iid in pairs:
        for arm in ("control", "perturn"):
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
    jc = {"control": 0, "perturn": 0}
    per = {}
    for r in rows:
        jc[r["arm"]] += r["judged"]
        per.setdefault(r["id"], {"control": 0, "perturn": 0})
        per[r["id"]][r["arm"]] += r["judged"]
    deltas = [per[i]["perturn"] - per[i]["control"] for i in per]
    up = sum(1 for d in deltas if d > 0)
    dn = sum(1 for d in deltas if d < 0)

    # delivery: from judged_map + results delivered field
    delivered = sum(v["perturn"].get("delivered", 0) for v in pairs.values())
    total_q = sum(v["perturn"]["nq"] for v in pairs.values())
    cw = sum(v["control"]["wall_s"] for v in pairs.values())
    pw = sum(v["perturn"]["wall_s"] for v in pairs.values())

    print(f"\ncomplete pairs {len(pairs)}")
    print(f"judged correct: control {jc['control']}, perturn {jc['perturn']} "
          f"of {len(rows)//2}")
    print(f"per-instance: perturn up {up}, control up {dn}, "
          f"tied {len(deltas)-up-dn}")
    print(f"delivery: {delivered}/{total_q} question-turns "
          f"({100*delivered//max(total_q,1)}%)")
    print(f"wall: control {cw}s, perturn {pw}s "
          f"({100*(pw-cw)/max(cw,1):+.1f}%)")

    print("\nREGISTERED — Track 21b")
    dr = 100 * delivered // max(total_q, 1)
    print(f"  T21b-P1 delivery 40-100%: "
          f"{'PASS' if 40 <= dr <= 100 else 'FAIL'} — {dr}%")
    p = sign_p(up, up + dn)
    print(f"  T21b-P2 benefit (perturn>control, sign p<=0.05): "
          f"{'PASS' if jc['perturn'] > jc['control'] and up > dn and p <= 0.05 else 'PARITY/FAIL'}"
          f" — perturn {jc['perturn']} vs control {jc['control']}, "
          f"{up}/{dn}, p={p:.3f}")
    print(f"  T21b-P3 wall (perturn within +15%): "
          f"{'PASS' if pw <= 1.15*max(cw,1) else 'FAIL'} — "
          f"{100*(pw-cw)/max(cw,1):+.1f}%")


if __name__ == "__main__":
    main()
