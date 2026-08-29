#!/usr/bin/env python3
"""Track 20 — MEMTRACK replay (registration in REVALIDATION.md before
any session). 43 usable instances (of 46; three excluded for
unreachable repos with code questions — the triage is committed in the
registration), 134 questions, paired arms:

  control  workspace only: events/*.jsonl exports + ./repo when the
           instance references a reachable repository
  rfm      same workspace, plus a per-instance store built by the
           open-throttle extraction over the event timeline, delivered
           by SessionStart injection (quarantine active: only
           twice-sighted facts inject — design fidelity, disclosed)

This is a REPLAY harness, not Patronus's docker stack (their harness is
unreleased); comparison to their published numbers is directional only.
The registered claim is the tax question their paper raises: memory
backends (Mem0/Zep) made their agents worse — ours must not.

Usage: run_track20.py [--dry-run | --build-stores | --smoke N]
"""
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import run_stream as rs        # noqa: E402  (AB, cli_version)

INTEGRATION = os.path.join(ROOT, "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
sys.path.insert(0, os.path.join(INTEGRATION, "hooks"))
import install_hooks           # noqa: E402

MT = os.path.join(HERE, "..", "data", "memtrack", "Memtrak")
DIR = os.path.join(HERE, "track20")
# sweep derives its DB_PATH/LOG from the environment AT IMPORT — point
# them into this track's directory before importing, so formation audit
# lines land in track20/rfm-log.jsonl, never the user's live store.
os.makedirs(DIR, exist_ok=True)
os.environ.setdefault("RFM_MEMORY_DB", os.path.join(DIR, "rfm-memory.db"))
import sweep                   # noqa: E402  (admit, ensure_schema, llm)
RESULTS = os.path.join(DIR, "results.jsonl")
SESSIONS = os.path.join(DIR, "sessions")
STORES = os.path.join(DIR, "stores")
WORK = os.path.join(DIR, "work")
REPOCACHE = os.path.join(DIR, "repocache")
MODEL = "claude-fable-5"
CHUNK = 10
CODE_Q = re.compile(r"\brepositor|clone|codebase|\.py\b|function|file|"
                    r"director|source code|line count|def statement", re.I)

EXTRACT = """You are building the long-term memory of an agent that
works inside this organization. Below is a chronological slice of the
organization's Slack messages, Linear tickets, and Git activity.

Extract at most 3 durable memories a team member would rely on later:
decisions made, ownership and leads, conventions adopted, states that
changed (and their latest value), corrections that superseded earlier
information. Skip pleasantries and transient chatter. Each memory must
stand alone.

--- BEGIN EVENTS ---
{events}
--- END EVENTS ---

Reply with a JSON list only (possibly empty), each item:
{{"content": "one self-contained sentence", "condition_class": "a short
kebab-case tag for when this matters (e.g. ticket-status, ownership,
convention, decision)", "action": "", "scope": "{scope}", "era": ""}}"""

PROMPT = """You are assisting a software team. Your working directory
contains exports of the organization's activity:

  events/slack.jsonl    — Slack messages, chronological
  events/linear.jsonl   — Linear ticket events, chronological
  events/git.jsonl      — Git/commit events, chronological
{repo_line}
Answer the following questions IN ORDER using those sources. Questions
may depend on details scattered across platforms, on later events
superseding earlier ones, and on the repository contents. Investigate
before answering; answers are short phrases.

{questions}

Output format — one line per question, nothing else after them:
[ANSWER 1] <short answer>
[ANSWER 2] <short answer>
(and so on for every question)"""


def instances():
    out = []
    for f in sorted(glob.glob(os.path.join(MT, "test_configs", "*.yaml"))):
        c = yaml.safe_load(open(f))
        b = c.get("benchmark") or {}
        qs = b.get("questions") or []
        if not qs:
            continue
        url = (c.get("repository") or {}).get("url", "")
        out.append({"id": os.path.basename(f)[:-5].replace("config_", ""),
                    "config": f, "url": url,
                    "events": os.path.join(MT, b["event_history"])
                    if not os.path.isabs(b.get("event_history", ""))
                    else b["event_history"],
                    "questions": qs,
                    "answers": b.get("expected_answers") or [],
                    "code_q": sum(bool(CODE_Q.search(q)) for q in qs)})
    return out


def repo_ok(url, cache={}):
    if not url:
        return False
    if url not in cache:
        try:
            r = subprocess.run(["git", "ls-remote", "--exit-code", url,
                                "HEAD"], capture_output=True, timeout=30)
            cache[url] = r.returncode == 0
        except Exception:
            cache[url] = False
    return cache[url]


def usable(inst):
    return [i for i in inst if i["code_q"] == 0 or repo_ok(i["url"])]


def event_text(e):
    md = e.get("generation_meta_data") or {}
    parts = [f"[{e.get('timestamp', '?')}] ({e.get('platform', '?')})"]
    for k in ("title", "description", "status", "team", "priority",
              "lead", "channel", "sender", "message", "author",
              "commit_message"):
        if md.get(k):
            parts.append(f"{k}={md[k]}")
    return " ".join(str(p) for p in parts)


def build_workspace(inst):
    wd = os.path.join(WORK, inst["id"])
    if os.path.exists(wd):
        shutil.rmtree(wd)
    os.makedirs(os.path.join(wd, "events"))
    events = json.load(open(inst["events"]))
    sinks = {}
    for e in events:
        p = str(e.get("platform", "other")).lower()
        p = p if p in ("slack", "linear", "git") else "other"
        sinks.setdefault(p, []).append(e)
    for p in ("slack", "linear", "git"):
        with open(os.path.join(wd, "events", f"{p}.jsonl"), "w") as f:
            for e in sinks.get(p, []):
                f.write(json.dumps(e) + "\n")
    if sinks.get("other"):
        with open(os.path.join(wd, "events", "other.jsonl"), "w") as f:
            for e in sinks["other"]:
                f.write(json.dumps(e) + "\n")
    has_repo = False
    if inst["url"] and repo_ok(inst["url"]):
        name = re.sub(r"[^a-zA-Z0-9_-]", "-", inst["url"].split("/")[-1])
        cache = os.path.join(REPOCACHE, name)
        if not os.path.isdir(cache):
            os.makedirs(REPOCACHE, exist_ok=True)
            r = subprocess.run(["git", "clone", "-q", "--depth", "1",
                                inst["url"], cache], capture_output=True,
                               timeout=600)
            if r.returncode != 0:
                cache = None
        if cache and os.path.isdir(cache):
            shutil.copytree(cache, os.path.join(wd, "repo"))
            has_repo = True
    return wd, has_repo


def store_path(inst):
    return os.path.join(STORES, f"{inst['id']}.db")


def build_store(inst):
    os.makedirs(STORES, exist_ok=True)
    path = store_path(inst)
    if os.path.exists(path):
        return 0
    db = sqlite3.connect(path)
    sweep.ensure_schema(db)
    events = json.load(open(inst["events"]))
    texts = [event_text(e) for e in events]
    calls = 0
    for i in range(0, len(texts), CHUNK):
        block = "\n".join(texts[i:i + CHUNK])[:6000]
        out = sweep.parse_json(sweep.llm(EXTRACT.format(
            events=block, scope=inst["id"])))
        calls += 1
        for mem in (out or [])[:3]:
            if isinstance(mem, dict):
                sweep.admit(db, mem, [], f"track20-{inst['id']}")
    db.commit()
    n, promoted = db.execute(
        "SELECT count(*), sum(COALESCE(sightings,1) >= 2) "
        "FROM rfm_memories").fetchone()
    db.close()
    print(f"  [{inst['id']}] {len(events)} events -> {n} memories "
          f"({promoted or 0} promoted), {calls} calls", flush=True)
    return calls


def run_session(inst, arm_name, ab_arm, wd, has_repo):
    qs = "\n".join(f"Question {k + 1}: {q}"
                   for k, q in enumerate(inst["questions"]))
    repo_line = ("  repo/                 — the project repository "
                 "checkout\n" if has_repo else "")
    env = {**os.environ, "RFM_MEMORY_DB": store_path(inst)}
    cmd = [rs.AB, "--arm", ab_arm,
           "--label", f"track20-{inst['id']}-{arm_name}",
           "-p", PROMPT.format(repo_line=repo_line, questions=qs),
           "--max-turns", rs.MAX_TURNS,
           "--allowedTools", "Bash,Read,Grep,Glob,mcp__rfm-memory"]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=wd, env=env, capture_output=True,
                           text=True, timeout=rs.SESSION_TIMEOUT)
        timed_out = False
    except subprocess.TimeoutExpired as e:
        r, timed_out = e, True
    wall = time.time() - t0
    os.makedirs(SESSIONS, exist_ok=True)

    def _text(x):
        return x.decode("utf-8", "replace") if isinstance(x, bytes) \
            else (x or "")
    out = _text(getattr(r, "stdout", ""))
    with open(os.path.join(SESSIONS, f"{inst['id']}.{arm_name}.log"),
              "w") as f:
        f.write(out)
        f.write("\n--- STDERR ---\n")
        f.write(_text(getattr(r, "stderr", "")))
    answers = {}
    for m in re.finditer(r"\[ANSWER (\d+)\]\s*(.+)", out):
        answers[int(m.group(1))] = m.group(2).strip()
    return answers, wall, timed_out


