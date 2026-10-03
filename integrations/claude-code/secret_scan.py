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

# (kind, pattern, group whose text is replaced; 0 = the whole match, or a
# tuple of alternative groups, the first that matched).
# Specific formats first, so a key inside `api_key=...` is named for its
# vendor rather than the generic assignment rule.
PATTERNS = [
    ("private_key", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?"
        r"(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|$)", re.S), 0),
    ("anthropic_key", re.compile(r"(?<![\w-])sk-ant-[A-Za-z0-9_-]{20,}"), 0),
    # Not preceded by a word char or dash, and with a digit in it:
    # `pip install sk-video-processing-toolkit` is a package, not a key.
    ("openai_key", re.compile(
        r"(?<![\w-])sk-(?:proj-|svcacct-)?(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{20,}"), 0),
    ("github_token", re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})"), 0),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"), 0),
    ("npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{36,}"), 0),
    ("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{30,}"), 0),
    ("pypi_token", re.compile(r"\bpypi-AgE[A-Za-z0-9_-]{40,}"), 0),
    ("google_oauth_secret", re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}"), 0),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}"), 0),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), 0),
    ("slack_webhook", re.compile(
        r"hooks\.slack\.com/services/([A-Za-z0-9/]{20,})"), 1),
    ("stripe_key", re.compile(r"\b[rs]k_(?:live|test)_[0-9A-Za-z]{16,}"), 0),
    ("sentry_dsn", re.compile(r"https://([0-9a-f]{32})@[^\s/]*sentry\.io"), 1),
    ("jwt", re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), 0),
    # A bearer token has a digit somewhere: "Bearer authentication" is prose.
    ("bearer_token", re.compile(
        r"(?i)\bbearer\s+(?=[A-Za-z0-9._~+/-]*\d)([A-Za-z0-9._~+/-]{8,}=*)"), 1),
    ("authorization", re.compile(
        r"(?i)\bauthorization:\s*(?:token|basic)\s+([A-Za-z0-9._~+/=-]{8,})"), 1),
    # user:password@host, empty user (redis://:pw@) included; greedy to the
    # last @ so a password containing @ is covered whole.
    ("url_credentials", re.compile(
        r"\b[a-z][a-z0-9+.-]*://[^/\s:@]*:([^\s/]+)@"), 1),
    # Credentials passed as flags to tools that take them that way.
    ("cli_password", re.compile(
        r"(?i)\b(?:mysql|mysqldump|mysqladmin|mariadb)\b[^\n|;&]*?\s-p(\S+)"
        r"|\b(?:docker|podman|twine|helm)\b[^\n|;&]*?\s(?:-p|--password)[ =](\S+)"
        r"|\bcurl\b[^\n|;&]*?\s(?:-u|--user)[ =]?['\"]?[^:\s'\"]+:([^\s'\"]+)"),
     (1, 2, 3)),
    ("netrc_password", re.compile(
        r"(?i)\bmachine\s+\S+(?:\s+login\s+\S+)?\s+password\s+(\S+)"), 1),
    ("aws_configure", re.compile(
        r"(?i)\baws\s+configure\s+set\s+\S*(?:secret|token|key)\S*\s+(\S+)"), 1),
    # KEY=value / "key": "value" where the name ENDS in a secret word
    # (GITHUB_TOKEN, db_password, apiKey -- not token_count, max_tokens).
    # A quoted value is taken whole (spaces and ; included); a bare one runs
    # to whitespace or , ; (a closing call paren excluded) -- `[ \t]*` so
    # YAML's key:\n value is not read
    # across lines. SKIP below exempts what is not a literal secret.
    ("secret_assignment", re.compile(
        r"(?i)\b[A-Za-z0-9_.-]*(?:password|passwd|secret|token|api[_-]?key|"
        r"access[_-]?key|secret[_-]?key|private[_-]?key|client[_-]?secret)"
        r"""(?![A-Za-z0-9_])["']?[ \t]*[:=][ \t]*"""
        r"""(?:"([^"\n]{6,})"|'([^'\n]{6,})'|`([^`\n]{6,})`"""
        r"""|([^\s"'`,;]{6,}?)(?=\)?(?:[\s"'`,;]|$)))"""),
     (1, 2, 3, 4)),
]


# A reference to a secret, not the secret: $VAR, ${VAR}, $(cmd),
# ${{ secrets.X }}, <placeholder>, %s / %(name)s, masked ****, or a span an
# earlier rule already redacted. Redacting these breaks the command they sit
# in and protects nothing.
_REFERENCE = (r"^\$\{?[A-Za-z_]\w*\}?$|^\$\(|^\$\{\{|^\{\{.*\}\}$|^<[^<>]*>$"
              r"|^%(?:\(\w+\))?s$|^\*+$|^\[REDACTED:")
# Per rule: a match whose group also matches this is left alone. Beyond
# references, only the generic assignment rule can match code -- an
# expression that PRODUCES a secret at run time, which is exactly the fix
# worth remembering: a call get_token(repo), a subscript os.environ[", a
# dotted name settings.SECRET_KEY (no digits in any segment, so
# hunter2.pass stays a password), a snake/SCREAMING identifier with an
# underscore (OPENAI_API_KEY, db_password), a jq path .access_token, or a
# filesystem path. The cost, accepted and stated: a literal passphrase
# written like an identifier (correct_horse_battery) is not redacted.
# Every rule leaves a span an earlier rule already redacted alone.
_ALREADY = re.compile(r"^\[REDACTED:")
SKIP = {
    "url_credentials": re.compile(_REFERENCE),
    "secret_assignment": re.compile(
        _REFERENCE + r"|^[A-Za-z_][\w.]*\([^()]*\)?$|^[A-Za-z_][\w.]*\[['\"]?$"
        r"|^[A-Za-z_][A-Za-z_]*(?:\.[A-Za-z_][A-Za-z_]*)+$"
        r"|^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+$"
        r"|^\.[A-Za-z_]|^(?:/|~/|\./)"
        # user:$TOKEN@host -- a URL's userinfo reference, seen from the
        # assignment rule's side (url_credentials already let it through).
        r"|^\$\{?[A-Za-z_]\w*\}?@[\w-]+\.[\w.-]+"),
}


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
        skip = SKIP.get(kind, _ALREADY)

        def sub(m, kind=kind, group=group, skip=skip):
            g = next((g for g in group if m.group(g) is not None), None) \
                if isinstance(group, tuple) else group
            if g is None or (skip and skip.search(m.group(g))):
                return m.group(0)
            kinds.append(kind)
            s, e = m.span(g)
            return (m.string[m.start():s] + f"[REDACTED:{kind}]"
                    + m.string[e:m.end()])
        text = pat.sub(sub, text)
    return text, kinds
