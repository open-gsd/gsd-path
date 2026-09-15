---
schema: gsd-path/live-evidence/v1
host: kimi
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

# Live milestone evidence — kimi

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-0524757/kimi`.

## Environment

- Host and CLI version: kimi 0.42.0
- Operator: Jeremy McSpadden; owner gates answered by the session evaluator and recorded in quick/owner-reply-*.txt
- Date: 2026-09-14
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-0524757/kimi/quick/repo
- Child-agent API used: Agent (description build_t001)

## Evidence

- Install command and result: kimi/install.json
- Router invocation and state artifact: kimi/router.json
- Child spawn output: kimi/child-spawn.json
- Task branch, worktree, and landing commit: kimi/task-landing.json
- Task Verify command and result: kimi/task-verify.json
- Wave and final review artifacts: kimi/reviews.json
- Archive validation output: kimi/archive.json
- Integration merge and milestone tag: kimi/integration.json
- Remaining `git worktree list` output: kimi/worktrees.json
- Native guard and Git-hook results: kimi/guards.json

Fixture Git bundle: kimi/fixture.bundle (all refs, including origin/main and the annotated milestone tag).
