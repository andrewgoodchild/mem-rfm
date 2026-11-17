#!/usr/bin/env python3
"""Decision formation and grouped delivery. Stdlib only: the LLM and the
embedder are stand-ins. Exit 0 = pass.

Usage: test_decisions.py
"""
import json
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="rfm-decisions-")
DB = os.path.join(TMP, "store.db")
os.environ.update(RFM_MEMORY_DB=DB, RFM_LOG="0", RFM_PERTURN_GROUP="1",
                  RFM_PERTURN_BUDGET="2400")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "hooks"))
import decisions as D          # noqa: E402
import rfm                     # noqa: E402
import store                   # noqa: E402
import sweep                   # noqa: E402
import user_prompt_submit as U  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail
                                                   else ""))
    if not ok:
        failures.append(name)


VECS = {"rule": [1.0, 0.0], "tail": [0.0, 1.0], "near": [0.8, 0.6],
        "other": [0.6, 0.8]}


def embed(text):
    return VECS[text.split()[0]]


U.embed = embed
db = sqlite3.connect(DB)
rfm.register(db)
store.ensure(db)
check("source column", any(r[1] == "source" for r in
                           db.execute("PRAGMA table_info(rfm_memories)")))

path = os.path.join(TMP, "t.jsonl")
with open(path, "w") as f:
    for rec in ({"type": "user", "message": {"content": "Seven."}},
                {"type": "assistant", "message": {"content": [
                    {"type": "text", "text": "Set to 7."},
                    {"type": "tool_use", "name": "Bash", "input": {}}]}},
                {"type": "user", "message": {"content": [
                    {"type": "tool_result", "content": "noise"}]}}):
        f.write(json.dumps(rec) + "\n")
chat = D.chat_of(path)
check("chat keeps both sides, drops tools",
      chat == "USER: Seven.\n\nASSISTANT: Set to 7.", repr(chat))

seen = []
reply = ('[{"content": "a", "quote": "the chat text"}, '
         '{"content": "", "quote": "the chat text"}, {"x": 1}, '
         '{"content": "b", "quote": "not in it at all"}, {"content": "c"}, '
         '{"content": "d", "quote": "THE   chat text"}]')
dropped = []
got = D.form("here is the chat text", lambda p: seen.append(p) or reply,
             sweep.parse_json, dropped)
check("form keeps grounded items", got == ["a", "d"], str(got))
check("form drops an absent or missing quote", dropped == ["b", "c"],
      str(dropped))
check("form sends the chat", "the chat text" in seen[0])
check("form survives garbage",
      D.form("c", lambda p: "no json", sweep.parse_json) == [])
items = D.form_items("here is the chat text", lambda p: reply,
                     sweep.parse_json)
check("form_items keeps the quote",
      items == [{"content": "a", "quote": "the chat text"},
                {"content": "d", "quote": "THE   chat text"}], str(items))

parts = D.windows("aaaa\n\nbbbb\n\nccccccccccc\n\ndd", cap=10)
check("windows break between turns, cut a long one",
      parts == ["aaaa\n\nbbbb", "cccccccccc", "c\n\ndd"], str(parts))
check("windows cover the chat", D.windows("short") == ["short"])

ids = D.save(db, ["rule one", "tail two [rfm-memory: x"], "chat:a", "proj",
             embed, created_at=100.0)
D.save(db, ["near three"], "chat:b", "proj", embed, created_at=200.0)
D.save(db, ["other four"], "chat:c", "proj", embed, created_at=300.0)
check("saved with no sightings", db.execute(
    "SELECT sightings FROM rfm_memories WHERE id = ?", (ids[0],)
).fetchone()[0] is None)
check("sanitized", "[rfm-memory:" not in db.execute(
    "SELECT content FROM rfm_memories WHERE id = ?", (ids[1],)).fetchone()[0])
check("re-forming adds nothing", D.save(db, ["rule x"], "chat:a", "proj",
                                        embed) == [])
check("a string memory has no quote and no origin", db.execute(
    "SELECT quote, origins FROM rfm_memories WHERE id = ?", (ids[0],)
).fetchone() == (None, None))
qid = D.save(db, [{"content": "rule five", "quote": "five it is"}], "chat:q",
             "proj", embed, transcript=path)[0]
check("a dict memory keeps its quote and transcript", db.execute(
    "SELECT quote, origins FROM rfm_memories WHERE id = ?", (qid,)
).fetchone() == ("five it is", json.dumps(
    [f"transcript:{os.path.abspath(path)}"])))
db.execute("DELETE FROM rfm_memories WHERE id = ?", (qid,))
db.commit()
db.close()

os.environ["RFM_EMBEDDER"] = U.EMBEDDER_ID
top = U.retrieve("rule please", TMP + "/elsewhere")
scoped_out = [r[3].split()[0] for r in top]
check("another project sees nothing", scoped_out == [], str(scoped_out))

os.makedirs(os.path.join(TMP, "proj", ".git"))
top = U.retrieve("rule please", os.path.join(TMP, "proj"))
words = [r[3].split()[0] for r in top]
check("the sibling below the floor comes with its source", "tail" in words,
      str(words))
check("K counts sources: the third stays out", "other" not in words,
      str(words))
check("latest first", words[0] == "near", str(words))

print(f"{'FAILED' if failures else 'OK'}: {len(failures)} failures")
sys.exit(1 if failures else 0)
