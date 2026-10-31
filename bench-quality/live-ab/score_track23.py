#!/usr/bin/env python3
"""Score Track 23 (show-on-error, live) against its registered bars.

Reads track23/results.jsonl and the transcripts the runner copied into
track23/transcripts/ (never ~/.claude/projects, which Claude Code prunes).

Metric of record: Bash events before the first pytest run that names one
of the task's required test files and shows a clean summary ("first
verified"); a session that never gets one ranks below any that does.
"Clean" is read from the output, not the exit code: agents pipe pytest
through tail, which makes every run exit 0 and can cut the error text.

Output means the whole Bash result. transcripts.claude_events keeps only
its first 800 characters and pytest's summary comes last, so the scorer as
registered misread long runs; full_bodies restores them, and the 800-char
reading is still printed for comparison.

Usage: score_track23.py [--dir track23-smoke]
"""
import collections
import datetime
import json
import math
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formation_study as F  # noqa: E402
import run_track23 as T      # noqa: E402
sys.path.insert(0, os.path.join(HERE, "..", "..", "integrations", "claude-code"))
import transcripts as X      # noqa: E402

se = F.se
CUT = 800

ERA = re.compile(r"VersionRequirementError|ExtensionError", re.I)
CLASS = re.compile(r"VersionRequirementError", re.I)   # the memory's class
NOTE = "[rfm-memory]"
SUMMARY = re.compile(r"\b\d+ (?:passed|failed|errors?)\b")
SHIM_WRITE = re.compile(r"(>|tee|cat\s*>).{0,60}sitecustomize")
PATH_PYTEST = re.compile(r"PYTHONPATH=\S+.*pytest")


def sign_p(wins, decided):
    """One-sided binomial P(X >= wins | n=decided, p=0.5)."""
    if decided == 0:
        return 1.0
    return sum(math.comb(decided, k) for k in range(wins, decided + 1)) \
        / 2 ** decided


def notes_in(tp):
    """Mod deliveries: hook_additional_context attachments carrying the
    [rfm-memory] note, with the memory ids they showed."""
    shown = []
    for line in open(tp):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        a = d.get("attachment") or {}
        if d.get("type") == "attachment" and \
                a.get("type") == "hook_additional_context":
            for c in a.get("content") or []:
                if str(c).startswith(NOTE):
                    shown.append([int(i) for i in
                                  re.findall(r'<memory id="(\d+)">', c)])
    return shown


def note_positions(tp):
    """{memory id: index of the first Bash event after its note}. Mod notes
    are not an exposure format transcripts.read knows, so the offline
    comparison places them here; the note follows the result it answered,
    and matching starts at the memory's first appearance."""
    seen, out = set(), {}
    for line in open(tp):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        for b in (d.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and \
                    b.get("name") == "Bash":
                seen.add(b["id"])
        a = d.get("attachment") or {}
        if d.get("type") == "attachment" and \
                a.get("type") == "hook_additional_context":
            for c in a.get("content") or []:
                if str(c).startswith(NOTE):
                    for mid in re.findall(r'<memory id="(\d+)">', c):
                        out.setdefault(int(mid), len(seen))
    return out


def offline_outcomes(tp, events, store):
    """session_end.infer_outcomes over the same transcript, given where the
    mod showed each memory: what the SessionEnd path would have recorded."""
    mems = {mid: (store[mid], idx) for mid, idx in note_positions(tp).items()}
    return se.infer_outcomes(mems, events)


def acted_commands(tp, events, store):
    """Commands acted_on credits to a shown memory, whatever their result:
    0 means the matcher never engaged, not that outcomes were abstained."""
    n = 0
    for mid, idx in note_positions(tp).items():
        sig = se._signature(store[mid])
        n += sum(1 for e in events[idx:] if se.acted_on(sig, e.cmd))
    return n


def timing(tp):
    """(output tokens deduplicated by message id, transcript span in s)."""
    tokens, stamps = {}, []
    for line in open(tp):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("timestamp"):
            stamps.append(d["timestamp"])
        m = d.get("message") or {}
        if d.get("type") == "assistant":
            tokens[m.get("id")] = (m.get("usage") or {}).get("output_tokens", 0)
    span = 0.0
    if stamps:
        at = lambda t: datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))
        span = (at(stamps[-1]) - at(stamps[0])).total_seconds()
    return sum(tokens.values()), span


