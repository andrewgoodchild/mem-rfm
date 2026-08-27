#!/usr/bin/env python3
"""Condition-conditioned value: the instrument Track 11 said to build.

A memory's ledger counts acted-on outcomes. This view splits every
injected session by whether the memory's TRIGGER CONDITION actually fired
(its error class appears in command output), and reports the acted-on
rate and outcome-shaped events in each half. A memory whose ledger was
earned entirely in condition-silent sessions was being copied, not
consulted — engagement, not value. Retroactive: reads committed
transcripts, runs nothing.

CAVEAT (RESULTS.md Track 11 Correction C4): firing is ENDOGENOUS to
acting — applying a workaround can surface the very error class it
guards against (Track 11's per-session /tmp clean forced stub
recreation, which is when the class appears). This view audits where a
ledger was earned; it is not a causal estimator, and a high fired-share
must never be read as "the memory was needed".

The condition regex per memory is declared here, next to the memory it
describes, because the trigger class is part of the memory's claim.

Usage: condition_value.py
"""
import re
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import formation_study as F  # noqa: E402

# (name, runs, memory-arm name(s), trigger regex, acted-on regex)
PANELS = [
    ("sphinx era-pin stubs (pilot4 id 2, 17 outcomes)",
     ["pilot2", "pilot3", "pilot4"], {"rfm"},
     re.compile(r"VersionRequirementError|ExtensionError", re.I),
     re.compile(r"PYTHONPATH=\S*stubs|sphinx_type_hint_links", re.I)),
    ("sphinx era-pin stubs, Track 11 delivery arms",
     ["track11"], {"verbatim", "abstract", "prose"},
     re.compile(r"VersionRequirementError|ExtensionError", re.I),
     re.compile(r"PYTHONPATH=\S*stubs|sphinx_type_hint_links", re.I)),
    ("xarray pkg_resources shim (track10 id 3, 4 outcomes)",
     ["track10"], {"rfm"},
     re.compile(r"pkg_resources|DistributionNotFound", re.I),
     re.compile(r"import xarray|pkg_resources", re.I)),
]


def arm_name(run, task, ab_arm):
    if run == "track11":
        return task.rsplit("-", 1)[1]
    return ab_arm


def main():
    for name, runs, arms, trigger, acted in PANELS:
        fired = silent = 0
        acted_fired = acted_silent = 0
        sessions_acted_fired = sessions_acted_silent = 0
        n = 0
        for run, task, ab_arm, tp in F.sessions(runs):
            if arm_name(run, task, ab_arm) not in arms:
                continue
            n += 1
            evs = F.events_of(tp)
            f = any(e.got and trigger.search(e.body or "") for e in evs)
            a = sum(1 for e in evs if acted.search(e.cmd or ""))
            if f:
                fired += 1
                acted_fired += a
                sessions_acted_fired += a > 0
            else:
                silent += 1
                acted_silent += a
                sessions_acted_silent += a > 0
        print(f"== {name}")
        print(f"   {n} memory-arm sessions: condition fired in {fired}, "
              f"silent in {silent}")
        print(f"   acted-on commands: {acted_fired} in fired sessions "
              f"({sessions_acted_fired} sessions), "
              f"{acted_silent} in silent sessions "
              f"({sessions_acted_silent} sessions)")
        if n:
            print(f"   -> share of acting that happened with the condition "
                  f"silent: "
                  f"{100 * acted_silent / max(acted_fired + acted_silent, 1):.0f}%"
                  )
        print()


if __name__ == "__main__":
    main()
