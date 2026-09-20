---
name: gsd-path-build
description: Execute or resume an approved GSD Path plan with isolated task worktrees, deterministic commits, and independent wave review. Use only when the user explicitly invokes $gsd-path-build or an active $gsd-path router explicitly routes to this phase.
---

Before executing project helpers, read [runtime selection](references/runtime-selection.md).

# GSD Path Build Orchestrator

Orchestrate coders, task landing, and reviewers from the main conversation.
Never write product code in the orchestrator.

Routing instructions below are caller handoffs under the AGENTS.md handoff
rule; never invoke an explicit-only sibling skill yourself.

## Preconditions and branch binding

- Require `pipeline: gsd-path/v2` in `.project/STATE.md`, an approved
  `.project/plan/PLAN.md`, and valid task files in `.project/tasks/`. A missing
  or different pipeline marker returns to `$gsd-path` for ownership checking.
  Legal entry is `plan/done`, `build/active|blocked`, or transition recovery
  from `build/done`; any later phase or an incomplete predecessor blocks
  rather than rewinding state. A concrete STATE.archive during `build/*`
  marks an interrupted milestone-abandon transaction: resume the Milestone
  abandon procedure below before any recovery or dispatch. `build/done` is
  recovery-only: follow [Completion](#completion) instead of dispatching.
- Resolve the bundled `scripts/dispatch_driver.py`, `scripts/workflow_run.py`,
  `scripts/pipeline_state.py`, `scripts/isolation.py`, and `scripts/build_state.py`.
  Helpers own task selection, state, Git, and evidence. Use their receipts.
- Read the [dispatch contract](references/dispatch.md) only when dispatching
  native children or resolving host counters. Children read their assigned role
  and template; the parent resolves those paths without loading their contents.
  Load the task template only when writing or repairing a task. Load the
  wave-panel and skeptic templates only when those branches apply.
- There is no board file. Task frontmatter is the only task-state record;
  when a report or question needs a wave summary, render it inline from the
  task files and wave reviews. Record escalations and plan defects in the
  STATE.md log.
- Require a Git worktree with no unrelated changes. Roadmap and plan
  approval checkpoints normally leave `.project/` fully committed; expected
  uncommitted `.project/` planning artifacts may remain only through initial
  branch binding when a checkpoint was deferred (a `Kind: new-github`
  transaction or no Git repository at approval time). On an approved patch
  re-entry, the exact review findings, appended
  plan/tasks, approval state, and no other changes are also expected; the build
  orchestrator checkpoints them with the `build/active` transition before a layer
  base. Append-only `.project/discuss/DIALOGUE.md` and `ANSWERS.md` records are
  also expected bookkeeping: verify that their diff only appends complete
  records, then include them in the next normal orchestrator bookkeeping checkpoint
  before establishing a layer base. Never discard, stash, or absorb another
  change.
- Before recovery or dispatch and again before each layer/wave gate, scan
  ANSWERS.md for pending required follow-ups under AGENTS.md. Apply an answer
  addressed to build only through PLAN/task bookkeeping that is legal in
  the current build state and append its disposition receipt. If it changes an
  approved upstream contract or names another owner, set `build/blocked`, link
  ANSWERS.md and the target artifact, and ask the user; never establish a new
  layer base from stale inputs.
- Fetch the configured remote and resolve its default ref and exact SHA without
  checking out, pulling, or updating the local default branch. When
  `STATE.branch` is set, adopt that recorded branch — never whatever clean
  unmerged non-default branch happens to be current: require the current
  symbolic branch to equal it. Ignore ship and integrate commits for older
  milestones inherited from main. Find only a ship subject whose M00N matches
  STATE.branch (including its legacy sequence form). If one exists and is not
  an ancestor of the resolved remote-default SHA, this milestone's integration
  is incomplete: stop and return to `$gsd-path`, which routes to ship, not
  build. If that current-milestone ship is on the default without its matching
  `integrate:` commit, block as externally polluted. A newly prebound branch
  whose HEAD equals the resolved remote-default SHA is valid. A null branch is
  always an incomplete router binding: return to `$gsd-path`, which runs
  `pipeline_git.py bind-initial` or resumes `bind-next`. Build never creates,
  selects, switches, or rebinds a milestone branch. A mismatch or a branch
  owned by another worktree blocks.
- When `.project/REPOSITORY.md` records `Kind: new-github`, parse its required
  fixed fields and verify the current root is the recorded linked primary
  worktree and the recorded default checkout stays clean on the remote
  default. Its local default ref may lag origin as integrations advance the
  remote default — that lag is not a violation, and the checkout is never
  entered or updated. The artifact's `GSD Path branch` is the first bound
  branch (`gsd-path/M001`); after a shipped milestone STATE.branch may be a
  later `gsd-path/M00N` created at the then-current remote-default SHA. Adopt
  the proven worktree and default checkout; do not parse STATE log prose or
  create another primary worktree.
- With the dispatch driver, let `round` perform the entry transition below.
  For manual dispatch, on entry from `plan/done`, run the bundled
  `pipeline_state.py transition` helper with the loaded state's full field
  set expected. Set `phase: build` and `status: active`, and use event `build
  started`. Recover `build/blocked` the same way with all old values expected.
  Checkpoint that transition with the expected initial `.project/` artifacts
  before dispatch. Never edit or append STATE.md through model-side text
  transforms. From then on, every
  dispatch round starts from a clean primary worktree and exact full `HEAD`
  SHA. Every orchestrator bookkeeping checkpoint uses subject `build: <what
  changed>` plus a body that starts with `Why: <one sentence>` and may add
  `Wave:`, `Tasks:`, and `Base:` field lines. Task landing still goes
  through `isolation.py land`; do not invent those commit messages.

**Bookkeeping checkpoint.** Every build-orchestrator instruction below to
checkpoint `.project/` records uses this helper. Record the exact full HEAD
before the first metadata change in that checkpoint, then run:

Explicit configuration edits in `.project/config.json` and
`.project/model-policy.json` are expected bookkeeping. Include them in the next
normal checkpoint before a clean dispatch base; they may remain pending while
an already dispatched task lands. Existing model selections stay pinned.

```text
python3 <absolute isolation.py> checkpoint \
  --repo <absolute primary> \
  --expected-head <recorded-full-HEAD> \
  --subject 'build: <what changed>' \
  --body 'Why: <one sentence>' \
  --allow-path .project
```

Add only the documented optional `Wave:`, `Tasks:`, and `Base:` body lines.
A typed error blocks and leaves no claimed checkpoint. The returned full
commit becomes the next clean base. This is the only build bookkeeping commit
path; product landing remains `isolation.py land`, and the ship commit remains
ship-owned. One checkpoint per repair, ruling, or transition: the edits and
the STATE.md log line that records them land together. Never add a second
STATE.md-only "finalize" checkpoint for work already checkpointed. The helper
refuses a `build:` checkpoint that deletes or renames a `.project/tasks/`
brief unless the canonical `build: abandon milestone <slug>` checkpoint moves
that same brief into `.project/archive/`; build adds fix tasks and repairs
briefs, it never replans.

## Execute from runtime receipts

For each wave in PLAN.md, use the existing dispatch driver when the owner has
supplied a child command. Preserve that command and its permission flags; never
invent a headless command or widen permissions to enable the driver.

```text
python3 <absolute dispatch_driver.py> round --repo <absolute primary> --wave <N> \
  --child-command '<owner command>'
```

`round` owns entry transition, recovery, ready-set checks, brief lint, isolation,
child dispatch, authoritative Verify, landing, ledger, retirement, and bookkeeping.
Do not replay those steps or rewrite their results in another report.

| Receipt | Next action |
|---|---|
| `in-flight` | Resume the same action to collect its existing children. |
| `done` from round | Run `review` with the same repo, wave, child command, and the current cycle. |
| Passing review, no panel required | Continue with the next wave or Completion. |
| `panel_required: true` | Read the panel procedure in [native build](references/build-native.md), then use the driver's `panel` action. |
| Blocked review with findings | Read step 7 in [native build](references/build-native.md); use `skeptics` or `fix-tasks` only as the finding receipt directs. |
| `question` | Answer from approved artifacts or escalate; record with `answer --task-id <id> --answer '<answer> — <citation>'`, then resume round. |
| Task/recovery `blocked` or structural escalation | Read the matching recovery or plan-defect branch in [native build](references/build-native.md). |

Without an owner-supplied child command, read [native build](references/build-native.md)
and the [dispatch contract](references/dispatch.md). That path uses native child
tools with the same contracts and evidence. A `verify-only` wave also reads the
native review procedure because the driver does not author that artifact.

A failing helper stops the step: report stderr and run the forensics diagnostic
under AGENTS.md. A live `in-flight` receipt is resumable work, not a failed helper.
Apply owner budgets through the dispatch contract. Never infer a new limit.

## Completion

```text
python3 <absolute dispatch_driver.py> complete --repo <absolute primary>
```

Use this runtime even when coders used native child tools. It proves all tasks
landed and wave reviews passed, writes the canonical build evidence, enters
`ship/active`, and checkpoints. A blocked receipt stops completion. On a done
receipt, report waves, task commits, fixed findings, and remaining risk; link the
absolute final wave review and use the executable phase handoff in AGENTS.md. Ship owns project Verify,
final review, archive, and publication; do not repeat or enter them here.

## Milestone abandon

Only when the owner abandons a program milestone or STATE.archive records an
interrupted abandon, read [milestone abandon](references/build-abandon.md).
