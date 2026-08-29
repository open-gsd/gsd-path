---
pipeline: gsd-path/v2
project: <slug>
milestone: null     # set by define; names the archive directory at ship
phase: define       # v2 tokens: inspect | define | research | decide | roadmap | plan | build | ship | shipped
                    # inspect only for brownfield; greenfield starts at define
                    # roadmap only in program flow (CHARTER.md exists)
status: active      # active | done | blocked; shipped is only phase: shipped + status: done
branch: null        # bound per milestone as gsd-path/M00N; after integration
                    # the router rebinds before any next-milestone file change
                    # the bound branch is never main; ship merges it there
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
- YYYY-MM-DD — <phase> — project initialized
