---
schema: gsd-path/live-evidence/v1
host: qwen
package: 1.0.0
pipeline: gsd-path/v2
candidate: 091d27927a2c0c2ecc55ce386fb2232556da6336
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

# Live milestone evidence — qwen

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-qwen-091d279`.

## Environment

- Host and CLI version: qwen-code 0.23.0 (OpenAI-compatible auth via OpenRouter, model qwen/qwen3.8-max-0902; model.maxToolCallsPerTurn=0)
- Operator: Jeremy McSpadden; owner gates answered by the session evaluator and recorded in quick/owner-reply-*.txt
- Date: 2026-09-08
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-qwen-091d279/quick/repo
- Child-agent API used: agent (description build_t001)

## Evidence

- Install command and result: qwen/install.json
- Router invocation and state artifact: qwen/router.json
- Child spawn output: qwen/child-spawn.json
- Task branch, worktree, and landing commit: qwen/task-landing.json
- Task Verify command and result: qwen/task-verify.json
- Wave and final review artifacts: qwen/reviews.json
- Archive validation output: qwen/archive.json
- Integration merge and milestone tag: qwen/integration.json
- Remaining `git worktree list` output: qwen/worktrees.json
- Native guard and Git-hook results: qwen/guards.json

Fixture Git bundle: qwen/fixture.bundle (all refs, including origin/main and the annotated milestone tag).
