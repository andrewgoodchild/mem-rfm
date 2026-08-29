#!/usr/bin/env python3
"""Register the formation loop's hooks in ~/.claude/settings.json.

Formation is harness-owned in this design (docs/lifecycle.md): the model is
never asked mid-task whether something is worth remembering. That only works
if the hooks actually fire, and hooks only fire if they are registered — an
unregistered hook is the discretionary design with extra steps. This
installer wires both halves of the loop:

  SessionStart  hooks/session_start.py  inject top memories by rfm_score
  SessionEnd    hooks/session_end.py    stage correction-pair candidates

It also maintains a marked block in ~/.claude/CLAUDE.md with the outcome-loop
instructions (memory_feedback after acting on a memory). This is the twin
problem from docs/lifecycle.md: feedback is a discretionary second call and
under-fires exactly like discretionary saving, and without it the prior stays
flat. A standing CLAUDE.md instruction is scaffolding, not a solution — but
it is the cheapest lever that raises the fire rate in every session, not just
ones where the SessionStart hook injects its usage trailer. User-level file,
because the store and the MCP server are user-global, not per-project.

Finally it installs the /memory-review skill (skills/memory-review/ ->
~/.claude/skills/), the ratification step: staged candidates are worthless
if reviewing them has no tooling. The skill is the user-invoked slot of the
loop; capture stays with hooks, where firing is not discretionary.

Merge semantics, chosen so re-running is always safe:

  * Never replaces the file wholesale — parses, edits, rewrites. Everything
    else in settings.json (other hooks, permissions, env) is untouched.
  * Idempotent by content: an existing hook whose command mentions the same
    script file is updated in place (repairs a moved repo or venv); anything
    else is left alone and the new hook is appended alongside.
  * Backs up to settings.json.bak-rfm before the first write. One backup,
    not a pile: the file is only written when something actually changes.

Paths are derived from this file's location, so a moved checkout just needs
a re-run. The venv interpreter is used for both hooks — the pure-Python
scoring engine runs on any Python, but pointing at the venv keeps one
interpreter for everything the integration runs.

Usage:  .venv/bin/python install_hooks.py [--dry-run] [--remove]
"""
import json
import os
import shlex
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(HERE, ".venv", "bin", "python")
SETTINGS = os.path.expanduser("~/.claude/settings.json")
CLAUDE_MD = os.path.expanduser("~/.claude/CLAUDE.md")
SKILL_SRC = os.path.join(HERE, "skills", "memory-review")
SKILL_DST = os.path.expanduser("~/.claude/skills/memory-review")

HOOKS = {
    "SessionStart": os.path.join(HERE, "hooks", "session_start.py"),
    "SessionEnd": os.path.join(HERE, "hooks", "session_end.py"),
    # Struggle-triggered synthesis (REVALIDATION.md Track 5). Registered
    # always, INERT unless RFM_SYNTHESIS=1 — it is a registered experiment,
    # not a default. Matched to Bash: this fires per tool call, and a Python
    # spawn on every Read/Edit/Grep would add latency to the very sessions
    # whose cost the experiment measures.
    "PostToolUse": os.path.join(HERE, "hooks", "post_tool_use.py"),
    # Per-turn query-conditioned retrieval (RFM_PERTURN=1). Registered
    # always, INERT unless the flag is set — a registered experiment
    # (Track 21b), not a default, on the same footing as the PostToolUse
    # synthesis/JIT capabilities.
    "UserPromptSubmit": os.path.join(HERE, "hooks", "user_prompt_submit.py"),
}
MATCHERS = {"PostToolUse": "Bash"}
# Per-tool-call hooks need a short leash; session hooks can take longer.
# UserPromptSubmit runs an optional applicability judge (RFM_PERTURN_JUDGE),
# a nested LLM call that overruns the 30s default; 150s lets it complete.
# That a per-turn hook needs 150s is itself the finding that live
# judge-in-hook retrieval is impractical in production — measured, not
# hidden (REVALIDATION.md Track 21b).
TIMEOUTS = {"PostToolUse": 10, "UserPromptSubmit": 150}

