---
pipeline: gsd-path/v2
project: repo
milestone: widget-counter
phase: build
                    # inspect only for brownfield; greenfield starts at define
                    # roadmap only in program flow (CHARTER.md exists)
status: blocked
branch: gsd-path/M001
                    # the router rebinds before any next-milestone file change
                    # the bound branch is never main; ship integrates it there
archive: null       # persisted archive transaction path; never recomputed
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
- 2026-09-04 — inspect — project initialized
- 2026-09-04 — inspect — router bound initial milestone
- 2026-09-04 — inspect — inspection artifacts passed; initial binding transition rejected custom event, diagnostic ok, canonical event succeeded
- 2026-09-04 — define — definition started
- 2026-09-04 — define — milestone intent approved
- 2026-09-04 — plan — planning started
- 2026-09-04 — plan — quick lane: research and decide skipped; log-only transition failed with missing changed field; diagnostic ok; explicit unchanged state supplied
- 2026-09-04 — plan — plan approved
- 2026-09-04 — build — build started
- 2026-09-04 — build — T001 coder ready; pre-landing isolated Verify blocked: isolate-verify refuses non-.project primary changes count.py,test_count.py; diagnostic status ok; serial helper selected primary but BUILD forbids primary Verify evidence; no landing or shipping claimed
- 2026-09-04 — build — evaluator recovery ruling applied; exact task bytes restored with matching hashes; pre-landing sidecar available at original task base
- 2026-09-04 — build — recovery checkpoint advanced serial task past base; activation rejected in-progress status; reconcile classification blocked; original isolated Verify passed; exact product bytes preserved
- 2026-09-04 — build — final evaluator recovery: pending task bookkeeping; exact product preserved; isolate before activation; no checkpoint before landing
- 2026-09-04 — build — final recovery fuse reached: T001 landed and isolated Verify passed; full reviewer passed in task-base sidecar; collect-artifact rejected primary HEAD differs from recorded base; subsequent wave gate missing canonical review; no further repair, ship or integration
