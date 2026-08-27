#!/usr/bin/env python3
"""Retroactive model audit (next-work item 2; RESULTS.md C4 point 5).

Past results.jsonl records carry no model id — the heterogeneity
(Track 10 on opus-5, everything else fable-5) was discovered by reading
transcripts. This script recovers the model ids per run from the
transcripts and writes model-audit.jsonl, committed alongside the
results so the mapping is part of the record. Past results files are
never edited. Track 13 onward stamp the model per record at run time;
future runners also stamp the CLI version (run_stream.cli_version).

Usage: model_audit.py   (regenerates model-audit.jsonl)
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formation_study as F  # noqa: E402

RUNS = ["pilot2", "pilot3", "pilot4", "reval-pytest", "reval-sphinx",
        "reval-xarray", "tax", "track10", "track11", "track13"]


def main():
    out = os.path.join(HERE, "model-audit.jsonl")
    with open(out, "w") as sink:
        for run in RUNS:
            models = collections.Counter()
            n = 0
            for _r, _task, _arm, tp in F.sessions([run]):
                n += 1
                seen = set()
                for line in open(tp):
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    m = rec.get("message", {})
                    if isinstance(m, dict) and m.get("model"):
                        seen.add(m["model"])
                models.update(seen)
            row = {"run": run, "sessions_with_transcripts": n,
                   "models": dict(models)}
            sink.write(json.dumps(row) + "\n")
            print(row)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
