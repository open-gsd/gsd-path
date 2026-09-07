# Workflow runner and observed token budgets

The runner assembles arguments for existing canonical helpers. It returns a JSON
receipt containing each command, exit code, stdout, stderr, and parsed result.
`build-evidence` also appends a step with `script` and `evidence` fields naming
the written proof file.
A failed helper stops the sequence before any later gate or checkpoint. Preserve
that receipt with the phase evidence; a blocked receipt routes to forensics.
It does not dispatch models or supply owner approvals.

## Workflow commands

Use the absolute `workflow_run.py` path in the active skill's scripts directory.
All commands require `--repo <absolute repository root>`.

| Command | Required input | Result |
| --- | --- | --- |
| `route` | Optional `--project-dir .project/next` | Canonical route; follow its action even when it blocks or requests recovery. |
| `gate-plan` | Git HEAD; optional lookahead project directory | Pending discussion, intent coverage, brief paths, and panel configuration checked in order. |
| `approve-plan` | Owner approval and `--expected-head <reviewed full SHA>` | Plan gates followed by the existing journaled approval checkpoint. |
| `lint-round` | Git HEAD; optional `--project-dir .project/next` | Task brief checks against HEAD, then plan handoff checks. |
| `prepare-task` | `--expected-head <clean base> --task-id <id> --round-size <ready task count>` | Canonical task isolation; serial work also gets a verification sidecar before the primary becomes dirty. |
| `build-evidence` | `--expected-head <full SHA>` | Canonical landing proof written to `<project-dir>/build/evidence.json` (default: `.project/build/evidence.json`). |

Plan approval recovery remains `pipeline_state.py resume-checkpoint`. Pre-Git
approvals and patch approvals retain their existing canonical flows. The runner
never changes a recorded base, retries a failed mutation, or repairs state itself.

For serial work, keep the returned verification sidecar until the coder finishes.
Validate the full task diff, reproduce only that patch in the sidecar, compare the
product diffs, and run Task Verify there. Record that exact evidence before landing.
The runner avoids having to remove a live product patch merely to create a sidecar.
Task verification, wave review, and ship-only project verification retain their
existing responsibilities.

## Dispatch driver

`dispatch_driver.py` in the router and build bundles runs one build wave's
deterministic loop so the orchestrating model only supplies judgment. `round`
and `finish` run recovery against Git and the task files before processing
dispatch records under the Git common directory
(`gsd-path/dispatch/<milestone slug>/<task>/attempt-N/`). The milestone slug
replaces `/` in the bound branch with `-` (for example, `gsd-path/M001`
becomes `gsd-path-M001`). `answer` and `status`
read the newest attempt records. Records are keyed by the bound branch, so a
new milestone starts with no attempts and the previous milestone's records
remain as evidence.
Review attempts use `gsd-path/dispatch/<milestone slug>/reviews/<logical name>/attempt-N/`;
`status` and `answer` cover task attempts only.

| Command | Result |
| --- | --- |
| `round --repo <root> --wave <N> --child-command '<cmd>' [--wait <s>] [--child-timeout <s>] [--capacity <N>] [--max-attempts <N>] [--task-limit <N> --session-limit <N> --budget-authority '<policy>']` | Recover, settle exited children, `ready`, checkpoint bookkeeping, lint, isolate, dispatch; Verify, land, record, retire each result in task-id order. Receipt status `done`, `in-flight`, `question`, or `blocked`. |
| `review --repo <root> --wave <N> --cycle <C> --child-command '<cmd>' [--wait <s>] [--child-timeout <s>] [--repair-evidence <receipt>]` | Step 6 at `full` or `deep` depth: clean review base, one verify sidecar and reviewer child per lens, validate in the sidecar, collect, retire; after every lens settles, checkpoint a `pass` when no panel is configured, or return the `review_findings.py collect` grouping on `blocked`. `verify-only` returns `not-applicable`; `panel_required` reports the PLAN panel setting. |
| `panel --repo <root> --wave <N> --cycle <C> --advertised <slugs> [--parent-slug <slug>] --child-command '<cmd with {model}>' [--wait <s>]` | Step 6 panel: `review_panel.py resolve`; `off`, a persisted skipped receipt, or one panelist per family in its own sidecar; collect, `review_panel.py merge`, then the single on-pass checkpoint with the review. |
| `fix-tasks --repo <root> --wave <N> --cycle <C>` | Step 7 batching: one fix task per `review_findings.py collect` batch with the failed criteria and observations verbatim, lint-checked; `escalate` for structural blockers, skeptic groups, cycle cap, or all-refuted. |
| `finish --repo <root> --task-id <id>` | Recover first; return a proven landing without repeating Verify, or verify, land, record, and retire one returned task. Without a dispatch record, derive the isolate from task frontmatter. |
| `answer --repo <root> --task-id <id> --answer '<text>'` | Append `Orchestrator answer:` to the isolate's task Log; the next `round` redispatches that isolate. |
| `status --repo <root>` | Every task's newest dispatch record. |

The child command is owner-supplied shell words. The driver runs it with the
isolated worktree as its working directory and the self-contained brief on
stdin; the owner's flags decide the child's permissions and model. Verified
templates: `claude -p --output-format json <owner permission flags>` and
`codex exec --json <owner sandbox flags>`. A coder child ends its final message with
`RESULT: <task id> ready|blocked`; no line means blocked. A Log delta whose
first entry after the last recorded `Orchestrator answer:` leads with
`NEEDS-ORCHESTRATOR:` is a question only when the child exits successfully;
a timeout or nonzero exit is a failure even if the child wrote a question.
Reviewer children instead return the `Wave verdict:` line in their validated
review artifact; they do not need a `RESULT:` line.
`--wave` is required and pins the parent-selected wave, including on resumed
calls. In `round`, an unfinished earlier wave blocks dispatch before the bookkeeping
checkpoint. Child completion is recorded in `exit.json`; the parent alone
writes `state.json`.
`--wait`, `--child-timeout`, and `--capacity` (concurrent children) have
no defaults. `--max-attempts` defaults to 2 dispatches per task per milestone,
the build contract's one logged redispatch after the first attempt; question
redispatches do not count. At the limit `round` returns `blocked` naming the
task, and a person rules.

