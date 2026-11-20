#!/usr/bin/env python3
"""Track 36 — CL-Bench through its own harness. The protocol and bars are
registered in RESULTS.md; this installs the system, smokes it, runs the arms
under the stop rule, and copies the results.

Setup: copies clbench_mem_rfm.py into the harness checkout as
`src/systems/mem_rfm/system.py` with an `__init__.py`, so the registry finds
it, then checks `clbench list` names mem_rfm. The checkout is expected at
bench-quality/data/clbench (gitignored; `git clone --depth 1
https://github.com/pgasawa/continual-learning-bench`), synced with
`uv sync --extra poker`, with `clbench setup database_exploration` done.

Smoke: `clbench smoke database_exploration --system mem_rfm` runs two
interactions end to end. Not an arm; its model is whatever --model says.

Runs: `clbench run TASK --system ARM --schedule default --system.model MODEL
--runs N` per arm. The harness runs the stateless baseline itself and
computes reward and gain. Output goes under the checkout's results/, and
this copies each run's summary into track36/. The stop rule reads the
harness's reported cost after each run and refuses the next past CEILING.
--score reads the trace files (results/<task>/traces/<group>/{baseline,run_N}
.json) and prints D1-D4. Cost is the upstream provider charge OpenRouter
reports per call (litellm prices nothing on that route), summed per run.

Usage: run_track36.py [--clbench DIR] [--model ID] --setup-only | --smoke |
         --run [--arms mem_rfm,icl_cached] [--reps 3] [--ceiling 30]
               [--task database_exploration] | --score [--arms ...]
"""
import glob
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(HERE, "track36")
CEILING = 30.0
SMOKE_MODEL = "gpt-5-mini"


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def env():
    e = {k: v for k, v in os.environ.items() if not k.startswith("RFM_")}
    e["MEM_RFM_REPO"] = REPO
    return e


SYSTEMS = (("mem_rfm", "clbench_mem_rfm.py", "MemRfmSystem"),
           ("icl_cached", "clbench_icl_cached.py", "ICLCachedSystem"))


def setup(clb):
    for name, source, cls in SYSTEMS:
        dest = os.path.join(clb, "src", "systems", name)
        os.makedirs(dest, exist_ok=True)
        shutil.copy(os.path.join(HERE, source), os.path.join(dest, "system.py"))
        with open(os.path.join(dest, "__init__.py"), "w") as f:
            f.write(f'"""{name} system (Track 36; source: mem-rfm '
                    f'bench-quality/live-ab/{source})."""\n'
                    f"from .system import {cls}\n\n"
                    f'__all__ = ["{cls}"]\n')
    r = subprocess.run(["uv", "run", "clbench", "list"], cwd=clb, env=env(),
                       capture_output=True, text=True)
    missing = [n for n, _s, _c in SYSTEMS if n not in r.stdout + r.stderr]
    if missing:
        sys.exit(f"clbench list does not name {missing}:\n" + (r.stdout + r.stderr)[-1500:])
    print("setup ok: " + ", ".join(n for n, _s, _c in SYSTEMS) + " registered", flush=True)


def smoke(clb, model, task):
    cmd = ["uv", "run", "clbench", "smoke", task, "--system", "mem_rfm",
           "--system.model", model, "--debug"]
    print("== " + " ".join(cmd[2:]), flush=True)
    return subprocess.call(cmd, cwd=clb, env=env())