# Sentinel-fenced so re-runs replace rather than append, and --remove can
# strip it cleanly. Everything outside the fence is never touched.
MD_BEGIN = "<!-- rfm-memory:begin (managed by mem-rfm install_hooks.py) -->"
MD_END = "<!-- rfm-memory:end -->"
MD_BLOCK = f"""{MD_BEGIN}
## Memory (rfm-memory MCP)

- Before exploring a recurring problem from scratch, `memory_search` for it.
- Outcomes for memories you act on are inferred from the transcript at
  session end. Call `memory_feedback(id, helped)` only for what inference
  cannot see: a memory that misled or wasted effort (helped=false), or one
  that clearly saved real work (helped=true). Skip routine confirmations.
- Do not volunteer `memory_save` mid-task — durable lessons are mined from
  the session automatically and staged for /memory-review. "remember this"
  from the user still means `memory_save` (durable operational facts only,
  scoped to the repo name); "forget that" means `memory_delete`.
- `memory_update` when a stored fact is outdated but still worth keeping —
  it preserves the memory's earned usage record; delete-then-save does not.
- To review staged memory candidates from past sessions, run /memory-review.
{MD_END}"""


def _marker(script):
    return f"# rfm-memory-hook:{os.path.basename(script)}"


def hook_entry(script):
    # shlex.quote: the command is run through a shell, and a checkout under
    # a path with a space (common under /Users/First Last/...) would
    # otherwise word-split into a hook that silently never launches.
    # The trailing marker is a harmless shell comment ('#' and everything
    # after it is ignored) that mentions() below matches on.
    event = next((e for e, s in HOOKS.items() if s == script), None)
    return {"type": "command",
            "command": f"{shlex.quote(PYTHON)} {shlex.quote(script)}  {_marker(script)}",
            "timeout": TIMEOUTS.get(event, 30)}


def mentions(entry, script):
    """Is this settings entry one of ours, for `script` specifically? A
    per-script sentinel comment, not a substring match on the bare basename
    or the repo's directory layout: 'session_start.py' is a generic name a
    substring match could adopt from another tool's hook (then rewrite or
    --remove it), and matching a hard-coded path suffix ties ownership to
    where this repo happens to keep its hooks today. Same technique the
    CLAUDE.md block below uses to identify its own fenced section.

    The path-suffix fallback recognizes a hook installed by a prior version
    of this script (which had no marker) so a re-run upgrades it in place
    instead of installing a duplicate alongside it."""
    cmd = entry.get("command", "")
    if _marker(script) in cmd:
        return True
    legacy_suffix = "integrations/claude-code/hooks/" + os.path.basename(script)
    return legacy_suffix in cmd


def install(settings, remove=False):
    """Returns a list of human-readable change descriptions (empty = no-op)."""
    changes = []
    hooks = settings.setdefault("hooks", {})
    for event, script in HOOKS.items():
        groups = hooks.setdefault(event, [])
        ours = [(g, h) for g in groups for h in g.get("hooks", [])
                if mentions(h, script)]
        if remove:
            for g, h in ours:
                g["hooks"].remove(h)
                changes.append(f"removed {event} -> {os.path.basename(script)}")
            hooks[event] = [g for g in groups if g.get("hooks")]
            if not hooks[event]:
                del hooks[event]
            continue
        desired = hook_entry(script)
        if not ours:
            group = {"hooks": [desired]}
            if event in MATCHERS:
                group["matcher"] = MATCHERS[event]
            groups.append(group)
            changes.append(f"registered {event} -> {desired['command']}")
        else:
            for g, h in ours:
                if h != desired:
                    g["hooks"][g["hooks"].index(h)] = desired
                    changes.append(f"updated {event} -> {desired['command']}")
    if remove and not settings.get("hooks"):
        settings.pop("hooks", None)
    return changes


