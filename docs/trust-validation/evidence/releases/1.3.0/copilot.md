---
schema: gsd-path/live-evidence/v1
host: copilot
package: 1.3.0
pipeline: gsd-path/v2
candidate: 45466c40e57c6cc0d7acd099e880d1644b33f5ee
verdict: pass
child_spawn: pass
state: pass
task_verify: pass
wave_review: pass
final_review: pass
archive: pass
integration: pass
guard_tier: git-only
---

# Live milestone evidence — copilot

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/copilot`.

## Environment

- Host and CLI version: GitHub Copilot CLI 1.0.86
- Operator: Release evaluation
- Date: 2026-09-20
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/copilot/quick/repo
- Child-agent API used: task (description build_T001)

## Evidence

- Install command and result: copilot/install.json
- Router invocation and state artifact: copilot/router.json
- Child spawn output: copilot/child-spawn.json
- Task branch, worktree, and landing commit: copilot/task-landing.json
- Task Verify command and result: copilot/task-verify.json
- Wave and final review artifacts: copilot/reviews.json
- Archive validation output: copilot/archive.json
- Integration merge and milestone tag: copilot/integration.json
- Remaining `git worktree list` output: copilot/worktrees.json
- Native guard and Git-hook results: copilot/guards.json

Fixture Git bundle: copilot/fixture.bundle (all refs, including origin/main and the annotated milestone tag).
