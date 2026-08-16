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
a re-run. The venv interpreter is used for both hooks: session_start needs
sqlite3 extension loading, which macOS system Python lacks.

Usage:  .venv/bin/python install_hooks.py [--dry-run] [--remove]
"""
import json
import os
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
}

# Sentinel-fenced so re-runs replace rather than append, and --remove can
# strip it cleanly. Everything outside the fence is never touched.
MD_BEGIN = "<!-- rfm-memory:begin (managed by mem-rfm install_hooks.py) -->"
MD_END = "<!-- rfm-memory:end -->"
MD_BLOCK = f"""{MD_BEGIN}
## Memory (rfm-memory MCP)

- Before exploring a recurring problem from scratch, `memory_search` for it.
- **After acting on any retrieved or injected memory, record the outcome:
  `memory_feedback(id, helped=true/false)`.** This is not optional polish —
  outcome feedback is the ranking signal; skipping it leaves every memory
  scored by recency and frequency alone.
- `memory_save` durable operational facts only (build quirks, dependency
  pins, invocation details, decisions, preferences) — never task state or
  anything derivable from the repo. Scope repo-specific facts to the repo
  name.
- `memory_update` when a stored fact is outdated but still worth keeping —
  it preserves the memory's earned usage record; delete-then-save does not.
- "remember this" means `memory_save`; "forget that" means `memory_delete`.
- To review staged memory candidates from past sessions, run /memory-review.
{MD_END}"""


def hook_entry(script):
    return {"type": "command",
            "command": f"{PYTHON} {script}",
            "timeout": 30}


def mentions(entry, script):
    return os.path.basename(script) in entry.get("command", "")


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
            groups.append({"hooks": [desired]})
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
        with open(CLAUDE_MD, "w") as f:
            f.write(new)
    return [change]


def sync_skill(dry=False, remove=False):
    """Copy the memory-review skill into ~/.claude/skills/."""
    if remove:
        if not os.path.isdir(SKILL_DST):
            return []
        if not dry:
            shutil.rmtree(SKILL_DST)
        return [f"removed {SKILL_DST}"]
    src_manifest = os.path.join(SKILL_SRC, "SKILL.md")
    if not os.path.exists(src_manifest):
        sys.exit(f"skill source missing: {src_manifest}")
    dst_manifest = os.path.join(SKILL_DST, "SKILL.md")
    try:
        if open(src_manifest).read() == open(dst_manifest).read():
            return []
    except FileNotFoundError:
        pass
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