def built_shim(tp):
    """Did the session write a sitecustomize.py, the memory's workaround?
    acted_on cannot see this: the stored command has a placeholder path."""
    for line in open(tp):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        for b in (d.get("message") or {}).get("content") or []:
            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                continue
            i = b.get("input") or {}
            if b.get("name") in ("Write", "Edit") and \
                    "sitecustomize" in str(i.get("file_path")):
                return True
            if b.get("name") == "Bash" and \
                    SHIM_WRITE.search(i.get("command") or ""):
                return True
    return False


def full_bodies(tp):
    """Each Bash event's whole result, in claude_events' order."""
    pending, out = {}, []
    for d in X.main_thread(X.parse_jsonl(tp)):
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if X.is_bash_call(b):
                pending[b.get("id")] = len(out)
                out.append("")
            elif b.get("type") == "tool_result":
                i = pending.pop(b.get("tool_use_id"), None)
                if i is not None:
                    out[i] = X._result_text(b.get("content")) or ""
    return out


def tokens_at_bash(tp):
    """(cumulative output tokens at each Bash call, session total)."""
    seen, marks = {}, []
    for line in open(tp):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        m = d.get("message") or {}
        seen[m.get("id")] = (m.get("usage") or {}).get("output_tokens", 0)
        for b in m.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and \
                    b.get("name") == "Bash":
                marks.append(sum(seen.values()))
    return marks, sum(seen.values())


def split_at(tp, k):
    """Output tokens before and after the k-th Bash call."""
    marks, total = tokens_at_bash(tp)
    before = marks[k - 1] if 0 < k <= len(marks) else total if k else 0
    return before, total - before


def required_runs(events, files):
    return [(i, e) for i, e in enumerate(events)
            if e.got and "pytest" in e.cmd and any(f in e.cmd for f in files)]


def clean(e, body):
    """A visible pytest summary with passes and no failures or errors,
    and no non-zero exit."""
    lines = [l for l in (body or "").splitlines() if SUMMARY.search(l)]
    if e.is_err or not lines:
        return False
    last = lines[-1]
    return "passed" in last and not re.search(r"failed|error", last)


def first_verified(events, files, bodies):
    return next((i for i, e in required_runs(events, files)
                 if clean(e, bodies[i])), None)


def bound(events, files, bodies):
    """The friction bound: the session's first required-file run was not
    clean (the era break is in place until the agent works around it)."""
    runs = required_runs(events, files)
    return bool(runs) and not clean(runs[0][1], bodies[runs[0][0]])


def rank(x):
    return math.inf if x is None else x


