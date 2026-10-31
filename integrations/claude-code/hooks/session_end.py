#!/usr/bin/env python3
"""SessionEnd hook: propose memories from what the session had to learn,
and record outcomes for the memories the session actually used.

Both jobs are post-hoc for the same measured reason: asking an agent
mid-task to do memory work under-fires, and when it does fire it
anti-selects (70 live sessions: 17 sincerely-chosen lessons, 15 of 16 later
outcomes negative). After the session, what mattered is visible in the
transcript. Post-hoc is the pattern Hermes (background_review) and Codex
(consolidation) both use; this is the cheap deterministic slice — no LLM,
only signals objectively present in the log.

FORMATION — **a command that failed, followed by a variant that worked** is
a gotcha the session paid for, in exactly the category our A/B says
transfers (operational knowledge). Candidates are *staged, never saved*
(`pending-memories.md`, ratified by /memory-review): every vendor that
auto-captured content into a long-lived store found unreviewed accumulation
made things worse (arXiv:2602.11988). Each staged candidate carries a
reconcile line — its nearest stored memories and pending candidates, with
similarity and provenance — so review can skip or merge a restatement
instead of saving it again (see RECONCILE below).

OUTCOMES — the M in RFM, and the loop the tool-call path never closes
reliably. Three deterministic steps:
  1. which memories were in play: ids and content from the SessionStart
     injection block ("- [id] content" under the [rfm-memory:] marker) and
     from memory_search tool results, both verbatim in the transcript;
  2. which were acted on: a backtick-quoted span from the memory appearing
     in a later command, or the command's tokens drawn from the memory
     (program match + overlap threshold — the correction-miner's own
     discipline);
  3. how that went: the harness recorded the command's result. Acted on and
     succeeded -> +1; acted on and failed -> -1 (this also catches the
     session's failed->fixed pair overturning a memory's advice). In play
     but never used -> NO outcome: absence of use is what rfm_prunable
     measures, not negative evidence.

Unlike formation, outcomes ARE written directly, and the asymmetry is
principled: formation admits new unbounded *claims* into the store (needs a
human), an outcome adjusts the weight on an existing claim inside a frozen
bounded blend (EWMA lambda=0.3, confidence shrink, beta-capped composition
— the math is the review step, and a wrong outcome decays). Thresholds are
tuned for precision over recall: a missed outcome costs little, a wrong one
pollutes. Every inferred outcome — and every failure to record one — is
logged to rfm-log.jsonl, and every run ends with a summary line (events,
in-play memories, staged, outcomes), so an empty run is distinguishable
from the hook never firing and the inference is auditable after the fact.

Install (settings.json):

    {"hooks": {"SessionEnd": [{"hooks": [{"type": "command",
      "command": "python3 /path/to/hooks/session_end.py"}]}]}}

Reads the hook payload on stdin; writes candidates to
$RFM_MEMORY_DB's directory as `pending-memories.md` and outcomes to the DB.
"""
import contextlib
import json
import os
import re
import signal
import sqlite3
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))  # repo root: rfm.py
sys.path.insert(0, os.path.join(HERE, ".."))               # server.py's dir
import rfm  # noqa: E402  (repo-root module; scoring engine)
import log_env  # noqa: E402  (server.py's sibling; shared RFM_LOG contract)
import secret_scan  # noqa: E402  (server.py's sibling; credential redaction)
import harnesses  # noqa: E402  (server.py's sibling; lifecycle registry)
import transcripts  # noqa: E402  (server.py's sibling; normalized session)
import similarity  # noqa: E402  (server.py's sibling; shared with sweep.py)

# Inside a 30 s hook the embedder loads from the local cache or not at all
# (token similarity instead); a first-run download belongs to the sweep.
similarity.LOCAL_ONLY = True

DB_PATH = os.path.expanduser(
    os.environ.get("RFM_MEMORY_DB", "~/.sqlite-rfm/claude-code.db"))
OUT = os.path.join(os.path.dirname(DB_PATH), "pending-memories.md")
# log_env mirrors server.py's RFM_LOG/RFM_LOG_CONTENT semantics exactly (one
# owner for both processes), so the hook's audit lines land in the same file
# the server writes, RFM_LOG=0 silences the hook too, and content redaction
# follows the same rule as server.py's _redact.
LOG_ENABLED, LOG = log_env.resolve_log(
    os.environ.get("RFM_LOG", "1"), os.path.dirname(DB_PATH))