def exact(got, want):
    n = lambda s: re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()
    return n(want) in n(got) or n(got) == n(want)


def main():
    inst = usable(instances())
    nq = sum(len(i["questions"]) for i in inst)
    print(f"usable instances {len(inst)} of 46, questions {nq}, "
          f"cli {rs.cli_version()}")
    if "--dry-run" in sys.argv:
        return
    os.makedirs(DIR, exist_ok=True)
    if "--build-stores" in sys.argv:
        total = sum(build_store(i) for i in inst)
        print(f"store build calls: {total}")
        return
    if "--smoke" in sys.argv:
        inst = inst[:int(sys.argv[sys.argv.index("--smoke") + 1])]

    missing = [i["id"] for i in inst if not os.path.exists(store_path(i))]
    if missing:
        sys.exit(f"PREFLIGHT: stores missing for {missing[:5]}... — run "
                 f"--build-stores first (registration order)")

    done = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS):
            r = json.loads(line)
            done.add((r["id"], r["arm"]))
    if done:
        print(f"resuming: {len(done)} recorded")
    cli = rs.cli_version()
    for change in install_hooks.sync_claude_md(remove=True):
        print(f"CLAUDE.md: {change}")
    try:
        with open(RESULTS, "a") as sink:
            for i in inst:
                for arm_name, ab_arm in (("control", "control"),
                                         ("rfm", "rfm")):
                    if (i["id"], arm_name) in done:
                        continue
                    print(f"=== {i['id']} [{arm_name}] "
                          f"({len(i['questions'])} q) ===", flush=True)
                    wd, has_repo = build_workspace(i)
                    answers, wall, timed_out = run_session(
                        i, arm_name, ab_arm, wd, has_repo)
                    correct = [int(k + 1 in answers and
                                   exact(answers[k + 1], a))
                               for k, a in enumerate(i["answers"])]
                    rec = {"id": i["id"], "arm": arm_name,
                           "track": "track20", "model": MODEL, "cli": cli,
                           "nq": len(i["questions"]),
                           "answered": len(answers),
                           "exact_correct": sum(correct),
                           "per_q": correct,
                           "answers": {str(k): v[:120]
                                       for k, v in answers.items()},
                           "wall_s": round(wall), "timed_out": timed_out,
                           "has_repo": has_repo}
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    print(f"    exact {sum(correct)}/{len(i['answers'])} "
                          f"wall={round(wall)}s", flush=True)
                    shutil.rmtree(wd, ignore_errors=True)
    finally:
        for change in install_hooks.sync_claude_md():
            print(f"CLAUDE.md: {change} (restored)")


if __name__ == "__main__":
    main()
