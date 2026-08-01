# Docs Audit

<!-- Written by the docs auditor ($gsd-path-docs-audit or $gsd-path-onboard).
     Every verdict carries evidence; a verdict without evidence is a defect. -->

Repo root: <absolute path>
Audited: <date>
Alignment mode: <yes | no — yes when .project/ artifacts were also audited>

## Summary

| Verdict | Count |
|---------|-------|
| verified | <n> |
| stale | <n> |
| aspirational | <n> |
| unverifiable | <n> |
| descriptive docs (no testable claims) | <n> |

Worst drift: <one sentence — the most misleading claim found>

## Doc: <path/to/doc.md>

| Claim | Type | Verdict | Evidence |
|-------|------|---------|----------|
| "<claim, short-quoted>" | command \| feature \| structure \| status \| config \| integration | verified \| stale \| aspirational \| unverifiable | <file:line or command → result> |

<!-- One section per inventoried doc. Descriptive docs get a one-line
     section: "descriptive — no testable claims." -->

## Alignment (alignment mode only)

- **INTENT success criteria**: <each → met so far | not yet | contradicted, with evidence>
- **Done tasks**: <each status:done task → commit SHA found? Verify re-run result?>
- **SYNTHESIS decisions**: <each → code conforms? evidence>
- **BOARD/STATE vs frontmatter**: <agree | discrepancies listed>

## User rulings

<!-- Appended after the ruling walk (standalone runs). Verbatim, append-only.
     accept-drift rulings suppress the item in future audits.
     `planned: no` rows are the alignment queue: $gsd-path and $gsd-path-plan offer
     to absorb them until drained. When a ruling becomes a task, set
     planned to the task id — never delete the row. -->

| Queue # | Ruling | User's words | Planned |
|---------|--------|--------------|---------|
| 1 | fix-code \| fix-doc \| accept-drift | "<verbatim>" | no \| <task id> \| n/a (accept-drift) |

## Remediation queue

<!-- Every non-verified claim, classified. The user rules on this queue;
     the auditor never fixes anything. -->

| # | Doc | Claim | Verdict | Class | Suggested action |
|---|-----|-------|---------|-------|------------------|
| 1 | <doc> | <claim> | stale | fix-doc \| fix-code \| NEEDS-USER | <one line> |