LOG_CONTENT = log_env.content_enabled(os.environ.get("RFM_LOG_CONTENT", "1"))
MAX_CANDIDATES = 10
# Retention window (days). rfm_prunable's guard makes automatic deletion
# safe: only memories idle past the window AND never proved useful qualify —
# a positive outcome record is never prunable however long idle
# (docs/lifecycle.md calls pruning formation's safety net; this is where it
# is wired). <= 0 disables; the value is never passed through at <= 0
# because rfm_prunable(id, 0) would mean "prune anything idle".
PRUNE_DAYS = float(os.environ.get("RFM_PRUNE_DAYS", "30"))

# A failure worth learning from names a cause. Exit-code noise ("1") and
# ordinary test failures are not gotchas — the agent expects those.
FAILURE = re.compile(
    r"command not found|no such file or directory|permission denied|"
    r"unrecognized option|invalid option|is not recognized|"
    r"modulenotfounderror|importerror|cannot find module|"
    r"unable to load|not a loadable|undefined symbol|"
    r"no matches found|bad interpreter|"
    # Environment/startup exception class (validated on the pilot-2 replay:
    # recovered the run's top-value gotcha — the era-pin stub workaround —
    # with zero noise, where a generic \w+Error class staged ordinary test
    # failures). Names an env cause, not code-under-test behavior.
    r"extensionerror|versionrequirementerror|distributionnotfound|"
    r"pkg_resources", re.I)

# Named condition classes for condition-conditioned outcomes (DESIGN_NOTES
# "config-driven extraction and value, and the three clocks"; motivated by
# RESULTS.md Track 11 Correction C4: the top memory's 17-outcome ledger was
# earned 79% condition-silent — agents copying a suggested command that was
# never at risk, the loop crediting every success). Aligned with FAILURE's
# environment alternations; a memory whose content names one of these
# classes only earns POSITIVE outcomes in sessions where the class actually
# appeared in command output. Negative outcomes are never gated: advice
# that broke something is evidence against it whether or not its condition
# fired. RFM_CONDITIONED_OUTCOMES=0 disables the gate.
CONDITION_CLASSES = (
    "command not found", "no such file or directory", "permission denied",
    "bad interpreter", "modulenotfounderror", "importerror",
    "extensionerror", "versionrequirementerror", "distributionnotfound",
    "pkg_resources")
CONDITIONED = os.environ.get("RFM_CONDITIONED_OUTCOMES", "1") != "0"


def fired_classes(events):
    """Condition classes exhibited THIS session: the class text appeared in
    the output of a command whose result arrived (t_fired's observation
    side). Matching mirrors the cost view's counting — got-events, output
    text, case-insensitive."""
    fired = set()
    for e in events:
        if not e.got:
            continue
        body = (e.body or "").lower()
        fired.update(c for c in CONDITION_CLASSES if c in body)
    return fired


def derive_condition(content):
    """A memory's condition classes, derived from its own text: the classes
    it names. Empty string = unconditioned (a memory naming no class keeps
    the old semantics). Comma-joined; the gate passes on ANY named class
    firing."""
    text = str(content).lower()
    return ",".join(c for c in CONDITION_CLASSES if c in text)


# Show-on-error retrieval (RFM_JIT; hooks/post_tool_use.py::jit_inject) reads
# memories by the same condition vocabulary the outcome gate uses, so a
# memory surfaced at a failure is exactly one that can earn a conditioned +1
# there. Some classes name their cause outright; others ("no such file or
# directory", "command not found", ...) fire constantly and incidentally
# (Track 19: the path class fired in 10 of 21 sessions, never as the
# memory's problem), so a memory matched only on one of those must also
# share a discriminating key with the failure — the missing module, path or
# program — before it may be surfaced.
SPECIFIC_CLASSES = frozenset((
    "bad interpreter", "extensionerror", "versionrequirementerror",
    "distributionnotfound", "pkg_resources"))
_SIG_KEYS = (
    re.compile(r"no module named ['\"]?([A-Za-z_][\w.]*)", re.I),
    re.compile(r"cannot import name ['\"]?([A-Za-z_]\w*)", re.I),
    re.compile(r"([\w.+-]+): command not found", re.I),
    re.compile(r"command not found: ([\w.+-]+)", re.I),
    re.compile(r"([^\s'\":]+)['\"]?: no such file or directory", re.I),
    re.compile(r"no such file or directory: ['\"]?([^\s'\"]+)", re.I),
    re.compile(r"([^\s'\":]+)['\"]?: permission denied", re.I),
    re.compile(r"permission denied: ['\"]?([^\s'\"]+)", re.I),
    re.compile(r"\b([A-Z]\w*(?:Error|Exception|NotFound))\b"),
    re.compile(r"\b([A-Za-z][\w.-]+) (?:needs|requires) ", re.I),
)
_SIG_STOP = {"error", "exception", "python", "python3", "bash", "zsh", "sh",
             "tmp", "usr", "bin", "lib", "dev", "null", "line",
             # English the "needs|requires" pattern catches ahead of the verb
             "this", "that", "which", "package", "module", "version",
             "project", "it", "also", "now", "still", "who", "one"}
