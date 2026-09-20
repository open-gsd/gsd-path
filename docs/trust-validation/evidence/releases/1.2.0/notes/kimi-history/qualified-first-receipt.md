---
schema: gsd-path/live-evidence/v1
host: kimi
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
guard_tier: git-only
---

# Live milestone evidence — kimi

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/kimi`.

## Environment

- Host and CLI version: 0.43.0
- Operator: release evidence evaluator
- Date: 2026-09-20
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/kimi/quick/repo
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