def sync_claude_md(dry=False, remove=False):
    """Maintain the fenced instruction block in ~/.claude/CLAUDE.md."""
    try:
        text = open(CLAUDE_MD).read()
    except FileNotFoundError:
        text = ""
    if MD_BEGIN in text and MD_END in text:
        head, rest = text.split(MD_BEGIN, 1)
        _, tail = rest.split(MD_END, 1)
        new = head + ("" if remove else MD_BLOCK) + tail
        change = "removed CLAUDE.md block" if remove else "updated CLAUDE.md block"
        if new == text:
            return []
    elif remove:
        return []
    else:
        new = (text.rstrip() + "\n\n" if text.strip() else "") + MD_BLOCK + "\n"
        change = f"added outcome-loop block to {CLAUDE_MD}"
    if not dry:
        os.makedirs(os.path.dirname(CLAUDE_MD), exist_ok=True)
        # Same discipline as settings.json below: back up what exists, then
        # write atomically. CLAUDE.md holds the user's own instructions; an
        # interrupted in-place rewrite must not be able to truncate it.
        if os.path.exists(CLAUDE_MD):
            shutil.copy2(CLAUDE_MD, CLAUDE_MD + ".bak-rfm")
        tmp = CLAUDE_MD + ".tmp-rfm"
        with open(tmp, "w") as f:
            f.write(new)
        os.replace(tmp, CLAUDE_MD)
    return [change]


def sync_skill(dry=False, remove=False):
    """Copy the memory-review skill into ~/.claude/skills/."""
    if remove:
        if not os.path.isdir(SKILL_DST):
            return []
        if not dry:
            shutil.rmtree(SKILL_DST)
        return [f"removed {SKILL_DST}"]
    if not os.path.exists(os.path.join(SKILL_SRC, "SKILL.md")):
        sys.exit(f"skill source missing: {os.path.join(SKILL_SRC, 'SKILL.md')}")

    def tree(root):
        """{relative path: contents} for every file under root."""
        out = {}
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                p = os.path.join(dirpath, name)
                with open(p, "rb") as f:
                    out[os.path.relpath(p, root)] = f.read()
        return out

    # Whole-tree comparison, not just SKILL.md: a skill that grows a helper
    # file must resync when only that file changed.
    if os.path.isdir(SKILL_DST) and tree(SKILL_SRC) == tree(SKILL_DST):
        return []
    if not dry:
        os.makedirs(os.path.dirname(SKILL_DST), exist_ok=True)
        if os.path.isdir(SKILL_DST):
            shutil.rmtree(SKILL_DST)
        shutil.copytree(SKILL_SRC, SKILL_DST)
    return [f"installed skill -> {SKILL_DST}"]


def main():
    dry, remove = "--dry-run" in sys.argv, "--remove" in sys.argv
    if not os.path.exists(PYTHON):
        sys.exit(f"venv python not found at {PYTHON} — create the venv first")
    for script in HOOKS.values():
        if not os.path.exists(script):
            sys.exit(f"hook script missing: {script}")

    try:
        with open(SETTINGS) as f:
            settings = json.load(f)
    except FileNotFoundError:
        settings = {}
    except json.JSONDecodeError as e:
        # A malformed settings.json silently disables EVERY setting in it;
        # editing on top would bless the corruption. Stop and say so.
        sys.exit(f"{SETTINGS} is not valid JSON ({e}) — fix it first")

    changes = install(settings, remove=remove)
    if changes and not dry:
        if os.path.exists(SETTINGS):
            shutil.copy2(SETTINGS, SETTINGS + ".bak-rfm")
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        tmp = SETTINGS + ".tmp-rfm"
        with open(tmp, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        os.replace(tmp, SETTINGS)
        changes.append(f"wrote {SETTINGS} (backup: {SETTINGS}.bak-rfm)")

    changes += sync_claude_md(dry=dry, remove=remove)
    changes += sync_skill(dry=dry, remove=remove)

    if not changes:
        print("already up to date, nothing written")
        return
    for c in changes:
        print(("would have " if dry else "") + c)
    if not dry:
        print("note: a running Claude Code session may need /hooks opened "
              "once (or a restart) to pick up hook changes")


if __name__ == "__main__":
    main()
