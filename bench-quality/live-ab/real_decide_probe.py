#!/usr/bin/env python3
"""Track 32 — does `decide` form true, durable memories from real sessions?

Tracks 29 and 30 formed memories from SDE-bench's seeded chats, written to hold
one decision each. Real sessions are long, wander and rarely announce a rule.
This forms a sample of the operator's own interactive Claude Code sessions,
window by window as `decide` now does, and has a judge rate each memory against
the window it came from. Outputs quote private work, so they go to OUT_DIR,
never the repository; only counts are reported.

Sample: interactive sessions (entrypoint cli) longer than one window, from
~/.claude/projects, excluding any path given with --exclude, drawn with seed 32.

Bars, written before the first call:
  W1  faithful: at least 80% of memories state what the window decided, not a
      rejected proposal, a guess or something absent.
  W2  durable: at least 50% are rules a later agent in that repository should
      follow, rather than task status, a one-off detail or generic advice.
  W3  windows matter: memories both faithful and durable from windows after the
      first number at least those from the first. Below that, reading only the
      head, as decide did, lost little.
      Counted, after the first run, over sessions read whole only: a session
      past MAX_WINDOWS never forms its first window, which the first run's
      count missed.
Also counted, no bar: memories the secret scan redacted.

Usage: real_decide_probe.py OUT_DIR [--n 8] [--exclude PATH ...]
"""
import concurrent.futures
import glob
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, INTEGRATION)
sys.path.insert(0, os.path.join(INTEGRATION, "hooks"))
import decisions as D   # noqa: E402
import secret_scan      # noqa: E402
import sweep            # noqa: E402

JUDGE_MODEL = "sonnet"
WORKERS = 6
JUDGE = """Below is part of a conversation between a developer and a coding
agent, and a memory another model formed from it for an agent that will work
in the same repository later.

--- BEGIN CONVERSATION PART ---
{window}
--- END CONVERSATION PART ---

Memory: {memory}

Answer two questions.
faithful: does this part of the conversation support the memory as stated, as
something the developer decided or accepted? false if it was proposed and
rejected, is guessed, contradicts the text, or is not there.
durable: is it a rule a later agent working in this repository should follow,
such as a convention, constraint, value or decision? false if it is task
status, a one-off detail of this session, or advice that holds anywhere.

Reply with JSON only: {{"faithful": true|false, "durable": true|false}}"""


def interactive(path):
    with open(path) as f:
        for n, line in enumerate(f):
            if n > 50:
                return False
            if '"entrypoint"' in line:
                return json.loads(line).get("entrypoint") == "cli"
    return False


def judge(window, memory):
    r = subprocess.run(["claude", "-p", "--model", JUDGE_MODEL,
                        JUDGE.format(window=window, memory=memory)],
                       env={**os.environ, "RFM_HOOKS_OFF": "1"},
                       capture_output=True, text=True, timeout=300)
    parsed = sweep.parse_json(r.stdout)
    return parsed if isinstance(parsed, dict) else {}


def main():
    out = sys.argv[1]
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 8
    exclude = {os.path.abspath(a) for a in sys.argv[2:] if a.endswith(".jsonl")}
    os.makedirs(out, exist_ok=True)
    pool = []
    for path in sorted(glob.glob(os.path.expanduser(
            "~/.claude/projects/*/*.jsonl"))):
        if os.path.abspath(path) in exclude or not interactive(path):
            continue
        chat = D.chat_of(path)
        if len(chat) > D.CAP:
            pool.append((path, chat))
    sample = random.Random(32).sample(pool, min(n, len(pool)))
    print(f"interactive sessions over one window: {len(pool)}, sampled "
          f"{len(sample)}")

    jobs = []
    for s, (path, chat) in enumerate(sample):
        parts = D.windows(chat)
        skipped = max(0, len(parts) - D.MAX_WINDOWS)
        for w in range(skipped, len(parts)):
            jobs.append((s, w, parts[w]))
    whole = {s for s, (_p, chat) in enumerate(sample)
             if len(D.windows(chat)) <= D.MAX_WINDOWS}
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
        formed = list(ex.map(
            lambda j: D.form(j[2], sweep.llm, sweep.parse_json), jobs))
    items = [(s, w, part, m) for (s, w, part), ms in zip(jobs, formed)
             for m in ms]
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
        verdicts = list(ex.map(lambda i: judge(i[2], i[3]), items))

    rows = []
    for (s, w, _part, m), v in zip(items, verdicts):
        rows.append({"session": s, "window": w, "memory": m, "text": _part,
                     "redacted": secret_scan.redact(m)[0] != m,
                     "faithful": v.get("faithful") is True,
                     "durable": v.get("durable") is True})
    with open(os.path.join(out, "track32.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    total = len(rows) or 1
    faithful = sum(r["faithful"] for r in rows)
    durable = sum(r["durable"] for r in rows)
    good = [r for r in rows if r["faithful"] and r["durable"]
            and r["session"] in whole]
    first = sum(r["window"] == 0 for r in good)
    later = len(good) - first
    print(f"windows formed {len(jobs)}, memories {len(rows)}, "
          f"sessions with any {len({r['session'] for r in rows})}")
    print(f"W1 {'PASS' if faithful / total >= 0.8 else 'FAIL'} faithful "
          f"{faithful}/{len(rows)} = {faithful / total:.0%}")
    print(f"W2 {'PASS' if durable / total >= 0.5 else 'FAIL'} durable "
          f"{durable}/{len(rows)} = {durable / total:.0%}")
    print(f"W3 {'PASS' if later >= first else 'FAIL'} faithful and durable, "
          f"{len(whole)} sessions read whole: first window {first}, later "
          f"windows {later}")
    print(f"redacted by the secret scan: {sum(r['redacted'] for r in rows)}")


if __name__ == "__main__":
    sys.exit(main())
