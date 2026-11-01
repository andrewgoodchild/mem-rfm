#!/usr/bin/env python3
"""Track 29 — SDE-bench A/B, adapted: does a formed, grouped memory reduce the
corrections an agent needs on decisions that live only in past conversations?

The official harness needs Docker and a mounted login, neither available here,
so this reproduces its protocol locally: the task's build, its prompt, up to 5
corrections carrying the pytest tail, and grading from a pristine build plus
the hidden test. Differences, all applying to both arms: the host instead of
containers, claude-sonnet-5-5 instead of sonnet-5, no chat transcripts left
reachable for the control, and the prompt's instructions moved to the system
prompt so the user turn, which retrieval reads, is the bug report alone (a smoke
run found the boilerplate let commits outrank the chat). Scores do not pool with the published runs,
so this has its own control.

Arms: control, nothing. memory, a store holding the decision-formed memories
of all 33 chats, the formed decoys and the host's commits, delivered per turn
by the shipped hook with RFM_PERTURN_GROUP=1. Each run gets a fresh store copy.
The 27 `conversation` tasks only: the 6 amended ones test supersession, which
is not built.

Bars, written before the first session:
  A1  task-level mean corrections fall, sign test p < 0.05 across 27 tasks.
  A2  runs needing no correction rise by at least 30 points.
  A3  proof of delivery: the task's own deciding chat is delivered on the first
      prompt in at least 60% of memory runs. Below that, A1 is not a memory test.
  A4  reported cost per run rises by no more than 15%.
Stops if reported cost passes CEILING.

Track 30, ablation, --out track30, bars written before its first session:
  raw      what a plain vector store does: the chats' raw turns, cut to 1,200
           characters, top-2 by cosine. No formation, no grouping.
  flat     formed memories, top-2 memories, no grouping.
Both at the 2,400 budget, 3 repeats, 27 tasks, compared with Track 29's memory arm.
  R1  memory beats raw on corrections, task-level sign p < 0.05.
  R2  memory beats flat on corrections, task-level sign p < 0.05.
--amended runs the 6 amended tasks in control and memory, stale and amended
memories both stored and the later shown first.
  R3  memory has fewer mean corrections than control on at least 4 of 6.

Usage: run_track29.py SDE_BENCH_DIR BOLTONS_HOST PYTHON_WITH_PYTEST
         [--seed AMB_OUTPUTS BOLTONS_GIT] [--smoke] [--reps N] [--score]
"""
import concurrent.futures
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
OUT = os.path.join(HERE, "track29")
SEED = os.path.join(OUT, "seed.db")
RAW_SEED = os.path.join(OUT, "seed-raw.db")
if "--out" in sys.argv:
    OUT = os.path.join(HERE, sys.argv[sys.argv.index("--out") + 1])
RESULTS = os.path.join(OUT, "results.jsonl")
HOOK = os.path.abspath(os.path.join(INTEGRATION, "hooks",
                                    "user_prompt_submit.py"))
VENV = os.path.abspath(os.path.join(INTEGRATION, ".venv", "bin", "python"))
MODEL = "claude-sonnet-5-5"
MAX_TURNS = "40"
TIMEOUT = 900
MAX_CORRECTIONS = 5
WORKERS = 3
CEILING = 90.0
ARMS = ("control", "memory")
TOOLS = "Bash,Edit,Write,Read,Grep,Glob"
SYSTEM = """You are a maintainer of the `boltons` Python project. The user reports a regression.

Fix the bug in the source code. Do NOT modify any test files — the graders supply their own.
Work efficiently: find the root cause, make the smallest change that fixes it, run the failing test to confirm it passes (and existing behaviour still works), then stop — avoid unnecessary exploration.
Save your changes to disk before finishing.
"""
GIT_ENV = {"GIT_AUTHOR_NAME": "x", "GIT_AUTHOR_EMAIL": "x@x",
           "GIT_COMMITTER_NAME": "x", "GIT_COMMITTER_EMAIL": "x@x"}
LOCK = threading.Lock()
SPENT = [0.0]


