"""The harness's `icl` system with prompt caching on the litellm route (Track 36).

Installed into the harness checkout as `src/systems/icl_cached/system.py` by
run_track36.py. `icl` keeps the whole run in context and, through litellm,
re-reads it uncached on every call: on a 40-question run that is tens of
dollars. Its native Anthropic path would cache the system prompt only. This
subclass changes nothing the model reads; it marks the last message of every
request with a `cache_control` breakpoint, so the growing prefix is written to
Anthropic's cache once and read from it after. The patch is applied to the
`icl` module's own reference to `completion_with_structured_output`, so only
`icl_cached` instances take it; `mem_rfm` keeps its own call path.

Cost in the trace files is still what OpenRouter reports as the upstream
charge, cache reads included, so D4 compares what each arm would really cost.
"""

from __future__ import annotations

import copy

from ...registry import register_system
from ..icl import system as _icl


def _merged(messages):
    """Consecutive same-role string messages joined into one. icl appends the
    task's feedback and its next prompt as two user messages; litellm merges
    them for Anthropic, and the merge moves the block boundary the previous
    call's breakpoint sat on, so the cache was written every call and read
    on none (Track 36: 3.9M tokens written, 0.01M read). Merging here first
    keeps one user block per turn and the prefix stable."""
    out = []
    for m in copy.deepcopy(messages):
        if (out and out[-1].get("role") == m.get("role")
                and isinstance(out[-1].get("content"), str)
                and isinstance(m.get("content"), str)):
            out[-1]["content"] = out[-1]["content"] + "\n\n" + m["content"]
        else:
            out.append(m)
    return out


def _with_breakpoint(messages):
    out = _merged(messages)
    for m in reversed(out):
        if m.get("role") in ("user", "assistant"):
            content = m.get("content")
            if isinstance(content, str):
                m["content"] = [{"type": "text", "text": content,
                                 "cache_control": {"type": "ephemeral"}}]
            elif isinstance(content, list) and content and isinstance(content[-1], dict):
                content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
            break
    return out


_ORIGINAL = _icl.completion_with_structured_output


def _cached_completion(model, messages, response_schema):
    return _ORIGINAL(model=model, messages=_with_breakpoint(messages),
                     response_schema=response_schema)


@register_system("icl_cached")
class ICLCachedSystem(_icl.ICLSystem):
    """`icl`, with a moving prompt-cache breakpoint on the last message."""

    # The CLI builds its --system.<param> flags from this signature, so it
    # must be explicit: icl's parameters, with the name and the litellm chat
    # path as defaults.
    def __init__(
        self,
        model: str = "gpt-5",
        max_tokens: int | None = None,
        system_prompt: str = "",
        name: str = "icl_cached",
        reserve_tokens: int = 500,
        provider_mode: str = "litellm_chat",
        openai_store: bool = True,
        openai_include_encrypted_reasoning: bool = False,
        anthropic_max_tokens: int | None = None,
    ):
        super().__init__(
            model=model, max_tokens=max_tokens, system_prompt=system_prompt,
            name=name, reserve_tokens=reserve_tokens, provider_mode=provider_mode,
            openai_store=openai_store,
            openai_include_encrypted_reasoning=openai_include_encrypted_reasoning,
            anthropic_max_tokens=anthropic_max_tokens)
        _icl.completion_with_structured_output = _cached_completion

    def get_run_artifacts(self):
        art = super().get_run_artifacts()
        art["artifact_type"] = "icl_cached"
        art["prompt_cache"] = "moving breakpoint on the last message"
        return art
