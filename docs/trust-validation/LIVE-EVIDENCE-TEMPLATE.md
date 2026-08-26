---
schema: gsd-path/live-evidence/v1
host: HOST
package: VERSION
pipeline: gsd-path/v2
candidate: FULL_CANDIDATE_SHA
verdict: pending
child_spawn: pending
state: pending
task_verify: pending
wave_review: pending
final_review: pending
archive: pending
integration: pending
guard_tier: MANIFEST_GUARD_TIER
---

# Live milestone evidence — HOST

Copy this file to `evidence/releases/<version>/<host>.md`. Replace every
placeholder. Create one tracked JSON file per step under
`evidence/releases/<version>/<host>/`, then use its plain relative path below.
Every receipt and step file must be added or updated after the tested candidate.

## Environment

- Host and CLI version:
- Operator:
- Date:
- Fixture repository:
- Child-agent API used:

## Evidence

- Install command and result: HOST/install.json
- Router invocation and state artifact: HOST/router.json
- Child spawn output: HOST/child-spawn.json
- Task branch, worktree, and landing commit: HOST/task-landing.json
- Task Verify command and result: HOST/task-verify.json
- Wave and final review artifacts: HOST/reviews.json
- Archive validation output: HOST/archive.json
- Integration merge and milestone tag: HOST/integration.json
- Remaining `git worktree list` output: HOST/worktrees.json
- Native guard and Git-hook results: HOST/guards.json

Each step file uses this base shape. Set `step` to the filename stem, retain the
actual command or host action, embed its inspectable output, and add the
step-specific fields below:

```json
{
  "schema": "gsd-path/live-step-evidence/v1",
  "host": "HOST",
  "step": "install",
  "command": "node scripts/install.mjs ...",
  "result": "pass",
  "output": "actual command output or artifact details"
}
```

| Step | Required fields |
|---|---|
| `install` | `host_version`, `install_root`, `exit_code: 0` |
| `router` | `state_artifact`, `state_phase: "shipped"` |
| `child-spawn` | `child_id`, `child_status: "completed"` |
| `task-landing` | `fixture_bundle`, `fixture_base_commit`, `task_branch`, `task_worktree`, `landing_commit` |
| `task-verify` | `verify_artifact`, `verify_exit_code: 0` |
| `reviews` | `wave_review_artifact`, `final_review_artifact` |
| `archive` | `archive_path`, `validation_exit_code: 0` |
| `integration` | `fixture_bundle`, `integration_commit`, `milestone_tag` |
| `worktrees` | non-empty `remaining_worktrees` string list |
| `guards` | manifest `declared_tier`, `native_guard`, and `git_hooks` results |

`fixture_bundle` is one tracked `git bundle` inside the host evidence directory.
It must contain the base and landing commits, an `integrate:` merge commit, and
an annotated `milestone/<NNN>-<slug>` tag at that merge. The landing and
integration steps must reference the same bundle. For a `git-only` host set
`native_guard` to `not-applicable`; otherwise set it to `pass`. `git_hooks`
must be `pass` for every host.

Do not mark `child_spawn: pass` for a top-level CLI invocation. If any result
is missing or cannot be reproduced, set the affected field to `unverifiable`.
