---
schema: gsd-path/live-evidence/v1
host: zed
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

# Live milestone evidence — zed

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.1.0-af0b082/zed`.

## Environment

- Host and CLI version: Zed eval-cli source 4a217d5316887826a21c554650c1ece6d51fff2a
- Operator: Release evaluator for Jeremy McSpadden
- Date: 2026-09-18
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.1.0-af0b082/zed/quick/repo
- Child-agent API used: spawn_agent (label build_t001)

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
