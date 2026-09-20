---
schema: gsd-path/live-evidence/v1
host: copilot
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

# Live milestone evidence — copilot

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/copilot-retry4`.

## Environment

- Host and CLI version: GitHub Copilot CLI 1.0.86.
Run 'copilot update' to check for updates.
- Operator: Release evaluator
- Date: 2026-09-20
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/copilot-retry4/quick/repo
- Child-agent API used: task (description build_t001)

## Evidence

- Install command and result: copilot/install.json
- Router invocation and state artifact: copilot/router.json
- Child spawn output: copilot/child-spawn.json
- Task branch, worktree, and landing commit: copilot/task-landing.json
- Task Verify command and result: copilot/task-verify.json
- Wave and final review artifacts: copilot/reviews.json
- Archive validation output: copilot/archive.json
- Integration merge and milestone tag: copilot/integration.json
- Remaining `git worktree list` output: copilot/worktrees.json
- Native guard and Git-hook results: copilot/guards.json

Fixture Git bundle: copilot/fixture.bundle (all refs, including origin/main and the annotated milestone tag).

## Scenario and budget evidence

- Independent oracle: copilot/widget-oracle.json (six checks passed).
- Native budget: copilot/usage.json (18 sessions, maximum21,937 output tokens including children).
- Review and verification reuse: copilot/final-ready-before-repeat.json, copilot/final-ready-after-repeat.json, copilot/recovery-and-reuse.json.
- Disclosed recovered path error and diagnosis-ordering deviation: copilot/SCENARIO-OBSERVATIONS.md and copilot/review-path-negative.json. No claim of flawless protocol compliance.
- Actual native task branch/worktree: copilot/coder-provenance.json.
