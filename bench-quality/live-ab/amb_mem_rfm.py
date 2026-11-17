"""mem-rfm as an agent-memory-benchmark provider (Track 34).

Installed into the harness checkout as `src/memory_bench/memory/mem_rfm.py` by
run_track34.py. The harness runs under its own `uv` environment, so this file
needs nothing but the standard library: formation, storage and retrieval run in
this repository's integration venv through `amb_mem_rfm_worker.py`, one process
per call, JSON in and out.

Each isolation unit (a task) gets its own store. Retrieval is the shipped
per-turn rule, so the harness's k is capped at the product's K.
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

from ..models import Document
from .base import MemoryProvider

HERE = Path(os.environ.get("MEM_RFM_REPO", "")) if os.environ.get("MEM_RFM_REPO") \
    else None
DELIVERY_LOG = os.environ.get("TRACK34_DELIVERY_LOG")


class MemRfmProvider(MemoryProvider):
    name = "mem-rfm"
    description = ("Decisions formed from past conversations, ranked by similarity "
                   "times an outcome prior; one SQLite file per task.")
    kind = "local"
    link = "https://github.com/andrewgoodchild/mem-rfm"
    concurrency = 1

    def __init__(self):
        if HERE is None:
            raise RuntimeError("MEM_RFM_REPO must point at the mem-rfm checkout")
        self._python = HERE / "integrations" / "claude-code" / ".venv" / "bin" / "python"
        self._worker = HERE / "bench-quality" / "live-ab" / "amb_mem_rfm_worker.py"
        self._store_dir = Path(tempfile.mkdtemp(prefix="mem-rfm-amb-"))

    def prepare(self, store_dir, unit_ids=None, reset=True):
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        if reset:
            for db in self._store_dir.glob("*.db"):
                db.unlink()

    def _db(self, user_id):
        return str(self._store_dir / f"{user_id or 'shared'}.db")

    def _call(self, command, payload):
        r = subprocess.run([str(self._python), str(self._worker), command],
                           input=json.dumps(payload), capture_output=True,
                           text=True, timeout=7200)
        if r.returncode != 0:
            raise RuntimeError(f"mem-rfm worker {command} failed: "
                               f"{r.stderr[-800:]}")
        return json.loads(r.stdout)

    def ingest(self, documents):
        by_unit = {}
        for d in documents:
            by_unit.setdefault(d.user_id, []).append(
                {"id": d.id, "content": d.content, "messages": d.messages})
        for user_id, docs in by_unit.items():
            self._call("ingest", {"db": self._db(user_id), "docs": docs})

    def retrieve(self, query, k=10, user_id=None, query_timestamp=None):
        out = self._call("retrieve", {"db": self._db(user_id), "query": query,
                                      "k": k})
        if DELIVERY_LOG:
            with open(DELIVERY_LOG, "a") as f:
                f.write(json.dumps({"run": os.environ.get("TRACK34_RUN"),
                                    "task": user_id,
                                    "sources": [m["source"] for m in out],
                                    "sims": [m["sim"] for m in out]}) + "\n")
        return [Document(id=f"{user_id}:mem{m['id']}", content=m["content"],
                         user_id=user_id, source_ids=[m["source"]])
                for m in out], None
