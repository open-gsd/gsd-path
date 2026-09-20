---
schema: gsd-path/live-evidence/v1
host: claude
package: 1.3.0
pipeline: gsd-path/v2
candidate: 45466c40e57c6cc0d7acd099e880d1644b33f5ee
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

# Live milestone evidence — claude

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/claude`.

## Environment

- Host and CLI version: 2.1.278 (Claude Code)
- Operator: release evidence evaluator
- Date: 2026-09-20
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/claude/quick/repo
- Child-agent API used: Agent (description build_T001)

## Evidence

- Install command and result: claude/install.json
- Router invocation and state artifact: claude/router.json
- Child spawn output: claude/child-spawn.json
- Task branch, worktree, and landing commit: claude/task-landing.json
- Task Verify command and result: claude/task-verify.json
- Wave and final review artifacts: claude/reviews.json
- Archive validation output: claude/archive.json
- Integration merge and milestone tag: claude/integration.json
- Remaining `git worktree list` output: claude/worktrees.json
- Native guard and Git-hook results: claude/guards.json

Fixture Git bundle: claude/fixture.bundle (all refs, including origin/main and the annotated milestone tag).
