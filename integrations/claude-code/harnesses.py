"""Harness registry: the one declaration of how mem-rfm plugs into each
coding agent. install_hooks.py writes host config from it and the hooks
resolve their payload fields and transcript reader from it, so the
installed wiring and the runtime cannot drift apart. (The pattern is
Hindsight's hook-lifecycle registry, vectorize-io/hindsight, MIT.)

mem-rfm's lifecycle has four stages (post_tool rides two host events)
plus one guard. Hindsight's has three; the extra stage, post_tool, is what
lets a memory surface the moment its condition fires:

  session_start  inject the top memories by prior        (session_start.py)
  prompt         per-turn retrieval, off by default      (user_prompt_submit.py)
  post_tool      condition-triggered JIT, off by default (post_tool_use.py)
                 — also on the host's tool-FAILURE event, where a non-zero
                 exit is delivered (post_tool_failure, same script)
  session_end    outcomes, correction mining, pruning    (session_end.py)
  pre_tool       guard: subagents never save or grade    (pre_tool_use.py)

Adding a harness is adding a row here and a transcript reader in
transcripts.READERS. Host differences are data, each pinned by
test_harnesses.py rather than a comment:

  config_style  how the host spells one hook registration. Only "nested"
                (Claude Code's matcher groups) is implemented; others will
                be added with the first harness that needs them.
  timeout_unit  the unit the host reads a timeout in. Hindsight found a
                host (Qwen Code) that reads milliseconds, where 30 kills a
                hook before Python starts; declared, not assumed.
  payload       the host's field names for the transcript path, session id,
                prompt, and the field that is present only when a hook
                fires inside a subagent ("subagent").
"""
import collections
import os
import sys

HookSpec = collections.namedtuple("HookSpec", "event script matcher timeout")
Harness = collections.namedtuple(
    "Harness", "name settings config_style timeout_unit payload reader hooks")

STAGES = ("session_start", "prompt", "post_tool", "post_tool_failure",
          "session_end", "pre_tool")

HARNESSES = {
    "claude-code": Harness(
        name="claude-code",
        settings="~/.claude/settings.json",
        config_style="nested",
        timeout_unit="seconds",
        # A tuple lists alternative spellings, tried in order: Claude
        # Code has sent the prompt as both.
        # "subagent": agent_id is in the hook input only when the hook fires
        # inside a subagent (Agent/Task tool worker). agent_type alone is NOT
        # a subagent marker: a main thread started with --agent carries it
        # without agent_id. Checked against Claude Code 2.1.300's hook-input
        # schema.
        payload={"transcript": "transcript_path", "session": "session_id",
                 "prompt": ("prompt", "user_prompt"), "subagent": "agent_id"},
        reader="claude-code",
        # Dict order is install order: the order a fresh install writes the
        # events into settings.json, kept as the pre-registry installer had it.
        hooks={
            "session_start": HookSpec("SessionStart", "session_start.py", None, 30),
            "session_end": HookSpec("SessionEnd", "session_end.py", None, 30),
            # Struggle-triggered synthesis and JIT (RFM_SYNTHESIS / RFM_JIT).
            # Registered always, INERT unless flagged. Matched to Bash: it
            # fires per tool call, and a Python spawn on every Read/Edit/Grep
            # would add latency to the very sessions it measures.
            "post_tool": HookSpec("PostToolUse", "post_tool_use.py", "Bash", 10),
            # A non-zero Bash exit is delivered on PostToolUseFailure, never
            # PostToolUse; show-on-error JIT needs both. Same script, same
            # inertness (RFM_JIT unset -> exits before reading stdin).
            "post_tool_failure": HookSpec("PostToolUseFailure",
                                          "post_tool_use.py", "Bash", 10),
            # Per-turn query-conditioned retrieval (RFM_PERTURN=1). Registered
            # always, INERT unless the flag is set (Track 21b). It runs an
            # optional applicability judge (RFM_PERTURN_JUDGE), a nested LLM
            # call that overruns 30s; 150s lets it complete. That a per-turn
            # hook needs 150s is itself the finding that live judge-in-hook
            # retrieval is impractical in production.
            "prompt": HookSpec("UserPromptSubmit", "user_prompt_submit.py", None, 150),
            # Subagents must not write the store: a worker sees a slice of
            # the task, its "lessons" are about the slice, and its feedback
            # grades memories against a goal it was never given. The MCP
            # server cannot tell who is calling, so the guard is a
            # PreToolUse deny keyed on agent_id. Matched to this server's
            # tools only, so it spawns on nothing else.
            "pre_tool": HookSpec("PreToolUse", "pre_tool_use.py",
                                 "mcp__rfm-memory__.*", 10),
        },
    ),
}

DEFAULT = "claude-code"


def current():
    """The harness this hook process serves: RFM_HARNESS, else Claude Code.
    Defaulting keeps every existing install working unchanged; an unknown
    name falls back too, but says so on stderr rather than silently reading
    another harness's transcripts as Claude Code's."""
    name = os.environ.get("RFM_HARNESS", DEFAULT)
    if name not in HARNESSES:
        print(f"rfm: unknown RFM_HARNESS {name!r}; using {DEFAULT} "
              f"(known: {', '.join(HARNESSES)})", file=sys.stderr)
        name = DEFAULT
    return HARNESSES[name]


def payload_field(harness, key, payload):
    """One field of a hook's stdin JSON, by the harness's own name for it."""
    names = harness.payload[key]
    for name in (names,) if isinstance(names, str) else names:
        value = (payload or {}).get(name)
        if value:
            return value
    return None


def is_subagent(harness, payload):
    """Did this hook fire inside a subagent? Hosts without the field (no
    entry in payload) never report one."""
    return "subagent" in harness.payload and bool(
        payload_field(harness, "subagent", payload))


def host_timeout(harness, seconds):
    """A timeout in the unit the host reads."""
    return seconds * 1000 if harness.timeout_unit == "milliseconds" else seconds
