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
placeholder and retain the command output or screenshot paths below. A release
receipt is valid only when every `pending` field is `pass`.

## Environment

- Host and CLI version:
- Operator:
- Date:
- Fixture repository:
- Child-agent API used:

## Evidence

- Install command and result:
- Router invocation and state artifact:
- Child spawn output:
- Task branch, worktree, and landing commit:
- Task Verify command and result:
- Wave and final review artifacts:
- Archive validation output:
- Integration merge and milestone tag:
- Remaining `git worktree list` output:
- Native guard and Git-hook results:

Do not mark `child_spawn: pass` for a top-level CLI invocation. If any result
is missing or cannot be reproduced, set the affected field to `unverifiable`.
