---
schema: gsd-path/live-evidence/v1
host: copilot
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
guard_tier: git-only
---

# Live milestone evidence — copilot

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-0524757/copilot`.

## Environment

- Host and CLI version: GitHub Copilot CLI 1.0.83
- Operator: Jeremy McSpadden; owner gates answered by the session evaluator and recorded in quick/owner-reply-*.txt
- Date: 2026-09-14
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-0524757/copilot/quick/repo
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
