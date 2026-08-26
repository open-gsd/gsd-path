---
schema: gsd-path/live-evidence/v1
host: HOST
package: VERSION
pipeline: gsd-path/v2
candidate: FULL_CANDIDATE_SHA
verdict: pending
child_spawn: pending
state: pending
task_verify: pending
wave_review: pending
final_review: pending
archive: pending
integration: pending
guard_tier: MANIFEST_GUARD_TIER
---

# Live milestone evidence — HOST

Copy this file to `evidence/releases/<version>/<host>.md`. Replace every
placeholder. Create one tracked JSON file per step under
`evidence/releases/<version>/<host>/`, then use its plain relative path below.
Every receipt and step file must be added or updated after the tested candidate.

## Environment

- Host and CLI version:
- Operator:
- Date:
- Fixture repository:
- Child-agent API used:

## Evidence

- Install command and result: HOST/install.json
- Router invocation and state artifact: HOST/router.json
- Child spawn output: HOST/child-spawn.json
- Task branch, worktree, and landing commit: HOST/task-landing.json
- Task Verify command and result: HOST/task-verify.json
- Wave and final review artifacts: HOST/reviews.json
- Archive validation output: HOST/archive.json
- Integration merge and milestone tag: HOST/integration.json
- Remaining `git worktree list` output: HOST/worktrees.json
- Native guard and Git-hook results: HOST/guards.json

Each step file uses this shape. Set `step` to the filename stem, retain the
actual command or host action, and embed its inspectable output:

```json
{
  "schema": "gsd-path/live-step-evidence/v1",
  "host": "HOST",
  "step": "install",
  "command": "node scripts/install.mjs ...",
  "result": "pass",
  "output": "actual command output or artifact details"
}
```

Do not mark `child_spawn: pass` for a top-level CLI invocation. If any result
is missing or cannot be reproduced, set the affected field to `unverifiable`.
