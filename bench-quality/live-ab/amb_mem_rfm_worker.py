#!/usr/bin/env python3
"""The mem-rfm side of the agent-memory-benchmark provider (Track 34). Runs in
this repository's integration venv; amb_mem_rfm.py calls it.

  ingest    {"db", "docs": [{"id", "content", "messages"|null}]}
            A document with messages is a conversation: formed into decision
            memories by decisions.form with haiku, as `decide` would, cached by
            the conversation's hash so the shared decoys form once. Any other
            document is a commit and is stored verbatim. Every memory of a
            document shares its id as `source`.
  retrieve  {"db", "query", "k"} -> [{"id", "content", "source", "sim"}]
            The shipped per-turn rule: cosine times rfm_prior, K above the
            floor, within the character budget. Priors are flat here.
  selftest  no input; a stand-in LLM, exit 0 on pass.

Usage: amb_mem_rfm_worker.py ingest|retrieve|selftest  < json
"""
import concurrent.futures
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
os.environ.setdefault("RFM_LOG", "0")
os.environ.setdefault("RFM_MEMORY_DB", os.path.join(tempfile.gettempdir(),
                                                    "mem-rfm-worker-unused.db"))
sys.path.insert(0, INTEGRATION)
sys.path.insert(0, os.path.join(INTEGRATION, "hooks"))
sys.path.insert(0, os.path.join(INTEGRATION, "..", ".."))
import decisions as D            # noqa: E402
import rfm                       # noqa: E402
import store                     # noqa: E402
import sweep                     # noqa: E402
import transcripts               # noqa: E402
import user_prompt_submit as U   # noqa: E402

FORM_MODEL = "haiku"
WORKERS = 6
CACHE = os.environ.get("TRACK34_CACHE",
                       os.path.join(HERE, "track34", "formed-cache.jsonl"))
TMP = tempfile.mkdtemp(prefix="mem-rfm-worker-")