def tasks(sde, source="conversation"):
    sys.path.insert(0, HERE)
    os.environ.setdefault("RFM_LOG", "0")
    import sde_reach_probe as S
    return [t for t in S.load_tasks(sde) if t["source"] == source]


def task_dir(sde, task):
    path = os.path.join(sde, task["codebase"], "tasks", "main")
    return path if os.path.exists(os.path.join(path, "task.json")) else \
        os.path.join(sde, task["codebase"], "tasks",
                     os.listdir(os.path.join(sde, task["codebase"], "tasks"))[0])


def build(sde, host, task, dest):
    env = {**os.environ, "SDEBENCH_BOLTONS_HOST": host, **GIT_ENV}
    subprocess.run([sys.executable, os.path.join(sde, task["codebase"],
                                                 task["build"]), dest],
                   env=env, check=True, capture_output=True)
    shutil.copy(os.path.join(task_dir(sde, task), task["regression_test_file"]),
                os.path.join(dest, "tests", "test_regression.py"))
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "test: add failing repro"],
                   cwd=dest, env=env, check=True)


def patch_of(repo):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    return subprocess.run(
        ["git", "diff", "--cached", "HEAD", "--", ".", ":(exclude)tests/**",
         ":(exclude)**/__pycache__/**", ":(exclude).pytest_cache/**"],
        cwd=repo, capture_output=True, text=True, check=True).stdout


def grade(sde, host, task, patch, work, python):
    gd = os.path.join(work, "grade")
    shutil.rmtree(gd, ignore_errors=True)
    build(sde, host, task, gd)
    shutil.copy(os.path.join(task_dir(sde, task), task["hidden_test_file"]),
                os.path.join(gd, "tests", "test_hidden.py"))
    applied = True
    if patch.strip():
        applied = subprocess.run(["git", "apply", "--whitespace=nowarn"],
                                 cwd=gd, input=patch, text=True,
                                 capture_output=True).returncode == 0
    r = subprocess.run([python, "-m", "pytest", "-q", "tests", "--no-header",
                        "-p", "no:cacheprovider"], cwd=gd,
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0 and not r.stdout.strip():
        raise RuntimeError("grading failed: " + r.stderr[-300:])
    return {"ok": r.returncode == 0 and applied, "applied": applied,
            "output": r.stdout}


def feedback(n, g):
    if not g["applied"]:
        body = ("Your change could not be applied cleanly to the source. "
                "Re-read the current code and make a focused edit that "
                "applies, then ensure the tests pass.")
    else:
        body = ("Your change did not fully fix the reported regression. "
                "Re-running the project's test suite now reports the "
                "following remaining failures:\n\n"
                f"```\n{g['output'][-2500:].strip()}\n```\n\n"
                "Fix the source so these pass. Do NOT modify any test file.")
    return f"[Feedback #{n}] {body}"


def agent(repo, message, sid, resume, env, settings):
    cmd = ["claude", "-p", message, "--model", MODEL, "--max-turns", MAX_TURNS,
           "--allowedTools", TOOLS, "--output-format", "json",
           "--strict-mcp-config", "--append-system-prompt", SYSTEM]
    cmd += ["--resume", sid] if resume else ["--session-id", sid]
    if settings:
        cmd += ["--settings", settings]
    r = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True,
                       timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        out = {"is_error": True, "result": (r.stdout + r.stderr)[-300:]}
    return out


def one(sde, host, python, task, arm, rep):
    work = tempfile.mkdtemp(prefix="rfm-t29-")
    repo = os.path.join(work, "boltons")
    build(sde, host, task, repo)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("RFM_")}
    env["PATH"] = f"{os.path.dirname(python)}:{env['PATH']}"
    log = None
    settings = None
    if arm != "control":
        db = os.path.join(work, "store.db")
        shutil.copy(RAW_SEED if arm == "raw" else SEED, db)
        log = os.path.join(work, "log.jsonl")
        env.update(RFM_MEMORY_DB=db, RFM_LOG=log, RFM_PERTURN="1",
                   RFM_PERTURN_BUDGET="2400")
        if arm == "memory":
            env["RFM_PERTURN_GROUP"] = "1"
        settings = os.path.join(work, "settings.json")
        with open(settings, "w") as f:
            json.dump({"hooks": {"UserPromptSubmit": [{"hooks": [
                {"type": "command", "command": f"{VENV} {HOOK}"}]}]}}, f)
    sid = str(uuid.uuid4())
    t0 = time.time()
    cost, turns, errors = 0.0, 0, []
    message = task["bug_report"]
    corrections = 0
    while True:
        out = agent(repo, message, sid, corrections > 0, env, settings)
        cost += out.get("total_cost_usd") or 0.0
        turns += out.get("num_turns") or 0
        if out.get("is_error"):
            errors.append(str(out.get("result"))[:200])
        g = grade(sde, host, task, patch_of(repo), work, python)
        if g["ok"] or corrections >= MAX_CORRECTIONS:
            break
        corrections += 1
        message = feedback(corrections, g)
    row = {"task": task["task_id"], "arm": arm, "rep": rep, "model": MODEL,
           "corrections": corrections, "solved": g["ok"], "cost": round(cost, 4),
           "turns": turns, "wall_s": round(time.time() - t0), "errors": errors,
           "session": sid, "tail": g["output"].strip().splitlines()[-1:]}
    if log and os.path.exists(log):
        row["delivered"] = delivered(log, db, task["task_id"])
    shutil.rmtree(work, ignore_errors=True)
    return row


