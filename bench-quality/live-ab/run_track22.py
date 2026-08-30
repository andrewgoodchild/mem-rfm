#!/usr/bin/env python3
"""Track 22 — substrate removal (REVALIDATION.md). The agent answers with
NO code execution: its only tool is the budgeted query_events MCP server,
so the control genuinely cannot read the source (enforcement probe passed).
The rfm arm additionally gets the instance's digested store prepended.

  run_track22.py [--smoke N | --dry-run]

Scored later by score_track22.py (judge-adjudicated).
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_stream as rs        # noqa: E402  (cli_version)
import run_track20 as t20      # noqa: E402  (store_path)
import track22_lib as t22      # noqa: E402

# Query budget is the substrate-tightness parameter (REVALIDATION Track 22
# scope; the budget-sweep hardening). --budget N and --model M reroute
# output to track22-b<N>[-<tag>] so sweep points and model replications
# never collide with the registered fable/budget-6 run.
BUDGET = "6"
MODEL = "claude-fable-5"
for _i, _a in enumerate(sys.argv):
    if _a == "--budget":
        BUDGET = sys.argv[_i + 1]
    if _a == "--model":
        MODEL = sys.argv[_i + 1]
_MTAG = "" if MODEL == "claude-fable-5" else "-" + MODEL.replace(
    "claude-", "").split("-")[0]
_SUF = ("" if BUDGET == "6" else f"-b{BUDGET}") + _MTAG
DIR = os.path.join(HERE, "track22" + _SUF)
RESULTS = os.path.join(DIR, "results.jsonl")
SESSIONS = os.path.join(DIR, "sessions")
VENV = os.path.abspath(os.path.join(HERE, "..", "..", "integrations",
                                    "claude-code", ".venv", "bin", "python"))
SERVER = os.path.abspath(os.path.join(HERE, "events_mcp_server.py"))
TOOL = "mcp__track22-events__query_events"

PROMPT = """You are assisting a software team. Your ONLY tool is
`query_events(keywords)`, which searches the team's Slack/Linear/Git
timeline and returns up to a few matching events. Retrieval is budgeted —
you cannot read the whole timeline, so query deliberately.
{memory}
Answer these questions IN ORDER. Answers are short phrases.

{questions}

Output exactly one line per question, nothing after:
[ANSWER 1] <short answer>
[ANSWER 2] <short answer>
"""


def store_memories(inst):
    """The instance's promoted digested facts (Track 20 sweep store)."""
    p = t20.store_path(inst)
    if not os.path.exists(p):
        return []
    db = sqlite3.connect(p)
    try:
        rows = db.execute(
            "SELECT content FROM rfm_memories WHERE "
            "COALESCE(sightings,1) >= 2 ORDER BY rfm_score(id) DESC").fetchall()
    except sqlite3.Error:
        rows = db.execute("SELECT content FROM rfm_memories").fetchall()
    db.close()
    return [r[0] for r in rows]


def mcp_config(inst, tmp):
    dbpath = os.path.join(t22.DATA, f"{inst['id']}.db")
    cfg = {"mcpServers": {"track22-events": {
        "command": VENV, "args": [SERVER],
        "env": {"TRACK22_EVENTS_DB": dbpath, "TRACK22_CAP": "5",
                "TRACK22_MAX_QUERIES": BUDGET}}}}
    path = os.path.join(tmp, "mcp.json")
    json.dump(cfg, open(path, "w"))
    return path


def run_session(inst, arm):
    t22.build_restricted_workspace(inst)          # builds the external DB
    tmp = tempfile.mkdtemp(prefix=f"t22-{inst['id']}-")
    cfg = mcp_config(inst, tmp)
    mem = ""
    if arm == "rfm":
        facts = store_memories(inst)
        if facts:
            mem = ("\nNotes already in the team's long-term memory (use if "
                   "helpful, and they may save queries):\n"
                   + "\n".join(f"- {f}" for f in facts) + "\n")
    qs = "\n".join(f"Question {k+1}: {q}"
                   for k, q in enumerate(inst["questions"]))
    prompt = PROMPT.format(memory=mem, questions=qs)
    t0 = time.time()
    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--model", MODEL,
             "--strict-mcp-config", "--mcp-config", cfg,
             "--allowedTools", TOOL, "--output-format", "json"],
            cwd=tmp, env={**os.environ, "RFM_HOOKS_OFF": "1"},
            capture_output=True, text=True, timeout=600)
        out = json.loads(r.stdout or "{}")
        text, turns = out.get("result", ""), out.get("num_turns")
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        text, turns = "", None
    wall = time.time() - t0
    os.makedirs(SESSIONS, exist_ok=True)
    given = {}
    for m in re.finditer(r"\[ANSWER (\d+)\]\s*(.+)", text):
        given[int(m.group(1))] = m.group(2).strip()
    ordered = [given.get(k + 1, "") for k in range(len(inst["questions"]))]
    with open(os.path.join(SESSIONS, f"{inst['id']}.{arm}.json"), "w") as f:
        json.dump({"given": ordered, "turns": turns}, f, indent=1)
    shutil.rmtree(tmp, ignore_errors=True)
    return ordered, wall, turns


def main():
    pool = t22.usable_event_only()
    print(f"pool {len(pool)} event-only instances, "
          f"{sum(len(i['questions']) for i in pool)} questions, "
          f"cli {rs.cli_version()}")
    if "--dry-run" in sys.argv:
        return
    if "--smoke" in sys.argv:
        pool = pool[:int(sys.argv[sys.argv.index("--smoke") + 1])]
    os.makedirs(DIR, exist_ok=True)
    done = set()
    if os.path.exists(RESULTS):
        for l in open(RESULTS):
            r = json.loads(l)
            done.add((r["id"], r["arm"]))
    cli = rs.cli_version()
    with open(RESULTS, "a") as sink:
        for i in pool:
            for arm in ("control", "rfm"):
                if (i["id"], arm) in done:
                    continue
                print(f"=== {i['id']} [{arm}] ({len(i['questions'])}q) ===",
                      flush=True)
                given, wall, turns = run_session(i, arm)
                rec = {"id": i["id"], "arm": arm, "track": "track22",
                       "model": MODEL, "cli": cli,
                       "nq": len(i["questions"]),
                       "answered": sum(1 for g in given if g),
                       "given": [g[:120] for g in given],
                       "turns": turns, "wall_s": round(wall)}
                sink.write(json.dumps(rec) + "\n")
                sink.flush()
                print(f"    answered {rec['answered']}/{rec['nq']} "
                      f"turns={turns} wall={round(wall)}s", flush=True)


if __name__ == "__main__":
    main()