# Output is scanned at both ends: a traceback or a pytest summary puts the
# error last, a shell puts it first.
_SIG_SPAN = 8000


def _key_re(k):
    """A key matches as a whole token, never inside a longer word ('six'
    must not match 'sixty'); '.', '-', '/' and '_' bind to the token."""
    return re.compile(r"(?<![\w./-])" + re.escape(k) + r"(?![\w-])")


def _classes(stamp):
    """A condition stamp as a set: case- and space-insensitive, since a
    host-owned stamp may be written by hand ('ModuleNotFoundError, x')."""
    return {c.strip().lower() for c in (stamp or "").split(",") if c.strip()}


def error_signature(body):
    """Structural signature of a tool result: the condition classes it
    exhibits (fired_classes' matching, one result at a time) plus
    discriminating keys — missing module (and its top package), missing
    path (and its basename), missing program, exception class names.
    None when no condition class appears: the trigger is the class, the
    keys only choose among memories that share it."""
    body = body or ""
    text = body if len(body) <= 2 * _SIG_SPAN \
        else body[:_SIG_SPAN] + "\n" + body[-_SIG_SPAN:]
    low = text.lower()
    classes = tuple(c for c in CONDITION_CLASSES if c in low)
    if not classes:
        return None
    keys = set()
    for pat in _SIG_KEYS:
        for m in pat.finditer(text):
            k = m.group(1).strip("'\"`.,;:()").lower()
            for part in (k, k.rsplit("/", 1)[-1], k.split(".")[0]):
                # A class name is the trigger, not a discriminator: as a
                # key it would match every memory stamped with that class.
                if (len(part) >= 3 and part not in _SIG_STOP
                        and part not in CONDITION_CLASSES):
                    keys.add(part)
    return {"classes": classes, "keys": frozenset(keys)}


def signature_match(sig, content, condition_class=None):
    """How well a stored memory answers this failure: None if it must not
    be surfaced, else the count of signature keys its text names (higher is
    better). The memory's condition_class (stamped, else derived from its
    content) must share a class with the failure; a match on a generic
    class additionally needs at least one shared key."""
    if not sig:
        return None
    cond = derive_condition(content) if condition_class is None \
        else condition_class
    shared = _classes(cond) & set(sig["classes"])
    if not shared:
        return None
    text = str(content).lower()
    overlap = sum(1 for k in sig["keys"] if _key_re(k).search(text))
    if not overlap and not (shared & SPECIFIC_CLASSES):
        return None
    return overlap


def ensure_conditions(db):
    """Host-owned column (rfm_schema.sql: tables are host-owned; the
    extension maintains only its marked columns): add condition_class if
    absent, then stamp any unstamped row by derivation from its content.
    Only NULL rows are stamped, so an explicit stamp is never overwritten;
    '' is a deliberate 'unconditioned' stamp, distinct from NULL."""
    try:
        db.execute("ALTER TABLE rfm_memories ADD COLUMN condition_class TEXT")
    except sqlite3.OperationalError:
        pass                                   # column already exists
    for mid, content in db.execute(
            "SELECT id, content FROM rfm_memories "
            "WHERE condition_class IS NULL").fetchall():
        cond = derive_condition(content)
        db.execute("UPDATE rfm_memories SET condition_class = ? WHERE id = ?",
                   (cond, mid))
        _log({"op": "condition_stamp", "id": mid, "condition": cond})

# The normalized session lives in transcripts.py. These three names stay
# importable from here only because bench-quality/live-ab's
# formation_study.py, eval_selection.py and miner_replay.py call them.
_parse_transcript = transcripts.parse_jsonl
load_events = transcripts.claude_events


def in_play_memories(records):
    return transcripts.claude_exposures(records)[0]


def tokens(cmd):
    return set(re.findall(r"[A-Za-z0-9_.\-/]+", cmd.split("<<")[0][:300]))


def program(cmd):
    """The command actually being run, skipping env-var prefixes."""
    for tok in cmd.split("<<")[0].split():
        if "=" in tok and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            continue
        return os.path.basename(tok.strip("\"'`(){};|&"))
    return ""


def _log(fields):
    """Append one line to rfm-log.jsonl. Never raises — a log write must
    not be the reason the hook fails."""
    if not LOG_ENABLED:
        return
    try:
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"t": round(time.time(), 3), **fields}) + "\n")
    except OSError:
        pass


