---
name: gsd-path-forensics
description: Use only when the user explicitly invokes $gsd-path-forensics. Read-only diagnosis of a stuck GSD Path pipeline. Runs existing helpers and names the exact retry command; never mutates state, git, or artifacts.
---

# GSD Path Forensics

One invocation = one read-only diagnosis. The bundled
[pipeline_diagnose.py](scripts/pipeline_diagnose.py) owns the probes; do not
re-derive stuckness from a directory listing or `git status` prose.

This skill never advances a phase gate, never edits `.project/`, and never
runs git mutations.

## Process

1. **Diagnose.** Run `python3 <absolute-bundled-pipeline_diagnose.py> diagnose
   --repo <absolute-root>`. Treat the JSON as the only diagnosis.
2. **Report.** Present **Outcome** as `status` (`ok`, `stuck`, or `unowned`)
   plus every `stuck` finding's `evidence`. **Review** links STATE.md when
   `status_snapshot.path` exists; otherwise link the repo root. **Next** is the
   `retry` string from the first `stuck` finding, or `$gsd-path status` when
   the verdict is `ok`.
3. **Stop.** Do not invoke the named retry. Do not apply undo. Name
   `$gsd-path-undo` only when a finding `id` is `undo-available` and the user
   asked to roll work back.

## Rules

- Never write a forensics file under `.project/`. The helper JSON is the
  artifact.
- Never resume a journal, bind a branch, or reset HEAD from this skill.
- Same-model agreement is not evidence: the helper output is the evidence.
