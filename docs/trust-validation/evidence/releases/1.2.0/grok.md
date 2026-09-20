---
schema: gsd-path/live-evidence/v1
host: grok
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

# Live milestone evidence — grok

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/grok-retry3`.

## Environment

- Host and CLI version: grok 1.0.34 (3736acbc8658) [stable]
- Operator: release evaluator
- Date: 2026-09-20
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/grok-retry3/quick/repo
- Child-agent API used: spawn_subagent (description build_t001)

## Evidence

- Install command and result: grok/install.json
- Router invocation and state artifact: grok/router.json
- Child spawn output: grok/child-spawn.json
- Task branch, worktree, and landing commit: grok/task-landing.json
- Task Verify command and result: grok/task-verify.json
- Wave and final review artifacts: grok/reviews.json
- Archive validation output: grok/archive.json
- Integration merge and milestone tag: grok/integration.json
- Remaining `git worktree list` output: grok/worktrees.json
- Native guard and Git-hook results: grok/guards.json

Fixture Git bundle: grok/fixture.bundle (all refs, including origin/main and the annotated milestone tag).

Run qualifications, earlier failures, budgets, and provenance: [grok/run-notes.md](grok/run-notes.md).
