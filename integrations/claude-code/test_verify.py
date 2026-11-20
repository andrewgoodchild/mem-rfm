#!/usr/bin/env python3
"""The verify pass against a stub model. Stdlib only. Exit 0 = pass.

What it pins: the quote finds its window; a contradiction stands only on
evidence that is really in the window; an unknown verdict is unsupported; a
missing transcript is source_gone, not an error; a contradicted row leaves
every delivery query and comes back under RFM_VERIFY_GATE=0; decide's save
keeps the quote and the transcript; a server-style content update clears
the verdict.

Usage: test_verify.py
"""
import json
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="rfm-verify-")
DB = os.path.join(TMP, "store.db")
os.environ.update(RFM_MEMORY_DB=DB, RFM_LOG="0")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "hooks"))
import decisions as D   # noqa: E402
import rfm              # noqa: E402
import store            # noqa: E402
import verify as V      # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail
                                                   else ""))
    if not ok:
        failures.append(name)


def parse(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# A transcript: the developer settles on 7, then reverses to 9.
path = os.path.join(TMP, "t.jsonl")
turns = [("user", "How many retries should the client make?"),
         ("assistant", "I suggest 7 retries with backoff."),
         ("user", "Fine, use seven retries."),
         ("assistant", "Set to 7."),
         ("user", "Actually make it nine retries, seven was too few."),
         ("assistant", "Changed to 9.")]
with open(path, "w") as f:
    for role, text in turns:
        f.write(json.dumps({"type": role, "message": {"content": text}}) + "\n")
chat = D.chat_of(path)

db = sqlite3.connect(DB)
rfm.register(db)
store.ensure(db)
check("schema has the verify columns",
      {"quote", "verified", "verified_at"} <= {
          r[1] for r in db.execute("PRAGMA table_info(rfm_memories)")})

ids = D.save(db, [{"content": "The client retries 7 times.",
                   "quote": "Fine, use seven retries."},
                  {"content": "The client retries 9 times.",
                   "quote": "make it nine retries"},
                  {"content": "Retries are logged.",
                   "quote": "this quote is nowhere"}],
             "chat:t", None, lambda t: [1.0], transcript=path)
db.commit()
rows = {r[0]: r for r in db.execute(
    "SELECT id, content, quote, origins FROM rfm_memories")}
check("save keeps the quote", rows[ids[0]][2] == "Fine, use seven retries.")
check("save keeps the transcript",
      V.transcript_of(rows[ids[0]][3]) == os.path.abspath(path),
      str(rows[ids[0]][3]))
check("a string memory still saves",
      D.save(db, ["plain"], "chat:u", None, lambda t: [1.0]) != [])

check("the quote finds its window",
      V.window_for(chat, "use SEVEN retries") is not None)
check("an absent quote finds none", V.window_for(chat, "zzz") is None)

REPLIES = {
    "7 times": '{"verdict": "contradicted", "evidence": "make it nine '
               'retries, seven was too few", "correction": "The client '
               'retries 9 times."}',
    "9 times": '{"verdict": "confirmed", "evidence": "", "correction": ""}',
}


def llm(prompt):
    for key, reply in REPLIES.items():
        if f"Memory: The client retries {key}" in prompt:
            return reply
    return "nonsense"


verdicts = {v["id"]: v for v in V.run(db, V.select(db), llm, parse)}
check("overridden rule is contradicted, with its evidence",
      verdicts[ids[0]]["verdict"] == "contradicted"
      and "nine" in verdicts[ids[0]]["evidence"], str(verdicts[ids[0]]))
check("a correction is proposed, not applied",
      verdicts[ids[0]]["correction"] == "The client retries 9 times."
      and db.execute("SELECT content FROM rfm_memories WHERE id = ?",
                     (ids[0],)).fetchone()[0] == "The client retries 7 times.")
check("final rule is confirmed", verdicts[ids[1]]["verdict"] == "confirmed")
check("a quote not in the source is unsupported without a model call",
      verdicts[ids[2]]["verdict"] == "unsupported"
      and verdicts[ids[2]].get("why") == "quote not in source")
check("verdicts are written",
      db.execute("SELECT verified FROM rfm_memories WHERE id = ?",
                 (ids[0],)).fetchone()[0] == "contradicted"
      and db.execute("SELECT verified_at FROM rfm_memories WHERE id = ?",
                     (ids[0],)).fetchone()[0] is not None)
check("select skips verified rows", V.select(db) == [])
check("--all re-selects them", len(V.select(db, everything=True)) == 3)

# Contradiction without grounded evidence is downgraded.
v = V.judge("the window text", "m", "q",
            lambda p: '{"verdict": "contradicted", "evidence": "not here"}',
            parse)
check("ungrounded contradiction becomes unsupported",
      v["verdict"] == "unsupported" and v["evidence"] == "")
v = V.judge("w", "m", "q", lambda p: '{"verdict": "banana"}', parse)
check("unknown verdict is unsupported", v["verdict"] == "unsupported")
v = V.judge("w", "m", "q", lambda p: "no json at all", parse)
check("garbage is unsupported", v["verdict"] == "unsupported")

# The delivery gate.
gate = store.not_contradicted()
shown = [r[0] for r in db.execute(
    f"SELECT id FROM rfm_memories WHERE {gate} ORDER BY id")]
check("contradicted row leaves delivery",
      ids[0] not in shown and ids[1] in shown and ids[2] in shown, str(shown))
os.environ["RFM_VERIFY_GATE"] = "0"
check("RFM_VERIFY_GATE=0 shows it again", store.not_contradicted() == "1")
del os.environ["RFM_VERIFY_GATE"]

# A missing transcript.
os.remove(path)
v = V.check((ids[1], "x", "make it nine retries", rows[ids[1]][3]), llm, parse)
check("a deleted transcript is source_gone", v["verdict"] == "source_gone")

# A content change clears the verdict (the stamp must not outlive its claim).
db.execute("UPDATE rfm_memories SET verified = 'confirmed', verified_at = 1 "
           "WHERE id = ?", (ids[1],))
db.execute(store.CLEAR_VERIFIED + " WHERE id = ?", (ids[1],))
check("CLEAR_VERIFIED resets both columns",
      db.execute("SELECT verified, verified_at FROM rfm_memories WHERE id = ?",
                 (ids[1],)).fetchone() == (None, None))

db.close()
print(f"{'FAILED' if failures else 'OK'}: {len(failures)} failures")
sys.exit(1 if failures else 0)
