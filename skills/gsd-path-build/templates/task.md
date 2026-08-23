---
id: T001
title: <imperative, specific>
wave: 1
deps: []            # task ids whose output or landed effect this task needs
status: pending     # orchestrator-owned: pending | in-progress | done | failed | blocked
agent: null         # orchestrator-owned: set at dispatch
commit: null        # orchestrator-owned: exact task commit SHA
base: null          # orchestrator-owned: clean layer SHA for isolated Verify
worktree: null      # orchestrator-owned: isolated task worktree while active
task_branch: null   # orchestrator-owned: gsd-path-task/<id> while parallel; null when serial
files:              # every file this task may touch — dispatch checks overlap
  - <path>
---

# T001 — <title>

## Context

<!-- 3–5 sentences. Everything the coder needs from SYNTHESIS, inlined.
     The coder reads this file, INTENT.md, and the codebase. -->

## Approach

<!-- Constraints, applicable pitfalls from research, and pointers to real
     paths, symbols, and schemas. Not an edit script — the coder owns the
     how within these constraints and the acceptance criteria. -->
- <constraint or pointer>

## Interface contract

<!-- Planner-owned. The exact shared symbols, signatures, types, paths,
     schemas, or formats this task exchanges with other tasks. Required when
     another task consumes this task's output or this task consumes a
     sibling's; write the identical contract in every involved task. Otherwise
     write `None`. Binding like the acceptance criteria: needing to deviate
     is a plan defect — block, never negotiate or improvise. -->
- None

## Intent coverage

<!-- SCn ids this task owns, matching PLAN.md Intent coverage. Write
     `- None` when this task owns no INTENT success criterion. -->
- SC1

## Acceptance criteria

<!-- Observable. The reviewer checks the diff against exactly these. -->
1. <behavior/command/output that must be true>

## Verify

```bash
<one command that fails if this task wasn't done>
```

## Log

<!-- Append-only: coder summary, blocks (`NEEDS-ORCHESTRATOR: <question> —
     readings: <candidates>` for contract ambiguity), orchestrator answers,
     review verdicts, fixes. -->
- <date> — created by planner