def informative_head(cmd):
    """Can this command's HEAD LINE serve as one side of rendered advice?
    Candidates are rendered from head lines only, so a bare interpreter fed
    by heredoc/stdin ('python - <<EOF') renders as advice with no reusable
    trigger — Track 3's mining artifacts, demoted by outcomes only after
    they had cost injection slots. Requires a token beyond the program,
    env prefixes, flags, and the stdin dash."""
    toks = cmd.split("<<")[0].split("\n")[0].split()
    toks = [t for t in toks if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t)]
    return any(t != "-" and not t.startswith("-") for t in toks[1:])


def corrections(events):
    """Failed command → the later command that fixed it.

    Requires substantial token overlap so we pair a command with its own
    retry rather than with whatever happened to run next, and requires the
    fix to have succeeded. A candidate must name a cause (FAILURE match):
    ordinary exit-1 noise — a failing test the agent is working on — is not
    a gotcha, per the module docstring. Failures are mined from the harness
    verdict OR an error-shaped output (a `.load`-style tool can fail while
    exiting 0), but the fix must be clean on both signals."""
    out, used = [], set()
    for i, e in enumerate(events):
        reason = FAILURE.search(e.body) if e.got else None
        if not e.got or not (e.is_err or reason):
            continue        # not a known failure
        if reason is None:
            continue        # failed, but names no cause: expected noise
        base = tokens(e.cmd)
        if not base:
            continue
        for j in range(i + 1, min(i + 6, len(events))):
            if j in used:
                continue
            fix = events[j]
            # Identity is checked on the FULL text: two heredoc calls can share
            # a first line while differing entirely in body.
            if (not fix.got or fix.is_err or FAILURE.search(fix.body)
                    or fix.cmd.strip() == e.cmd.strip()):
                continue
            # The fix must be a retry of the SAME program, not merely the next
            # thing that ran — without this, an unrelated success gets paired
            # with the failure that happened to precede it.
            prog = program(e.cmd)
            if not prog or prog not in tokens(fix.cmd):
                continue
            overlap = len(base & tokens(fix.cmd)) / max(1, len(base))
            if overlap >= 0.5:
                head_a = e.cmd.split("\n")[0][:200]
                head_b = fix.cmd.split("\n")[0][:200]
                # Two heredoc calls can differ only in their body; the rendered
                # advice would then read "X fails; use X instead". Useless.
                if head_a == head_b:
                    continue
                # Both rendered sides must carry a reusable trigger/action;
                # a heredoc-bodied bare interpreter on either side does not.
                if not (informative_head(e.cmd) and informative_head(fix.cmd)):
                    continue
                out.append({
                    "failed": head_a,
                    "fixed": head_b,
                    "error": reason.group(0).lower(),
                    # Provenance: indices into the session's Bash events
                    # (transcripts.claude_events order), failed -> fixed.
                    "events": (i, j),
                })
                used.add(j)
                break
    return out


def candidate_line(c):
    """The staged line for one correction pair. The candidate file is
    plaintext on disk and the source of memory_save calls, so it is
    scrubbed like the store is."""
    line, kinds = secret_scan.redact(
        f"- In this project, `{c['failed']}` fails ({c['error']}); "
        f"use `{c['fixed']}` instead.")
    if kinds:
        _log({"op": "secret_redacted", "kinds": kinds})
    return line


# RECONCILE — the "reconcile sheet". Each staged candidate is followed by
# one metadata line naming its nearest existing memories (store ids) and
# nearest still-unreviewed candidates, with similarity, a likely-duplicate
# mark, the condition class they share, and where in the transcript the
# pair came from. /memory-review uses it to offer skip / merge / supersede
# instead of saving a near-duplicate — and the store's save path only
# dedupes on EXACT content, which never fired on a staged candidate in any
# recorded run (0 "already stored" of 29 ratified; 13 of those 29 restated
# a lesson already in the store, bench-quality/live-ab/reconcile_replay.py).
# Advisory only: nothing is dropped or merged here — the reviewer decides.
#
# Thresholds are per similarity mode (similarity.py: embedding cosine, or
# token Jaccard when fastembed is absent — different scales). Replayed on
# the 29 recorded candidates (13 known duplicates) and the 65-row Track 18
# sweep store (41): embedding 0.80 flagged 13/13 and 33/41, marking 1 of
# 35 non-duplicates against an unrelated row (7 more against a same-
# condition sibling — arguably the merge case); 0.85 flagged 10/13 and
# 23/41 with no unrelated flags. Jaccard 0.40 flagged 9/13 of the
# command-shaped candidates and 1/41 paraphrases: degraded mode catches
# re-mined commands, not reworded lessons. Chosen on these same small
# sets — a starting point, not a calibration.
RECONCILE = os.environ.get("RFM_RECONCILE", "1") != "0"
DUPLICATE_AT = {"embedding": 0.80, "tokens": 0.40}
NEAREST_FLOOR = {"embedding": 0.70, "tokens": 0.20}
NEAREST_K = 3
# Newest rows only: bounds the hook's embedding cost (~6 ms/row batched,
# ~1 s model load) on a large store; staged lessons recur near-term.
RECONCILE_MAX_ROWS = 500
# Unreviewed candidates compared against: the newest, same reasoning.
RECONCILE_MAX_PENDING = 200
# SessionEnd has 30 s. Reconcile is advisory, so it gets a slice of that
# and is abandoned (candidates staged without hints) when it overruns;
# outcomes are recorded before staging so they never wait on it.
RECONCILE_BUDGET_S = float(os.environ.get("RFM_RECONCILE_BUDGET_S", 10))
META = "  <!-- rfm-reconcile: "


