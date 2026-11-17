#!/usr/bin/env python3
"""Track 34 — SDE-bench through the official harness. The protocol and bars are
registered in RESULTS.md; this installs the provider, builds the images, runs
the arms and scores them.

Setup: copies amb_mem_rfm.py into the harness checkout as a registered provider
(one import and one registry line appended to memory/__init__.py), builds
sdebench-base and sdebench-agent-claude if absent, and checks `amb providers`
lists mem-rfm. Auth for the agent container: CLAUDE_CODE_OAUTH_TOKEN (from
`claude setup-token`) or ANTHROPIC_API_KEY, in the environment or in
~/.sdebench/env as KEY=VALUE lines. The runner insists on GEMINI_API_KEY; the
coding mode never calls Gemini, so a placeholder is set when it is absent.

Runs: for each repeat, each arm in order, as `amb run --dataset sdebench --split
boltons --mode coding --memory ARM --category CATEGORY --name ARM-rN`. A run
whose result file exists is skipped, so the script resumes. Stops when the
agents' reported cost passes CEILING. Results are copied, compacted, into
track34/results.jsonl; the harness's full JSON stays in the checkout.

Usage: run_track34.py AMB_DIR BOLTONS_HOST [--arms mem-rfm,vanilla] [--reps 3]
         [--category conversation] [--limit N] [--setup-only] [--score]
"""
import glob
import gzip
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(HERE, "track34")
RESULTS = os.path.join(OUT, "results.jsonl")
CEILING = 30.0
PUBLISHED_VANILLA = 1.42
PUBLISHED_HINDSIGHT = 0.53


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def auth_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("RFM_")}
    path = os.path.expanduser("~/.sdebench/env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    if not (env.get("CLAUDE_CODE_OAUTH_TOKEN") or env.get("ANTHROPIC_API_KEY")) \
            and "--setup-only" not in sys.argv:
        sys.exit("no CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY: run "
                 "`claude setup-token` and put the token in ~/.sdebench/env")
    # The runner builds an answer LLM and a judge at start-up and the coding
    # mode calls neither (runner.py: a coding task's result is its pytest
    # grade). Clients are built with placeholders; the default answer LLM is
    # Groq, whose client refuses to build without a key, so it is pointed at
    # the Gemini client instead.
    env.setdefault("GEMINI_API_KEY", "placeholder-the-coding-mode-makes-no-gemini-call")
    env.setdefault("GROQ_API_KEY", "placeholder-the-coding-mode-makes-no-groq-call")
    env.setdefault("OMB_ANSWER_LLM", "gemini")
    env["SDE_AGENT"] = "claude-code"
    env["MEM_RFM_REPO"] = REPO
    env["TRACK34_DELIVERY_LOG"] = os.path.join(OUT, "delivery.jsonl")
    env["TRACK34_CACHE"] = os.path.join(OUT, "formed-cache.jsonl")
    return env


def setup(amb, host, env):
    mem = os.path.join(amb, "src", "memory_bench", "memory")
    shutil.copy(os.path.join(HERE, "amb_mem_rfm.py"),
                os.path.join(mem, "mem_rfm.py"))
    init = os.path.join(mem, "__init__.py")
    text = open(init).read()
    if "mem_rfm" not in text:
        with open(init, "a") as f:
            f.write("\nfrom .mem_rfm import MemRfmProvider  # Track 34, mem-rfm\n"
                    "REGISTRY[\"mem-rfm\"] = MemRfmProvider\n")
    sde = os.path.join(amb, "sdebench")
    for image, dockerfile in (("sdebench-base", "Dockerfile"),
                              ("sdebench-agent-claude", "Dockerfile.agent-claude")):
        if subprocess.run(["docker", "image", "inspect", image],
                          capture_output=True).returncode != 0:
            print(f"building {image}", flush=True)
            subprocess.run(["docker", "build", "-q", "-t", image, "-f",
                            os.path.join(sde, dockerfile), sde], check=True)
    env["SDEBENCH_BOLTONS_HOST"] = host
    r = subprocess.run(["uv", "run", "amb", "providers"], cwd=amb, env=env,
                       capture_output=True, text=True)
    if "mem-rfm" not in r.stdout:
        sys.exit("amb providers does not list mem-rfm:\n" + (r.stdout + r.stderr)[-1500:])
    print("setup ok: provider registered, images present", flush=True)


def result_path(amb, name):
    return os.path.join(amb, "outputs", "sdebench", name, "coding", "boltons.json")


def rows_of(amb, name):
    arm, rep = name.rsplit("-r", 1)
    data = json.load(open(result_path(amb, name)))
    for q in data["results"]:
        raw = q.get("raw_response") or {}
        yield {"task": q["query_id"], "arm": arm, "rep": int(rep),
               "corrections": raw.get("interventions"), "solved": raw.get("solved"),
               "cost": raw.get("cost_usd") or 0.0, "turns": raw.get("turns"),
               "wall_s": raw.get("wall_s"), "error": raw.get("error"),
               "model": raw.get("model")}


def spent(amb, names):
    return sum(r["cost"] for n in names if os.path.exists(result_path(amb, n))
               for r in rows_of(amb, n))


def run(amb, env, arms, reps, category, limit):
    os.makedirs(OUT, exist_ok=True)
    names = [f"{arm}-r{rep}" for rep in range(1, reps + 1) for arm in arms]
    for name in names:
        if os.path.exists(result_path(amb, name)):
            continue
        total = spent(amb, names)
        if total >= CEILING:
            print(f"stopping: reported spend ${total:.2f} passed the ceiling")
            break
        cmd = ["uv", "run", "amb", "run", "--dataset", "sdebench", "--split",
               "boltons", "--mode", "coding", "--memory", name.rsplit("-r", 1)[0],
               "--name", name]
        if category:
            cmd += ["--category", category]
        if limit:
            cmd += ["--query-limit", str(limit)]
        print(f"== {name}: {' '.join(cmd[3:])}", flush=True)
        with open(os.path.join(OUT, name + ".log"), "w") as log:
            subprocess.run(cmd, cwd=amb, env={**env, "TRACK34_RUN": name},
                           stdout=log, stderr=subprocess.STDOUT)
        if not os.path.exists(result_path(amb, name)):
            print(f"{name}: no result file, see track34/{name}.log", flush=True)
            break
        rs = list(rows_of(amb, name))
        print(f"{name}: {len(rs)} tasks, corrections "
              f"{statistics.mean(r['corrections'] or 0 for r in rs):.2f}, "
              f"solved {sum(bool(r['solved']) for r in rs)}, "
              f"${sum(r['cost'] for r in rs):.2f}, errors "
              f"{sum(bool(r['error']) for r in rs)}", flush=True)
    with open(RESULTS, "w") as f:
        for name in names:
            if os.path.exists(result_path(amb, name)):
                for r in rows_of(amb, name):
                    f.write(json.dumps(r) + "\n")


def published(amb, prefix, source="conversation"):
    """{task: [interventions per published run]}."""
    out = {}
    for run_dir in glob.glob(os.path.join(amb, "outputs", "sdebench",
                                          prefix + "-[0-9]*")):
        path = os.path.join(run_dir, "coding", "boltons.json.gz")
        if not os.path.exists(path):
            continue
        for row in json.load(gzip.open(path))["results"]:
            if (row.get("meta") or {}).get("source") != source:
                continue
            m = re.search(r"interventions=(\d+)", row.get("reasoning") or "")
            if m:
                out.setdefault(row["query_id"], []).append(int(m.group(1)))
    return out


def sign(pairs):
    """(better, worse, tied, two-sided p) over (a, b) task means, a better if lower."""
    better = sum(a < b for a, b in pairs)
    worse = sum(a > b for a, b in pairs)
    n = better + worse
    p = min(1.0, sum(comb(n, k) for k in range(max(better, worse), n + 1))
            / 2 ** n * 2) if n else 1.0
    return better, worse, len(pairs) - n, p


def score(amb):
    rows = [json.loads(line) for line in open(RESULTS)]
    by = {}
    for r in rows:
        by.setdefault(r["task"], {}).setdefault(r["arm"], []).append(r)
    mean = lambda v: statistics.mean(v) if v else float("nan")
    for arm in ("mem-rfm", "vanilla"):
        rs = [r for r in rows if r["arm"] == arm]
        if rs:
            print(f"{arm:8} runs {len(rs):3}  corrections "
                  f"{mean([r['corrections'] or 0 for r in rs]):.2f}  none needed "
                  f"{mean([r['corrections'] == 0 for r in rs]):.0%}  solved "
                  f"{mean([bool(r['solved']) for r in rs]):.0%}  "
                  f"${mean([r['cost'] for r in rs]):.2f}/run  errors "
                  f"{sum(bool(r['error']) for r in rs)}")
    own = [(mean([r["corrections"] or 0 for r in arms["mem-rfm"]]),
            mean([r["corrections"] or 0 for r in arms["vanilla"]]))
           for arms in by.values() if "mem-rfm" in arms and "vanilla" in arms]
    b, w, t, p = sign(own)
    print(f"H1 {'PASS' if p < 0.05 and b > w else 'FAIL'} own control: better {b} "
          f"worse {w} tied {t} p {p:.4f}")
    pub = published(amb, "vanilla-claude")
    mem_mean = mean([r["corrections"] or 0 for r in rows if r["arm"] == "mem-rfm"])
    pairs = [(mean([r["corrections"] or 0 for r in arms["mem-rfm"]]), mean(pub[t]))
             for t, arms in by.items() if "mem-rfm" in arms and t in pub]
    b, w, t, p = sign(pairs)
    print(f"H2 {'PASS' if mem_mean < PUBLISHED_VANILLA and p < 0.05 and b > w else 'FAIL'} "
          f"published vanilla: mean {mem_mean:.2f} against {PUBLISHED_VANILLA}, "
          f"better {b} worse {w} tied {t} p {p:.4f} over {len(pairs)} tasks")
    log = os.path.join(OUT, "delivery.jsonl")
    hits, n = 0, 0
    if os.path.exists(log):
        for line in open(log):
            d = json.loads(line)
            if d.get("run", "").startswith("mem-rfm"):
                n += 1
                hits += any(s.startswith(f"{d['task']}:chat") for s in d["sources"])
    print(f"H3 {'PASS' if n and hits / n >= 0.6 else 'FAIL'} own chat delivered "
          f"{hits}/{n}")
    cm = mean([r["cost"] for r in rows if r["arm"] == "mem-rfm"])
    cv = mean([r["cost"] for r in rows if r["arm"] == "vanilla"])
    print(f"H4 {'PASS' if cm <= cv * 1.15 else 'FAIL'} cost ${cm:.3f} against "
          f"${cv:.3f} ({(cm / cv - 1) * 100:+.0f}%)")
    hs = published(amb, "hindsight-claude")
    if hs:
        print(f"published hindsight-claude on these tasks: "
              f"{mean([mean(v) for v in hs.values()]):.2f} (documented {PUBLISHED_HINDSIGHT})")


def main():
    amb, host = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    if "--score" in sys.argv:
        return score(amb)
    env = auth_env()
    setup(amb, host, env)
    if "--setup-only" in sys.argv:
        return 0
    run(amb, env, arg("--arms", "mem-rfm,vanilla").split(","),
        int(arg("--reps", "3")), arg("--category", "conversation"),
        int(arg("--limit", "0")))
    return score(amb)


if __name__ == "__main__":
    sys.exit(main())