def main():
    out = os.path.join(HERE, sys.argv[sys.argv.index("--dir") + 1]) \
        if "--dir" in sys.argv else os.path.join(HERE, "track23")
    res = [json.loads(l) for l in open(os.path.join(out, "results.jsonl"))]
    by_id = {t["instance_id"]: t for t in json.load(
        open(os.path.join(HERE, "tasks_v2.json")))}
    by = collections.defaultdict(dict)
    for r in res:
        by[r["instance_id"]][r["arm"]] = r
    pairs = {k: v for k, v in by.items() if len(v) == 2}
    print(f"sessions {len(res)}   complete pairs {len(pairs)}   "
          f"incomplete: {[k for k, v in by.items() if len(v) < 2] or 'none'}")

    db = sqlite3.connect(os.path.join(out, "rfm-memory.db"))
    store = dict(db.execute("SELECT id, content FROM rfm_memories"))
    recorded = db.execute("SELECT COUNT(*) FROM rfm_accesses "
                          "WHERE outcome IS NOT NULL").fetchone()[0]
    db.close()

    S = {}
    for iid, arms in pairs.items():
        files = T.test_files(by_id[iid])
        for arm, r in arms.items():
            tp = r.get("transcript") and os.path.join(HERE, r["transcript"])
            if not tp or not os.path.exists(tp):
                S[(iid, arm)] = None
                continue
            evs = F.events_of(tp)
            toks, span = timing(tp)
            full = full_bodies(tp)
            cut = [b[:CUT] for b in full]
            S[(iid, arm)] = {
                "shim": built_shim(tp),
                "shim_runs": sum(1 for e in evs if PATH_PYTEST.search(e.cmd)),
                "tokens": toks,
                "span": span,
                "offline": offline_outcomes(tp, evs, store),
                "acted": acted_commands(tp, evs, store),
                "bound": bound(evs, files, full),
                "fired": sum(1 for e, b in zip(evs, full)
                             if e.got and ERA.search(b)),
                "fired_vr": any(CLASS.search(b) for b in full),
                "notes": notes_in(tp),
                "verified": first_verified(evs, files, full),
                "verified_cut": first_verified(evs, files, cut),
                "green": F.first_green_corrected(evs),
            }

    fmt = lambda x: "never" if x is None else str(x)
    print(f"\n{'task':<8}{'fired c/s':>10}{'shown':>6}{'ctl ver':>8}"
          f"{'show ver':>9}{'ctl wall':>9}{'show wall':>10}{'verdict':>9}")
    wins = losses = ties = cut_wins = cut_losses = cut_ties = 0
    slower = faster = 0
    ctl_bound = ctl_fired = show_fired = shown_when_fired = 0
    contaminated = []
    for iid in sorted(pairs):
        c, s = S.get((iid, "control")), S.get((iid, "show"))
        cw, sw = pairs[iid]["control"]["wall_s"], pairs[iid]["show"]["wall_s"]
        if c is None or s is None:
            print(f"{iid[-6:]:<8} transcript missing")
            continue
        ctl_bound += c["bound"]
        ctl_fired += c["fired"] > 0
        show_fired += s["fired"] > 0
        shown_when_fired += s["fired"] > 0 and bool(s["notes"])
        if c["notes"]:
            contaminated.append(iid)
        cv, sv = rank(c["verified"]), rank(s["verified"])
        verdict = "show" if sv < cv else "control" if cv < sv else "tie"
        wins += verdict == "show"
        losses += verdict == "control"
        ties += verdict == "tie"
        cc, cs = rank(c["verified_cut"]), rank(s["verified_cut"])
        cut_wins += cs < cc
        cut_losses += cc < cs
        cut_ties += cc == cs
        slower += sw > cw
        faster += sw < cw
        print(f"{iid[-6:]:<8}{c['fired']:>5}/{s['fired']:<4}"
              f"{len(s['notes']):>6}{fmt(c['verified']):>8}"
              f"{fmt(s['verified']):>9}{cw:>9}{sw:>10}{verdict:>9}")

    n = len(pairs)
    tc = sum(p["control"]["wall_s"] for p in pairs.values())
    ts = sum(p["show"]["wall_s"] for p in pairs.values())
    rc = sum(bool(p["control"]["resolved"]) for p in pairs.values())
    rsv = sum(bool(p["show"]["resolved"]) for p in pairs.values())
    print(f"\nP1 liveness: first required-file run not clean in "
          f"{ctl_bound}/{n} control sessions ({100 * ctl_bound / max(n, 1):.0f}%;"
          f" bar 60%); era text visible in {ctl_fired}/{n}")
    print(f"P2 delivery: memory shown in {shown_when_fired}/{show_fired} "
          f"show sessions where the class fired (bar 80%); control "
          f"sessions with a note: {len(contaminated)} (must be 0)")
    print(f"P3 benefit: show {wins} / control {losses} / tied {ties}; "
          f"one-sided sign p = {sign_p(wins, wins + losses):.3f} (bar 0.05)")
    print(f"   as first registered (800-char bodies): show {cut_wins} / "
          f"control {cut_losses} / tied {cut_ties}; sign p = "
          f"{sign_p(cut_wins, cut_wins + cut_losses):.3f}")
    print(f"P4 no harm: show wall {ts}s vs control {tc}s "
          f"({100 * (ts - tc) / max(tc, 1):+.1f}%; bar +15%); slower on "
          f"{slower}, faster on {faster}; sign p (slower) = "
          f"{sign_p(slower, slower + faster):.3f}")
    print(f"resolved: control {rc}/{n}, show {rsv}/{n}")
    last = res[-1].get("ledger") if res else None
    print(f"P5 ledger (id, outcomes, value) at end: {last}")
    shows = [S[(i, "show")] for i in pairs if S.get((i, "show"))]
    offline = [o for x in shows for o in x["offline"]]
    print(f"P5 mod outcomes recorded: {recorded}; session_end inference on "
          f"the same transcripts: {len(offline)} {offline or ''}; commands "
          f"acted_on credited: {sum(x['acted'] for x in shows)}")

    # Unregistered description of P2, P3 and P4, added after the run.
    with_class = [x for x in shows if x["fired_vr"]]
    print(f"\nunregistered: the memory's own class fired in {len(with_class)} "
          f"show sessions, shown in {sum(bool(x['notes']) for x in with_class)}")
    noted = [x for x in shows if x["notes"]]
    print(f"\nunregistered: shown the memory {len(noted)}/{len(shows)}; of "
          f"those, built the shim {sum(x['shim'] for x in noted)}, ran pytest "
          f"with PYTHONPATH {sum(x['shim_runs'] > 0 for x in noted)}; control "
          f"built it {sum(S[(i, 'control')]['shim'] for i in pairs)}/{n}")
    pre, post = [], []
    for i in pairs:
        k = min(note_positions(os.path.join(HERE, pairs[i]["show"]["transcript"]))
                .values(), default=None)
        if k is None:
            continue
        sb, sa = split_at(os.path.join(HERE, pairs[i]["show"]["transcript"]), k)
        cb, ca = split_at(os.path.join(HERE, pairs[i]["control"]["transcript"]), k)
        pre.append((sb, cb))
        post.append((sa, ca))
    for label, rows in (("before the note", pre), ("after the note", post)):
        up, down = sum(a > b for a, b in rows), sum(a < b for a, b in rows)
        print(f"  output tokens {label}, split at the same Bash index: show "
              f"{sum(a for a, _ in rows)} vs control "
              f"{sum(b for _, b in rows)}; show higher {up}, lower {down}, "
              f"sign p = {sign_p(up, up + down):.4f}")
    nn = [i for i in pairs if not S[(i, "show")]["notes"]]
    up = sum(pairs[i]["show"]["wall_s"] > pairs[i]["control"]["wall_s"]
             for i in nn)
    print(f"  no-note sessions slower on {up} of {len(nn)}, sign p = "
          f"{sign_p(up, len(nn)):.3f}")

    print("\nunregistered: where P4's wall went, by whether a note arrived")
    for label, keep in (("note shown", True), ("no note", False)):
        ids = [i for i in pairs if bool(S[(i, "show")]["notes"]) == keep]
        sum_of = lambda k, arm: sum(S[(i, arm)][k] for i in ids)
        wc = sum(pairs[i]["control"]["wall_s"] for i in ids)
        ws = sum(pairs[i]["show"]["wall_s"] for i in ids)
        print(f"  {label:<11}n={len(ids):<3}wall {wc} -> {ws} "
              f"({100 * (ws - wc) / max(wc, 1):+.1f}%)  transcript span "
              f"{sum_of('span', 'control'):.0f} -> {sum_of('span', 'show'):.0f}"
              f"  output tokens {sum_of('tokens', 'control')} -> "
              f"{sum_of('tokens', 'show')}")


if __name__ == "__main__":
    main()
