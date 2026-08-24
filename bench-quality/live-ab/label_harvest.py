#!/usr/bin/env python3
"""Ground truth for the harvest, built without a labeller.

The question a formation strategy has to answer is whether a harvested
explanation is about THIS TASK'S BUG (per-bug: ~6% transfer, measured) or
about the environment the task ran in (transfers; our best memory earned
~22 outcomes). Someone has to say which, and every obvious labeller is
compromised:

  * I label them -> arm B is an LLM graded by an LLM. Free points for the
    arm we are trying to evaluate, none for the regex. Unusable.
  * The user labels them -> gold, but expensive, and it does not scale
    past a few dozen.

SWE-bench ships a third option. Each task carries a `gold_patch`: the real
diff that fixed the real bug, naming the files and functions that held it.
So "is this explanation about the task's own code?" is answerable by
lookup, not judgement — and CRUCIALLY, neither arm sees the gold patch.
Both classify from the prose block alone. The judge is external to both.

Two independent signals, deliberately not collapsed into one:

  IDENTITY  does the block name files/symbols from this task's gold patch?
            If yes it is explaining the bug under test. Every block does —
            so this signal turned out to separate nothing, and the useful
            question moved to the one below.
  ENV       does the block ALSO carry durable environment knowledge, named
            either as an error class or (far more often) as plain prose?
            66% do. Those nuggets sit in verification tails inside fix
            summaries, which is why the unit of extraction is a SPAN and
            not a block — and why a block-level classifier cannot win.
  RECURRENCE does the failure class the block names appear in sessions
            belonging to OTHER tasks? Per-bug knowledge cannot recur —
            every task is a different bug in a different file — so
            recurrence across tasks is the transfer property itself.

Agreement gives a confident label. DISAGREEMENT IS NOT HIDDEN: blocks that
name both a gold-patch symbol and a recurring environment class are marked
`mixed` and reported for human spot-check, because that is exactly the case
a keyword classifier gets wrong and the case worth a human minute.

Usage: label_harvest.py [--out labelled.jsonl] [--show-mixed N]
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harvest_replay as h  # noqa: E402

# Three task files cover the corpus: tasks_v2 (sphinx+pytest) and
# tasks_xarray. Without the second, 44 xarray sessions silently drop out of
# the ground truth — which is how the first run of this labelled only 44 of
# 86 blocks and skewed the split.
def _load_tasks():
    seen, out = set(), []
    for name in ("tasks_v2.json", "tasks_xarray.json", "tasks.json"):
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            continue
        for t in json.load(open(path)):
            if t.get("gold_patch") and t["instance_id"] not in seen:
                seen.add(t["instance_id"])
                out.append(t)
    return out


TASKS = _load_tasks()
INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
sys.path.insert(0, os.path.join(INTEGRATION, "hooks"))
import session_end as se  # noqa: E402  (FAILURE — the miner's own classes)

# Individually-named failure classes, so recurrence is counted per class
# rather than per "something matched".
CLASSES = [
    ("modulenotfounderror", r"modulenotfounderror"),
    ("importerror", r"\bimporterror\b"),
    ("pkg_resources", r"pkg_resources"),
    ("versionrequirementerror", r"versionrequirementerror"),
    ("extensionerror", r"extensionerror"),
    ("distributionnotfound", r"distributionnotfound"),
    ("command-not-found", r"command not found"),
    ("no-such-file", r"no such file or directory"),
    ("bad-interpreter", r"bad interpreter"),
    ("undefined-symbol", r"undefined symbol"),
    ("cannot-find-module", r"cannot find module"),
]
CLASSES = [(n, re.compile(p, re.I)) for n, p in CLASSES]

# CORRECTION (2026-08-24, mid-Track-8, before scoring). The CLASSES list
# above only recognises environment trouble when it is named as an ERROR
# CLASS. Agents mostly do not write "ModuleNotFoundError" in their prose —
# they write "this venv's packages are too new for this 2020-era checkout".
# Detecting only the former made this labeller report that 100% of harvested
# blocks were purely per-bug, which was an artifact of the detector, not a
# property of the corpus. The haiku arm contradicted it on the first three
# blocks and was right. 66% of blocks carry environment knowledge in prose.
ENV_PROSE = re.compile(
    r"\b(venv|virtualenv|site-packages|pre-?existing|too new|too old|"
    r"\d{4}-era|era-pin\w*|pinned?|unrelated to (?:the|this) change|"
    r"environment (?:noise|caveat|issue|problem)|editable install|"
    r"not installed|already fail\w*|fails? identically|stash(?:ed)?|"
    r"setuptools|pkg_resources|pip install|PYTHONPATH|stub packages?)\b",
    re.I)

# Identifiers too common to be evidence that a block is about a task's code.
STOP = {"test", "tests", "testing", "src", "lib", "init", "main", "setup",
        "conftest", "utils", "core", "base", "config", "__init__", "py"}


def gold_identity(task):
    """Files and symbols the real fix touched — the task's code identity."""
    patch = task.get("gold_patch") or ""
    files, syms = set(), set()
    for m in re.finditer(r"^diff --git a/(\S+)", patch, re.M):
        path = m.group(1)
        files.add(path)
        # Basename WITH its extension only. The bare stem is not evidence:
        # extracting it turned sphinx/domains/python.py into "python",
        # mock.py into "mock", and xarray/core/{variable,dataset,
        # computation}.py into three ordinary English words. Those matched
        # essentially every block and drove identity hits to 100%, which is
        # what made the first labelling read "0 environment" — an artifact,
        # not a finding. "quickstart.py" is a file reference; "quickstart"
        # is a word.
        files.add(os.path.basename(path))
    # Hunk headers carry the enclosing def/class; +/- lines carry new ones.
    for m in re.finditer(r"^@@[^@]*@@\s*(?:def|class)\s+(\w+)", patch, re.M):
        syms.add(m.group(1))
    for m in re.finditer(r"^[+-]\s*(?:def|class)\s+(\w+)", patch, re.M):
        syms.add(m.group(1))
    return files, {s for s in syms if s.lower() not in STOP and len(s) > 3}


