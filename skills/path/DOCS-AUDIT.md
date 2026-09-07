---
name: gsd-path-docs-audit
description: Verify Markdown claims against the actual code, commands, and GSD Path artifacts. Use only when the user explicitly invokes $gsd-path-docs-audit or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Docs Audit

Answer one question with evidence: **does the project do what its documents
say it does?** Runs standalone at the safe checkpoints below, and as half of
`$gsd-path-inspect`. Output: `.project/research/DOCS-AUDIT.md`.

Routing instructions below are caller handoffs under the AGENTS.md handoff
rule; never invoke an explicit-only sibling skill yourself.

Before audit work and again before completion, apply the AGENTS.md
pending-answer rule with the bundled `scripts/discussion_records.py`; a
follow-up owned by docs audit is resolved in DOCS-AUDIT.md, or the phase
blocks.

Require an existing `.project/STATE.md` that passes `python3 <absolute
pipeline_state.py> validate --repo <absolute root>`; never
create pipeline state or write into an unowned `.project/`. A missing state
stops and offers explicit `$gsd-path` initialization; do not invoke it
automatically. A different marker blocks and reports ownership without writing.
Embedded inspect mode is legal only at `inspect/active|blocked`.
Standalone mode is legal only at a stable pre-build boundary
`inspect|define|research|decide|roadmap|plan` with `status: done`, or at
`ship/blocked` with no in-progress task. `build/*`, `ship/active`,
`shipped/done`, and every other state block: changing the canonical audit there
would dirty execution, invalidate review, or mutate shipped history.

## Process

1. Before writing the output, freeze the helper's exact stdout from `python3
   <absolute check_docs_audit.py> --repo <absolute root> --emit-inventory`
   (add `--alignment` in alignment mode) in a temporary file. Before any
   rewrite, preserve an existing canonical audit in a separate temporary file
   and record its SHA-256. When that audit records an `Audited HEAD` that Git
   resolves as an ancestor of HEAD, also freeze the changed set — `git -c
   core.quotePath=false diff --name-only --no-renames <prior HEAD>` plus
   `git -c core.quotePath=false ls-files --others --exclude-standard`, one
   path per line — in a temporary file; otherwise there is no changed set and
   the auditor re-verifies every claim. The frozen inventory and
   changed set travel inside the dispatch brief and
   the gate below; never persist them as `.project/` sidecar files — the
   audit's own path records are the durable copy. If a previous run left an
   inventory sidecar under `.project/research/`, the orchestrator deletes it
   when transferring the new audit — a leftover sidecar blocks the archive
   transaction. Dispatch one docs auditor with deterministic logical task
   name `docs_audit`, following the local
   [runtime dispatch contract](references/dispatch.md): local role
   [docs-auditor](references/docs-auditor.md), template
   [docs-audit](templates/docs-audit.md), absolute repo root, exact frozen
   inventory, the changed set when one exists, alignment flag, prior audit as
   carry-forward input, and output
   `.project/research/DOCS-AUDIT.md`. When Git has a resolvable HEAD and no
   non-`.project` worktree changes, the orchestrator creates a verify sidecar
   with `python3 <absolute isolation.py> isolate-verify --repo <absolute
   primary> --base <HEAD> --name docs-audit` for project commands. The auditor
   writes only its assigned output under that sidecar. Gate it there before
   collection. Then run `python3 <absolute isolation.py> collect-artifact
   --repo <absolute primary> --source <returned worktree> --base <recorded
   HEAD> --branch <returned branch> --source-path
   .project/research/DOCS-AUDIT.md --destination-path
   .project/research/DOCS-AUDIT.md`, adding `--expected-destination <recorded
   prior SHA-256>` when a prior audit existed. Require the returned base,
   branch, source, and destination to match; then non-force retire that exact
   worktree and branch with `isolation.py retire`. A corrected redispatch is
   gated before collection and uses the same expected prior hash. Otherwise no
   project command may run. The dispatch brief carries current HEAD as the
   audit baseline only when that verify sidecar was created at HEAD; otherwise
   it carries `none`. The auditor writes that baseline as `Audited HEAD`.
2. Gate the artifact with the bundled helper: write the frozen inventory to
   a temporary file (one path per line) and run
   `python3 <absolute check_docs_audit.py> --repo <docs sidecar> --inventory
   <file> [--prior-audit <temporary prior-audit file>] [--changed <temporary
   changed-set file>]`.
   It enforces the contract — every doc with at least one testable claim has
   a claims table, every claim a valid type and verdict with evidence, every
   claimless doc appears once in the `## Descriptive docs` list, the section
   paths and that list are disjoint and together equal the frozen inventory
   exactly, the Summary counts match the rows, the remediation queue
   classifies every non-verified claim, every prior User-ruling row and
   Planned value survives in order, and every `unchanged:` row satisfies
   the Delta rule below. A non-zero exit names the failed
   rule. Redispatch one complete corrected brief under logical task name
   `docs_audit`, following the runtime dispatch contract. If it still fails,
   present **Outcome** with the failed gate, **Review** linking DOCS-AUDIT.md or
   STATE.md when it is missing, and **Next** naming the required correction.
