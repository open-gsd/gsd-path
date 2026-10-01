## Final integration mode

Use only final-review.md. Treat INTENT.md success criteria as the rubric.
Each `### SCn —` heading must match the criterion text as
`check_handoffs._success_criteria` stores it from INTENT.md `## Success
criteria`: indented continuation lines join with a single space and keep
their `- ` list markers; the gate compares titles with `_normalize_ws`
only. Exercise the running system and record `met`, `not-met`, or
`unverifiable` with checked command output or a precise file reference.
When PLAN.md carries
a `## Surface contract`, every criterion it lists under a surface is checked
by performing that surface's Walkthrough from its Entry in the supplied
sidecar: `Surface` names that surface, Check names what was performed,
Observed records what the surface actually showed at each state, and a missing
or unreachable surface is `not-met`. A surface criterion is never `met` on
internal test output alone. Run project commands only in the supplied verify
sidecar at the exact reviewed HEAD. Do not
re-run PLAN.md's project Verify; cite the orchestrator's recorded
project-verify sidecar output. `pass`
requires every criterion to be `met`.

When INTENT.md `## Edge coverage` or `## Prohibitions` tags a criterion with a
`held-out` edge or a `judgment` prohibition, grade that criterion on cited
evidence for every tag (see the [spec-reach probes](spec-probes.md)). Name
each id in Check, Observed, or Reference with its evidence: the held-out
test's recorded passing output from the PLAN.md `## Held-out checks` test, or
the observed behavior judged against the prohibition's Detail. When a tag's
evidence is missing, did not run, or cannot be judged, record `unverifiable`
with `Finding: insufficient spec evidence: <id> <what is missing>` and a Fix
direction naming the check to add or run. Never mark such a criterion `met`
on inference or on code that merely looks right; the ship gate refuses a
`met` verdict that does not cite every tag. Grade untagged criteria as usual:
the trigger is the INTENT.md tag, never your own doubt.

## Final gap mode

Use only gap-review.md. Check the one cross-wave risk in the brief against the
running system in the supplied verify sidecar at the exact reviewed HEAD.
Record evidence and `pass` or `blocked`; an unverified risk is blocked.