def delivered(log, db, tid):
    """Per prompt, the sources shown, and whether the first held the task's
    own deciding chat."""
    con = sqlite3.connect(db)
    source = dict(con.execute("SELECT id, source FROM rfm_memories"))
    con.close()
    shown = [[source.get(i) for i in json.loads(line).get("injected", [])]
             for line in open(log)
             if '"perturn_retrieval"' in line]
    return {"first_own": bool(shown) and f"{tid}/gold" in shown[0],
            "prompts": len(shown), "first": shown[0] if shown else []}


def seed(sde, outputs, git):
    sys.path.insert(0, INTEGRATION)
    sys.path.insert(0, os.path.join(INTEGRATION, "hooks"))
    os.makedirs(OUT, exist_ok=True)
    os.environ.update(RFM_MEMORY_DB=SEED, RFM_LOG="0")
    import decisions as D
    import rfm
    import sde_formed_probe as F
    import store
    import user_prompt_submit as U
    if os.path.exists(SEED):
        os.remove(SEED)
    formed = json.load(open(os.path.join(HERE, "track27", "decision.json")))
    db = sqlite3.connect(SEED)
    rfm.register(db)
    store.ensure(db)
    n, base = 0, time.time() - 86400 * 30
    for key in sorted(formed, key=lambda k: not k.endswith("/stale")):
        n += 1
        D.save(db, F.contents(formed[key]), key, None, U.embed,
               created_at=base + n)
    for i, text in enumerate(F.S.commits(outputs, git)):
        D.save(db, [text], f"commit-{i}", None, U.embed, created_at=base)
    store.stamp_embedder(db, U.EMBEDDER_ID, len(U.embed("x")))
    db.commit()
    print("seeded", db.execute("SELECT count(*), count(embedding) "
                               "FROM rfm_memories").fetchone())
    db.close()
    seed_raw(sde, outputs, git, D, F, U, rfm, store)


def seed_raw(sde, outputs, git, D, F, U, rfm, store):
    S = F.S
    if os.path.exists(RAW_SEED):
        os.remove(RAW_SEED)
    db = sqlite3.connect(RAW_SEED)
    rfm.register(db)
    store.ensure(db)
    base = time.time() - 86400 * 30
    chats = {}
    for task in S.load_tasks(sde):
        for tag, chat in zip(("stale", "gold"), S.chats_of(task)):
            if chat is not None:
                chats[f"{task['task_id']}/{tag}"] = chat
    decoys = json.load(open(os.path.join(sde, "gen",
                                         "decoy_conversations.json")))
    for n, decoy in enumerate(decoys):
        chats[f"decoy-{n}"] = decoy["turns"]
    for n, key in enumerate(sorted(chats,
                                   key=lambda k: not k.endswith("/stale"))):
        D.save(db, [t["text"][:1200] for t in chats[key]], key, None, U.embed,
               created_at=base + n)
    for i, text in enumerate(S.commits(outputs, git)):
        D.save(db, [text[:1200]], f"commit-{i}", None, U.embed, created_at=base)
    store.stamp_embedder(db, U.EMBEDDER_ID, len(U.embed("x")))
    db.commit()
    print("raw seeded", db.execute("SELECT count(*), count(embedding) "
                                   "FROM rfm_memories").fetchone())
    db.close()