3. Report to the user: verdict counts, the drift list (stale + aspirational
   claims), and the remediation queue. Link the resolved absolute
   `.project/research/DOCS-AUDIT.md` path before asking for any ruling. Do not
   fix anything in this skill.
4. **Collect rulings** (standalone runs; during `$gsd-path-inspect` define
   owns this). Walk the remediation queue with the user — batches of three,
   an interactive input tool when available. Present the auditor's
   classification as the first option marked `(recommended)` with its
   recorded evidence as the one-line reason; a `NEEDS-USER` item where the
   auditor cannot tell which side is wrong carries no recommendation, stated
   as such. Each item gets one ruling:
   - `fix-code` — the doc is the contract; the code must catch up
   - `fix-doc` — reality is right; the doc must be corrected
   - `accept-drift` — known and tolerated; recorded so the next audit
     doesn't resurface it
   Append every ruling to DOCS-AUDIT.md under `## User rulings`, verbatim.
   A ruling that contradicts an INTENT.md veto stops the walk — the veto
   wins until the user amends INTENT.md itself.
5. **Queue, don't execute.** Every `fix-code` and `fix-doc` ruling enters
   the alignment queue: its `## User rulings` row is marked
   `planned: no`. Ruling and executing are separate decisions — the user
   may not be ready to work the backlog. Close by offering once: plan the
   patch wave now, or hold. If an active `$gsd-path` routed this audit and the
   user chooses now, return control with DOCS-AUDIT.md as the patch findings
   source. When invoked directly, do not invoke an explicit-only sibling;
   tell a user who chooses now to explicitly invoke `$gsd-path`, which will
   offer the queued source to plan. On hold — the default — report the queue
   size and that `$gsd-path` will offer alignment until the
   queue is drained. Only `accept-drift` rulings → nothing queued, done.
   After the choice, link the updated DOCS-AUDIT.md and state whether planning
   starts now or the queue remains for a later router pass.

## The verification methodology

The auditor follows this checklist for every doc; the audit file is the
filled-in checklist, so the method and the artifact stay one thing.

**Inventory.** Every `.md` in the repo (root, `docs/`, nested), plus
`.project/` artifacts when present. Excluded: `node_modules`, build output,
vendored code, `.project/archive/`, and the output audit itself — archives are
read-only history and are never audited. The orchestrator freezes this list
before dispatch; the auditor uses it verbatim. Every file is accounted for —
a doc with no testable claims gets one line in `## Descriptive docs`, not its
own section and not skipped. Rewriting DOCS-AUDIT.md preserves any
existing `## User rulings` rows: rulings and `planned` markers carry forward
verbatim, so a re-audit never wipes the alignment queue.

**Delta.** A re-audit re-verifies only what could have moved: every doc in
the changed set, every claim whose evidence names a changed path, every
command claim, and every prior non-verified claim. Any other prior
`verified` row is carried with exactly one `unchanged: ` prefix on its
Evidence. An already-carried row is copied verbatim without adding another
prefix. The gate rejects a carried row that fails any of those conditions.
No recorded `Audited HEAD`, or one that is not an ancestor of HEAD, means no
changed set and a full re-audit.

**Extract claims.** A claim is any statement reality can contradict:

| Claim type | Example | Check |
|------------|---------|-------|
| command | "run `npm test`" | run it; record exit code |
| feature | "supports OAuth login" | find the implementing code path |
| structure | "parsers live in `src/parse/`" | path exists and matches |
| status | "phase 2 complete", checked box | artifact/commit/code exists |
| config | "set `API_URL` in `.env`" | variable is actually read |
| integration | "syncs to Linear" | client code + config present |

**Verify.** Each claim gets checked by the cheapest sufficient method, in
order: run the command; read the named code; run the relevant test; check
git history. Verdicts:

- `verified` — checked and true, evidence recorded (file:line or command + output)
- `stale` — was plausibly true once; code has moved on
- `aspirational` — describes something never built
- `unverifiable` — cannot be checked from the repo (external service, credentials)

**Alignment mode** (when `.project/` exists) — the pipeline audits itself:

- every INTENT.md success criterion → `met` so far / `not yet` / `contradicted`
- every task with `status: done` → `isolation.py recover` proves its landing
  commit and its Verify command still passes
- SYNTHESIS.md decisions → the code actually uses the decided stack/shape
- STATE.md → agrees with task frontmatter and review files

**Remediate.** Every non-`verified` claim lands in the remediation queue,
classified `fix-doc` (reality is right, doc lies) or `fix-code`
(doc is the contract, code fell short) or `NEEDS-USER` when the auditor
cannot tell which side is wrong. The queue is input for the user's ruling —
during inspection it feeds define; mid-project, accepted `fix-code`
items become a patch wave through `$gsd-path-plan`.

## Rules

- Audit is read-only; the auditor never edits docs or code.
- Build, test, lint, and help commands run only in an agent-specific verify
  sidecar at a recorded clean revision. If that cannot faithfully
  represent the claim, use static evidence or mark it `unverifiable`; never run
  project commands in the source worktree.
- A verdict without recorded evidence is itself a defect — the audit must
  meet the same evidence standard it enforces.
- Never let the auditor decide doc-vs-code conflicts; that is a user ruling.
