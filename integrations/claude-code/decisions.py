#!/usr/bin/env python3
"""Decision formation: the developer's rulings in a conversation, as memories.

The sweep stores what transfers to different tasks, reads only assistant
prose, and forbids naming a function or file, so it forms nothing from a chat
that settles a project rule (Track 27: 0 memories from 39 chats). This reads
both sides of one conversation and keeps the rule, with its values.

It runs when an operator points it at a transcript, never on its own, and by
default only prints what it formed: on real sessions about a quarter of the
memories were judged both faithful and durable (Track 32), so storing them is a
choice made with --save. A saved row has no sightings: the operator's choice stands in for quarantine,
as a memory_save does. Every memory of a conversation shares a `source`, so
per-turn delivery can show a decision whole (RFM_PERTURN_GROUP).

A conversation longer than CAP is formed in windows that break between turns,
and past MAX_WINDOWS only the latest are read: real sessions settle things late,
and reading the first CAP characters missed a median 89% of the long ones.

Each memory carries a quote from the conversation, and a memory whose quote
is not there verbatim is dropped. That catches the few made up outright, 3% on
real sessions, and no more: a judge still found 37% of the rest unsupported by
the window they came from, since a quote shows where a memory came from, not
that the developer decided it (Tracks 32 and 33). A saved memory keeps its
quote and the transcript it came from, so `verify.py` can check it against
that source later, the one check the outcome ledger cannot make for a rule
(Track 31: a stale decision shown 15 times earned no outcome).

Conversations are not consolidated. A later decision does not replace an
earlier one: an LLM doing that was wrong on 13 of 21 (Track 28). Both stay,
dated, and delivery shows the later first.

Usage: decisions.py TRANSCRIPT [--save] [--scope NAME]
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
MAX_WINDOWS = 20
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

Reply with a JSON list only, at most {limit} items, possibly empty. Each item
quotes the conversation: a verbatim excerpt of at most 200 characters from the
turn that settles the decision, so the memory can be checked against it.
[{{"content": "the memory", "quote": "verbatim excerpt"}}]"""


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


def windows(chat, cap=CAP):
    """The conversation in pieces of at most `cap` characters, cut between
    turns; a single turn longer than that is cut."""
    out, cur = [], ""
    for turn in chat.split("\n\n"):
        while len(turn) > cap:
            if cur:
                out.append(cur)
                cur = ""
            out.append(turn[:cap])
            turn = turn[cap:]
        if cur and len(cur) + 2 + len(turn) > cap:
            out.append(cur)
            cur = ""
        cur = cur + "\n\n" + turn if cur else turn
    if cur:
        out.append(cur)
    return out


def _norm(text):
    return " ".join(text.split()).lower()


def grounded(item, chat):
    """Does the item's quote occur in the chat, whitespace and case aside? A
    memory whose quote is not there was made up or misread."""
    quote = item.get("quote")
    return isinstance(quote, str) and len(_norm(quote)) >= 12 \
        and _norm(quote) in _norm(chat)


def form_items(chat, llm, parse, dropped=None):
    """The memories in one conversation, each {"content", "quote"}: `llm`
    answers a prompt, `parse` reads its JSON. A memory whose quote is not in
    the conversation is dropped, into `dropped` when a list is given."""
    chat = chat[:CAP]
    items = parse(llm(PROMPT.format(chat=chat, limit=MAX_PER_CHAT)))
    if not isinstance(items, list):
        return []
    kept = []
    for i in items:
        if not (isinstance(i, dict) and isinstance(i.get("content"), str)
                and i["content"].strip()):
            continue
        if grounded(i, chat):
            kept.append({"content": i["content"], "quote": i["quote"]})
        elif dropped is not None:
            dropped.append(i["content"])
    return kept[:MAX_PER_CHAT]


def form(chat, llm, parse, dropped=None):
    """form_items, as content strings: what the probes and the Track 34
    provider read."""
    return [i["content"] for i in form_items(chat, llm, parse, dropped)]


def source_of(chat):
    return "chat:" + hashlib.sha256(chat.encode()).hexdigest()[:16]


def save(db, memories, source, scope, embed, created_at=None,
         transcript=None):
    """Insert a conversation's memories, sanitized as a server save is.
    Re-forming a conversation adds nothing. A memory may be a string or a
    form_items dict; a dict's quote is kept, and `transcript` (a path) goes
    in `origins` as the source verify.py reads it back from."""
    if db.execute("SELECT 1 FROM rfm_memories WHERE source = ? LIMIT 1",
                  (source,)).fetchone():
        return []
    origins = json.dumps([f"transcript:{os.path.abspath(transcript)}"]) \
        if transcript else None
    ids = []
    for m in memories:
        content = m["content"] if isinstance(m, dict) else m
        quote = m.get("quote") if isinstance(m, dict) else None
        text = secret_scan.redact(transcripts.flatten(content))[0]
        vec = embed(text)
        blob = struct.pack(f"{len(vec)}f", *vec) if vec else None
        cur = db.execute(
            "INSERT INTO rfm_memories (content, created_at, embedding, scope,"
            " source, quote, origins) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (text, created_at or time.time(), blob, scope, source,
             secret_scan.redact(quote)[0] if isinstance(quote, str) else None,
             origins))
        ids.append(cur.lastrowid)
    return ids


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("transcript")
    ap.add_argument("--scope", default=None,
                    help="default: the current repository")
    ap.add_argument("--save", action="store_true",
                    help="store the memories; without it they are only printed")
    args = ap.parse_args(argv)
    import sqlite3
    import rfm
    import sweep
    import user_prompt_submit as ups
    chat = chat_of(args.transcript)
    if not chat:
        print("no conversation in that file")
        return 1
    parts = windows(chat)
    skipped = max(0, len(parts) - MAX_WINDOWS)
    memories = [m for part in parts[skipped:]
                for m in form_items(part, sweep.llm, sweep.parse_json)]
    # The store-to-source ratio: bytes of memory per byte of conversation
    # read. A memory layer that approaches its source has abstracted
    # nothing (Anthropic's dreaming write-up found a wiki at 1.77x its
    # corpus); on real sessions decide runs near 1%.
    source_chars = sum(len(p) for p in parts[skipped:])
    formed_chars = sum(len(m["content"]) for m in memories)
    summary = {"windows": len(parts) - skipped, "skipped": skipped,
               "formed": len(memories), "source_chars": source_chars,
               "formed_chars": formed_chars,
               "ratio": round(formed_chars / max(1, source_chars), 4)}
    if not args.save:
        for n, m in enumerate(memories, 1):
            print(f"{n}. {m['content']}\n   quote: {m['quote']!r}\n")
        sweep._log({"op": "decide", **summary, "saved": 0})
        print(json.dumps({**summary, "saved": None}))
        return 0
    db = sqlite3.connect(sweep.DB_PATH, timeout=10.0)
    rfm.register(db)
    store.ensure(db)
    ids = save(db, memories, source_of(chat), args.scope or store.project(),
               ups.embed, transcript=args.transcript)
    db.commit()
    db.close()
    sweep._log({"op": "decide", **summary, "saved": len(ids)})
    print(json.dumps({**summary, "saved": ids}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
