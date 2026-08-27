#!/usr/bin/env python3
"""Track 18 — the open-throttle replay (REVALIDATION.md, registered
before any sweep call). Replays sweep.py over the 50 pilot 2/3/4
transcripts, chronological by mtime, into a fresh store under track18/.
Writes the ordered transcript list and the transcript→task mapping the
leak check needs.

Usage: run_track18.py [--dry-run]
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formation_study as F  # noqa: E402

INTEGRATION = os.path.join(HERE, "..", "..", "integrations", "claude-code")
VARIANT = "b" if "b" in sys.argv[1:] else ""
DIR = os.path.join(HERE, "track18" + VARIANT)
DB = os.path.join(DIR, "rfm-memory.db")
LIST = os.path.join(DIR, "transcripts.txt")
MAPPING = os.path.join(DIR, "mapping.json")
RUNS = ["pilot2", "pilot3", "pilot4"]
# The integration venv carries fastembed; the sweep degrades to token
# Jaccard without it, which is exactly the defect 18b exists to fix.
VENV_PY = os.path.join(INTEGRATION, ".venv", "bin", "python")
PY = VENV_PY if os.path.exists(VENV_PY) else sys.executable


def main():
    rows = [(tp, run, task, arm) for run, task, arm, tp in F.sessions(RUNS)]
    rows.sort(key=lambda r: os.path.getmtime(r[0]))
    if not rows:
        sys.exit("PREFLIGHT: no pilot transcripts found")
    os.makedirs(DIR, exist_ok=True)
    with open(LIST, "w") as f:
        f.write("\n".join(tp for tp, *_ in rows) + "\n")
    with open(MAPPING, "w") as f:
        json.dump({os.path.basename(tp): {"run": run, "task": task,
                                          "arm": arm}
                   for tp, run, task, arm in rows}, f, indent=2)
    print(f"preflight ok: {len(rows)} transcripts "
          f"({sum(1 for r in rows if r[3] == 'rfm')} rfm-arm), "
          f"store {DB}")
    if "--dry-run" in sys.argv:
        return
    if os.path.exists(DB):
        sys.exit("PREFLIGHT: store exists — remove track18/rfm-memory.db "
                 "to rerun from scratch (the replay is not resumable "
                 "mid-store)")
    env = {**os.environ, "RFM_MEMORY_DB": DB, "RFM_LOG": "1"}
    r = subprocess.run(
        [PY, os.path.join(INTEGRATION, "sweep.py"),
         "--replay", LIST], env=env)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
