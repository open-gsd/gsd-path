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
guard_tier: git-only
---

# Live milestone evidence — HOST

Copy this file to `evidence/releases/<version>/<host>.md`. Replace every
placeholder. Put non-empty command output, logs, artifacts, or screenshots in
`evidence/releases/<version>/<host>/`, then use plain relative paths below. A
release receipt is valid only when every `pending` field is `pass` and every
evidence path resolves to a non-empty file in that host directory.

## Environment

- Host and CLI version:
- Operator:
- Date:
- Fixture repository:
- Child-agent API used:

## Evidence

- Install command and result: HOST/install.txt
- Router invocation and state artifact: HOST/router.txt
- Child spawn output: HOST/child-spawn.txt
- Task branch, worktree, and landing commit: HOST/task-landing.txt
- Task Verify command and result: HOST/task-verify.txt
- Wave and final review artifacts: HOST/reviews.txt
- Archive validation output: HOST/archive.txt
- Integration merge and milestone tag: HOST/integration.txt
- Remaining `git worktree list` output: HOST/worktrees.txt
- Native guard and Git-hook results: HOST/guards.txt

Do not mark `child_spawn: pass` for a top-level CLI invocation. If any result
is missing or cannot be reproduced, set the affected field to `unverifiable`.
