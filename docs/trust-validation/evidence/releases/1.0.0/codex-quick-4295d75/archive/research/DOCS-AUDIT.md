# Docs Audit

Repo root: /Users/jeremymcspadden/orca/evaluations/gsd-path-finish-line-4295d75/quick/repo.gsd-path/verify/inspect-docs
Audited: 2026-09-06
Audited HEAD: 18c315c8da5e1b382a8efc016db2d4050e9cb0b2
Alignment mode: no

## Summary

| Verdict | Count |
|---------|-------|
| verified | 1 |
| stale | 0 |
| aspirational | 0 |
| unverifiable | 0 |
| descriptive docs (no testable claims) | 2 |

Worst drift: None found in fixture product claims; README contains only a title and specifies no count.py behavior.

Scope: Exact frozen inventory supplied by the orchestrator: AGENTS.md, README.md, WORKFLOW.md. AGENTS.md and WORKFLOW.md prescribe pipeline operations and describe the upstream distribution. Those prescriptions are governing policy, not claims about this fixture product or authority to audit the installed plugin implementation. Alignment is disabled. No runtime behavior of the installed plugin was tested.

## Doc: WORKFLOW.md

| Claim | Type | Verdict | Evidence |
|-------|------|---------|----------|
| Project installs include .gsd-path/runtime/ and the launcher .gsd-path/status_runtime.py | structure | verified | At audited HEAD, sidecar test -d .gsd-path/runtime and test -f .gsd-path/status_runtime.py both returned 0; .gsd-path/status_runtime.py:2 describes its launcher purpose and .gsd-path/status_runtime.py:13 contains the project status launcher marker. This verifies installed paths only. |

## Descriptive docs

- AGENTS.md
- README.md

AGENTS.md supplies operational rules and upstream distribution context, with no fixture product behavior claim. README.md:1 is the title Feature evaluation fixture and contains no commands, configuration, feature promises, or status claims.

## User rulings

| Queue # | Ruling | User’s words | Planned |
|---------|--------|--------------|---------|

## Remediation queue

| # | Doc | Claim | Verdict | Class | Suggested action |
|---|-----|-------|---------|-------|------------------|

No non-verified fixture claims; no remediation or user ruling required.
