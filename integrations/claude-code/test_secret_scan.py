#!/usr/bin/env python3
"""Credential redaction on every write path (secret_scan.py). No LLM
calls. Exit 0 = pass.

Usage: test_secret_scan.py
"""
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="rfm-secrettest-")
os.environ["RFM_MEMORY_DB"] = os.path.join(TMP, "test.db")
os.environ["RFM_LOG"] = "0"
sys.path.insert(0, HERE)
import secret_scan  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail
                                                   else ""))
    if not ok:
        failures.append(name)


GH = "ghp_" + "a1B2" * 9
SECRETS = {
    "github_token": f"export GITHUB_TOKEN={GH} then re-run npm ci",
    "openai_key": "OPENAI_API_KEY=sk-proj-" + "x7" * 16,
    "anthropic_key": "key sk-ant-api03-" + "Zq" * 20,
    "aws_access_key": "aws configure set aws_access_key_id AKIAIOSFODNN7EXAMPLE",
    "bearer_token": 'curl -H "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123" api',
    "url_credentials": "pip install --index-url https://bob:hunter2pass@pypi.corp/simple x",
    "private_key": "-----BEGIN OPENSSH PRIVATE KEY----- b3BlbnNzaC1rZXk -----END OPENSSH PRIVATE KEY-----",
    "secret_assignment": 'DB_PASSWORD="s3cretValue!" in .env',
    "jwt": "cookie eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_X",
}
print("redaction")
for kind, text in SECRETS.items():
    out, kinds = secret_scan.redact(text)
    check(kind, f"[REDACTED:{kind}]" in out and kinds[:1] == [kind],
          f"{out!r} {kinds}")
out, _ = secret_scan.redact(SECRETS["github_token"])
check("context around a secret survives",
      out.startswith("export GITHUB_TOKEN=") and out.endswith("then re-run npm ci"), out)
check("secret text is gone", GH not in out)

# Things that look near a secret but are not one: a false positive would
# silently corrupt a command the agent later copies.
BENIGN = [
    "password=$DB_PASSWORD is read from the environment",
    "api_key: ${API_KEY}",
    "set token=<your-token-here> in config",
    "token_count=12345678 exceeds the window",
    "max_tokens=40000000",
    "setuptools 82 no longer ships pkg_resources; add a shim to PYTHONPATH",
    "git clone https://github.com/org/repo.git",
    "use --token-file ~/.config/tok instead of inline tokens",
    "PASSWORD=****",
]
print("benign text passes through")
for text in BENIGN:
    out, kinds = secret_scan.redact(text)
    check(text[:40], out == text and not kinds, f"{out!r} {kinds}")

print("RFM_SECRET_SCAN=0 disables")
os.environ["RFM_SECRET_SCAN"] = "0"
check("off", secret_scan.redact(SECRETS["github_token"])[1] == [])
del os.environ["RFM_SECRET_SCAN"]

print("sweep admission stores the redacted text")
import sweep  # noqa: E402
sweep.DB_PATH = os.environ["RFM_MEMORY_DB"]
sweep.LOG = os.path.join(TMP, "rfm-log.jsonl")
db = sqlite3.connect(sweep.DB_PATH)
sweep.ensure_schema(db)
mid = sweep.admit(db, {"content": f"npm ci 401s until the registry token is set: "
                                  f"NPM_TOKEN={GH}",
                       "condition_class": "permission denied"}, [], "test")
stored = db.execute("SELECT content FROM rfm_memories WHERE id = ?",
                    (mid,)).fetchone()[0]
check("no token in store", GH not in stored, stored)
check("redaction marker stored", "[REDACTED:github_token]" in stored, stored)

print("memory_save / memory_update validation redacts")
try:
    import server  # noqa: E402  (needs the integration venv: mcp, sqlite-vec)
except ImportError as e:
    print(f"  skip  server path — {e}")
else:
    got = server._check(f"registry needs GITHUB_TOKEN={GH}")
    check("server._check", GH not in got and "[REDACTED:github_token]" in got, got)

print()
if failures:
    print(f"FAILED: {len(failures)} — {', '.join(failures)}")
    sys.exit(1)
print("all passed")
