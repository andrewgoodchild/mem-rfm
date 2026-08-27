#!/usr/bin/env python3
"""The open-throttle sweep (DESIGN_NOTES 2026-08-28): continuous,
LLM-judged memory formation and outcome scoring over session
transcripts. No manual gate — quarantine (two independent sightings)
replaces review, a cap replaces pruning discretion, and the outcome
judge is asked the CONDITIONED question so it cannot rebuild the C4
fossil.

Modes:
  sweep.py                     cron/hook mode: new transcripts since the
                               last sweep (state file beside the DB)
  sweep.py --replay LISTFILE   replay an ordered list of transcript
                               paths (one per line); no state

Config: sweep-config.json beside this script (model, instruction,
ontology, thresholds, cap). DB: $RFM_MEMORY_DB.
"""
import argparse
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "hooks"))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import session_end as se  # noqa: E402  (parse, events, corrections, acted_on)
import rfm                # noqa: E402

CONFIG = json.load(open(os.path.join(HERE, "sweep-config.json")))
DB_PATH = os.path.expanduser(
    os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))
STATE = os.path.join(os.path.dirname(DB_PATH), "sweep-state.json")
LOG = os.path.join(os.path.dirname(DB_PATH), "rfm-log.jsonl")


def _log(fields):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write(json.dumps({"t": round(time.time(), 3), **fields}) + "\n")
    except OSError:
        pass