def run(clb, model, task, arms, reps, ceiling=CEILING):
    os.makedirs(OUT, exist_ok=True)
    for arm in arms:
        log = os.path.join(OUT, f"{task}-{arm}.log")
        cmd = ["uv", "run", "clbench", "run", task, "--system", arm,
               "--schedule", "default", "--system.model", model,
               "--runs", str(reps)]
        if arm == "icl":
            # icl's "auto" provider mode sends a Claude id to the harness's
            # native Anthropic client, which wants ANTHROPIC_API_KEY; through
            # OpenRouter both arms must take litellm's chat path, as mem_rfm
            # does by construction and icl_cached does by default. The CLI
            # hyphenates parameter names.
            cmd += ["--system.provider-mode", "litellm_chat"]
        print(f"== {arm}: {' '.join(cmd[2:])}", flush=True)
        with open(log, "a") as fh:
            rc = subprocess.call(cmd, cwd=clb, env=env(), stdout=fh,
                                 stderr=subprocess.STDOUT)
        print(f"   exit {rc}; log {log}", flush=True)
        spent = reported_spend(clb)
        if spent is not None and spent >= ceiling:
            print(f"stopping: reported spend ${spent:.2f} passed the ceiling ${ceiling:.0f}")
            break


def result_files(clb, task=None):
    """Every finished trace file the harness wrote: results/<task>/traces/
    <group>/{baseline,run_NNNN}.json. Live snapshots and failed stubs are
    left out."""
    root = os.path.join(clb, "results")
    for task_dir in sorted(glob.glob(os.path.join(root, task or "*"))):
        for path in sorted(glob.glob(os.path.join(task_dir, "traces", "*", "*.json"))):
            yield path


def events_of(data):
    """Every billable call recorded in a trace file, rollout or baseline."""
    for inter in data.get("interactions", []) or []:
        usage = inter.get("usage") or {}
        for kind in ("respond", "observe"):
            for ev in (usage.get(kind) or {}).get("events", []) or []:
                yield ev
    for trace in data.get("instance_traces", []) or []:
        for inter in trace.get("interactions", []) or []:
            usage = inter.get("usage") or {}
            for kind in ("respond", "observe"):
                for ev in (usage.get(kind) or {}).get("events", []) or []:
                    yield ev


def event_cost(ev):
    """Dollars for one call. litellm prices nothing on the openrouter/ route
    (cost_usd 0, pricing_complete false), but OpenRouter's raw usage carries
    the upstream provider's charge under cost_details, which on a BYOK key
    is what the operator pays Anthropic. Fall back to litellm's figure."""
    raw = ev.get("raw_usage") or {}
    details = raw.get("cost_details") or {}
    up = details.get("upstream_inference_cost")
    if isinstance(up, (int, float)) and up > 0:
        return float(up)
    for key in ("cost", "cost_usd"):
        v = raw.get(key) if key == "cost" else ev.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return 0.0


def spend_of(data):
    return sum(event_cost(ev) for ev in events_of(data))


def reported_spend(clb):
    """Dollars across every finished trace file, or None when there is none."""
    files = list(result_files(clb))
    if not files:
        return None
    total = 0.0
    for path in files:
        try:
            total += spend_of(json.load(open(path)))
        except (OSError, json.JSONDecodeError):
            continue
    return total


def load_runs(clb, task, system):
    """[(kind, run_index, data)] for one system, from its NEWEST trace group:
    kind is 'baseline' or 'rollout'. An earlier group of the same system is a
    superseded attempt (icl_cached's first run, whose cache never read) and
    stays on disk as the record."""
    out = []
    groups = {}
    for path in result_files(clb, task):
        groups.setdefault(os.path.basename(os.path.dirname(path)), []).append(path)
    chosen = []
    for gid in sorted(groups):
        try:
            data = json.load(open(groups[gid][0]))
        except (OSError, json.JSONDecodeError):
            continue
        sysinfo = data.get("system") or {}
        # The arm's name is the system's `name` parameter when one was passed
        # (mem_rfm_flat, mem_rfm_cached are the mem_rfm class under other
        # names); the registry name is the fallback.
        arm = (sysinfo.get("params") or {}).get("name") or sysinfo.get("name") \
            or sysinfo.get("system_name")
        if str(arm) == system:
            chosen = groups[gid]           # later groups replace earlier ones
    for path in chosen:
        try:
            data = json.load(open(path))
        except (OSError, json.JSONDecodeError):
            continue
        kind = "baseline" if os.path.basename(path).startswith("baseline") else "rollout"
        out.append((kind, (data.get("execution") or {}).get("run_index"), data))
    return out


