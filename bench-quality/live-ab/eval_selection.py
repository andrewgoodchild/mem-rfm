#!/usr/bin/env python3
"""Offline injection-selection policy evaluation on pilot 2's ground truth.

For each of pilot 2's 10 rfm sessions: candidates = memories created before
the session started. Policies pick an injection set; we score it against
what that session actually proved: helpful = ids that earned a positive
outcome (explicit feedback or replayed inference), harmful = ids with
explicit negative feedback.

Known bias, disclosed: ground truth is conditioned on what pilot 2
actually surfaced (prior-only top-5 + searches) — a memory no channel
surfaced has unknown counterfactual value. The decisive comparison is
retention of known-good ids and exclusion of known-bad/inert ones.

Prior proxy for counterfactual policies: the as-run log prior where the
memory was injected that session, else that session's minimum logged
prior (never-injected memories were mid/low-prior per-bug entries).

Run with integrations/claude-code/.venv/bin/python (needs fastembed).
"""
import json
import os
import struct
import sys
import collections

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CC = os.path.join(REPO, "integrations", "claude-code")
PILOT = os.path.join(REPO, "bench-quality", "live-ab", "pilot2")
os.environ["RFM_LOG"] = "0"
os.environ.setdefault("RFM_MEMORY_DB", os.path.join(PILOT, "rfm-memory.db"))
sys.path.insert(0, os.path.join(CC, "hooks"))
sys.path.insert(0, CC)
sys.path.insert(0, REPO)
import server                      # noqa: E402  (embed(), byte-identical)
import session_end as se           # noqa: E402

AB = os.path.join(CC, "ab")
TASKS = {t["instance_id"]: t for t in
         json.load(open(os.path.join(REPO, "bench-quality", "live-ab",
                                     "tasks_v2.json")))}

def unpack(blob):
    v = struct.unpack(f"{len(blob)//4}f", blob)
    return v

def dot(a, b):
    return sum(x * y for x, y in zip(a, b))

# --- store ------------------------------------------------------------
import sqlite3
db = sqlite3.connect(os.path.join(PILOT, "rfm-memory.db"))
mems = {r[0]: {"content": r[1], "created": r[2], "vec": unpack(r[3])}
        for r in db.execute(
            "SELECT id, content, created_at, embedding FROM rfm_memories")}

# --- sessions: sid8 -> label, start epoch ------------------------------
ablog = {r["ab_session"]: r for r in
         (json.loads(l) for l in open(os.path.join(AB, "ab_log.jsonl")))
         if str(r.get("label", "")).startswith("pilot2-") and r["arm"] == "rfm"}
sid2lab, sid2start, sid2path = {}, {}, {}
for line in open(os.path.join(AB, "ab_sessions.jsonl")):
    s = json.loads(line)
    meta = ablog.get(s["ab_session"])
    if meta and s["arm"] == "rfm":
        sid8 = s["session_id"][:8]
        sid2lab[sid8] = meta["label"].replace("pilot2-", "")
        sid2start[sid8] = meta["start"]
        sid2path[sid8] = s["transcript_path"]

# --- log walk: per-session injections, feedback, value timeline --------
inject, explicit = {}, collections.defaultdict(list)
value_now = collections.defaultdict(float)      # value BEFORE each session
value_at = {}                                   # sid8 -> {id: value}
order = []
cur = None
for line in open(os.path.join(PILOT, "rfm-log.jsonl")):
    r = json.loads(line)
    if r["op"] == "injection":
        cur = r["session"]
        order.append(cur)
        inject[cur] = {d["id"]: d["prior"] for d in r["results"]}
        value_at[cur] = dict(value_now)
    elif r["op"] == "feedback" and cur:
        explicit[cur].append((r["id"], r["outcome"]))
        if "value" in r:
            value_now[r["id"]] = r["value"]

# --- inferred positives (replayed with the fixed inference) ------------
inferred = collections.defaultdict(set)
for sid8, path in sid2path.items():
    records = se._parse_transcript(path)
    events = se.load_events(records)
    ms = se.rehydrate(se.in_play_memories(records))
    for o in se.infer_outcomes(ms, events):
        if o["outcome"] > 0:
            inferred[sid8].add(o["id"])

# --- query embeddings --------------------------------------------------
qvec = {}
for sid8, lab in sid2lab.items():
    prob = TASKS[lab]["problem_statement"]
    qvec[sid8] = unpack(server.embed(prob))

# --- policies ----------------------------------------------------------
def cands(sid8):
    return [i for i, m in mems.items() if m["created"] < sid2start[sid8]]

def floor_ok(sid8, i):
    return value_at[sid8].get(i, 0.0) >= 0.0

def pol_asrun(sid8):
    return list(inject[sid8])

def pol_floor(sid8):
    return [i for i in inject[sid8] if floor_ok(sid8, i)]

