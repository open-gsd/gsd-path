---
schema: gsd-path/live-evidence/v1
host: claude
package: 1.4.0
pipeline: gsd-path/v2
candidate: cab24a78d31ba41d9d1b357dd72aeae00775ef2d
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

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/evaluations/gsd-path-release-2026-10-07-cab24a78/claude`.

## Environment

- Host and CLI version: Claude Code 2.1.284
- Operator: local release evaluator
- Date: 2026-10-07
- Fixture repository: /Users/jeremymcspadden/evaluations/gsd-path-release-2026-10-07-cab24a78/claude/quick/repo
- Child-agent API used: Agent (description build_t001)

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