def rewards_of(data):
    """{instance_id: (instance_index, reward)} from a trace file."""
    out = {}
    for o in (data.get("result") or {}).get("instance_outcomes", []) or []:
        out[o["instance_id"]] = (o.get("instance_index"), float(o["reward"]))
    return out


def bootstrap_ci(xs, n=10000, seed=7):
    import random
    rng = random.Random(seed)
    xs = list(xs)
    if not xs:
        return (float("nan"), float("nan"))
    means = sorted(sum(rng.choice(xs) for _ in xs) / len(xs) for _ in range(n))
    return (means[int(0.025 * n)], means[int(0.975 * n) - 1])


def score(clb, task, arms):
    """D1-D4 from the trace files. Prints; returns a dict for the record."""
    sys.path.insert(0, os.path.join(REPO, "bench-quality"))
    report = {}
    per_arm = {}
    for arm in arms:
        runs = load_runs(clb, task, arm)
        base = [d for k, _i, d in runs if k == "baseline"]
        rolls = [d for k, _i, d in runs if k == "rollout"]
        if not base or not rolls:
            print(f"{arm}: baseline {len(base)}, rollouts {len(rolls)}: not scorable yet")
            continue
        b = rewards_of(base[0])
        # A baseline instance runs alone, so its own instance_index is 0;
        # the stage a question belongs to comes from the rollouts, whose
        # index places it before (< 20) or after the migration.
        stage = {}
        for d in rolls:
            for iid, (idx, _rew) in rewards_of(d).items():
                if idx is not None:
                    stage[iid] = idx
        gains, pre_post = [], {"base_post": [], "roll_post": []}
        roll_means, costs = [], []
        for d in rolls:
            r = rewards_of(d)
            roll_means.append(sum(v for _i, v in r.values()) / max(1, len(r)))
            costs.append(spend_of(d))
            for iid, (idx, rew) in r.items():
                if iid in b:
                    gains.append(rew - b[iid][1])
                if idx is not None and idx >= 20:
                    pre_post["roll_post"].append(rew)
        for iid, (_idx, rew) in b.items():
            if stage.get(iid, -1) >= 20:
                pre_post["base_post"].append(rew)
        base_mean = sum(v for _i, v in b.values()) / max(1, len(b))
        roll_mean = sum(roll_means) / len(roll_means)
        lo, hi = bootstrap_ci(gains)
        per_arm[arm] = {
            "baseline_mean": base_mean, "rollout_mean": roll_mean,
            "runs": len(rolls),
            "normalized_gain": (roll_mean - base_mean) / (1.0 - base_mean)
            if base_mean < 1.0 else None,
            "gain_ci": (lo, hi),
            "post_base": sum(pre_post["base_post"]) / max(1, len(pre_post["base_post"])),
            "post_roll": sum(pre_post["roll_post"]) / max(1, len(pre_post["roll_post"])),
            "cost_per_run": sum(costs) / len(costs), "baseline_cost": spend_of(base[0]),
        }
        a = per_arm[arm]
        print(f"{arm}: {a['runs']} runs; baseline {a['baseline_mean']:.3f}, rollout "
              f"{a['rollout_mean']:.3f}, normalized gain "
              f"{a['normalized_gain'] if a['normalized_gain'] is None else round(a['normalized_gain'], 3)}, "
              f"per-question gain CI [{lo:+.3f}, {hi:+.3f}]; post-migration baseline "
              f"{a['post_base']:.3f} vs rollout {a['post_roll']:.3f}; cost/run "
              f"${a['cost_per_run']:.2f} (baseline ${a['baseline_cost']:.2f})")
    m = per_arm.get("mem_rfm")
    i = per_arm.get("icl") or per_arm.get("icl_cached")
    flat = per_arm.get("mem_rfm_flat")
    if m and flat:
        # Track 36b, B1: the full arm against the same arm with outcomes
        # never recorded, on the post-migration half, paired per question
        # across the runs (run k of one arm against run k of the other).
        full_runs = [d for k, _i, d in load_runs(clb, task, "mem_rfm") if k == "rollout"]
        flat_runs = [d for k, _i, d in load_runs(clb, task, "mem_rfm_flat") if k == "rollout"]
        diffs = []
        for a, b in zip(full_runs, flat_runs):
            ra, rb = rewards_of(a), rewards_of(b)
            for iid, (idx, rew) in ra.items():
                if iid in rb and idx is not None and idx >= 20:
                    diffs.append(rew - rb[iid][1])
        lo, hi = bootstrap_ci(diffs)
        mean = sum(diffs) / max(1, len(diffs))
        report["B1"] = "PASS" if mean >= 0.05 and lo > 0 else "FAIL"
        print(f"B1 {report['B1']}: full - flat on post-migration {mean:+.3f} "
              f"CI [{lo:+.3f}, {hi:+.3f}] over {len(diffs)} pairs (bar +0.05, CI > 0); "
              f"means full {m['post_roll']:.3f} flat {flat['post_roll']:.3f}, "
              f"whole run {m['rollout_mean']:.3f} vs {flat['rollout_mean']:.3f}")
    if m:
        report["D1"] = "PASS" if m["gain_ci"][0] > 0 else "FAIL"
        report["D2"] = "PASS" if m["post_roll"] >= m["post_base"] else "FAIL"
        print(f"D1 {report['D1']}: gain CI lower bound {m['gain_ci'][0]:+.3f}")
        print(f"D2 {report['D2']}: post-migration {m['post_roll']:.3f} vs baseline {m['post_base']:.3f}")
    if m and i:
        report["D3"] = "PASS" if m["rollout_mean"] >= i["rollout_mean"] - 0.05 else "FAIL"
        report["D4"] = "PASS" if m["cost_per_run"] <= i["cost_per_run"] else "FAIL"
        print(f"D3 {report['D3']}: mem_rfm {m['rollout_mean']:.3f} vs icl {i['rollout_mean']:.3f} (bar: icl - 0.05)")
        print(f"D4 {report['D4']}: ${m['cost_per_run']:.2f} vs ${i['cost_per_run']:.2f} per run")
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"{task}-score.json"), "w") as f:
        json.dump({"arms": per_arm, "bars": report}, f, indent=1, default=str)
    return report


def main():
    clb = os.path.abspath(arg("--clbench", os.path.join(REPO, "bench-quality",
                                                         "data", "clbench")))
    model = arg("--model", SMOKE_MODEL)
    task = arg("--task", "database_exploration")
    if not os.path.isdir(os.path.join(clb, "src", "systems")):
        sys.exit(f"no CL-Bench checkout at {clb}")
    setup(clb)
    if "--setup-only" in sys.argv:
        return 0
    if "--smoke" in sys.argv:
        return smoke(clb, model, task)
    if "--run" in sys.argv:
        if "--model" not in sys.argv:
            sys.exit("--run needs --model, named before the first arm "
                     "(RESULTS.md, Track 36)")
        arms = arg("--arms", "mem_rfm,icl").split(",")
        spent = reported_spend(clb) or 0.0
        ceiling = float(arg("--ceiling", str(CEILING)))
        if spent >= ceiling:
            sys.exit(f"reported spend ${spent:.2f} already passes the ceiling ${ceiling:.0f}")
        run(clb, model, task, arms, int(arg("--reps", "3")), ceiling)
        return 0
    if "--score" in sys.argv:
        score(clb, task, arg("--arms", "mem_rfm,icl").split(","))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
