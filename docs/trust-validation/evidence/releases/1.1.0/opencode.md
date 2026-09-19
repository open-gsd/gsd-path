---
schema: gsd-path/live-evidence/v1
host: opencode
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

# Live milestone evidence — opencode

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.1.0-af0b082/opencode-rerun`.

## Environment

- Host and CLI version: 1.18.25
- Operator: Release evaluator for Jeremy McSpadden
- Date: 2026-09-18
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.1.0-af0b082/opencode-rerun/quick/repo
- Child-agent API used: Task (description build_T001)

## Evidence

- Install command and result: opencode/install.json
- Router invocation and state artifact: opencode/router.json
- Child spawn output: opencode/child-spawn.json
- Task branch, worktree, and landing commit: opencode/task-landing.json
- Task Verify command and result: opencode/task-verify.json
- Wave and final review artifacts: opencode/reviews.json
- Archive validation output: opencode/archive.json
- Integration merge and milestone tag: opencode/integration.json
- Remaining `git worktree list` output: opencode/worktrees.json
- Native guard and Git-hook results: opencode/guards.json

Fixture Git bundle: opencode/fixture.bundle (all refs, including origin/main and the annotated milestone tag).
