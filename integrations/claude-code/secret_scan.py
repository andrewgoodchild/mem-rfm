"""Credential redaction for everything that becomes a memory.

A memory is plaintext in the SQLite store and is re-injected into future
sessions, so a secret that gets in is replayed indefinitely. Two paths write
with no human in the loop -- sweep.py's admission and the SessionEnd miner's
candidate file -- and both draw on transcripts, where a failing command's
output can carry a token. Owned once, like log_env.py, so server.py, sweep.py
and hooks/session_end.py cannot drift on what counts as a secret.

Redact rather than refuse: "401 from the registry until GITHUB_TOKEN is
exported" is still worth remembering with the token itself gone. Patterns are
deliberately narrow (vendor-prefixed formats, PEM blocks, credentials in URLs,
and secret-named assignments with a literal value) because a false positive
silently mangles a command the agent will copy later. References such as
`$GITHUB_TOKEN`, `${API_KEY}` or `<your-token>` are not secrets and survive.

RFM_SECRET_SCAN=0 disables (the store is yours; this guards the default).
"""
import os
import re

# (kind, pattern, group whose text is replaced; 0 = the whole match).
# Specific vendor formats first, so a key inside `api_key=...` is named for
# its vendor rather than the generic assignment rule.
PATTERNS = [
    ("private_key", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
        r"(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)", re.S), 0),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"), 0),
    ("openai_key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}"), 0),
    ("github_token", re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})"), 0),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}"), 0),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), 0),
    ("stripe_key", re.compile(r"\b[rs]k_(?:live|test)_[0-9A-Za-z]{16,}"), 0),
    ("jwt", re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), 0),
    ("bearer_token", re.compile(
        r"(?i)\bbearer\s+([A-Za-z0-9._~+/-]{20,}=*)"), 1),
    # user:password@host, but not user:${TOKEN}@host -- a reference is not
    # a secret, and redacting it breaks the command it sits in.
    ("url_credentials", re.compile(
        r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:(?![$<{%*\[])([^@\s/]+)@"), 1),
    # KEY=value / key: "value" where the name ENDS in a secret word
    # (GITHUB_TOKEN, db_password -- not token_count, max_tokens) and the
    # value is a literal: not a $VAR, ${VAR}, <placeholder>, %s, masked ****,
    # a span an earlier rule already redacted, or code (SKIP below:
    # os.environ["API_KEY"], get_token(repo), settings.SECRET_KEY).
    ("secret_assignment", re.compile(
        r"(?i)\b[A-Za-z0-9_.-]*(?:password|passwd|secret|token|api[_-]?key|"
        r"access[_-]?key|secret[_-]?key|private[_-]?key|client[_-]?secret)"
        r"""(?![A-Za-z0-9_])["']?\s*[:=]\s*["']?(?![$<{%*\[])"""
        r"""([^\s"'`,;]{8,})"""), 1),
]


# Per rule: a match whose group also matches this is left alone. Only the
# generic assignment rule can match code -- a call, a subscript, or a dotted
# name, an expression that PRODUCES a secret at run time and is exactly the
# fix worth remembering. Vendor-prefixed formats cannot be code.
SKIP = {"secret_assignment": re.compile(
    r"[(\[]|^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$")}


def enabled():
    return os.environ.get("RFM_SECRET_SCAN", "1").strip().lower() not in (
        "0", "off", "false", "no")


def redact(text):
    """(clean_text, kinds) -- every credential-shaped span replaced by
    [REDACTED:<kind>], and the kinds found, in order, for the caller to log.
    Never logs or returns the secret itself."""
    if not text or not enabled():
        return text, []
    kinds = []
    for kind, pat, group in PATTERNS:
        skip = SKIP.get(kind)

        def sub(m, kind=kind, group=group, skip=skip):
            if skip and skip.search(m.group(group)):
                return m.group(0)
            kinds.append(kind)
            s, e = m.span(group)
            return (m.string[m.start():s] + f"[REDACTED:{kind}]"
                    + m.string[e:m.end()])
        text = pat.sub(sub, text)
    return text, kinds