Token budgets are opt-in. Passing `--task-limit`, `--session-limit`, and
`--budget-authority` together configures this milestone's ledger at
`gsd-path/budget/<milestone slug>.json` under the Git common directory, records
each child's usage from its captured stdout when it exits, and runs `admit`
before preparing or activating a fresh task and before each question
redispatch; a blocked admission stops the round. The ledger's
policy is fixed once configured. Later rounds and `finish` enforce that policy
even when budget flags are omitted; only explicit flags configure it. Each
attempt records its own usage, including question redispatches. A new milestone
gets a new ledger. Usage
is read from Codex `--json` events or Claude `--output-format json`; output
that proves no usage stops the round rather than estimating. At most one `Heavy: yes`
Verify task is in flight at a time, and a round stops at a wave boundary.
Without `--wait`, the call returns after processing currently available work;
children continue running. `--capacity`, when supplied, must be positive.

`round`, `review`, `finish`, and `answer` hold a repository-scoped advisory lock for the
whole call, including `--wait`. A concurrent invocation returns `blocked`
with `another dispatch_driver invocation holds the lock`; wait for the
active call to return before retrying. Bookkeeping also blocks if an
in-progress primary task has no open dispatch record.

Verify output is saved in `verify.json`. A `verify-record` ledger entry is
written only when the landing commit's parent equals the recorded task base;
a later parallel landing can therefore have no ledger entry.

For task attempts, the driver reports and never repairs: a failed child, a failed Verify, a
recovery or reconciliation verdict, or a `ready` error returns `blocked` with
the evidence, and the isolate stays in place for the build contract's
documented procedure.

Resume an `in-flight` review with the same wave and cycle. Missing lens records
are dispatched only while the primary is clean and HEAD still matches the
recorded base. For cycle 2 or later, every previous-cycle lens artifact must
exist before dispatch. Invalid review files remain in their sidecars for
inspection. Collection progress is saved before cleanup; a cleanup failure
returns `blocked` with helper findings, and a later call retries cleanup.
Reusing a collected verdict requires the canonical artifact to match its saved
validation hash. Review inputs must still match the recorded base: only this
cycle's review artifacts may differ, and HEAD may advance only by the cycle's
own review checkpoint. Other changes block reuse and require a new cycle.

## Token accounting

`token_budget.py` is in the router and build bundles. Limits have no defaults.
The dispatch driver owns its ledger as described [above](#dispatch-driver).
For manual accounting, configure one ledger for the logical session, outside
the worktree, using the owner's exact
limits and their authority. For example, use a path under the Git common directory
returned by Git; do not assume `.git` is a directory in a linked worktree.

```text
python3 <token_budget.py> configure --ledger <absolute ledger> --task-limit <owner value> --session-limit <owner value> --authority <quoted owner policy>
python3 <token_budget.py> record --ledger <absolute ledger> --task <logical task> --events <completed host event file>
python3 <token_budget.py> admit --ledger <absolute ledger> --task <next logical task>
```

The metric is the host's `output_tokens`, including its reported reasoning output;
reasoning is not added again. Input and cached input are not included. Resumptions
reuse the ledger and task identity. Each CLI invocation uses its immutable event
file. Re-observing that file is idempotent; new invocations accumulate. Native
single-invocation child sessions and Claude `--output-format json` usage
receipts are supported. Resumed native child logs with
ambiguous cumulative counters fail closed; use separate CLI run receipts instead.
Record every completed parent invocation and child, not only coder work.

`admit` blocks once observed task or session output reaches the configured limit.
A negative exit is not permission to start a new ledger, rename the task, or omit
usage. Incomplete usage cannot establish remaining budget. Configuration preserves
existing observations and refuses a changed policy for the same session ledger.

This is **observed admission enforcement**. Concurrent, unreported, and in-flight
usage remains unproven. Codex CLI 0.153.4 exposes usage after execution but its help
and published configuration list no hard output-token cap. Use
`admit --require-hard-cap` when hard enforcement is required: this host returns
blocked with `hard_cap_supported: false`. These helpers do not make a strict
budget-compliance claim. Other hosts need a verified counter/cap adapter.

Sources checked for this host: local `codex exec --help`,
[official CLI reference](https://developers.openai.com/codex/cli/reference), and
[official configuration reference](https://developers.openai.com/codex/config-reference).
The Responses API's generation limits are a different interface; they do not
establish a Codex CLI capability.

## Lean final verification

The ship bundle's `workflow_run.py prepare-final --repo <root> --expected-head
<full SHA>` sequences landing proof, isolated project Verify, evidence collection,
and final reuse. A command/commit receipt stores exact stdout/stderr once; retry
rebuilds its gap view and cleans up an interrupted sidecar without another run.
Legacy receipts without output require reconciliation if no valid proof can be
recovered. A full quick-lane wave explicitly covering final scope supplies FINAL.md
when every criterion and surface walkthrough is proven and Git shows unchanged
product and contracts. Other scopes retain final review. The output names whether
review is needed; models do not route reuse by comparing prose or file sizes.
