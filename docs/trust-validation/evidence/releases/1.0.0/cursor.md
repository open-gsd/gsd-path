---
schema: gsd-path/live-evidence/v1
host: cursor
package: 1.0.0
pipeline: gsd-path/v2
candidate: 052475792bbe211f104d34a524c22db056bdee71
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

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-0524757/cursor`.

## Environment

- Host and CLI version: cursor-agent 2026.09.10-fd3934a
- Operator: Jeremy McSpadden; owner gates answered by the session evaluator and recorded in quick/owner-reply-*.txt
- Date: 2026-09-14
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-0524757/cursor/quick/repo
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
