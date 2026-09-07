# Workflow runner and observed token budgets

The runner assembles arguments for existing canonical helpers. It returns a JSON
receipt containing each command, exit code, stdout, stderr, and parsed result.
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
| `build-evidence` | `--expected-head <full SHA>` | Canonical landing proof with the correct repo-relative project directory. |

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
(`gsd-path/dispatch/<task>/attempt-N/`). `answer` and `status` read the newest
attempt records.

| Command | Result |
| --- | --- |
| `round --repo <root> --wave <N> --child-command '<cmd>' [--wait <s>] [--child-timeout <s>] [--capacity <N>]` | Recover, settle exited children, `ready`, checkpoint bookkeeping, lint, isolate, dispatch; Verify, land, record, retire each result in task-id order. Receipt status `done`, `in-flight`, `question`, or `blocked`. |
| `finish --repo <root> --task-id <id>` | Recover first; return a proven landing without repeating Verify, or verify, land, record, and retire one returned task. Without a dispatch record, derive the isolate from task frontmatter. |
| `answer --repo <root> --task-id <id> --answer '<text>'` | Append `Orchestrator answer:` to the isolate's task Log; the next `round` redispatches that isolate. |
| `status --repo <root>` | Every task's newest dispatch record. |

The child command is owner-supplied shell words. The driver runs it with the
isolated worktree as its working directory and the self-contained brief on
stdin; the owner's flags decide the child's permissions and model. Verified
templates: `claude -p --output-format json <owner permission flags>` and
`codex exec --json <owner sandbox flags>`. A child ends its final message with
`RESULT: <task id> ready|blocked`; no line means blocked. A Log delta whose
first entry after the last recorded `Orchestrator answer:` leads with
`NEEDS-ORCHESTRATOR:` is a question.
`--wave` is required and pins the parent-selected wave, including on resumed
calls. An unfinished earlier wave blocks dispatch before the bookkeeping
checkpoint. Child completion is recorded in `exit.json`; the parent alone
writes `state.json`.
`--wait`, `--child-timeout`, and `--capacity` (concurrent children) have
no defaults. At most one `Heavy: yes`
Verify task is in flight at a time, and a round stops at a wave boundary.
Without `--wait`, the call returns after processing currently available work;
children continue running. `--capacity`, when supplied, must be positive.

`round`, `finish`, and `answer` hold a repository-scoped advisory lock for the
whole call, including `--wait`. A concurrent invocation returns `blocked`
with `another dispatch_driver invocation holds the lock`; wait for the
active call to return before retrying. Bookkeeping also blocks if an
in-progress primary task has no open dispatch record.

Verify output is saved in `verify.json`. A `verify-record` ledger entry is
written only when the landing commit's parent equals the recorded task base;
a later parallel landing can therefore have no ledger entry. Token-budget
admission for headless children remains deferred.

The driver reports and never repairs: a failed child, a failed Verify, a
recovery or reconciliation verdict, or a `ready` error returns `blocked` with
the evidence, and the isolate stays in place for the build contract's
documented procedure.

## Token accounting

`token_budget.py` is in the router bundle. Limits have no defaults. Configure one
ledger for the logical session, outside the worktree, using the owner's exact
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
single-invocation child sessions are supported. Resumed native child logs with
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