def sim(sid8, i):
    return dot(qvec[sid8], mems[i]["vec"])

def prior_proxy(sid8, i):
    pri = inject[sid8]
    return pri.get(i, min(pri.values()) if pri else 0.2)

def pol_sim(sid8, k, minsim, use_floor=True):
    cs = [i for i in cands(sid8) if (not use_floor or floor_ok(sid8, i))]
    ranked = sorted(cs, key=lambda i: -sim(sid8, i))
    return [i for i in ranked[:k] if sim(sid8, i) >= minsim]

def pol_simprior(sid8, k, minsim, use_floor=True):
    cs = [i for i in cands(sid8) if (not use_floor or floor_ok(sid8, i))]
    ranked = sorted(cs, key=lambda i: -sim(sid8, i) * (0.7 + 0.3 * prior_proxy(sid8, i)))
    return [i for i in ranked[:k] if sim(sid8, i) >= minsim]

POLICIES = {
    "as-run (prior top-5)":        pol_asrun,
    "as-run + neg-floor":          pol_floor,
    "sim top-5":                   lambda s: pol_sim(s, 5, 0.0),
    "sim top-3":                   lambda s: pol_sim(s, 3, 0.0),
    "sim top-3, minsim .25":       lambda s: pol_sim(s, 3, 0.25),
    "sim*prior top-5":             lambda s: pol_simprior(s, 5, 0.0),
    "sim*prior top-3":             lambda s: pol_simprior(s, 3, 0.0),
    "sim*prior top-3, minsim .25": lambda s: pol_simprior(s, 3, 0.25),
}

# --- score -------------------------------------------------------------
print(f"{'policy':30} {'inj':>4} {'hits':>4} {'distr':>5} {'missed':>6} {'chars':>6}")
for name, pol in POLICIES.items():
    tot_inj = hits = distr = missed = chars = 0
    for sid8 in order:
        helpful = ({i for i, o in explicit[sid8] if o > 0} | inferred[sid8])
        harmful = {i for i, o in explicit[sid8] if o < 0}
        picked = set(pol(sid8))
        tot_inj += len(picked)
        hits += len(picked & helpful)
        distr += len(picked & harmful)
        missed += len(helpful - picked)
        chars += sum(min(len(mems[i]["content"]), 1500) for i in picked)
    print(f"{name:30} {tot_inj:4} {hits:4} {distr:5} {missed:6} {chars//10:6}")

# per-session detail for the leading candidate policy
print("\nsim*prior top-3, minsim .25 — per session:")
for sid8 in order:
    helpful = ({i for i, o in explicit[sid8] if o > 0} | inferred[sid8])
    harmful = {i for i, o in explicit[sid8] if o < 0}
    picked = pol_simprior(sid8, 3, 0.25)
    sims = {i: round(sim(sid8, i), 3) for i in picked}
    print(f"  {sid2lab.get(sid8, sid8):26} picked={sims} "
          f"helpful={sorted(helpful)} harmful={sorted(harmful)}")

# --- prior-ranked variants (log order IS prior-descending) -------------
def pol_prior_topk(sid8, k):
    return [i for i in list(inject[sid8])[:k] if floor_ok(sid8, i)]

def pol_proven_first(sid8, k, unproven_slots):
    ranked = [i for i in inject[sid8] if floor_ok(sid8, i)]
    proven = [i for i in ranked if value_at[sid8].get(i, 0.0) > 0]
    unproven = [i for i in ranked if i not in proven][:unproven_slots]
    return (proven + unproven)[:k]

MORE = {
    "prior top-3 + floor":        lambda s: pol_prior_topk(s, 3),
    "prior top-2 + floor":        lambda s: pol_prior_topk(s, 2),
    "proven-first k3 u1":         lambda s: pol_proven_first(s, 3, 1),
    "proven-first k3 u2":         lambda s: pol_proven_first(s, 3, 2),
    "proven-first k5 u2":         lambda s: pol_proven_first(s, 5, 2),
}
print(f"\n{'policy':30} {'inj':>4} {'hits':>4} {'distr':>5} {'missed':>6} {'chars':>6}")
for name, pol in MORE.items():
    tot_inj = hits = distr = missed = chars = 0
    for sid8 in order:
        helpful = ({i for i, o in explicit[sid8] if o > 0} | inferred[sid8])
        harmful = {i for i, o in explicit[sid8] if o < 0}
        picked = set(pol(sid8))
        tot_inj += len(picked); hits += len(picked & helpful)
        distr += len(picked & harmful); missed += len(helpful - picked)
        chars += sum(min(len(mems[i]["content"]), 1500) for i in picked)
    print(f"{name:30} {tot_inj:4} {hits:4} {distr:5} {missed:6} {chars//10:6}")