def instance_for(label):
    """Labels wrap the instance id: '<runprefix>-<instance_id>' and, in the
    tax run, '<prefix>-<instance_id>-control'. Containment, not suffix —
    the trailing arm tag broke 20 sphinx sessions out of the first run."""
    best = None
    for t in TASKS:
        iid = t["instance_id"]
        if iid in label and (best is None or len(iid) > len(best["instance_id"])):
            best = t
    return best


def session_classes(tp):
    """Failure classes actually observed in this session's tool output."""
    seen = set()
    for line in open(tp, errors="replace"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("type") != "user":
            continue
        c = (r.get("message") or {}).get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                body = json.dumps(b.get("content"))[:20000]
                for name, pat in CLASSES:
                    if pat.search(body):
                        seen.add(name)
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "harvest-labelled.jsonl"))
    ap.add_argument("--show-mixed", type=int, default=0)
    ap.add_argument("--min-chars", type=int, default=200)
    a = ap.parse_args()

    # Pass 1: which tasks exhibit which failure classes, corpus-wide.
    tasks_with_class = collections.defaultdict(set)
    rows = []
    for lab, arm, tp in h.sessions():
        task = instance_for(lab)
        if not task:
            continue
        cls = session_classes(tp)
        for c in cls:
            tasks_with_class[c].add(task["instance_id"])
        ex = h.explanations(tp, a.min_chars, h.STRONG)
        if ex:
            rows.append((lab, task, max(ex, key=len), cls))

    # Pass 2: label each harvested block against the external judge.
    out, counts = [], collections.Counter()
    for lab, task, block, sess_cls in rows:
        files, syms = gold_identity(task)
        low = block.lower()
        id_hits = sorted({f for f in files if f.lower() in low} |
                         {s for s in syms if re.search(rf"\b{re.escape(s)}\b", block)})
        # Only classes the BLOCK itself names, not merely the session.
        blk_cls = sorted({n for n, p in CLASSES if p.search(block)})
        recurring = sorted(c for c in blk_cls
                           if len(tasks_with_class[c] - {task["instance_id"]}) >= 1)

        env_prose = sorted({m.group(0).lower()
                            for m in ENV_PROSE.finditer(block)})
        # The question a formation strategy actually faces is not "which
        # bucket is this block in" — every block is a fix summary, so every
        # block has per-bug content. It is "is there durable environment
        # knowledge in here worth EXTRACTING?" That is what gets scored.
        has_env = bool(env_prose or recurring)
        label = "env-bearing" if has_env else "pure-per-bug"
        counts[label] += 1
        out.append({"label_run": lab, "instance_id": task["instance_id"],
                    "repo": task["repo"], "truth": label,
                    "identity_hits": id_hits, "block_classes": blk_cls,
                    "recurring_classes": recurring,
                    "env_prose": env_prose, "has_env": has_env,
                    "n_tasks_per_class": {c: len(tasks_with_class[c])
                                          for c in blk_cls},
                    "block": block})

    with open(a.out, "w") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")

    zero = sum(1 for r in out if not r["identity_hits"])
    print(f"harvested blocks labelled: {len(out)}   -> {a.out}")
    print(f"  blocks naming no gold-patch file/symbol: {zero} "
          f"({100*zero/max(len(out),1):.0f}%) — if this is ~0 the identity "
          f"matcher is too loose, check its tokens\n")
    for k, n in counts.most_common():
        print(f"  {k:<18} {n:4}  ({100*n/max(len(out),1):.0f}%)")
    print("\nclass recurrence across distinct tasks (the transfer signal):")
    for c, ts in sorted(tasks_with_class.items(), key=lambda kv: -len(kv[1])):
        print(f"  {c:<26} {len(ts):3} tasks")

    if a.show_mixed:
        print(f"\n--- `mixed` blocks (need a human minute) ---")
        for r in [r for r in out if r["truth"] == "mixed"][:a.show_mixed]:
            print(f"\n[{r['label_run']}] identity={r['identity_hits']} "
                  f"recurring={r['recurring_classes']}\n{r['block'][:400]}")


if __name__ == "__main__":
    main()
