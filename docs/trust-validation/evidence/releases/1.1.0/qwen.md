---
schema: gsd-path/live-evidence/v1
host: qwen
package: 1.1.0
pipeline: gsd-path/v2
candidate: af0b082964510c471798826d7e2e05617d8d6dc3
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

# Live milestone evidence — qwen

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.1.0-af0b082/qwen-sonnet`.

## Environment

- Host and CLI version: 0.23.0
- Operator: Release evaluator for Jeremy McSpadden
- Date: 2026-09-18
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.1.0-af0b082/qwen-sonnet/quick/repo
- Child-agent API used: agent (description build_T001)

## Evidence

- Install command and result: qwen/install.json
- Router invocation and state artifact: qwen/router.json
- Child spawn output: qwen/child-spawn.json
- Task branch, worktree, and landing commit: qwen/task-landing.json
- Task Verify command and result: qwen/task-verify.json
- Wave and final review artifacts: qwen/reviews.json
- Archive validation output: qwen/archive.json
- Integration merge and milestone tag: qwen/integration.json
- Remaining `git worktree list` output: qwen/worktrees.json
- Native guard and Git-hook results: qwen/guards.json

Fixture Git bundle: qwen/fixture.bundle (all refs, including origin/main and the annotated milestone tag).
