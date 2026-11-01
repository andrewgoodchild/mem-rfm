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
import secret_scan        # noqa: E402
import harnesses          # noqa: E402
import similarity as _similarity  # noqa: E402
import store              # noqa: E402
import transcripts        # noqa: E402
import log_env            # noqa: E402

CONFIG = json.load(open(os.path.join(HERE, "sweep-config.json")))
DB_PATH = os.path.expanduser(
    os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))
STATE = os.path.join(os.path.dirname(DB_PATH), "sweep-state.json")
# The same RFM_LOG / RFM_LOG_CONTENT contract as the server and hooks:
# RFM_LOG=0 means nothing is written, and content fields are redacted.
LOG_ENABLED, LOG = log_env.resolve_log(
    os.environ.get("RFM_LOG", "1"), os.path.dirname(DB_PATH))
LOG_CONTENT = log_env.content_enabled(os.environ.get("RFM_LOG_CONTENT", "1"))


def _log(fields):
    if not LOG_ENABLED:
        return
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
function, or file). This session ran in the repository {project}.

--- BEGIN SESSION MATERIAL ---
{material}
--- END SESSION MATERIAL ---

Reply with a JSON list only (possibly empty), each item:
{{"content": "one self-contained sentence stating condition and remedy",
"condition_class": "from or extending the ontology", "action": "the
runnable command if the session ran one, else empty", "scope": "the
repository's name if this holds only there, else empty", "era":
"version/era bound or empty"}}"""

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


tokens = _similarity.tokens


# Embedding similarity, as the design specified (Track 18 measured the
# token-Jaccard shortcut failing on paraphrase: 22 rewordings of one
# fact, zero merges). similarity.py owns the model and the degraded
# Jaccard fallback — shared with session_end's reconcile step so the two
# formation paths cannot drift; the sweep adds only its audit line when
# the fallback engages.
similarity = _similarity.similarity
_similarity.on_degraded.append(
    lambda: _log({"op": "sweep_degraded_similarity"}))


def material_of(sess):
    parts = []
    for c in se.corrections(sess.events)[:4]:
        parts.append(f"FAILED: {c['failed']}\nERROR: {c['error']}\n"
                     f"FIXED BY: {c['fixed']}")
    # Reader prose arrives with our own injected blocks already stripped
    # (transcripts.strip_injected): extracting from the session's echo of a
    # memory would be the store confirming itself.
    prose = [t for t in sess.prose if len(t) >= 200]
    parts.extend(prose[-3:])
    return "\n\n".join(parts)[:6000]


def best_match(text, rows):
    """(id, similarity) of the stored row closest to `text` when it clears
    the dedupe threshold, else (None, best similarity). The one matching
    rule shared by admission, self-sighting and the in-play judge."""
    best, best_sim = None, 0.0
    for mid, existing in rows:
        s = similarity(text, existing)
        if s > best_sim:
            best, best_sim = mid, s
    if best_sim >= CONFIG["dedupe_threshold"]:
        return best, best_sim
    return None, best_sim


def exposed_ids(db, sess):
    """Store ids of the memories this session was shown (injected, or read
    through any memory tool: sess.seen), matched by SIMILARITY for the same reason judge_in_play
    matches that way: transcript ids belong to whatever store ran the
    session."""
    rows = db.execute("SELECT id, content FROM rfm_memories").fetchall()
    matched = (best_match(c, rows)[0] for c in sess.seen.values())
    return {mid for mid in matched if mid is not None}


def _classes(condition):
    return {c for c in (condition or "").split(",") if c}


def scope_of(mem, project):
    """The session's repository, if the extractor bound the memory to it.
    Anything else stays global: a free-form context ("python", "testing")
    matches no project, so it would hide the row from every session."""
    named = str(mem.get("scope") or "").strip().rsplit("/", 1)[-1]
    return project if project and named.lower() == project.lower() else None


def origin_of(condition, fired, project, src):
    """What one sighting is independent evidence of (DESIGN_NOTES, the
    quarantine red-team: count distinct origins, not distinct sessions).

    A session whose own commands showed the condition observed it first
    hand, so each such session is its own origin. Anything else was read,
    and a README, issue or page the agent reads recurs in every session
    without being independent evidence once. Those all share one origin per
    repository. Decided here, from the session's events, and not by asking
    the extractor where a lesson came from: the text being judged is what an
    attacker controls, and it could name a new source every time.

    fired=None is a caller with no session to judge; src is then the origin,
    the old one-session-one-sighting rule."""
    if fired is None:
        return src
    if _classes(condition) & set(fired):
        return f"session:{src}"
    return f"repo:{project}"


def admit(db, mem, cmds, src, exposed=frozenset(), touched=None, fired=None,
          project=None):
    """Dedupe-as-frequency, provenance, quarantine — then insert or bump.

    A near-duplicate bumps sightings — the quarantine's evidence that a
    second independent session learned the same thing — only when it is
    independent, so none of these count:
      `exposed`   store ids this session was shown (injected, or read via
                  any memory tool): restating what it was told;
      `touched`   ids this session already inserted or bumped: two
                  paraphrases from one session are one sighting;
      a match across condition classes: a different lesson that happens to
                  embed nearby is not the same lesson seen again;
      an origin already counted: see origin_of.
    Matching stays within the memory's scope, as a server save does.
    (test_feedback_loop.py)"""
    content = (mem.get("content") or "").strip()
    cond = (mem.get("condition_class") or "").strip()
    if not content or not cond:
        return None
    action = (mem.get("action") or "").strip()
    if action:
        at = tokens(action)
        if not at or not any(
                len(at & tokens(c)) / len(at) >= 0.6 for c in cmds):
            _log({"op": "sweep_provenance_drop", "src": src,
                  "action": log_env.redact(secret_scan.redact(action[:80])[0],
                                           LOG_CONTENT)})
            action = ""
    text = content if not action else f"{content} Command: `{action}`"
    # Same sanitizing as a server save: this row is injected later.
    text = transcripts.flatten(text)
    text, kinds = secret_scan.redact(text)
    if kinds:
        _log({"op": "secret_redacted", "kinds": kinds, "src": src})
    scope = scope_of(mem, project)
    scoped, scope_args = store.in_scope(scope)
    best, best_sim = best_match(text, db.execute(
        f"SELECT id, content FROM rfm_memories WHERE {scoped}",
        scope_args).fetchall())
    condition = se.derive_condition(text) or cond.lower()
    origin = origin_of(condition, fired, project, src)
    touched = set() if touched is None else touched
    if best is not None:
        why = None
        if best in exposed:
            why = "sweep_self_sighting"
        elif best in touched:
            why = "sweep_same_session"
        else:
            row = db.execute("SELECT condition_class, sightings, origins "
                             "FROM rfm_memories WHERE id = ?", (best,)).fetchone()
            origins = json.loads(row[2] or "[]")
            if row[1] is not None and not (_classes(row[0]) & _classes(condition)):
                why = "sweep_cross_condition"
            elif origin in origins:
                why = "sweep_same_origin"
        if why:
            _log({"op": why, "id": best, "similarity": round(best_sim, 3),
                  "src": src})
            return best
        touched.add(best)
        db.execute("SELECT rfm_record_access(?)", (best,))
        db.execute("UPDATE rfm_memories SET sightings = "
                   "COALESCE(sightings, 1) + 1, origins = ? WHERE id = ?",
                   (json.dumps(origins + [origin]), best))
        _log({"op": "sweep_dedupe_hit", "id": best,
              "similarity": round(best_sim, 3), "src": src})
        return best
    era = secret_scan.redact(transcripts.flatten(mem.get("era") or ""))[0]
    cur = db.execute(
        "INSERT INTO rfm_memories (content, created_at, condition_class,"
        " sightings, scope, era, origins) VALUES (?, ?, ?, 1, ?, ?, ?)",
        (text, time.time(), condition, scope, era[:80] or None,
         json.dumps([origin])))
    touched.add(cur.lastrowid)
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


def judge_in_play(db, sess, fired, src):
    # Transcript-parsed in-play content, matched to this store's rows by
    # SIMILARITY, never by id: transcript ids belong to whatever store
    # ran that session, and rehydrating them against this one collides
    # (Track 18's vacuous P3 — wrong content, dead signatures, silent
    # skips). A similarity match also recovers the full text that
    # injection truncation cut from the transcript line.
    rows = db.execute("SELECT id, content FROM rfm_memories").fetchall()
    for _tid, (tcontent, first_idx) in sess.exposures.items():
        target, _sim = best_match(tcontent, rows)
        content = tcontent if target is None else dict(rows)[target]
        sig = se._signature(content)
        acted = []
        for e in sess.events[first_idx:]:
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
    harness = harnesses.current()
    sess = transcripts.read(tp, harness.reader)
    src = os.path.basename(tp)
    if not sess.readable:
        _log({"op": "sweep_unreadable", "harness": harness.name, "src": src})
        return
    events = sess.events
    fired = se.fired_classes(events)
    cmds = [e.cmd for e in events if e.cmd]
    mat = material_of(sess)
    project = store.project(sess.cwd) if sess.cwd else None
    if mat.strip():
        out = parse_json(llm(EXTRACT.format(
            instruction=CONFIG["instruction"],
            ontology=", ".join(CONFIG["ontology"]),
            max_per_session=CONFIG["max_per_session"], material=mat,
            project=project or "unknown")))
        mems = [m for m in (out or [])[:CONFIG["max_per_session"]]
                if isinstance(m, dict)]
        # Matched before any admission, and only when there is something
        # to admit: the scan is O(exposures x rows).
        exposed = exposed_ids(db, sess) if mems else set()
        touched = set()
        for mem in mems:
            admit(db, mem, cmds, src, exposed, touched, fired, project)
    judge_in_play(db, sess, fired, src)
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
        try:
            sweep_one(db, tp)
        except Exception as e:
            # One transcript must not abort the sweep — in discover mode an
            # abort also skips the state write, so the same file would kill
            # every later run. Roll back its partial writes and move on.
            db.rollback()
            _log({"op": "sweep_error", "src": os.path.basename(tp),
                  "error": f"{type(e).__name__}: {e}"[:200]})
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