def llm(prompt):
    """One formation call on the host's own Claude Code login: the agent
    container's auth variables, which the harness puts in this process's
    environment, are dropped. A failed call raises; it is never a memory."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")}
    r = subprocess.run(["claude", "-p", "--model", FORM_MODEL, prompt],
                       env={**env, "RFM_HOOKS_OFF": "1"}, cwd=TMP,
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not (r.stdout or "").strip():
        raise RuntimeError(f"claude -p failed (rc={r.returncode}): "
                           f"{(r.stderr or r.stdout)[-400:]}")
    return r.stdout.strip()


MAX_UNPARSED = 0.2


def chat_text(messages):
    return "\n\n".join(f"{(m.get('role') or 'user').upper()}: {m.get('content', '')}"
                       for m in messages)


def load_cache():
    out = {}
    if os.path.exists(CACHE):
        for line in open(CACHE):
            row = json.loads(line)
            out[row["key"]] = row["memories"]
    return out


def form_all(chats, llm_fn, parse=sweep.parse_json):
    """{key: memories} for the chats not yet in the cache. Nothing is cached
    until every call has answered, and a batch where more than MAX_UNPARSED of
    the windows got no JSON list back is a failed batch, not 141 empty chats:
    the first smoke run cached exactly that."""
    cache = load_cache()
    todo = {k: c for k, c in chats.items() if k not in cache}
    unparsed = [0]

    def counting_parse(text):
        items = parse(text)
        if not isinstance(items, list):
            unparsed[0] += 1
        return items

    def one(item):
        key, chat = item
        parts = D.windows(chat)[-D.MAX_WINDOWS:]
        return key, [m for part in parts
                     for m in D.form(part, llm_fn, counting_parse)], len(parts)
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        formed = list(pool.map(one, todo.items()))
    windows = sum(n for _k, _m, n in formed)
    if windows and unparsed[0] > MAX_UNPARSED * windows:
        raise RuntimeError(f"formation answered with no JSON list on "
                           f"{unparsed[0]} of {windows} windows; nothing cached")
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "a") as f:
        for key, memories, _n in formed:
            cache[key] = memories
            f.write(json.dumps({"key": key, "memories": memories}) + "\n")
    return cache


def open_db(path):
    db = sqlite3.connect(path, timeout=30.0)
    rfm.register(db)
    store.ensure(db)
    return db


def ingest(payload, llm_fn=llm):
    docs = payload["docs"]
    chats = {}
    for d in docs:
        if d.get("messages"):
            text = chat_text(d["messages"])
            chats[hashlib.sha256(text.encode()).hexdigest()[:16]] = text
    formed = form_all(chats, llm_fn)
    db = open_db(payload["db"])
    base = time.time() - 86400 * 30
    saved = 0
    for n, d in enumerate(docs):
        if d.get("messages"):
            key = hashlib.sha256(chat_text(d["messages"]).encode()).hexdigest()[:16]
            memories = formed.get(key, [])
        else:
            memories = [d["content"]]
        saved += len(D.save(db, memories, d["id"], None, U.embed,
                            created_at=base + n))
    store.stamp_embedder(db, U.EMBEDDER_ID, len(U.embed("x")))
    db.commit()
    db.close()
    return {"docs": len(docs), "conversations": len(chats), "saved": saved}


def retrieve(payload):
    qvec = U.embed(payload["query"])
    db = open_db(payload["db"])
    rows = db.execute(
        "SELECT id, content, embedding, rfm_prior(id) AS prior, created_at, "
        "source FROM rfm_memories "
        "WHERE NOT (outcome_count > 0 AND value_score < 0) "
        f"AND {store.released()} AND embedding IS NOT NULL").fetchall()
    scored = []
    for mid, content, blob, prior, created, source in rows:
        sim = U.cosine(qvec, blob)
        scored.append((sim * prior, sim, mid, content, created, source))
    scored.sort(reverse=True)
    top = [t for t in scored if t[1] >= U.FLOOR][:min(U.K, int(payload["k"]))]
    used, out = 0, []
    for _score, sim, mid, content, created, source in top:
        line = transcripts.line_head(mid, created) + U.sanitize(content)
        if used + len(line) > U.CHAR_BUDGET:
            break
        used += len(line) + 1
        db.execute("SELECT rfm_record_access(?)", (mid,))
        out.append({"id": mid, "content": U.sanitize(content), "source": source,
                    "sim": round(float(sim), 3)})
    db.commit()
    db.close()
    return out


def selftest():
    global CACHE
    CACHE = os.path.join(TMP, "cache.jsonl")
    db = os.path.join(TMP, "t.db")
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return ('[{"content": "Retry.max_attempts is 7, measured against the rate '
                'limit window", "quote": "seven attempts"}]')
    docs = [{"id": "t:chat0", "content": "x", "messages": [
                {"role": "user", "content": "Use seven attempts for the retrier."},
                {"role": "assistant", "content": "Set to 7."}]},
            {"id": "t:decoy-1", "content": "x", "messages": [
                {"role": "user", "content": "Use seven attempts for the retrier."},
                {"role": "assistant", "content": "Set to 7."}]},
            {"id": "t:git-abc", "content": "Git commit: fix typo in docs",
             "messages": None}]
    r = ingest({"db": db, "docs": docs}, fake)
    ok = r["conversations"] == 1 and len(calls) == 1 and r["saved"] == 3
    print("ingest forms once per distinct chat, stores commits verbatim:", ok, r)
    r2 = ingest({"db": db, "docs": docs}, fake)
    ok2 = len(calls) == 1 and r2["saved"] == 0
    print("re-ingest hits the cache and adds nothing:", ok2)
    got = retrieve({"db": db, "query": "the retrier gives up too early, how many "
                                      "attempts should it make", "k": 10})
    ok3 = got and "max_attempts" in got[0]["content"] and \
        got[0]["source"] in ("t:chat0", "t:decoy-1") and len(got) <= U.K
    print("retrieve returns the formed decision within K:", bool(ok3),
          [(g["source"], g["sim"]) for g in got])
    before = len(load_cache())
    try:
        ingest({"db": os.path.join(TMP, "u.db"),
                "docs": [{"id": "u:chat0", "content": "x", "messages": [
                    {"role": "user", "content": "Something new to form."}]}]},
               lambda prompt: "I cannot help with that.")
        ok4 = False
    except RuntimeError:
        ok4 = len(load_cache()) == before
    print("a batch of unparsed answers raises and caches nothing:", ok4)
    return 0 if ok and ok2 and ok3 and ok4 else 1


def main():
    command = sys.argv[1]
    if command == "selftest":
        return selftest()
    payload = json.load(sys.stdin)
    result = ingest(payload) if command == "ingest" else retrieve(payload)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
