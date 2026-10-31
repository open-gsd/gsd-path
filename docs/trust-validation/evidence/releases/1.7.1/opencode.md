---
schema: gsd-path/live-evidence/v1
host: opencode
package: 1.7.1
pipeline: gsd-path/v2
candidate: ab909c7ddd43a178305672e74f48a6d3d5624e62
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

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.7.1-ab909c7d/opencode`.

## Environment

- Host and CLI version: 1.18.25
- Operator: local release evaluator
- Date: 2026-10-31
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.7.1-ab909c7d/opencode/quick/repo
- Child-agent API used: Task (description build_t001)

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
