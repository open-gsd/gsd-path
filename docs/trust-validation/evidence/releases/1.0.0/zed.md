---
schema: gsd-path/live-evidence/v1
host: zed
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

# Live milestone evidence — zed

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-0524757/zed`.

## Environment

- Host and CLI version: Zed 1.18.1; eval-cli built from zed-industries/zed 4a217d5 (local settings-JSON fix + ZED_EVAL_UNSANDBOXED env gate setting agent.sandbox_permissions.allow_unsandboxed; model openrouter/anthropic/claude-sonnet-5)
- Operator: Jeremy McSpadden; owner gates answered by the session evaluator and recorded in quick/owner-reply-*.txt
- Date: 2026-09-14
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-0524757/zed/quick/repo
- Child-agent API used: spawn_agent (label build_T001)

## Evidence

- Install command and result: zed/install.json
- Router invocation and state artifact: zed/router.json
- Child spawn output: zed/child-spawn.json
- Task branch, worktree, and landing commit: zed/task-landing.json
- Task Verify command and result: zed/task-verify.json
- Wave and final review artifacts: zed/reviews.json
- Archive validation output: zed/archive.json
- Integration merge and milestone tag: zed/integration.json
- Remaining `git worktree list` output: zed/worktrees.json
- Native guard and Git-hook results: zed/guards.json

Fixture Git bundle: zed/fixture.bundle (all refs, including origin/main and the annotated milestone tag).
