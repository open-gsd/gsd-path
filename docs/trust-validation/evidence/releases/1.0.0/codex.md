---
schema: gsd-path/live-evidence/v1
host: codex
package: 1.0.0
pipeline: gsd-path/v2
candidate: 3c32f3d332ad126b2a406f5ff48bfc16c6d6932f
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

# Live milestone evidence — codex

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-codex-3c32f3d`.

## Environment

- Host and CLI version: codex-cli 0.153.4
- Operator: Jeremy McSpadden; owner gates answered by the session evaluator and recorded in quick/owner-reply-*.txt
- Date: 2026-09-06
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-codex-3c32f3d/quick/repo
- Child-agent API used: collaboration.spawn_agent (task_name build_t001)

## Evidence

- Install command and result: codex/install.json
- Router invocation and state artifact: codex/router.json
- Child spawn output: codex/child-spawn.json
- Task branch, worktree, and landing commit: codex/task-landing.json
- Task Verify command and result: codex/task-verify.json
- Wave and final review artifacts: codex/reviews.json
- Archive validation output: codex/archive.json
- Integration merge and milestone tag: codex/integration.json
- Remaining `git worktree list` output: codex/worktrees.json
- Native guard and Git-hook results: codex/guards.json

Fixture Git bundle: codex/fixture.bundle (all refs, including origin/main and the annotated milestone tag).
