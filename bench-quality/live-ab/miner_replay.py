#!/usr/bin/env python3
"""Offline formation-miner replay: run alternative mining strategies and
the outcome-inference path over a pilot's real session transcripts.
No LLM, no DB writes — reports what each strategy WOULD have staged and
which explicitly-reported outcomes inference WOULD have recovered. This
is the harness that justified the pilot-3 interventions; keep using it to
evaluate miner changes against recorded corpora before any live run.

Strategies:
  committed   corrections() exactly as session_end.py ships
  narrow      the pre-pilot-2 FAILURE class (ablation: what the original
              miner missed — on pilot 2 it missed the run's top-value
              gotcha, the era-pin stub workaround)
  wide        any CamelCase *Error + traceback (the rejected direction:
              on pilot 2 it stages ordinary test failures — the agent's
              own bug-fixing — as gotchas)
  frequency   successful invocations recurring across >=4 sessions.
              Verdict on pilot 2: confirmatory, not formative — the only
              recurring invocation recurred in the rfm arm BECAUSE
              injection suggested it; the control stream had no
              recurrence to mine. Kept for future corpora.
  inference   in_play + rehydrate + infer_outcomes vs the explicit
              memory_feedback calls in the pilot's committed log. The
              misses to EXPECT are relevance judgments (helped=false on
              an un-acted-on memory, partial scores) — those are the
              trailer's job, not inference's.

Usage: python3 miner_replay.py [pilot-dir]      (default: pilot2/)
Needs: <pilot-dir>/rfm-log.jsonl, <pilot-dir>/rfm-memory.db, and the
ab/ab_sessions.jsonl sidecar rows whose transcripts still exist locally.
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PILOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                        else os.path.join(HERE, "pilot2"))
os.environ["RFM_LOG"] = "0"      # session_end reads these at import
os.environ["RFM_MEMORY_DB"] = os.path.join(PILOT, "rfm-memory.db")
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "integrations", "claude-code", "hooks"))
sys.path.insert(0, os.path.join(REPO, "integrations", "claude-code"))
sys.path.insert(0, REPO)
import session_end as se  # noqa: E402

AB = os.path.join(REPO, "integrations", "claude-code", "ab")

NARROW = re.compile(
    r"command not found|no such file or directory|permission denied|"
    r"unrecognized option|invalid option|is not recognized|"
    r"modulenotfounderror|importerror|cannot find module|"
    r"unable to load|not a loadable|undefined symbol|"
    r"no matches found|bad interpreter", re.I)
WIDE = re.compile(NARROW.pattern +
                  r"|traceback \(most recent call last\)"
                  r"|\b[A-Z][a-zA-Z]{2,}Error\b", re.I)


def mine_with(events, failure):
    committed = se.FAILURE
    se.FAILURE = failure
    try:
        return se.corrections(events)
    finally:
        se.FAILURE = committed


def norm_invocation(cmd):
    head = cmd.split("<<")[0].split("\n")[0].strip()
    toks = head.split()
    envs = [t.split("=")[0] + "=*" for t in toks
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t)]
    rest = [t for t in toks if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t)]
    return " ".join(envs + rest[:3]) if rest else None


def main():
    prefix = os.path.basename(PILOT) + "-"
    ablog = {r["ab_session"]: r for r in
             (json.loads(l) for l in open(os.path.join(AB, "ab_log.jsonl")))
             if str(r.get("label", "")).startswith(prefix)}
    sessions = []
    for line in open(os.path.join(AB, "ab_sessions.jsonl")):
        s = json.loads(line)
        meta = ablog.get(s["ab_session"])
        if not meta or not os.path.exists(s.get("transcript_path") or ""):
            continue
        sessions.append({
            "arm": s["arm"], "sid8": (s["session_id"] or "?")[:8],
            "label": meta["label"].replace(prefix, ""),
            "path": s["transcript_path"]})
    if not sessions:
        sys.exit(f"no {prefix}* sessions with surviving transcripts")

    # Explicit-feedback ground truth from the committed pilot log; feedback
    # lines carry no session field, so attribute to the preceding injection.
    explicit, cur = collections.defaultdict(list), None
    for line in open(os.path.join(PILOT, "rfm-log.jsonl")):
        r = json.loads(line)
        if r["op"] == "injection":
            cur = r["session"]
        elif r["op"] == "feedback" and cur:
            explicit[cur].append((r["id"], r["outcome"]))

    cand = collections.defaultdict(list)
    counts = collections.Counter()
    inference_rows = []
    for s in sessions:
        records = se._parse_transcript(s["path"])
        events = se.load_events(records)
        for key, failure in (("committed", se.FAILURE), ("narrow", NARROW),
                             ("wide", WIDE)):
            for c in mine_with(events, failure):
                cand[key].append((s["arm"], s["label"], c))
        for inv in {norm_invocation(e.cmd) for e in events
                    if e.got and not e.is_err and norm_invocation(e.cmd)}:
            counts[(s["arm"], inv)] += 1
        if s["arm"] == "rfm":
            mems = se.rehydrate(se.in_play_memories(records))
            inferred = se.infer_outcomes(mems, events)
            inference_rows.append(
                (s["label"], {(o["id"], o["outcome"]) for o in inferred},
                 set(explicit.get(s["sid8"], []))))

    print(f"{len(sessions)} session(s) from {os.path.basename(PILOT)}\n")
    for key in ("committed", "narrow", "wide"):
        print(f"=== {key}: {len(cand[key])} candidate(s)")
        for arm, label, c in cand[key]:
            print(f"  [{arm}:{label}] ({c['error']})")
            print(f"     FAIL {c['failed'][:110]}")
            print(f"     FIX  {c['fixed'][:110]}")
        print()

    print("=== frequency: successful invocations recurring >=4 sessions")
    for (arm, inv), n in counts.most_common():
        if n >= 4 and re.search(r"=\*|/tmp/|venv", inv):
            print(f"  [{arm}] x{n}  {inv[:110]}")
    print()

    print("=== inference coverage vs explicit feedback (rfm sessions)")
    tp = fn = extra = flip = 0
    for label, inf, exp in inference_rows:
        for i, o in sorted(exp):
            got = next((io for ii, io in inf if ii == i), None)
            if got is None:
                fn += 1
                tag = "MISSED"
            elif (got > 0) == (o > 0) or o == 0:
                tp += 1
                tag = "recovered"
            else:
                flip += 1
                tag = f"SIGN FLIP (inf {got:+})"
            print(f"  [{label}] explicit id={i} {o:+.1f} -> {tag}")
        for i, o in sorted(inf):
            if i not in {ii for ii, _ in exp}:
                extra += 1
                print(f"  [{label}] inferred-only id={i} {o:+.1f}")
    print(f"\n  explicit: {tp + fn + flip}, recovered: {tp}, missed: {fn}, "
          f"sign flips: {flip}, inference-only: {extra}")


if __name__ == "__main__":
    main()
