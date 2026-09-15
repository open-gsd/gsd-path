## Final integration mode

Use only final-review.md. Treat INTENT.md success criteria as the rubric.
Exercise the running system and record `met`, `not-met`, or `unverifiable`
with checked command output or a precise file reference. When PLAN.md carries
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

## Final gap mode

Use only gap-review.md. Check the one cross-wave risk in the brief against the
running system in the supplied verify sidecar at the exact reviewed HEAD.
Record evidence and `pass` or `blocked`; an unverified risk is blocked.
