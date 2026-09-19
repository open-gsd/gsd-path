# GSD Path

Pipeline that takes an idea to shipped code through gated phases. This glossary
is for the product domain, not for any one implementation of git.

## Language

**Milestone close**:
The ship-phase sequence after final-review approval: the archive, the ship
commit, and whatever git makes that close durable. It is not task-end landing
and not abandon.
_Avoid_: end of work, ship (the whole phase), integration (the merge leg)

**Ship commit**:
The single `.project/`-only commit on the bound branch, subject
`ship: M00N — <slug>` with an `Archive:` / `Reviewed-HEAD:` body, that
records shipped state, final reviews, and the archive.
_Avoid_: ship merge, integrate commit

**Milestone tag**:
An annotated tag `milestone/<NNN>-<slug>` pointing at the integration merge.
Ship creates it at close and pushes it to origin. It names that close.
_Avoid_: release, GitHub Release, lightweight tag

**Integration**:
The two-parent merge that puts the ship commit onto the remote default `main`.
In `direct` mode, Path creates it with subject
`integrate: M00N — merge gsd-path/M00N into main`. In `pull-request` mode,
GitHub creates it after a user merges the Path-owned PR.
_Avoid_: ship, land (unless you mean this)

**Integration mode**:
The closeout path selected before build: `direct` or `pull-request`.
`STATE.integration_default` is the project setting and `STATE.integration` is
the locked choice for the current milestone. `STATE.integration_source` records
whether that choice follows the default or is an explicit milestone override.
_Avoid_: merge strategy (GitHub uses that term for merge, squash, or rebase)

**Default ancestry**:
The milestone's product commits, the ship commit, and the integrate merge
are ancestors of the remote default branch. Required before the router
reports shipped.
_Avoid_: landed (unless you mean this)

**Landing pointer**:
Not used. Close lands by merging onto the remote default.
_Avoid_: pointer (bare)

**GitHub remote**:
`origin` whose host is github.com or GitHub Enterprise Server. Pull-request
integration currently supports GitHub.com only.
_Avoid_: GitHub (bare, unless you mean the host family), github.com (unless you
mean that host only)

**Bound branch**:
The per-milestone `gsd-path/M00N` branch recorded in `STATE.branch`. Pipeline
commits for that milestone live here. It is never the GitHub default.
_Avoid_: feature branch, worktree branch, `gsd-path/<project-slug>`

**Default branch**:
The repository's remote default, required to be `main`. New repositories keep
GitHub's `main`, and ship integrates onto it.
_Avoid_: production branch

**Shipped**:
The router-visible "this milestone is complete" state. True when the ship
commit validates and `validate-integrated` proves the merge, tag, and
default ancestry. The router may start the next milestone then.
_Avoid_: archived, done

**Dispatch round**:
The set of ready tasks isolated together at one recorded base SHA.
_Avoid_: wave, layer

**Task isolation**:
The checkout a coder uses for one task until task landing. A parallel
dispatch round uses a named branch distinct from the bound branch. A serial
dispatch round (one ready task) uses the bound branch itself.
_Avoid_: detached HEAD, feature branch, worktree (bare)

**Task landing**:
The orchestrator-owned commit that records one task's product on the bound
branch.
_Avoid_: integration, ship commit, cherry-pick

**Verify sidecar**:
A named throwaway checkout at a recorded revision used only for review,
inspect, or project Verify. It is never the bound branch.
_Avoid_: detached HEAD, disposable worktree (unless you mean the filesystem path)

**Surface**:
Something a person opens, sees, or types into to get a milestone's outcome:
a screen, a command, an endpoint. `Surfaces:` on the roadmap entry and
INTENT.md names them; `none` means nobody touches the work directly. Each
named surface carries a success criterion observable there and a PLAN.md
Surface contract.
_Avoid_: UI (unless you mean a screen only), frontend, interface (that is the
task-to-task Interface contract)

**Unverified**:
Available workflow facts whose required validation evidence is unavailable or
has not passed. They may be displayed, but do not establish that a milestone
is Shipped.
_Avoid_: failed, complete, shipped

**Roadmap**:
The ordered milestone scope, dependencies, status, and open questions for a
program. It identifies which milestone is ready after its dependencies.
_Avoid_: task list, wave plan


**Approval checkpoint**:
The durable record of an approved Roadmap or Plan, including its planning
artifacts and phase transition. Normally a planning-only commit; when the
workflow defers checkpointing, build records it.
_Avoid_: task landing, ship commit, approval alone

**Lookahead promotion**:
The adoption of a prepared next-milestone planning track as the active
milestone after validated Integration and binding its new bound branch.
_Avoid_: task landing, phase transition (without naming the milestone change)

**Dispatch model policy**:
The rules for choosing a model and reasoning effort for pipeline sub-agent
roles. Model choice does not change a role's authority.
_Avoid_: review policy, model ranking

**Project runtime**:
The selected GSD Path execution version for a project's status, guards, and
pipeline operations. It changes through an explicit project upgrade, not an
installed skill or plugin update.
_Avoid_: latest installed plugin, host runtime

**Runtime declaration**:
The version-controlled record identifying a project's selected Project runtime.
Clones and named checkouts inherit this selection; setup, migration, or an
explicit project upgrade establishes or changes it.
_Avoid_: installed plugin version, local runtime cache
