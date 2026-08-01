---
id: T001
title: <imperative, specific>
wave: 1
deps: []            # task ids that must be done first
status: pending     # orchestrator-owned: pending | in-progress | done | failed | blocked
agent: null         # orchestrator-owned: set at dispatch
commit: null        # orchestrator-owned: exact task commit SHA
base: null          # orchestrator-owned: clean layer SHA for isolated Verify
worktree: null      # orchestrator-owned: isolated task worktree while active
task_branch: null   # orchestrator-owned: isolated task branch while active
files:              # every file this task may touch — dispatch checks overlap
  - <path>
---

# T001 — <title>

## Context

<!-- 3–5 sentences. Everything the coder needs from INTENT/SYNTHESIS,
     inlined. The coder reads ONLY this file plus the codebase. -->

## Steps

<!-- Concrete and ordered. Real paths, function names, schemas.
     Include applicable pitfalls from research. No judgment calls left open. -->
1. <step>
2. <step>

## Acceptance criteria

<!-- Observable. The reviewer checks the diff against exactly these. -->
1. <behavior/command/output that must be true>

## Verify

```bash
<one command that fails if this task wasn't done>
```

## Log

<!-- Append-only: coder summary, blocks, review verdicts, fixes. -->
- <date> — created by planner
