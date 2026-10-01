# Final Review — <project name>

<!-- Authorship and evidence reuse follow the ship phase contract. Each INTENT.md success
     criterion appears exactly once and carries checked evidence. A criterion
     listed in PLAN.md's Surface contract also names its Surface, and its
     Check is the walkthrough performed — never internal test output. Embedded
     angle brackets are valid in concrete Check and Observed values.
     When .project/build/members.json locks members, add one line per locked
     member after Reviewed HEAD: `Member reviewed HEAD: <member> <full SHA>`,
     naming that member's bound branch tip. -->

Reviewed HEAD: <full SHA>
Overall verdict: <pass | blocked>

<!-- pass only when every criterion is met; blocked when any criterion is
     not-met or unverifiable.
     A criterion with a held-out edge (E#) or judgment prohibition (N#) in
     INTENT.md is met only when Check, Observed, or Reference cites every such
     id with its evidence; otherwise it is unverifiable with
     `Finding: insufficient spec evidence: <id> ...`. -->

## Success criteria

<!-- Each `### SCn —` title must match INTENT.md `## Success criteria` as
     `_success_criteria` stores it: continuation lines join with a single
     space and keep `- ` sub-bullet markers; comparison uses `_normalize_ws`
     only. -->

### SC1 — <criterion as stored by the gate>

- **Verdict**: <met | not-met | unverifiable>
- **Surface**: <exactly the surface name PLAN.md's Surface contract lists this criterion under, with no detail after it; omit the whole field for any other criterion>
- **Check**: `<command actually run, or "none">`
- **Observed**: <relevant output or observed behavior>
- **Reference**: <file:line, artifact path, or "none">
- **Finding**: <none, or what was found instead>
- **Fix direction**: <none, or concrete direction for a patch task>

<!-- Repeat once per success criterion, preserving INTENT.md order. -->
