---
pipeline: gsd-path/v2
project: <slug>
milestone: null     # set by define; names the archive directory at ship
phase: define       # v2 tokens: inspect | define | research | decide | roadmap | plan | build | ship | shipped
                    # inspect only for brownfield; greenfield starts at define
                    # roadmap only in program flow (CHARTER.md exists)
status: active      # active | done | blocked; shipped is only phase: shipped + status: done
branch: null        # bound per milestone as gsd-path/M00N; reset after ship
                    # the bound branch is never the remote default; ship merges
                    # it onto main (or the existing default)
archive: null       # persisted archive transaction path; never recomputed
---

# Project State

One file, always current. The router reads this first; every phase updates
it on completion. If this file and the artifacts disagree, the artifacts win
— fix this file.

## Log

<!-- append one line per transition: date, phase, event -->
- YYYY-MM-DD — <phase> — project initialized
