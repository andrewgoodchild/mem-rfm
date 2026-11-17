#!/usr/bin/env python3
"""Wiring test for the CL-Bench system (Track 36) with a scripted model: no
API key, no cost. Runs two database questions end to end through the real
task and the real system, with the LLM call replaced by a script that
queries once and answers, and checks that a note was formed from question
one, shown on question two, acted on there, and scored.

Needs the harness checkout synced and set up (run_track36.py --setup-only),
and the integration venv for the worker. Run with the harness's python:

  bench-quality/data/clbench/.venv/bin/python \\
      bench-quality/live-ab/test_clbench_mem_rfm.py [CLBENCH_DIR]
"""
import dataclasses
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CLB = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else \
    os.path.join(REPO, "bench-quality", "data", "clbench")
sys.path.insert(0, CLB)
os.environ["MEM_RFM_REPO"] = REPO
os.chdir(CLB)          # the task opens data/database_exploration/*.db by a relative path

from src.usage import UsageEvent                          # noqa: E402
from src.systems.mem_rfm import system as S               # noqa: E402
from src.tasks.database_exploration.task import DatabaseExploration  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def usage_event():
    kw = {}
    for f in dataclasses.fields(UsageEvent):
        if f.default is not dataclasses.MISSING or \
                f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
            continue
        kw[f.name] = {"str": "stub", "int": 0, "float": 0.0, "bool": False
                      }.get(getattr(f.type, "__name__", str(f.type)), None)
    return UsageEvent(**kw)


calls = {"answer": 0, "form": 0, "saw_memory": False}


def flat(content):
    """Message content as text: the system now sends the last message as a
    block list carrying the cache breakpoint."""
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


def scripted(model, messages, response_schema):
    """QUERY the catalogue once, then ANSWER; form one note on request."""
    text = flat(messages[-1]["content"])
    assert isinstance(messages[-1]["content"], list) and \
        "cache_control" in messages[-1]["content"][-1], "cache breakpoint missing"
    if response_schema is S.Notes:
        calls["form"] += 1
        return S.Notes(notes=[S.Note(
            rule="Table names live in `sqlite_master`; office products are the "
                 "`g1_items` table with prices in `prc`.",
            applies_to="all", evidence="SELECT name FROM sqlite_master")]), \
            usage_event()
    calls["answer"] += 1
    if S.MARKER in text:
        calls["saw_memory"] = True
    if "FEEDBACK:" in text or "Queries used so far this question: 1/" in text:
        return response_schema(action="ANSWER", content="42"), usage_event()
    sql = "SELECT name FROM sqlite_master WHERE type='table'"
    if calls["saw_memory"]:          # question two: act on the shown note
        sql = "SELECT avg(prc) FROM g1_items"
    return response_schema(action="QUERY", content=sql), usage_event()


S.completion_with_structured_output = scripted

task = DatabaseExploration(schedule="default")
system = S.MemRfmSystem(model="stub")
query = task.reset()
system.reset()
check("question text extracted", len(system.question_of(query.prompt)) < len(query.prompt)
      and "You have access" not in system.question_of(query.prompt))

instances = 0
steps = 0
while instances < 2 and steps < 12:
    response = system.respond(query)
    result = task.step(response)
    steps += 1
    system.observe(result.observation, result.next_query)
    if result.observation.instance_complete:
        instances += 1
    if result.done:
        break
    query = result.next_query

check("two questions ran in a handful of steps", instances == 2 and steps <= 6,
      f"instances={instances} steps={steps}")
check("formation ran once per question", calls["form"] == 2, str(calls))
art = system.get_run_artifacts()
counts = art["counts"]
check("a note was stored, the second merged into it",
      art["memory_count"] == 1 and counts["admitted"] == 1 and counts["merged"] == 1,
      json.dumps({"memories": art["memory_count"], **counts}))
check("the note was shown on question two", counts["shown"] == 1 and calls["saw_memory"],
      str(counts))
check("acted on: question two queried `g1_items`, which the note names",
      counts["acted"] == 1 and counts["outcomes"] == 1, str(counts))
row = art["memories"][0] if art["memories"] else {}
check("ledger: one outcome, negative (the scripted answer is wrong)",
      row.get("outcome_count") == 1 and row.get("value_score", 0) < 0, json.dumps(row))
check("usage events recorded for answers and formation",
      len(system.consume_usage_events()) == calls["answer"] + calls["form"])

system.reset()
check("reset empties the store", system.get_run_artifacts()["memory_count"] == 0)

check("acted_on needs a whole identifier",
      S.MemRfmSystem.acted_on("prices are in `prc`", ["SELECT prc FROM t"])
      and not S.MemRfmSystem.acted_on("prices are in `prc`", ["SELECT prc_v2 FROM t"])
      and not S.MemRfmSystem.acted_on("prices are in cents", ["SELECT prc FROM t"]))

print(f"{'FAILED' if failures else 'OK'}: {len(failures)} failures")
sys.exit(1 if failures else 0)
