# Milestone-close git

**Status:** Superseded  
**Map:** [Wayfinder: Milestone-close git](https://github.com/open-gsd/gsd-path/issues/21)

Issues 22–30 locked a PR-only close that left default ancestry to a human.
The owner reversed that on 2026-08-17. The live contract is
[SHIP.md](../skills/gsd-path/SHIP.md), [WORKFLOW.md](../WORKFLOW.md), and
[CONTEXT.md](../CONTEXT.md).

## Current close

After final-review approval, ship:

1. Completes the archive transaction and the `.project/`-only
   `ship: M00N — <slug>` commit on `gsd-path/M00N`. The commit body names
   `Archive:` and `Reviewed-HEAD:`.
2. Merges that ship commit onto the remote default (usually `main`) with
   `--no-ff` in a named `gsd-path-integrate/M00N` worktree, subject
   `integrate: M00N — merge gsd-path/M00N into <default>`.
3. Pushes the merge to the default branch, the bound branch, and the
   annotated tag `milestone/<NNN>-<slug>` pointing at the merge.
4. Reports shipped only after `validate-integrated` passes.

The bound branch is never the GitHub default. The next milestone binds a new
`gsd-path/M00N` at the updated remote default.
