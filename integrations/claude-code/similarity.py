"""Text similarity shared by the sweep's dedupe and session_end's
reconcile step: embedding cosine when fastembed is importable (the
integration venv has it), token Jaccard as the degraded fallback.

One owner so the two formation paths cannot drift on what "similar"
means or on how they degrade. Track 18 measured the Jaccard shortcut
failing on paraphrase (22 rewordings of one fact, zero merges), so the
fallback is loud, once, and callers that threshold must pick a
threshold per `mode()` — a cosine cut-off means nothing applied to a
Jaccard score.
"""
import os
import re
import sys

_EMB = {"model": None, "tried": False, "cache": {}}
# True: never download the model, use only the local cache (hooks set it).
LOCAL_ONLY = False
# Called once, with no arguments, the first time the embedder fails to
# load — sweep.py hooks its own audit-log line in here.
on_degraded = []


def tokens(s):
    return set(re.findall(r"[a-z0-9_./-]{3,}", (s or "").lower()))


def _model():
    if not _EMB["tried"]:
        _EMB["tried"] = True
        try:
            # No Hugging Face Hub telemetry; read when huggingface_hub is imported.
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
            from fastembed import TextEmbedding
            _EMB["model"] = (TextEmbedding(local_files_only=True)
                             if LOCAL_ONLY else TextEmbedding())
        except Exception:
            _EMB["model"] = None
            print("rfm: WARNING — fastembed unavailable, similarity "
                  "degraded to token overlap; run under the integration "
                  "venv for real dedupe", file=sys.stderr)
            for fn in on_degraded:
                try:
                    fn()
                except Exception:
                    pass
    return _EMB["model"]


def mode():
    """'embedding' or 'tokens' — which scale similarity() returns."""
    return "embedding" if _model() is not None else "tokens"


def prime(texts):
    """Embed many texts in one batch (fastembed is far cheaper batched than
    one call per text). A no-op in degraded mode."""
    m = _model()
    if m is None:
        return
    todo = list(dict.fromkeys(t[:1000] for t in texts
                              if t[:1000] not in _EMB["cache"]))
    if todo:
        for key, vec in zip(todo, m.embed(todo)):
            _EMB["cache"][key] = vec


def _embed(text):
    if _model() is None:
        return None
    key = text[:1000]
    if key not in _EMB["cache"]:
        prime([key])
    return _EMB["cache"][key]


def jaccard(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def similarity(a, b):
    ea, eb = _embed(a), _embed(b)
    if ea is not None and eb is not None:
        num = float((ea * eb).sum())
        den = float((ea * ea).sum()) ** 0.5 * float((eb * eb).sum()) ** 0.5
        return max(0.0, num / den) if den else 0.0
    return jaccard(a, b)
