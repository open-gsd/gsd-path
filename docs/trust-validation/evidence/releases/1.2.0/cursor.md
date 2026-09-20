---
schema: gsd-path/live-evidence/v1
host: cursor
package: 1.2.0
pipeline: gsd-path/v2
candidate: f36f24aed82ac0019d082c7e31b8a4342d8e03f1
verdict: pass
child_spawn: pass
state: pass
task_verify: pass
wave_review: pass
final_review: pass
archive: pass
integration: pass
guard_tier: native-fail-closed
---

# Live milestone evidence — cursor

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/cursor`.

## Environment

- Host and CLI version: 2026.09.18-9a7762b
- Operator: release evaluator
- Date: 2026-09-20
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/cursor/quick/repo
- Child-agent API used: Task (description build_T001)

## Evidence

- Install command and result: cursor/install.json
- Router invocation and state artifact: cursor/router.json
- Child spawn output: cursor/child-spawn.json
- Task branch, worktree, and landing commit: cursor/task-landing.json
- Task Verify command and result: cursor/task-verify.json
- Wave and final review artifacts: cursor/reviews.json
- Archive validation output: cursor/archive.json
- Integration merge and milestone tag: cursor/integration.json
- Remaining `git worktree list` output: cursor/worktrees.json
- Native guard and Git-hook results: cursor/guards.json

Fixture Git bundle: cursor/fixture.bundle (all refs, including origin/main and the annotated milestone tag).

Run qualifications, negative attempts, usage, and raw-log paths: [cursor/run-notes.md](cursor/run-notes.md).
