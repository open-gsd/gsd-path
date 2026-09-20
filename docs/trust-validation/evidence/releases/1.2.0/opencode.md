---
schema: gsd-path/live-evidence/v1
host: opencode
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

# Live milestone evidence — opencode

Full quick-lane milestone run by the pinned candidate on a fresh fixture; evaluator-driven owner gates. Run directory: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/opencode-retry4`.

## Environment

- Host and CLI version: 1.18.25
- Operator: release evaluator
- Date: 2026-09-20
- Fixture repository: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/opencode-retry4/quick/repo
- Child-agent API used: Task (description build_t001)

## Evidence

- Install command and result: opencode/install.json
- Router invocation and state artifact: opencode/router.json
- Child spawn output: opencode/child-spawn.json
- Task branch, worktree, and landing commit: opencode/task-landing.json
- Task Verify command and result: opencode/task-verify.json
- Wave and final review artifacts: opencode/reviews.json
- Archive validation output: opencode/archive.json
- Integration merge and milestone tag: opencode/integration.json
- Remaining `git worktree list` output: opencode/worktrees.json
- Native guard and Git-hook results: opencode/guards.json

Fixture Git bundle: opencode/fixture.bundle (all refs, including origin/main and the annotated milestone tag).

Recovery history, exact native identities, candidate-helper provenance, and budget qualifications: [run notes](opencode/run-notes.md). The superseded canceled recovery has unknown usage and is not counted as accepted budget evidence.
