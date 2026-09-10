---
schema: gsd-path/live-evidence/v1
host: kiro
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

# Live milestone evidence — kiro

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-kiro-091d279`.

## Environment

- Host and CLI version: kiro-cli 2.21.2
- Operator: Jeremy McSpadden; owner gates answered by the session evaluator and recorded in quick/owner-reply-*.txt
- Date: 2026-09-09
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-kiro-091d279/quick/repo
- Child-agent API used: invoke_sub_agent (task build_T001)

## Evidence

- Install command and result: kiro/install.json
- Router invocation and state artifact: kiro/router.json
- Child spawn output: kiro/child-spawn.json
- Task branch, worktree, and landing commit: kiro/task-landing.json
- Task Verify command and result: kiro/task-verify.json
- Wave and final review artifacts: kiro/reviews.json
- Archive validation output: kiro/archive.json
- Integration merge and milestone tag: kiro/integration.json
- Remaining `git worktree list` output: kiro/worktrees.json
- Native guard and Git-hook results: kiro/guards.json

Fixture Git bundle: kiro/fixture.bundle (all refs, including origin/main and the annotated milestone tag).
