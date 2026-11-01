#!/usr/bin/env python3
"""Decision formation: the developer's rulings in a conversation, as memories.

The sweep stores what transfers to different tasks, reads only assistant
prose, and forbids naming a function or file, so it forms nothing from a chat
that settles a project rule (Track 27: 0 memories from 39 chats). This reads
both sides of one conversation and keeps the rule, with its values.

It runs when an operator points it at a transcript, never on its own. A row
therefore has no sightings: the operator's choice stands in for quarantine,
as a memory_save does. Every memory of a conversation shares a `source`, so
per-turn delivery can show a decision whole (RFM_PERTURN_GROUP).

Conversations are not consolidated. A later decision does not replace an
earlier one: an LLM doing that was wrong on 13 of 21 (Track 28). Both stay,
dated, and delivery shows the later first.

Usage: decisions.py TRANSCRIPT [--scope NAME]
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "hooks"))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import secret_scan  # noqa: E402
import store        # noqa: E402
import transcripts  # noqa: E402

CAP = 12000
MAX_PER_CHAT = 3
PROMPT = """You decide what enters the long-term memory of a coding agent
that will work on this repository later. Below is a past conversation between
a developer and an agent.

Record the decisions the developer reached that the code alone does not
explain: exact rules, values, orderings and exceptions. Ignore proposals the
conversation rejected; where a later turn overrides an earlier one, keep only
the final rule. Each memory must stand alone for someone who never saw this
conversation: name the module or function and the symptom it answers, and
state the rule in full, with its exact values.

--- BEGIN CONVERSATION ---
{chat}
--- END CONVERSATION ---

Reply with a JSON list only, at most {limit} items, possibly empty:
[{{"content": "the memory"}}]"""


def chat_of(path):
    """A Claude Code transcript's human and assistant text, in order. Tool
    results are not the conversation, and our injected blocks never count."""
    turns = []
    for rec in transcripts.main_thread(transcripts.parse_jsonl(path)):
        if rec.get("type") not in ("user", "assistant"):
            continue
        content = (rec.get("message") or {}).get("content")
        if isinstance(content, str):
            blocks = [content]
        elif isinstance(content, list):
            blocks = [b.get("text", "") for b in content
                      if isinstance(b, dict) and b.get("type") == "text"]
        else:
            continue
        text = transcripts.strip_injected("\n".join(blocks)).strip()
        if text:
            turns.append(f"{rec['type'].upper()}: {text}")
    return "\n\n".join(turns)


def form(chat, llm, parse):
    """The memories in one conversation: `llm` answers a prompt, `parse`
    reads its JSON."""
    items = parse(llm(PROMPT.format(chat=chat[:CAP], limit=MAX_PER_CHAT)))
    if not isinstance(items, list):
        return []
    return [i["content"] for i in items
            if isinstance(i, dict) and isinstance(i.get("content"), str)
            and i["content"].strip()][:MAX_PER_CHAT]


def source_of(chat):
    return "chat:" + hashlib.sha256(chat.encode()).hexdigest()[:16]


def save(db, memories, source, scope, embed, created_at=None):
    """Insert a conversation's memories, sanitized as a server save is.
    Re-forming a conversation adds nothing."""
    if db.execute("SELECT 1 FROM rfm_memories WHERE source = ? LIMIT 1",
                  (source,)).fetchone():
        return []
    ids = []
    for content in memories:
        text = secret_scan.redact(transcripts.flatten(content))[0]
        vec = embed(text)
        blob = struct.pack(f"{len(vec)}f", *vec) if vec else None
        cur = db.execute(
            "INSERT INTO rfm_memories (content, created_at, embedding, scope,"
            " source) VALUES (?, ?, ?, ?, ?)",
            (text, created_at or time.time(), blob, scope, source))
        ids.append(cur.lastrowid)
    return ids


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("transcript")
    ap.add_argument("--scope", default=None,
                    help="default: the current repository")
    args = ap.parse_args(argv)
    import sqlite3
    import rfm
    import sweep
    import user_prompt_submit as ups
    chat = chat_of(args.transcript)
    if not chat:
        print("no conversation in that file")
        return 1
    memories = form(chat, sweep.llm, sweep.parse_json)
    db = sqlite3.connect(sweep.DB_PATH, timeout=10.0)
    rfm.register(db)
    store.ensure(db)
    ids = save(db, memories, source_of(chat), args.scope or store.project(),
               ups.embed)
    db.commit()
    db.close()
    print(json.dumps({"formed": len(memories), "saved": ids}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
