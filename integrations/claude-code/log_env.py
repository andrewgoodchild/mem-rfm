"""Shared RFM_LOG / RFM_LOG_CONTENT contract.

Owned once so server.py, hooks/session_end.py, and log_stats.py cannot
drift on what a given RFM_LOG value means — they all read/write the same
rfm-log.jsonl and must agree on where it lives and whether it's on.

RFM_LOG is both a switch and a path: an off-ish sentinel disables, an
on-ish sentinel (users mirror the source's own default) keeps the default
path beside the database, anything else IS the path. Treating "1" as a
literal path made LOG_PATH="1", whose empty dirname made every log() raise
— logging enabled yet silently dead. Sentinels are matched
case-insensitively and cover both polarities: RFM_LOG=false/no/OFF must
disable, not become a literal log file named "false" with content logging
still on.
"""
import os

OFF = ("0", "off", "", "false", "no")
ON = ("1", "on", "true", "yes")


def resolve_log(raw, default_dir):
    """(enabled, path) for an RFM_LOG value, given the directory the
    default log file lives beside (the memory database's directory)."""
    norm = raw.strip().lower()
    enabled = norm not in OFF
    path = (os.path.join(default_dir, "rfm-log.jsonl") if norm in OFF + ON
             else os.path.expanduser(raw))
    return enabled, path


def content_enabled(raw):
    return raw not in ("0", "off")


def redact(text, content_on):
    """Queries and memory content are the sensitive part of a log line;
    content_on=False keeps lengths only."""
    return text if content_on else f"<{len(text)} chars>"