def pending_entries(path):
    """[(ref, content)] for candidates already staged and not yet reviewed.
    Same "- " predicate as session_start's count and ratify_staged's load;
    the ref comes from the candidate's metadata line when it has one."""
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for k, line in enumerate(lines):
        if not line.startswith("- "):
            continue
        nxt = lines[k + 1] if k + 1 < len(lines) else ""
        m = re.search(r"ref=(\S+)", nxt) if nxt.startswith(META) else None
        out.append((m.group(1) if m else f"pending-{len(out) + 1}",
                    line[2:].strip()))
    return out


def store_rows(limit=RECONCILE_MAX_ROWS):
    """[(id, content, scope)] newest first, read-only. Empty on any trouble:
    reconcile is advisory and must never block staging."""
    if not os.path.exists(DB_PATH):
        return []
    try:
        db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        return []
    try:
        try:
            return db.execute("SELECT id, content, scope FROM rfm_memories "
                              "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        except sqlite3.OperationalError:          # pre-scope schema
            return [(i, c, None) for i, c in db.execute(
                "SELECT id, content FROM rfm_memories "
                "ORDER BY id DESC LIMIT ?", (limit,))]
    except sqlite3.Error:
        return []
    finally:
        db.close()


def _classes_of(text):
    return {c for c in derive_condition(text).split(",") if c}


def reconcile(new, rows, pending):
    """For each new (ref, text), in order: its nearest store rows and
    nearest pending candidates — earlier candidates of this same batch
    included, since two sessions' worth of one lesson usually meet in the
    pending file before they meet in the store. Returns one
    {"mode", "nearest": [...]} per new candidate."""
    if not new:
        return []
    similarity.prime([t for _, t in new] + [c for _, c, _ in rows]
                     + [c for _, c in pending])
    mode = similarity.mode()
    earlier, out = list(pending), []
    for ref, text in new:
        cond = _classes_of(text)
        near = [{"ref": f"#{mid}", "sim": similarity.similarity(text, content),
                 "scope": scope, "shared": sorted(cond & _classes_of(content))}
                for mid, content, scope in rows]
        near += [{"ref": pref, "sim": similarity.similarity(text, content),
                  "scope": None, "shared": sorted(cond & _classes_of(content))}
                 for pref, content in earlier]
        near = sorted((n for n in near if n["sim"] >= NEAREST_FLOOR[mode]),
                      key=lambda n: -n["sim"])[:NEAREST_K]
        for n in near:
            n["duplicate"] = n["sim"] >= DUPLICATE_AT[mode]
        out.append({"mode": mode, "nearest": near})
        earlier.append((ref, text))
    return out


def meta_line(ref, rec, transcript, events_ij):
    """The metadata line under a candidate. Indented and comment-wrapped so
    every "- " reader (session_start's count, ratify_staged, the review
    skill's candidate list) still sees exactly one line per candidate."""
    parts = [f"ref={ref}"]
    if rec is not None:
        items = []
        for n in rec["nearest"]:
            s = f"{n['ref']} {n['sim']:.2f}"
            if n["duplicate"]:
                s += " likely-duplicate"
            if n["shared"]:
                s += f" condition={','.join(n['shared'])}"
            if n["scope"]:
                s += f" scope={n['scope']}"
            items.append(s)
        parts.append(f"nearest[{rec['mode']}]=" +
                     ("; ".join(items) if items else "none"))
    i, j = events_ij
    # Last: a transcript path may contain spaces.
    parts.append(f"from=bash#{i}->#{j} of {transcript}")
    return META + " ".join(parts).replace("-->", "->") + " -->"


class _Overrun(Exception):
    pass


@contextlib.contextmanager
def _deadline(seconds):
    """Raise _Overrun in the main thread after `seconds` (POSIX timer; a
    no-op where SIGALRM is unavailable or off the main thread)."""
    if not hasattr(signal, "SIGALRM") or \
            threading.current_thread() is not threading.main_thread():
        yield
        return

    def _fire(*_):
        raise _Overrun(f"reconcile exceeded {seconds:g}s")
    old = signal.signal(signal.SIGALRM, _fire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def stage(found, session, transcript):
    """Append this session's candidates, each followed by its reconcile
    metadata line. Reconcile failure degrades to provenance-only lines."""
    cands = found[:MAX_CANDIDATES]
    lines = [candidate_line(c) for c in cands]
    pending = pending_entries(OUT)
    # A resumed session (same id, SessionEnd again) or a missing id ('?')
    # would reuse refs already in the file; a stage suffix keeps each unique.
    taken = {ref for ref, _ in pending}
    prefix, n = session, 1
    while any(r.startswith(prefix + ".") for r in taken):
        n += 1
        prefix = f"{session}~{n}"
    refs = [f"{prefix}.{k + 1}" for k in range(len(cands))]
    recs = [None] * len(cands)
    if RECONCILE:
        try:
            with _deadline(RECONCILE_BUDGET_S):
                recs = reconcile(list(zip(refs, (l[2:] for l in lines))),
                                 store_rows(), pending[-RECONCILE_MAX_PENDING:])
        except Exception as e:                  # advisory: never block staging
            _log({"op": "reconcile_failed",
                  "error": f"{type(e).__name__}: {e}"[:200]})
            recs = [None] * len(cands)
    for ref, rec in zip(refs, recs):
        if rec is not None:
            _log({"op": "reconcile", "ref": ref, "mode": rec["mode"],
                  "nearest": [[n["ref"], round(n["sim"], 3)]
                              for n in rec["nearest"]],
                  "duplicate": any(n["duplicate"] for n in rec["nearest"])})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as f:
        f.write(f"\n## Candidates from session {session}\n")
        f.write("<!-- Proposed, not saved. Review, then keep the useful ones\n"
                "     with memory_save. -->\n\n")
        for c, line, ref, rec in zip(cands, lines, refs, recs):
            f.write(line + "\n")
            f.write(meta_line(ref, rec, transcript, c["events"]) + "\n")
    return len(cands)


def rehydrate(mems):
    """Replace transcript-derived memory content with the store's full text.
    Injected lines are cut to the injection char budget, so a signature
    built from the transcript can lack exactly the backtick spans that
    identify acted-on commands (pilot 2: the top memory's stubs path sat
    past the cut in every session, and inference recovered 1 of 15
    outcomes). The transcript text stays as fallback for deleted ids."""
    if not mems or not os.path.exists(DB_PATH):
        return mems
    try:
        db = sqlite3.connect(DB_PATH, timeout=10.0)
        for mid, (content, idx) in list(mems.items()):
            row = db.execute("SELECT content FROM rfm_memories WHERE id = ?",
                             (mid,)).fetchone()
            if row is not None:
                mems[mid] = (row[0], idx)
        db.close()
    except sqlite3.Error:
        pass
    return mems


PLACEHOLDER = re.compile(r"/path/to/\S*|<[A-Za-z][\w -]*>")
HOLE = "\0"


def _signature(mem_content):
    """(backtick spans, program-tokens) for a memory's content, computed
    once and reused against every candidate command — acted_on's inputs
    that don't vary per command, hoisted out of infer_outcomes' inner
    loop."""
    return re.findall(r"`([^`]{8,})`", mem_content), tokens(mem_content)


def _holes(span):
    """The span with its placeholders marked, or None if it has none."""
    held = PLACEHOLDER.sub(HOLE, span)
    return held if held != span or "..." in span.split() else None


def _template(span):
    """A backtick span with placeholders as [(kind, text), ...] to match
    word by word, or None when it has no placeholder or is too generic to
    credit (Track 24): it needs an anchored word (`KEY=<value>`), or three
    literal words after the first, or `python -m pytest <tests>` would
    credit every test run."""
    held = _holes(span)
    if held is None:
        return None
    words = []
    for w in held.split():
        if w == "...":
            continue
        head = w.split(HOLE)[0]
        words.append(("literal", w) if HOLE not in w else
                     ("anchored", head) if head else ("any", ""))
    kinds = [k for k, _ in words]
    if "anchored" in kinds or kinds.count("literal") > 3:
        return words
    return None


def _fills(kind, text, word):
    if kind == "any":
        return True
    if kind == "anchored":
        return word.startswith(text) and \
            re.search(r"[A-Za-z0-9]", word[len(text):]) is not None
    return word == text or (text.endswith("/") and word.startswith(text))


def _fills_template(words, cmd):
    """The template's words appear in order; others may sit between."""
    have = iter(cmd.split("<<")[0].split())
    return all(any(_fills(k, t, w) for w in have) for k, t in words)


def acted_on(sig, cmd):
    """Did this command come from the memory this signature was built for?
    Precision over recall: a backtick-quoted span reproduced verbatim, or
    filled in if it is a template, or, for a memory with no template, the
    command's tokens drawn from the memory with its program named there.
    Token share would credit bare `python -m pytest` to a template that
    needs an override."""
    spans, mt = sig
    for span in spans:
        if span in cmd:
            return True
        words = _template(span)
        if words and _fills_template(words, cmd):
            return True
    if any(_holes(span) for span in spans):
        return False
    prog = program(cmd)
    if not prog or prog not in mt:
        return False
    ct = tokens(cmd)
    return bool(ct) and len(ct & mt) / len(ct) >= 0.6


def infer_outcomes(mems, events):
    """First acted-on command per memory decides the outcome. In play but
    never acted on -> no outcome (idleness is rfm_prunable's signal).

    Precision over recall, so abstain wherever the verdict is not the
    harness's own: matching starts at the memory's first appearance (an
    earlier command cannot have come from it), a command whose result never
    arrived decides nothing, and a zero-exit command whose output still
    looks error-shaped is ambiguous — no outcome beats a wrong one."""
    out = []
    for mid, (content, first_idx) in mems.items():
        sig = _signature(content)
        for e in events[first_idx:]:
            if not acted_on(sig, e.cmd):
                continue
            if not e.got:
                break                 # result never arrived: verdict unknown
            if not e.is_err and FAILURE.search(e.body):
                break                 # zero-exit but error-shaped: ambiguous
            out.append({"id": mid, "outcome": -1.0 if e.is_err else 1.0,
                        "cmd": e.cmd.split("\n")[0][:200]})
            break
    return out


def record_outcomes(inferred, session_start, fired=frozenset()):
    """Write outcomes, deferring to any loop the model already closed THIS
    session: an outstanding access gets the outcome attached; a memory with
    no access — or whose latest access carries an outcome from a PREVIOUS
    session, which is a closed retrieval, not this one — gets its use
    recorded as a fresh access; a latest access whose outcome was recorded
    this session is left alone (explicit feedback wins). With no
    session_start (no parseable transcript timestamp), any existing outcome
    defers — abstaining beats double-counting."""
    if not inferred or not os.path.exists(DB_PATH):
        return 0
    try:
        db = sqlite3.connect(DB_PATH, timeout=10.0)
    except sqlite3.Error as e:
        _log({"op": "outcome_inferred_failed", "error": f"connect: {e}"})
        return 0
    done = 0
    try:
        rfm.register(db)
        ensure_conditions(db)
        for o in inferred:
            try:
                if CONDITIONED and o["outcome"] > 0:
                    cond = db.execute(
                        "SELECT condition_class FROM rfm_memories "
                        "WHERE id = ?", (o["id"],)).fetchone()
                    classes = [c for c in (cond[0] or "").split(",")
                               if c] if cond else []
                    if classes and not (set(classes) & fired):
                        # The memory's condition never fired this session:
                        # a successful copy proves nothing (C4). Skipped,
                        # and the skip is auditable.
                        _log({"op": "outcome_skipped_condition_silent",
                              "id": o["id"], "condition": classes,
                              "fired": sorted(fired)})
                        continue
                row = db.execute(
                    "SELECT accessed_at, outcome FROM rfm_accesses "
                    "WHERE memory_id = ? "
                    "ORDER BY accessed_at DESC, rowid DESC LIMIT 1",
                    (o["id"],)).fetchone()
                if row is not None and row[1] is not None and (
                        session_start is None or row[0] >= session_start):
                    continue      # explicit feedback this session; it wins
                if row is None or row[1] is not None:
                    db.execute("SELECT rfm_record_access(?)", (o["id"],))
                db.execute("SELECT rfm_record_outcome(?, ?)",
                           (o["id"], o["outcome"]))
                done += 1
                rec = dict(o)
                rec["cmd"] = log_env.redact(o["cmd"], LOG_CONTENT)
                _log({"op": "outcome_inferred", **rec})
            except sqlite3.Error as e:
                # Unknown id or other DB trouble on this one item — logged
                # so a systematic failure is distinguishable from "nothing
                # was acted on this session", never fatal to the hook.
                _log({"op": "outcome_inferred_failed", "id": o["id"],
                      "error": str(e)})
                continue
        db.commit()
    except sqlite3.Error as e:
        _log({"op": "outcome_inferred_failed", "error": f"commit: {e}"})
        done = 0          # e.g. locked past the timeout at commit: best-effort
    finally:
        db.close()
    return done


def prune(window_days):
    """Retention pass: delete memories that rfm_prunable marks — idle past
    the window AND never useful. Mirrors server _delete (both tables), and
    logs each removal with redacted content so an audit can see what left
    and why. Best-effort like everything else in this hook."""
    if window_days <= 0 or not os.path.exists(DB_PATH):
        return 0
    try:
        db = sqlite3.connect(DB_PATH, timeout=10.0)
    except sqlite3.Error:
        return 0
    pruned = 0
    try:
        rfm.register(db)
        rows = db.execute(
            "SELECT id, content FROM rfm_memories "
            "WHERE rfm_prunable(id, ?) = 1", (float(window_days),)).fetchall()
        for mid, content in rows:
            db.execute("DELETE FROM rfm_memories WHERE id = ?", (mid,))
            db.execute("DELETE FROM rfm_accesses WHERE memory_id = ?", (mid,))
            _log({"op": "prune", "id": mid, "window_days": window_days,
                  "content": log_env.redact(str(content), LOG_CONTENT)})
            pruned += 1
        db.commit()
    except sqlite3.Error as e:
        _log({"op": "prune_failed", "error": str(e)})
        pruned = 0
    finally:
        db.close()
    return pruned


def main():
    # RFM_HOOKS_OFF=1: run with the hooks inert — the attachment-tax
    # ablation (REVALIDATION.md Track 4) needs an arm where the MCP
    # server is attached but nothing else happens.
    if os.environ.get("RFM_HOOKS_OFF") == "1":
        return
    # A/B gating: when an experiment is running (ab/ab-claude sets
    # RFM_AB_ARM), a control-arm session must neither stage candidates nor
    # record outcomes — the arms run the same task back-to-back, so a
    # control lesson ratified into the shared store would leak the current
    # task into the rfm arm. Mirrors session_start.py's gate.
    if os.environ.get("RFM_AB_ARM", "rfm") != "rfm":
        return
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    harness = harnesses.current()
    # Subagent gate. Claude Code fires SubagentStop, not SessionEnd, for a
    # worker today, so this is defence in depth: if a host ever does run
    # SessionEnd inside a subagent, its slice of the task must neither stage
    # candidates nor grade memories (see hooks/pre_tool_use.py).
    if harnesses.is_subagent(harness, payload):
        _log({"op": "session_end", "skipped": "subagent"})
        return
    transcript = harnesses.payload_field(harness, "transcript", payload)
    if not transcript or not os.path.exists(transcript):
        return
    sess = transcripts.read(transcript, harness.reader, prose=False)
    events = sess.events
    session = (harnesses.payload_field(harness, "session", payload) or "?")[:8]
    notes = []

    # Outcomes first: staging's reconcile step is the slow part of this
    # hook, and a host timeout must not cost the session's outcomes.
    mems = rehydrate(dict(sess.exposures))
    fired = fired_classes(events)
    recorded = record_outcomes(infer_outcomes(mems, events), sess.start, fired)

    found = corrections(events)
    staged = 0
    if found:
        staged = stage(found, session, transcript)
        notes.append(f"staged {staged} memory candidate(s) in {OUT}")
    if recorded:
        notes.append(f"recorded {recorded} inferred outcome(s)")
    pruned = prune(PRUNE_DAYS)
    if pruned:
        notes.append(f"pruned {pruned} idle never-useful memor"
                     + ("y" if pruned == 1 else "ies"))
    # Run marker, written even when every count is zero: without it, a run
    # that found nothing is indistinguishable in the log from the hook never
    # firing, and the formation loop cannot be audited.
    # `readable` separates "nothing happened" from "could not read this
    # harness's transcript" — the degraded, MCP-only mode, in which
    # outcomes come only from explicit memory_feedback.
    _log({"op": "session_end", "session": session, "harness": harness.name,
          "readable": sess.readable, "events": len(events),
          "in_play": len(mems), "staged": staged, "outcomes": recorded,
          "conditions": sorted(fired), "pruned": pruned})
    if notes:
        print("rfm: " + "; ".join(notes), file=sys.stderr)


if __name__ == "__main__":
    main()
