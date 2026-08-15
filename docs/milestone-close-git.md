# Milestone-close git

**Status:** Locked  
**Map:** [Wayfinder: Milestone-close git](https://github.com/open-gsd/gsd-path/issues/21)  
**Hard limit:** the pipeline never pushes, merges, or force-updates the default branch.

This spec replaces the current integrate-and-push-default landing leg. The local `.project/`-only `ship: <NNN>-<slug>` commit and archive transaction stay. Implementation is a later effort; do not treat today's `SHIP.md` integrate path as this spec.

Terms follow [CONTEXT.md](../CONTEXT.md).

## Close vs default ancestry

Default ancestry is required eventually: the milestone's product commits and the ship commit must become ancestors of the remote default branch. The bound branch is a work lane, not a second trunk.

Milestone close does not wait for that ancestry. Close is complete when both exist:

1. The ship commit (local archive transaction validated and committed).
2. A landing pointer a human can use to create default ancestry later.

Decided in [Must the milestone become an ancestor of default?](https://github.com/open-gsd/gsd-path/issues/22).

## Landing pointer

Split by remote, decided in [Is landing GitHub-native or generic git?](https://github.com/open-gsd/gsd-path/issues/23) and [If default must contain the milestone, what is the landing path?](https://github.com/open-gsd/gsd-path/issues/28).

- **GitHub remote** (`origin` host is github.com or GitHub Enterprise Server): one pull request, base = default, head = bound branch. If that PR is already open, reuse it (the bound-branch push updates it).
- **Otherwise:** the pushed bound branch. This spec does not invent a GitLab or Bitbucket merge-request flow.

A write-access human creates default ancestry from that pointer. On GitHub they may use the merge button, `gh pr merge`, auto-merge, or a merge queue. The pipeline never merges, never enqueues, never enables auto-merge. The repository's merge settings win; the old `--no-ff` `integrate: <NNN>-<slug>` commit is not required.

## What ship may push

Decided in [What remotes and refs may ship push?](https://github.com/open-gsd/gsd-path/issues/24) and [Do we keep annotated milestone tags?](https://github.com/open-gsd/gsd-path/issues/25).

Origin only. Extra remotes are out of this spec.

On origin, ship may:

- push the bound branch, fast-forward only (no force, no force-with-lease);
- create and push the annotated tag `milestone/<NNN>-<slug>` pointing at the ship commit (create-only; no force).

It never updates the default branch. The tag names the close; it is not the landing pointer.

## Shipped

Decided in [When does the router report shipped?](https://github.com/open-gsd/gsd-path/issues/29).

`STATE` is `shipped` when the local ship commit validates and the landing pointer exists. The milestone tag is part of close, not the shipped gate. The router may start the next milestone at that point. It does not wait for default ancestry.

`validate-integrated` (merge commit on default + tag ancestry on origin/default) is not the shipped gate.

## Close procedure

Decided in [What does ship do instead of integrate and push default?](https://github.com/open-gsd/gsd-path/issues/30).

After final-review approval, ship:

1. Completes the existing archive transaction and the `.project/`-only `ship: <NNN>-<slug>` commit on the bound branch.
2. Pushes the bound branch to origin (`git push origin <bound-branch>`), fast-forward only.
3. Creates the annotated tag on the ship commit (`git tag -a milestone/<NNN>-<slug> <ship-commit>`) and pushes it (`git push origin refs/tags/milestone/<NNN>-<slug>`), create-only.
4. On a GitHub remote, opens or reuses one PR (`gh pr create` / existing PR from that head to default). Otherwise stops after the bound-branch push.
5. Presents **Outcome** (close complete, shipped), **Review** (PR URL or bound-branch URL), and **Next** (human lands the pointer). Then the router may start the next milestone.

Ship must not run:

- `git push` to the default branch;
- `git merge` (or `--no-ff` `integrate: <NNN>-<slug>`) onto default;
- `gh pr merge`, auto-merge enablement, or merge-queue enqueue;
- `validate-integrated` as a condition of reporting shipped.

A non-fast-forward bound-branch push fails closed. It is not a license to force-push.

## Protections (GitHub)

Recorded in [What GitHub protections allow close without mutating default?](https://github.com/open-gsd/gsd-path/issues/26) and [How do comparable agent pipelines close onto a protected default?](https://github.com/open-gsd/gsd-path/issues/27).

Write / Contents:write is repo-wide. Default stays unwritable because a classic protection rule or ruleset targets it. The pipeline uses Contents:write + Pull requests:write, no Administration, no bypass. Comparable agent pipelines stop at a non-default branch and PR; a human or GitHub (after a human arms auto-merge or a merge queue) updates protected default.

## Out of this spec

These stay past the locked close. They are not required to implement the procedure above.

- Default has commits the bound branch lacks.
- Close is complete but the landing pointer is never merged (unmet default ancestry after the next milestone starts).
- GitHub Releases or signed tags.
- Crash-recovery of a half-done human/CI land, beyond "FF push fails closed."
- Fate of the uncommitted integrate-and-push-default patch: discard it when this spec is implemented; do not extend it.
