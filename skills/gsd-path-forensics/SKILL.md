---
name: gsd-path-forensics
description: Use only when the user explicitly invokes $gsd-path-forensics. Read-only diagnosis of a stuck GSD Path pipeline. Runs existing helpers and names the exact retry command; never mutates state, git, or artifacts.
---

Before executing project helpers, read [runtime selection](references/runtime-selection.md).

# GSD Path Forensics

One invocation = one read-only diagnosis. The bundled
[pipeline_diagnose.py](scripts/pipeline_diagnose.py) owns the probes; do not
re-derive stuckness from a directory listing or `git status` prose.

This skill never advances a phase gate, never edits `.project/`, and never
runs git mutations.

When `.gsd-path/runtime.json` exists, run `python3 -B
<absolute-project>/.gsd-path/status_runtime.py --repo <absolute-project>
--runtime-path`. Use the returned verified directory for its bundled helpers.
A missing or invalid selected runtime stops execution with its explicit restore
action; never substitute the installed plugin's helpers. Legacy projects without
a declaration may use `.gsd-path/runtime/`, or the skill bundle when that directory
is absent. An explicit `--runtime-migrate` produces the reviewed migration diff.

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
