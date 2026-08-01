---
pipeline: gsd-path/v1
project: <slug>
milestone: null     # set by the grill; names the archive directory at ship
phase: grill        # onboard | grill | research | synthesize | plan | build | review | shipped
                    # onboard only for brownfield projects; greenfield starts at grill
status: active      # active | done | blocked
branch: null        # bound once at build; reset for the next milestone
archive: null       # persisted archive transaction path; never recomputed
---

# Project State

One file, always current. The router reads this first; every phase updates
it on completion. If this file and the artifacts disagree, the artifacts win
— fix this file.

## Log

<!-- append one line per transition: date, phase, event -->
- YYYY-MM-DD — <phase> — project initialized
