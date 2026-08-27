#!/usr/bin/env python3
"""Track 17 formation pass (REVALIDATION.md): mine Phase A's haiku
transcripts. Three outputs, printed for the consolidation review and
written to track17/mined-candidates.json:

  1. T17-P1 gate data: fired condition classes per control session.
  2. Deterministic candidates: session_end.corrections replayed.
  3. v3 structured extraction (haiku) over causal prose blocks, with the
     provenance rule applied — an extracted action is kept only if some
     Phase A command actually ran it (token overlap); otherwise the
     action is dropped and the condition kept.

Usage: mine_track17.py [--jobs 4]
"""
import argparse
import concurrent.futures as cf
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formation_study as F      # noqa: E402
import harvest_replay as h       # noqa: E402  (explanations, LOOSE)
import run_track8 as t8          # noqa: E402  (parse_json)
import run_track16 as t16        # noqa: E402  (PROMPT_V3)

INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, os.path.join(INTEGRATION, "hooks"))
import session_end as se         # noqa: E402  (corrections, fired_classes)

OUT = os.path.join(HERE, "track17", "mined-candidates.json")
MAX_BLOCKS_PER_SESSION = 3


def phase_a_sessions():
    for _run, label_task, _arm, tp in F.sessions(["track17"]):
        iid, phasearm = label_task.rsplit("-", 1)
        if phasearm == "Anone":
            yield iid, tp


def ask_v3(repo, block, cwd):
    import subprocess
    prompt = t16.PROMPT_V3.format(repo=repo, block=block[:t8.MAX_BLOCK])
    env = {**os.environ, "RFM_HOOKS_OFF": "1"}
    try:
        r = subprocess.run(["claude", "-p", "--model", "haiku", prompt],
                           cwd=cwd, env=env, capture_output=True, text=True,
                           timeout=180)
        return t8.parse_json((r.stdout or "").strip())
    except subprocess.TimeoutExpired:
        return None


def action_evidenced(action, all_cmds):
    """Provenance: did any Phase A command actually run this action?
    Token-overlap match in the miner's own spirit (session_end.acted_on
    uses 0.6; the bar here is the same)."""
    at = se.tokens(action)
    if not at:
        return False
    return any(len(at & se.tokens(c)) / len(at) >= 0.6 for c in all_cmds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()

    sessions = list(phase_a_sessions())
    print(f"phase A transcripts: {len(sessions)}")
    fired_by, corrections_by, blocks = {}, {}, []
    all_cmds = []
    for iid, tp in sessions:
        evs = F.events_of(tp)
        all_cmds.extend(e.cmd for e in evs if e.cmd)
        fired_by[iid] = sorted(se.fired_classes(evs))
        corrections_by[iid] = se.corrections(evs)
        for b in h.explanations(tp, 200, h.LOOSE)[:MAX_BLOCKS_PER_SESSION]:
            blocks.append({"iid": iid, "block": b})

    print("\n== T17-P1 gate: fired condition classes per control session ==")
    live = 0
    for iid in sorted(fired_by):
        print(f"  {iid[-9:]}: {fired_by[iid] or '-'}")
        live += bool(fired_by[iid])
    print(f"  -> classes fired in {live}/{len(fired_by)} sessions "
          f"(gate: >= 4)")

    print(f"\n== deterministic miner: "
          f"{sum(len(v) for v in corrections_by.values())} candidates ==")
    for iid, cs in corrections_by.items():
        for c in cs:
            print(f"  [{iid[-9:]}] {c['error']}: `{c['failed'][:60]}` -> "
                  f"`{c['fixed'][:60]}`")

    print(f"\n== v3 extraction over {len(blocks)} prose blocks ==")
    cwd = os.path.join(HERE, "track16", "sandbox")
    extracted = []
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for row, v in zip(blocks, ex.map(
                lambda r: ask_v3("xarray", r["block"], cwd), blocks)):
            if not v or not v.get("store"):
                continue
            cond = (v.get("condition_class") or "").strip()
            if not cond:
                continue                     # condition is mandatory
            action = (v.get("action") or "").strip()
            provenance = "quoted" if action and action_evidenced(
                action, all_cmds) else ("dropped" if action else "none")
            if provenance == "dropped":
                action = ""
            extracted.append({"iid": row["iid"], "condition_class": cond,
                              "scope": v.get("scope", ""),
                              "era": v.get("era", ""),
                              "action": action,
                              "action_provenance": provenance,
                              "evidence": v.get("evidence", "")})
            print(f"  [{row['iid'][-9:]}] {cond[:40]} | "
                  f"action({provenance}): {action[:60]}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"fired_by_session": fired_by,
                   "deterministic": {k: v for k, v in corrections_by.items()
                                     if v},
                   "extracted": extracted}, f, indent=2)
        f.write("\n")
    print(f"\nwrote {OUT} — consolidate to <= 6 facts, review, commit "
          f"store-track17.json before Phase B")


if __name__ == "__main__":
    main()
