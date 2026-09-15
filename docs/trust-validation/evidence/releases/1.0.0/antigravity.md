---
schema: gsd-path/live-evidence/v1
host: antigravity
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

# Live milestone evidence — antigravity

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-0524757/antigravity`.

## Environment

- Host and CLI version: agy 1.2.2
- Operator: Jeremy McSpadden; owner gates answered by the session evaluator and recorded in quick/owner-reply-*.txt
- Date: 2026-09-14
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-0524757/antigravity/quick/repo
- Child-agent API used: invoke_subagent (role build_t001)

## Evidence

- Install command and result: antigravity/install.json
- Router invocation and state artifact: antigravity/router.json
- Child spawn output: antigravity/child-spawn.json
- Task branch, worktree, and landing commit: antigravity/task-landing.json
- Task Verify command and result: antigravity/task-verify.json
- Wave and final review artifacts: antigravity/reviews.json
- Archive validation output: antigravity/archive.json
- Integration merge and milestone tag: antigravity/integration.json
- Remaining `git worktree list` output: antigravity/worktrees.json
- Native guard and Git-hook results: antigravity/guards.json

Fixture Git bundle: antigravity/fixture.bundle (all refs, including origin/main and the annotated milestone tag).