def llm(prompt):
    try:
        r = subprocess.run(["claude", "-p", "--model", CONFIG["model"], prompt],
                           env={**os.environ, "RFM_HOOKS_OFF": "1"},
                           cwd=os.path.dirname(DB_PATH),
                           capture_output=True, text=True, timeout=180)
        return (r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return ""


def parse_json(text):
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    m = re.search(r"[\[{].*[\]}]", t, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


EXTRACT = """{instruction}

The condition ontology for this deployment (name the closest, or coin a
concrete new one): {ontology}

Below is material from one coding session: the agent's explanatory prose
and any failed->fixed command pairs. Most of it is about the specific
task and should be IGNORED — per-task lessons do not transfer. Extract
at most {max_per_session} durable memories, each standing alone for
someone who never saw this session (never name the task's own bug,
function, or file).

--- BEGIN SESSION MATERIAL ---
{material}
--- END SESSION MATERIAL ---

Reply with a JSON list only (possibly empty), each item:
{{"content": "one self-contained sentence stating condition and remedy",
"condition_class": "from or extending the ontology", "action": "the
runnable command if the session ran one, else empty", "scope": "repo or
context", "era": "version/era bound or empty"}}"""

JUDGE = """A coding agent had this stored memory available during a
session:

MEMORY: {memory}

The session's commands that appear to act on it, with results:
{acted}

Condition classes observed anywhere in the session's command output:
{fired}

Answer the CONDITIONED question, not "was it used":
1. condition_present — did this session actually exhibit the problem or
   state the memory describes (not merely mention it)?
2. verdict — "helped" only if acting on the memory changed the outcome
   for the better versus not having it; "harmed" if following it made
   things worse or wasted effort; else "unclear". A command that
   succeeded while nothing was at risk is NOT evidence of help.

Reply with JSON only:
{{"condition_present": true or false, "verdict": "helped" or "harmed"
or "unclear", "reason": "under 20 words"}}"""


def ensure_schema(db):
    rfm.register(db)
    db.execute("SELECT rfm_init()")
    se.ensure_conditions(db)
    try:
        db.execute("ALTER TABLE rfm_memories ADD COLUMN sightings INTEGER")
    except sqlite3.OperationalError:
        pass


def tokens(s):
    return set(re.findall(r"[a-z0-9_./-]{3,}", (s or "").lower()))


# Embedding similarity, as the design specified (Track 18 measured the
# token-Jaccard shortcut failing on paraphrase: 22 rewordings of one
# fact, zero merges). fastembed when importable (the integration venv
# has it); Jaccard as the degraded fallback, which near-verbatim pairs
# still clear.
_EMB = {"model": None, "tried": False, "cache": {}}


def _embed(text):
    if not _EMB["tried"]:
        _EMB["tried"] = True
        try:
            from fastembed import TextEmbedding
            _EMB["model"] = TextEmbedding()
        except Exception:
            _EMB["model"] = None
    if _EMB["model"] is None:
        return None
    key = text[:1000]
    if key not in _EMB["cache"]:
        _EMB["cache"][key] = list(_EMB["model"].embed([key]))[0]
    return _EMB["cache"][key]


def similarity(a, b):
    ea, eb = _embed(a), _embed(b)
    if ea is not None and eb is not None:
        num = float((ea * eb).sum())
        den = float((ea * ea).sum()) ** 0.5 * float((eb * eb).sum()) ** 0.5
        return max(0.0, num / den) if den else 0.0
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def material_of(records, events):
    parts = []
    for c in se.corrections(events)[:4]:
        parts.append(f"FAILED: {c['failed']}\nERROR: {c['error']}\n"
                     f"FIXED BY: {c['fixed']}")
    prose = []
    for r in records:
        if r.get("type") != "assistant":
            continue
        c = (r.get("message") or {}).get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    t = (b.get("text") or "").strip()
                    if len(t) >= 200:
                        prose.append(t)
    parts.extend(prose[-3:])
    return "\n\n".join(parts)[:6000]


def admit(db, mem, cmds, src):
    """Dedupe-as-frequency, provenance, quarantine — then insert or bump."""
    content = (mem.get("content") or "").strip()
    cond = (mem.get("condition_class") or "").strip()
    if not content or not cond:
        return None
    action = (mem.get("action") or "").strip()
    if action:
        at = tokens(action)
        if not at or not any(
                len(at & tokens(c)) / len(at) >= 0.6 for c in cmds):
            _log({"op": "sweep_provenance_drop", "action": action[:80],
                  "src": src})
            action = ""
    text = content if not action else f"{content} Command: `{action}`"
    best, best_sim = None, 0.0
    for mid, existing in db.execute(
            "SELECT id, content FROM rfm_memories").fetchall():
        s = similarity(text, existing)
        if s > best_sim:
            best, best_sim = mid, s
    if best is not None and best_sim >= CONFIG["dedupe_threshold"]:
        db.execute("SELECT rfm_record_access(?)", (best,))
        db.execute("UPDATE rfm_memories SET sightings = "
                   "COALESCE(sightings, 1) + 1 WHERE id = ?", (best,))
        _log({"op": "sweep_dedupe_hit", "id": best,
              "similarity": round(best_sim, 3), "src": src})
        return best
    cur = db.execute(
        "INSERT INTO rfm_memories (content, created_at, condition_class,"
        " sightings) VALUES (?, ?, ?, 1)",
        (text, time.time(), se.derive_condition(text) or cond.lower()))
    _log({"op": "sweep_admit", "id": cur.lastrowid, "condition": cond,
          "action_provenance": "quoted" if action else "none", "src": src})
    return cur.lastrowid


def outcome_of(v):
    """The conditioned mapping, kept pure for the acceptance audit:
    harm counts in any state; help counts only with the condition
    present (C4); everything else records nothing."""
    if v.get("verdict") == "harmed":
        return -1.0
    if v.get("verdict") == "helped" and v.get("condition_present"):
        return 1.0
    return None


def judge_in_play(db, records, events, fired, src):
    # Transcript-parsed in-play content, matched to this store's rows by
    # SIMILARITY, never by id: transcript ids belong to whatever store
    # ran that session, and rehydrating them against this one collides
    # (Track 18's vacuous P3 — wrong content, dead signatures, silent
    # skips). A similarity match also recovers the full text that
    # injection truncation cut from the transcript line.
    mems = se.in_play_memories(records)
    rows = db.execute("SELECT id, content FROM rfm_memories").fetchall()
    for _tid, (tcontent, first_idx) in mems.items():
        target, best_sim = None, 0.0
        for mid, existing in rows:
            s = similarity(tcontent, existing)
            if s > best_sim:
                target, best_sim = mid, s
        content = tcontent
        if target is not None and best_sim >= CONFIG["dedupe_threshold"]:
            content = next(c for m, c in rows if m == target)
        else:
            target = None
        sig = se._signature(content)
        acted = []
        for e in events[first_idx:]:
            if se.acted_on(sig, e.cmd):
                acted.append(f"$ {e.cmd.splitlines()[0][:160]}\n"
                             f"  -> {'ERROR' if e.is_err else 'ok'}: "
                             f"{(e.body or '')[:200]}")
            if len(acted) >= 3:
                break
        if not acted:
            continue
        v = parse_json(llm(JUDGE.format(memory=content[:800],
                                        acted="\n".join(acted),
                                        fired=sorted(fired) or "none")))
        if not v:
            continue
        outcome = outcome_of(v)
        if target is None:
            _log({"op": "sweep_judge_unmatched", "verdict": v.get("verdict"),
                  "src": src})
            continue
        _log({"op": "sweep_judge", "id": target,
              "condition_present": bool(v.get("condition_present")),
              "verdict": v.get("verdict"), "outcome": outcome, "src": src})
        if outcome is not None:
            db.execute("SELECT rfm_record_access(?)", (target,))
            db.execute("SELECT rfm_record_outcome(?, ?)", (target, outcome))


def evict(db):
    cap = CONFIG["max_entries"]
    n = db.execute("SELECT count(*) FROM rfm_memories").fetchone()[0]
    if n <= cap:
        return
    grace = time.time() - CONFIG["evict_grace_hours"] * 3600
    rows = db.execute(
        "SELECT id, rfm_score(id) AS s FROM rfm_memories "
        "WHERE created_at < ? ORDER BY s ASC LIMIT ?",
        (grace, n - cap)).fetchall()
    for mid, s in rows:
        db.execute("DELETE FROM rfm_memories WHERE id = ?", (mid,))
        db.execute("DELETE FROM rfm_accesses WHERE memory_id = ?", (mid,))
        _log({"op": "sweep_evict", "id": mid, "score": round(s, 4)})


def sweep_one(db, tp):
    records = se._parse_transcript(tp)
    events = se.load_events(records)
    if not events and not records:
        return
    fired = se.fired_classes(events)
    cmds = [e.cmd for e in events if e.cmd]
    src = os.path.basename(tp)
    mat = material_of(records, events)
    if mat.strip():
        out = parse_json(llm(EXTRACT.format(
            instruction=CONFIG["instruction"],
            ontology=", ".join(CONFIG["ontology"]),
            max_per_session=CONFIG["max_per_session"], material=mat)))
        for mem in (out or [])[:CONFIG["max_per_session"]]:
            if isinstance(mem, dict):
                admit(db, mem, cmds, src)
    judge_in_play(db, records, events, fired, src)
    evict(db)
    db.commit()


def discover(since):
    root = os.path.expanduser("~/.claude/projects")
    out = []
    for tp in glob.glob(os.path.join(root, "*", "*.jsonl")):
        if os.path.getmtime(tp) > since:
            out.append(tp)
    return sorted(out, key=os.path.getmtime)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", help="file listing transcript paths, in order")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15.0)
    ensure_schema(db)
    if a.replay:
        paths = [l.strip() for l in open(a.replay) if l.strip()]
    else:
        state = {}
        if os.path.exists(STATE):
            state = json.load(open(STATE))
        paths = discover(state.get("last", 0))
    print(f"sweep: {len(paths)} transcript(s), db {DB_PATH}", flush=True)
    for i, tp in enumerate(paths, 1):
        if not os.path.exists(tp):
            continue
        sweep_one(db, tp)
        if i % 5 == 0:
            print(f"  {i}/{len(paths)}", flush=True)
    if not a.replay:
        with open(STATE, "w") as f:
            json.dump({"last": time.time()}, f)
    n = db.execute("SELECT count(*) FROM rfm_memories").fetchone()[0]
    print(f"sweep done: store has {n} memories", flush=True)
    db.close()


if __name__ == "__main__":
    main()