def score():
    rows = [json.loads(line) for line in open(RESULTS)]
    if "--versus" in sys.argv:
        rows += [json.loads(line) for line in open(
            os.path.join(HERE, sys.argv[sys.argv.index("--versus") + 1],
                         "results.jsonl"))]
    by = {}
    for r in rows:
        by.setdefault(r["task"], {}).setdefault(r["arm"], []).append(r)
    mean = lambda v: sum(v) / len(v) if v else 0.0
    wins = losses = ties = 0
    for arms in by.values():
        if len(arms) < 2:
            continue
        c = mean([r["corrections"] for r in arms["control"]])
        m = mean([r["corrections"] for r in arms["memory"]])
        wins += m < c
        losses += m > c
        ties += m == c
    n = wins + losses
    from math import comb
    p = sum(comb(n, k) for k in range(wins, n + 1)) / 2 ** n * 2 if n else 1.0
    for arm in ARMS:
        rs = [r for r in rows if r["arm"] == arm]
        print(f"{arm:8} runs {len(rs):3}  corrections "
              f"{mean([r['corrections'] for r in rs]):.2f}  none needed "
              f"{mean([r['corrections'] == 0 for r in rs]):.0%}  solved "
              f"{mean([r['solved'] for r in rs]):.0%}  ${mean([r['cost'] for r in rs]):.2f}"
              f"/run  ${sum(r['cost'] for r in rs):.2f} total  "
              f"{mean([r['wall_s'] for r in rs]):.0f}s  "
              f"errors {sum(bool(r['errors']) for r in rs)}")
    mem = [r for r in rows if r["arm"] == "memory"]
    print(f"tasks better {wins} worse {losses} tied {ties}  sign p {min(p, 1):.4f}")
    print(f"own chat delivered first prompt "
          f"{mean([bool(r.get('delivered', {}).get('first_own')) for r in mem]):.0%}")


def main():
    if "--score" in sys.argv:
        return score()
    sde, host, python = sys.argv[1:4]
    os.makedirs(OUT, exist_ok=True)
    if "--seed" in sys.argv:
        i = sys.argv.index("--seed")
        return seed(sde, sys.argv[i + 1], sys.argv[i + 2])
    smoke = "--smoke" in sys.argv
    reps = int(sys.argv[sys.argv.index("--reps") + 1]) if "--reps" in sys.argv \
        else 3
    source = "conversation-amended" if "--amended" in sys.argv \
        else "conversation"
    pool = tasks(sde, source)[:1] if smoke else tasks(sde, source)
    arms = sys.argv[sys.argv.index("--arms") + 1].split(",") \
        if "--arms" in sys.argv else ARMS
    out = os.path.join(OUT, "smoke.jsonl") if smoke else RESULTS
    done = set()
    if os.path.exists(out):
        for line in open(out):
            r = json.loads(line)
            done.add((r["task"], r["arm"], r["rep"]))
            SPENT[0] += r["cost"]
    jobs = [(t, a, n) for n in range(1, (1 if smoke else reps) + 1)
            for t in pool for a in arms if (t["task_id"], a, n) not in done]

    def run(job):
        with LOCK:
            if SPENT[0] >= CEILING:
                return
        row = one(sde, host, python, *job)
        with LOCK:
            SPENT[0] += row["cost"]
            with open(out, "a") as f:
                f.write(json.dumps(row) + "\n")
            print(f"{row['task']} {row['arm']} rep{row['rep']} corrections "
                  f"{row['corrections']} solved {row['solved']} ${row['cost']} "
                  f"total ${SPENT[0]:.2f} {row.get('delivered', '')} "
                  f"{row['errors'][:1]}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool_:
        list(pool_.map(run, jobs))


if __name__ == "__main__":
    sys.exit(main())
