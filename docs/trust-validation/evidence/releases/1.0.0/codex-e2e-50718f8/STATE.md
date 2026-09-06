---
pipeline: gsd-path/v2
project: repo
milestone: widget-counter
phase: shipped
                    # inspect only for brownfield; greenfield starts at define
                    # roadmap only in program flow (CHARTER.md exists)
status: done
branch: gsd-path/M001
                    # the router rebinds before any next-milestone file change
                    # the bound branch is never main; ship integrates it there
archive: .project/archive/001-widget-counter
integration_default: direct # direct | pull-request; project setting
integration: direct # current milestone; may override the default before build
integration_source: default # default | milestone; preserves override provenance
---

# Project State

One file, always current. The router reads this first; every phase updates
it on completion. If this file and the artifacts disagree, the artifacts win
— fix this file.

## Log

<!-- append one line per transition: date, phase, event -->
- 2026-09-05 — inspect — project initialized
- 2026-09-05 — inspect — router bound initial milestone
- 2026-09-05 — inspect — inspection artifacts passed
- 2026-09-05 — define — definition started
- 2026-09-05 — define — milestone intent approved
- 2026-09-05 — plan — planning started
- 2026-09-05 — plan — plan approved
- 2026-09-05 — build — build started
- 2026-09-05 — ship — build done; final review pending
- 2026-09-05 — ship — new HEAD final gate passed; shipping proceeds under standing owner approval and authorized recovery; external history preserved
- 2026-09-05 — shipped — archive preflight passed; shipment recorded
