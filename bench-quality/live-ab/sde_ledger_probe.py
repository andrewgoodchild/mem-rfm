#!/usr/bin/env python3
"""Track 31 — can the ledger see decision memories? Free replay: no sessions,
no LLM calls.

Tracks 29 and 30 ran with flat priors and nothing wrote an outcome, so they say
nothing about the ledger. Their transcripts survive. This replays the shipped
session_end inference over every session that was shown formed memories, as if
it had been installed: transcripts.read, rehydrate from the seed store,
infer_outcomes. record_outcomes' condition gate is applied to the +1s.

Bars, written before this script first ran:
  L1  coverage: on at least 50% of runs shown the task's own memory, that memory
      earns an outcome. Below that the ledger is blind to decision memories,
      and a paid repeated-task run would measure flat priors again.
  L2  attribution: at least 80% of all outcomes land on the task's own memories.
      Below that the ledger credits bystanders.
  L3  sign: mean corrections are lower on runs where the own memory earned +1
      than on runs shown it where it earned nothing. An outcome that does not
      track the correction count cannot rank by it.
Added after L1 to L3 were read, before any amended transcript was:
  L4  demotion: on the 6 amended tasks, on at least a third of memory runs shown
      the stale memory, it earns -1. Demoting a wrong memory is the ledger's
      own job, and these are the venue's only wrong memories.
Prediction, no bar: L1 fails. Decision memories state rules, not commands, and
acted_on credits only a quoted span in a command or a token share.

Also printed, no bar: the ledger's ceiling. Priors can only reorder what cosine
already retrieves, so its most is the runs that did not get their own memory
first, and what those runs cost in corrections.

Usage: sde_ledger_probe.py [PROJECTS_DIR]
"""
import collections
import glob
import json
import os
import shutil
import sqlite3
import statistics
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
TMP = tempfile.mkdtemp(prefix="rfm-track31-")
SEED = os.path.join(TMP, "seed.db")
shutil.copy(os.path.join(HERE, "track29", "seed.db"), SEED)
os.environ.update(RFM_MEMORY_DB=SEED, RFM_LOG="0")
sys.path.insert(0, INTEGRATION)
sys.path.insert(0, os.path.join(INTEGRATION, "hooks"))
import session_end as E   # noqa: E402
import transcripts        # noqa: E402

RUNS = (("track29", "memory"), ("track30", "flat"))


def amended(projects, source, condition):
    runs = [json.loads(line) for line in open(
        os.path.join(HERE, "track30-amended", "results.jsonl"))]
    shown, bad, good, other = 0, 0, 0, 0
    for r in runs:
        if r["arm"] != "memory":
            continue
        found = glob.glob(os.path.join(projects, "*", r["session"] + ".jsonl"))
        sess = transcripts.read(found[0], prose=False)
        mems = E.rehydrate(dict(sess.exposures))
        stale = f"{r['task']}/stale"
        ids = {m for m in mems if source.get(m) == stale}
        shown += bool(ids)
        values = [o["outcome"] for o in E.infer_outcomes(mems, sess.events)
                  if o["id"] in ids]
        bad += -1.0 in values
        good += 1.0 in values
        other += not values and bool(ids)
    print(f"L4 {'PASS' if shown and bad / shown >= 1 / 3 else 'FAIL'} demotion: "
          f"stale shown on {shown} runs, -1 on {bad}, +1 on {good}, "
          f"nothing on {other}")


def main():
    projects = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.expanduser("~/.claude/projects")
    con = sqlite3.connect(SEED)
    source = dict(con.execute("SELECT id, source FROM rfm_memories"))
    condition = dict(con.execute("SELECT id, condition_class FROM rfm_memories"))
    con.close()
    rows, missing = [], 0
    for track, arm in RUNS:
        for line in open(os.path.join(HERE, track, "results.jsonl")):
            r = json.loads(line)
            if r["arm"] != arm:
                continue
            found = glob.glob(os.path.join(projects, "*", r["session"] + ".jsonl"))
            if not found:
                missing += 1
                continue
            sess = transcripts.read(found[0], prose=False)
            mems = E.rehydrate(dict(sess.exposures))
            fired = E.fired_classes(sess.events)
            outcomes = []
            for o in E.infer_outcomes(mems, sess.events):
                classes = [c for c in (condition.get(o["id"]) or "").split(",")
                           if c]
                if o["outcome"] > 0 and classes and not set(classes) & fired:
                    continue
                outcomes.append(o)
            own = f"{r['task']}/gold"
            rows.append({"arm": arm, "task": r["task"],
                         "corrections": r["corrections"],
                         "first_own": r["delivered"]["first_own"],
                         "shown": len(mems),
                         "shown_own": any(source.get(m) == own for m in mems),
                         "own": [o["outcome"] for o in outcomes
                                 if source.get(o["id"]) == own],
                         "other": [source.get(o["id"]) for o in outcomes
                                   if source.get(o["id"]) != own],
                         "cmds": [o["cmd"] for o in outcomes]})
    print(f"sessions replayed {len(rows)}, transcripts missing {missing}, "
          f"events {'read' if rows else 'none'}, "
          f"memories shown per run {statistics.mean(r['shown'] for r in rows):.1f}")

    shown = [r for r in rows if r["shown_own"]]
    earned = [r for r in shown if r["own"]]
    cover = len(earned) / len(shown)
    n_own = sum(len(r["own"]) for r in rows)
    n_other = sum(len(r["other"]) for r in rows)
    attrib = n_own / (n_own + n_other) if n_own + n_other else 0.0
    plus = [r["corrections"] for r in shown if 1.0 in r["own"]]
    idle = [r["corrections"] for r in shown if not r["own"]]
    signs = collections.Counter(v for r in rows for v in r["own"])
    print(f"shown own {len(shown)}/{len(rows)}, own outcomes {dict(signs)}, "
          f"other outcomes {n_other}")
    print(f"L1 {'PASS' if cover >= 0.5 else 'FAIL'} coverage "
          f"{len(earned)}/{len(shown)} = {cover:.0%}")
    print(f"L2 {'PASS' if attrib >= 0.8 else 'FAIL'} attribution "
          f"{n_own}/{n_own + n_other} = {attrib:.0%}")
    if plus and idle:
        a, b = statistics.mean(plus), statistics.mean(idle)
        print(f"L3 {'PASS' if a < b else 'FAIL'} corrections with +1 {a:.2f} "
              f"(n={len(plus)}), with nothing {b:.2f} (n={len(idle)})")
    else:
        print(f"L3 FAIL, no comparison: +1 runs {len(plus)}, idle {len(idle)}")
    for cmd in [c for r in rows for c in r["cmds"]][:12]:
        print("  credited:", cmd[:110])

    amended(projects, source, condition)
    print("ceiling, no bar:")
    for arm in ("flat", "memory"):
        pool = [r for r in rows if r["arm"] == arm]
        for label, part in (("own first", [r for r in pool if r["first_own"]]),
                            ("not first", [r for r in pool
                                           if not r["first_own"]])):
            if part:
                print(f"  {arm:6} {label}: {len(part):3} runs, corrections "
                      f"{statistics.mean(r['corrections'] for r in part):.2f}")
        best = sum(r["corrections"] for r in pool if not r["first_own"])
        print(f"  {arm:6} corrections on those runs: {best} of "
              f"{sum(r['corrections'] for r in pool)}")
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
