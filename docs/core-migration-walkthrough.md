# Core intake walkthrough

This is a worked fixture, not approval of a real project's intent.

## Core input inspected

The temporary project contained `app.py`, defining `list_tasks(tasks)` to
return each task's title, and these six `.planning/` files:

| Source | Relevant evidence |
| --- | --- |
| PROJECT.md | Project operators; Python standard library only; "No cloud sync." |
| REQUIREMENTS.md | LIST-1: list saved tasks, checked complete; EXPORT-1: export saved tasks as CSV, unchecked |
| STATE.md | Core state version 1.0, planning, phase 2 of 2 |
| ROADMAP.md | Phase 1 listing complete; phase 2 CSV export unfinished |
| phases/01/SUMMARY.md | LIST-1 shipped; listing must remain available |
| phases/02/PLAN.md | Deliver EXPORT-1; columns id,title; preserve commas and quotes in titles |

## Executed preparation and entry

Ran `migrate_core.py prepare` to a new external bundle, then `verify`.
Results: `prepared`, then `verified-bundle`. Compared all six original files
with their bundle copies and confirmed exact bytes. Ran Path's existing
`detect_project.py initialize` with its canonical state template, then
`pipeline_state.py validate` in the temporary source project.

Initialization returned `brownfield`, `route: inspect`, `wrote_state: true`.
Validated Path state was `pipeline: gsd-path/v2`, `phase: inspect`,
`status: active`, `milestone: null`, `branch: null`, `archive: null`.
Core source files still matched their original bytes. The fixture was removed
after inspection. No branch binding, intent approval or later gate was claimed.

## Worked IMPORT.md content

**Context:** project operators need a CSV representation of their task data.
The existing Python helper returns task titles; export is not implemented.

**Constraints and exclusions:** "Python standard library only." and
"No cloud sync." carry forward verbatim from PROJECT.md.

| Source | Original status | Path disposition |
| --- | --- | --- |
| REQUIREMENTS.md, LIST-1; phases/01/SUMMARY.md | Complete/shipped | Preserve existing listing behavior. Inspection confirms the helper, not saved-task persistence. Retain the historical claim and ask about the missing persistence boundary. |
| REQUIREMENTS.md, EXPORT-1; ROADMAP.md, phase 2 | Unfinished | Include CSV export in proposed intent. |
| phases/02/PLAN.md, columns id,title | Planned | Include column order and names in an observable export criterion. |
| phases/02/PLAN.md, commas and quotes | Planned | Include CSV round-trip preservation in an observable export criterion. |
| PROJECT.md, constraints/out of scope | Binding context | Carry standard-library constraint and cloud-sync veto into intent. |
| STATE.md, phase 2 of 2 | Core position | Preserve as history. Path starts at inspection. |

**History:** the phase 1 summary is retained. It does not establish Path task
completion or prove a persistence layer that the inspected code lacks.

**Hook cutover:** use the supported host procedure and receipts described in
MIGRATE.md. This fixture exercises data intake only. Native project plugin
scope and standalone hook preservation have separate recorded evidence in
core-migration.md; no live target session is asserted here.

**Open questions:** where are saved tasks read from; does the user want a CLI
or a library surface for export? Resolve before intent approval. No requirement
or plan outcome disappeared because its answer was missing.

## Proposed intent playback

At define entry, re-supply the saved IMPORT.md path explicitly; the preceding
router invocation is not its durable transport. The worked define input is:

```text
$gsd-path-define Use <absolute-bundle>/IMPORT.md as the supplied spec. Verify its bundle, read its work map, and reconcile every row against proposed intent. Record this source path in INTENT.md's Summary.
```

The define-entry playback reads the Context, Constraints, Work map, History
and Open questions above and maps them into the following draft. Its Summary
records `Source: <absolute-bundle>/IMPORT.md` with the actual path substituted
in a live migration. Thus a fresh define session consumes the same on-disk
source explicitly, rather than guessing from earlier chat. The unresolved
persistence and surface questions remain pending for the fixture owner.

The supplied-spec define process can carry this reviewed mapping into its
canonical intent template. The following is the draft content, not a passed gate:

- **Summary/problem/users:** project operators have task data and an existing
  listing helper, but no CSV export. Add export while retaining listing.
- **Success criteria:** the chosen export surface emits id,title columns in
  order; titles containing commas or quotes survive CSV parsing unchanged;
  existing listing behavior remains available.
- **Scope in:** export and compatibility with listing.
- **Scope out:** "No cloud sync."
- **Constraints:** "Python standard library only."
- **Current state:** in-memory listing helper exists; persisted storage is not
  proven by the code inspected.
- **Open questions:** saved-task input boundary and export surface need user
  answers. They block approval rather than being silently chosen.

This walkthrough closes preservation, source-to-intent mapping and clean Path
entry claims for the fixture. It deliberately leaves the real product's normal
human approval gate intact. A future user migration is complete only after its
own questions, hook checks and intent approval are satisfied.
