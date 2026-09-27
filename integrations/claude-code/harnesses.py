"""Harness registry: the one declaration of how mem-rfm plugs into each
coding agent. install_hooks.py writes host config from it and the hooks
resolve their payload fields and transcript reader from it, so the
installed wiring and the runtime cannot drift apart. (The pattern is
Hindsight's hook-lifecycle registry, vectorize-io/hindsight, MIT.)

mem-rfm's lifecycle has four stages. Hindsight's has three; the extra one,
post_tool, is what lets a memory surface the moment its condition fires:

  session_start  inject the top memories by prior        (session_start.py)
  prompt         per-turn retrieval, off by default      (user_prompt_submit.py)
  post_tool      condition-triggered JIT, off by default (post_tool_use.py)
  session_end    outcomes, correction mining, pruning    (session_end.py)

Adding a harness is adding a row here and a transcript reader in
transcripts.READERS. Host differences are data, each pinned by
test_harnesses.py rather than a comment:

  config_style  how the host spells one hook registration. Only "nested"
                (Claude Code's matcher groups) is implemented; others will
                be added with the first harness that needs them.
  timeout_unit  the unit the host reads a timeout in. Hindsight found a
                host (Qwen Code) that reads milliseconds, where 30 kills a
                hook before Python starts; declared, not assumed.
  payload       the host's field names for the transcript path, session id
                and prompt in a hook's stdin JSON.
"""
import collections
import os

HookSpec = collections.namedtuple("HookSpec", "event script matcher timeout")
Harness = collections.namedtuple(
    "Harness", "name settings config_style timeout_unit payload reader hooks")

STAGES = ("session_start", "prompt", "post_tool", "session_end")

HARNESSES = {
    "claude-code": Harness(
        name="claude-code",
        settings="~/.claude/settings.json",
        config_style="nested",
        timeout_unit="seconds",
        payload={"transcript": "transcript_path", "session": "session_id",
                 "prompt": "prompt"},
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
            # Per-turn query-conditioned retrieval (RFM_PERTURN=1). Registered
            # always, INERT unless the flag is set (Track 21b). It runs an
            # optional applicability judge (RFM_PERTURN_JUDGE), a nested LLM
            # call that overruns 30s; 150s lets it complete. That a per-turn
            # hook needs 150s is itself the finding that live judge-in-hook
            # retrieval is impractical in production.
            "prompt": HookSpec("UserPromptSubmit", "user_prompt_submit.py", None, 150),
        },
    ),
}

DEFAULT = "claude-code"


def current():
    """The harness this hook process serves: RFM_HARNESS, else Claude Code.
    Defaulting keeps every existing install working unchanged."""
    return HARNESSES.get(os.environ.get("RFM_HARNESS", DEFAULT),
                         HARNESSES[DEFAULT])


def payload_field(harness, key, payload):
    """One field of a hook's stdin JSON, by the harness's own name for it."""
    return (payload or {}).get(harness.payload[key])


def host_timeout(harness, seconds):
    """A timeout in the unit the host reads."""
    return seconds * 1000 if harness.timeout_unit == "milliseconds" else seconds
