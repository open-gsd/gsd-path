---
schema: gsd-path/live-evidence/v1
host: kiro
package: 1.1.0
pipeline: gsd-path/v2
candidate: af0b082964510c471798826d7e2e05617d8d6dc3
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

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.1.0-af0b082/kiro-rerun-2`.

## Environment

- Host and CLI version: kiro-cli 2.21.2
- Operator: Release evaluator for Jeremy McSpadden
- Date: 2026-09-18
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.1.0-af0b082/kiro-rerun-2/quick/repo
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
